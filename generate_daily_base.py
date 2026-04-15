#!/usr/bin/env python3
"""
generate_daily_base.py  —  SALCI Stage 1 Pre-Compute
======================================================
Nightly GitHub Actions script (~2 AM ET).

What it does
------------
1.  Fetches today's MLB schedule (statsapi.mlb.com)
2.  For each game: fetches probable starters
3.  Computes SALCI v4 scores using:
      • Statcast / pybaseball data (if available)
      • MLB Stats API proxy fallback
4.  Uses TEAM-LEVEL opponent K% (no lineups yet)
5.  Writes  data/daily/YYYY-MM-DD_base.json

Lineups are NOT confirmed at this stage.
Stage 2 (generate_daily_final.py) upgrades matchup_score once lineups drop.

Run locally
-----------
    python generate_daily_base.py            # today
    python generate_daily_base.py 2026-04-16 # specific date

GitHub Actions environment variables required
---------------------------------------------
    GH_TOKEN   — for git commit/push (set automatically in Actions)

Optional
--------
    TARGET_DATE  — override date (ISO string)
"""

import json
import os
import sys
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("stage1")

# ---------------------------------------------------------------------------
# Resolve target date
# ---------------------------------------------------------------------------
TARGET_DATE = (
    os.environ.get("TARGET_DATE")
    or (sys.argv[1] if len(sys.argv) > 1 else None)
    or datetime.today().strftime("%Y-%m-%d")
)
log.info(f"Target date: {TARGET_DATE}")

# ---------------------------------------------------------------------------
# Import SALCI scoring engine
# (Requires: statcast_connector.py in same repo)
# ---------------------------------------------------------------------------
SALCI_V3_AVAILABLE = False
try:
    from statcast_connector import (
        calculate_salci_v3,
        calculate_expected_ks_v3,
        get_pitcher_statcast_profile,
        classify_pitcher_profile,
        calculate_stuff_plus,
        calculate_location_plus,
        calculate_workload_score_v3,
        calculate_matchup_score_v3,
        SALCI_V3_WEIGHTS,
        PYBASEBALL_AVAILABLE,
    )
    SALCI_V3_AVAILABLE = True
    log.info(f"SALCI v3 engine loaded. Pybaseball: {PYBASEBALL_AVAILABLE}")
except ImportError as e:
    log.warning(f"statcast_connector not available: {e}. Will use proxy scoring.")

try:
    from data_loader import save_precomputed
except ImportError:
    # Inline fallback
    import json as _json

    def save_precomputed(date_str, pitchers, stage, metadata=None):
        os.makedirs(os.path.join("data", "daily"), exist_ok=True)
        meta = {
            "date": date_str, "stage": stage,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "pitcher_count": len(pitchers),
            "lineup_confirmed_count": 0,
            "statcast_count": sum(1 for p in pitchers if p.get("is_statcast")),
        }
        if metadata:
            meta.update(metadata)
        path = os.path.join("data", "daily", f"{date_str}_{stage}.json")
        with open(path, "w") as f:
            _json.dump({"metadata": meta, "pitchers": pitchers}, f, indent=2, default=str)
        return True

# ---------------------------------------------------------------------------
# MLB Stats API helpers
# ---------------------------------------------------------------------------

BASE = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 15


def _get(url: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning(f"GET {url} failed: {exc}")
        return None


def fetch_schedule(date_str: str) -> list:
    data = _get(f"{BASE}/schedule", {"sportId": 1, "date": date_str, "hydrate": "probablePitcher,team"})
    if not data:
        return []
    return data.get("dates", [{}])[0].get("games", []) if data.get("dates") else []


def fetch_team_stats(team_id: int, season: int) -> dict:
    """Fetch season batting stats for a team (opponent K% proxy)."""
    data = _get(f"{BASE}/teams/{team_id}/stats", {"stats": "season", "group": "hitting", "season": season})
    if not data:
        return {}
    splits = data.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return {}
    s = splits[0].get("stat", {})
    ab = int(s.get("atBats", 0))
    so = int(s.get("strikeOuts", 0))
    return {"OppK%": so / ab if ab else 0.22}


def fetch_pitcher_season_stats(player_id: int, season: int) -> dict:
    """Fetch season pitching stats for a player."""
    data = _get(f"{BASE}/people/{player_id}/stats", {
        "stats": "season", "group": "pitching", "season": season
    })
    if not data:
        return {}
    splits = data.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return {}
    s = splits[0].get("stat", {})
    ip_raw = float(s.get("inningsPitched", 0) or 0)
    # Convert 6.1 → 6.33, 6.2 → 6.67
    ip_full = int(ip_raw)
    ip_frac = round((ip_raw - ip_full) / 3, 2)
    ip = ip_full + ip_frac

    bf = int(s.get("battersFaced", 0) or 0) or 1
    so = int(s.get("strikeOuts", 0) or 0)
    bb = int(s.get("baseOnBalls", 0) or 0)
    hr = int(s.get("homeRuns", 0) or 0)
    np_per_ip = float(s.get("pitchesPerInning", 0) or 0)

    return {
        "K9": round(so / max(ip, 1) * 9, 2) if ip > 0 else 7.5,
        "K_percent": round(so / bf, 3),
        "K/BB": round(so / max(bb, 1), 2),
        "P/IP": np_per_ip or 16.0,
        "ERA": float(s.get("era", 4.50) or 4.50),
        "WHIP": float(s.get("whip", 1.25) or 1.25),
        "avg_ip_per_start": round(ip / max(int(s.get("gamesStarted", 1) or 1), 1), 2),
        "games_started": int(s.get("gamesStarted", 0) or 0),
    }


def fetch_pitcher_recent_stats(player_id: int, n_games: int = 7) -> dict:
    """Fetch last N game logs for a pitcher."""
    data = _get(f"{BASE}/people/{player_id}/stats", {
        "stats": "gameLog", "group": "pitching", "limit": n_games
    })
    if not data:
        return {}
    splits = data.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return {}
    # Aggregate last N starts
    total_k, total_ip_raw, total_bf = 0, 0.0, 0
    for sp in splits[:n_games]:
        s = sp.get("stat", {})
        total_k += int(s.get("strikeOuts", 0) or 0)
        ip_raw = float(s.get("inningsPitched", 0) or 0)
        ip_full = int(ip_raw)
        ip_frac = (ip_raw - ip_full) / 3
        total_ip_raw += ip_full + ip_frac
        total_bf += int(s.get("battersFaced", 0) or 0)

    total_bf = total_bf or 1
    return {
        "K9": round(total_k / max(total_ip_raw, 1) * 9, 2),
        "K_percent": round(total_k / total_bf, 3),
    }


# ---------------------------------------------------------------------------
# SALCI proxy scorer (used when statcast_connector is unavailable)
# ---------------------------------------------------------------------------

def _proxy_salci(pitcher_stats: dict, opp_stats: dict) -> tuple:
    """
    Rough SALCI v4 proxy from MLB Stats API data only.
    Returns (salci_score, breakdown, grade).
    """
    k9 = pitcher_stats.get("K9", 7.5)
    k_pct = pitcher_stats.get("K_percent", 0.22)
    k_bb = pitcher_stats.get("K/BB", 2.5)
    avg_ip = pitcher_stats.get("avg_ip_per_start", 5.5)
    opp_k = opp_stats.get("OppK%", 0.22)

    # Normalise each to [0, 100]
    def _norm(val, lo, hi, higher_better=True):
        if hi == lo:
            return 50.0
        x = max(lo, min(hi, val))
        n = (x - lo) / (hi - lo)
        return round(n * 100 if higher_better else (1 - n) * 100, 1)

    stuff_proxy = (
        _norm(k9, 4.5, 12.0) * 0.50 +
        _norm(k_pct, 0.12, 0.38) * 0.30 +
        _norm(k_bb, 1.0, 5.0) * 0.20
    )
    matchup_proxy = _norm(opp_k, 0.15, 0.30)
    workload_proxy = _norm(avg_ip, 4.0, 7.5)
    location_proxy = 50.0  # no data → neutral

    # SALCI v4 weights
    salci = (
        stuff_proxy * 0.52 +
        matchup_proxy * 0.30 +
        workload_proxy * 0.10 +
        location_proxy * 0.08
    )
    salci = round(max(0, min(100, salci)), 1)

    grade = (
        "S" if salci >= 80 else
        "A" if salci >= 70 else
        "B+" if salci >= 60 else
        "B" if salci >= 52 else
        "C" if salci >= 44 else
        "D" if salci >= 30 else "F"
    )

    breakdown = {
        "stuff_score": round(stuff_proxy, 1),
        "matchup_score": round(matchup_proxy, 1),
        "workload_score": round(workload_proxy, 1),
        "location_score": round(location_proxy, 1),
    }
    return salci, breakdown, grade


def _proxy_expected_ks(salci: float, avg_ip: float = 5.5) -> tuple:
    """
    Project expected Ks and build K-line probability table.
    Returns (expected_ks, lines_dict).
    """
    from scipy.stats import poisson as _poisson  # type: ignore[import]

    # Map SALCI to a K/9 estimate
    k9_est = 4.5 + (salci / 100) * 8.0
    expected = round(k9_est / 9.0 * avg_ip, 2)

    # Build Poisson CDF for whole-number K lines
    lines = {}
    for k in range(3, 10):
        # P(X >= k) = 1 - P(X <= k-1)
        prob = round((1 - _poisson.cdf(k - 1, expected)) * 100)
        lines[str(k)] = max(0, min(100, prob))

    # Best line (closest to 50% over probability)
    best_line = min(lines, key=lambda x: abs(lines[x] - 50))

    return expected, lines, best_line


# ---------------------------------------------------------------------------
# Statcast path
# ---------------------------------------------------------------------------

def _statcast_salci(player_id: int, pitcher_stats: dict, opp_stats: dict) -> Optional[tuple]:
    """
    Try full SALCI v3/v4 computation via statcast_connector.
    Returns (salci, breakdown, grade, profile_type, stuff_breakdown) or None.
    """
    if not SALCI_V3_AVAILABLE or not PYBASEBALL_AVAILABLE:
        return None
    try:
        today = datetime.today()
        start = (today - timedelta(days=60)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        sc_profile = get_pitcher_statcast_profile(player_id, start, end)
        if not sc_profile:
            return None

        stuff = calculate_stuff_plus(sc_profile)
        location = calculate_location_plus(sc_profile)
        workload = calculate_workload_score_v3(pitcher_stats, pitcher_stats)
        matchup = calculate_matchup_score_v3(
            opp_stats, opp_stats,
            pitcher_hand=sc_profile.get("hand", "R"),
        )
        salci, breakdown = calculate_salci_v3(stuff, location, workload, matchup)
        profile_type = classify_pitcher_profile(stuff, location)
        grade = (
            "S" if salci >= 80 else "A" if salci >= 70 else
            "B+" if salci >= 60 else "B" if salci >= 52 else
            "C" if salci >= 44 else "D" if salci >= 30 else "F"
        )
        stuff_bd = sc_profile.get("arsenal_stuff", {})
        return salci, breakdown, grade, profile_type, stuff_bd
    except Exception as exc:
        log.warning(f"Statcast path failed for {player_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_base(date_str: str) -> list:
    """
    Fetch all probable starters for date_str and compute Stage 1 SALCI scores.
    Returns a list of pitcher dicts.
    """
    season = int(date_str[:4])
    games = fetch_schedule(date_str)
    log.info(f"Found {len(games)} games on {date_str}")

    pitchers = []

    for game in games:
        game_pk = game.get("gamePk")
        status = game.get("status", {}).get("abstractGameState", "")
        if status in ("Final",):
            log.debug(f"Skipping completed game {game_pk}")
            continue

        home_team = game.get("teams", {}).get("home", {})
        away_team = game.get("teams", {}).get("away", {})

        for side, team_data, opp_data in [
            ("home", home_team, away_team),
            ("away", away_team, home_team),
        ]:
            prob = team_data.get("probablePitcher", {})
            if not prob:
                continue

            player_id = prob.get("id")
            pitcher_name = prob.get("fullName", "Unknown")
            team_name = team_data.get("team", {}).get("name", "?")
            team_abbr = team_data.get("team", {}).get("abbreviation", "?")
            opp_name = opp_data.get("team", {}).get("name", "?")
            opp_abbr = opp_data.get("team", {}).get("abbreviation", "?")
            opp_id = opp_data.get("team", {}).get("id")

            log.info(f"Processing {pitcher_name} ({team_abbr}) vs {opp_abbr}")

            # Fetch stats
            pitcher_season = fetch_pitcher_season_stats(player_id, season)
            pitcher_recent = fetch_pitcher_recent_stats(player_id, 7)
            opp_team_stats = fetch_team_stats(opp_id, season) if opp_id else {}

            # Merge recent into season
            blended = dict(pitcher_season)
            if pitcher_recent.get("K9"):
                blended["K9"] = 0.6 * pitcher_recent["K9"] + 0.4 * pitcher_season.get("K9", 7.5)
            if pitcher_recent.get("K_percent"):
                blended["K_percent"] = 0.6 * pitcher_recent["K_percent"] + 0.4 * pitcher_season.get("K_percent", 0.22)

            avg_ip = pitcher_season.get("avg_ip_per_start", 5.5)

            # Attempt Statcast path first
            sc_result = _statcast_salci(player_id, blended, opp_team_stats)
            is_statcast = sc_result is not None

            if is_statcast:
                salci, breakdown, grade, profile_type, stuff_bd = sc_result
                stuff_score = breakdown.get("stuff_score")
                location_score = breakdown.get("location_score")
                matchup_score = breakdown.get("matchup_score")
                workload_score = breakdown.get("workload_score")
            else:
                salci, breakdown, grade = _proxy_salci(blended, opp_team_stats)
                stuff_score = breakdown.get("stuff_score")
                location_score = breakdown.get("location_score")
                matchup_score = breakdown.get("matchup_score")
                workload_score = breakdown.get("workload_score")
                profile_type = "proxy"
                stuff_bd = {}

            # K projections
            try:
                expected, lines, best_line = _proxy_expected_ks(salci, avg_ip)
            except ImportError:
                expected = round(salci / 100 * 9, 1)
                lines = {}
                best_line = None

            # Store the pitcher record
            pitchers.append({
                "pitcher": pitcher_name,
                "pitcher_id": player_id,
                "team": team_abbr,
                "team_name": team_name,
                "opponent": opp_abbr,
                "opponent_name": opp_name,
                "opponent_id": opp_id,
                "game_pk": game_pk,
                "salci": salci,
                "salci_grade": grade,
                "expected": expected,
                "k_line": best_line,
                "k_lines": lines,
                "lines": lines,
                "odds": None,           # No odds in base stage
                "model_prob": None,     # Will be set in Stage 2
                "edge": None,
                "stuff_score": stuff_score,
                "matchup_score": matchup_score,
                "workload_score": workload_score,
                "location_score": location_score,
                "stuff_breakdown": stuff_bd,
                "profile_type": profile_type,
                "lineup_confirmed": False,  # Always False in base
                "is_statcast": is_statcast,
                "stage": "base",
                "generated_at": datetime.utcnow().isoformat() + "Z",
            })

    pitchers.sort(key=lambda x: x["salci"], reverse=True)
    return pitchers


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info(f"=== SALCI Stage 1 — Daily Base === {TARGET_DATE}")

    pitchers = build_base(TARGET_DATE)
    log.info(f"Computed {len(pitchers)} pitcher records")

    if not pitchers:
        log.warning("No pitchers computed. Exiting without writing file.")
        sys.exit(0)

    ok = save_precomputed(
        TARGET_DATE,
        pitchers,
        stage="base",
        metadata={
            "script": "generate_daily_base.py",
            "salci_version": "6.0",
            "statcast_enabled": SALCI_V3_AVAILABLE,
            "pybaseball_enabled": SALCI_V3_AVAILABLE and PYBASEBALL_AVAILABLE,
        },
    )
    if ok:
        log.info(f"Wrote data/daily/{TARGET_DATE}_base.json ({len(pitchers)} pitchers)")
    else:
        log.error("Failed to write base JSON!")
        sys.exit(1)

    # Prune files older than 7 days
    try:
        from data_loader import prune_old_files
        deleted = prune_old_files(7)
        if deleted:
            log.info(f"Pruned {deleted} old JSON files")
    except Exception:
        pass

    log.info("Stage 1 complete.")
