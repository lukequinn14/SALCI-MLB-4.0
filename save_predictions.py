#!/usr/bin/env python3
"""
SALCI Save Predictions Script
==============================
Runs at ~10 AM ET daily via GitHub Actions (before games start).

What it does:
  1. Fetches today's MLB schedule + probable pitchers
  2. Computes SALCI scores using the same logic as the Streamlit app
  3. Saves predictions to data/predictions/YYYY-MM-DD.json
  4. Commits + pushes the file to the GitHub repo (persistent storage)

Usage:
  python scripts/save_predictions.py              # today
  python scripts/save_predictions.py 2025-04-13   # specific date (backfill)
"""

import base64
import json
import math
import os
import sys
import requests
from datetime import datetime
from typing import Optional, Dict, List, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT       = os.path.join(os.path.dirname(__file__), "..")
PREDICTIONS_DIR = os.path.join(REPO_ROOT, "data", "predictions")
CURRENT_SEASON  = datetime.today().year

DEFAULT_WEIGHTS = {
    "K9": 0.18, "K_percent": 0.18, "K/BB": 0.14,
    "P/IP": 0.10, "OppK%": 0.22, "OppContact%": 0.18,
}

BOUNDS = {
    "K9":          (6.0,  13.0, True),
    "K_percent":   (0.15, 0.38, True),
    "K/BB":        (1.5,  7.0,  True),
    "P/IP":        (13,   18,   False),
    "OppK%":       (0.18, 0.28, True),
    "OppContact%": (0.70, 0.85, False),
}


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def ensure_dirs():
    os.makedirs(PREDICTIONS_DIR, exist_ok=True)


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# MLB API
# ─────────────────────────────────────────────────────────────────────────────

def get_games_by_date(date_str: str) -> List[Dict]:
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={date_str}&hydrate=probablePitcher,lineups,team"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("dates"):
            return []
        games = []
        for g in data["dates"][0]["games"]:
            info = {
                "game_pk":      g.get("gamePk"),
                "home_team":    g["teams"]["home"]["team"]["name"],
                "away_team":    g["teams"]["away"]["team"]["name"],
                "home_team_id": g["teams"]["home"]["team"]["id"],
                "away_team_id": g["teams"]["away"]["team"]["id"],
            }
            for side in ("home", "away"):
                pp = g["teams"][side].get("probablePitcher")
                if pp:
                    info[f"{side}_pitcher"]     = pp.get("fullName", "TBD")
                    info[f"{side}_pid"]          = pp.get("id")
                    info[f"{side}_pitcher_hand"] = pp.get("pitchHand", {}).get("code", "R")
                else:
                    info[f"{side}_pitcher"]     = "TBD"
                    info[f"{side}_pid"]          = None
                    info[f"{side}_pitcher_hand"] = "R"
            games.append(info)
        return games
    except Exception as e:
        log(f"ERROR fetching schedule: {e}")
        return []


def get_player_season_stats(player_id: int, season: int) -> Optional[Dict]:
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
        f"?stats=season&season={season}&group=pitching"
    )
    try:
        r = requests.get(url, timeout=10)
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        return splits[0]["stat"] if splits else None
    except Exception:
        return None


def get_recent_pitcher_stats(player_id: int, num_games: int = 7) -> Optional[Dict]:
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
        f"?stats=gameLog&group=pitching"
    )
    try:
        r = requests.get(url, timeout=10)
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        games = sorted(splits, key=lambda x: x.get("date", ""), reverse=True)[:num_games]
        totals = {"ip": 0.0, "so": 0, "bb": 0, "tbf": 0, "np": 0, "n": len(games)}
        for g in games:
            s = g.get("stat", {})
            parts = str(s.get("inningsPitched", "0.0")).split(".")
            ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
            totals["ip"]  += ip
            totals["so"]  += int(s.get("strikeOuts", 0))
            totals["bb"]  += int(s.get("baseOnBalls", 0))
            totals["tbf"] += int(s.get("battersFaced", 0))
            totals["np"]  += int(s.get("numberOfPitches", 0))
        if totals["ip"] == 0 or totals["tbf"] == 0:
            return None
        return {
            "K9":               totals["so"] / totals["ip"] * 9,
            "K_percent":        totals["so"] / totals["tbf"],
            "K/BB":             totals["so"] / totals["bb"] if totals["bb"] > 0 else totals["so"] * 2,
            "P/IP":             totals["np"] / totals["ip"],
            "avg_ip_per_start": totals["ip"] / totals["n"],
            "games_sampled":    totals["n"],
        }
    except Exception:
        return None


def parse_season_stats(stats: Dict) -> Dict:
    if not stats:
        return {}
    parts = str(stats.get("inningsPitched", "0.0")).split(".")
    ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
    if ip == 0:
        return {}
    so  = int(stats.get("strikeOuts",      0))
    bb  = int(stats.get("baseOnBalls",     0))
    tbf = int(stats.get("battersFaced",    1))
    np  = int(stats.get("numberOfPitches", 0))
    return {
        "K9":        so / ip * 9,
        "K_percent": so / tbf,
        "K/BB":      so / bb if bb > 0 else so * 2,
        "P/IP":      np / ip if np > 0 else 15.0,
        "ERA":       float(stats.get("era",  0)),
        "WHIP":      float(stats.get("whip", 0)),
    }


def get_team_batting_stats(team_id: int, season: int) -> Optional[Dict]:
    url = (
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
        f"?stats=season&season={season}&group=hitting"
    )
    try:
        r = requests.get(url, timeout=10)
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            s    = splits[0]["stat"]
            so   = int(s.get("strikeOuts", 0))
            ab   = int(s.get("atBats",     1))
            hits = int(s.get("hits",       0))
            dbls = int(s.get("doubles",    0))
            trpl = int(s.get("triples",    0))
            hrs  = int(s.get("homeRuns",   0))
            singles = hits - dbls - trpl - hrs
            contact = (hits + singles) / ab if ab > 0 else 0.75
            return {
                "OppK%":       so / ab if ab > 0 else 0.22,
                "OppContact%": min(contact, 0.95),
            }
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SALCI v1 COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(value: float, low: float, high: float, positive: bool) -> float:
    if high == low:
        return 50.0
    raw = (max(low, min(high, value)) - low) / (high - low) * 100
    return raw if positive else 100 - raw


def compute_salci(
    p_recent:   Optional[Dict],
    p_baseline: Optional[Dict],
    opp_recent:   Optional[Dict],
    opp_baseline: Optional[Dict],
    weights:    Dict,
    games_played: int = 5,
) -> Tuple[Optional[float], Dict, List[str]]:
    # Blend pitcher stats
    combined: Dict = {}
    if p_baseline:
        combined.update(p_baseline)
    if p_recent and games_played >= 3:
        w_r = min(0.7, games_played / 10)
        w_b = 1 - w_r
        for k in ("K9", "K_percent", "K/BB", "P/IP"):
            if k in p_recent and k in combined:
                combined[k] = p_recent[k] * w_r + combined[k] * w_b
            elif k in p_recent:
                combined[k] = p_recent[k]

    # Blend opp stats
    opp: Dict = {}
    if opp_baseline:
        opp.update(opp_baseline)
    if opp_recent:
        for k in ("OppK%", "OppContact%"):
            if k in opp_recent and k in opp:
                opp[k] = opp_recent[k] * 0.6 + opp[k] * 0.4
            elif k in opp_recent:
                opp[k] = opp_recent[k]
    combined.update(opp)

    score      = 0.0
    breakdown: Dict      = {}
    missing:   List[str] = []

    for metric, weight in weights.items():
        if metric not in combined:
            missing.append(metric)
            continue
        low, high, pos = BOUNDS[metric]
        norm = _normalize(combined[metric], low, high, pos)
        contribution = norm * weight
        score += contribution
        breakdown[metric] = {
            "raw": combined[metric], "normalized": round(norm, 1),
            "weight": weight, "contribution": round(contribution, 1),
        }

    if not breakdown:
        return None, {}, missing

    total_w = sum(weights[m] for m in breakdown)
    if total_w < 1.0:
        score = score / total_w

    return round(score, 1), breakdown, missing


def project_lines(salci: float, base_k9: float = 9.0) -> Dict:
    k_per_ip  = (base_k9 * (salci / 50)) / 9
    proj_ip   = max(3.0, min(7.0, 4.5 + (salci - 50) * 0.04))
    expected  = k_per_ip * proj_ip
    lam       = expected
    lines     = {}
    for t in (3, 4, 5, 6, 7, 8):
        cdf = sum((lam ** k) * math.exp(-lam) / math.factorial(k) for k in range(t))
        lines[t] = round((1 - cdf) * 100, 1)
    return {"expected": round(expected, 1), "lines": lines, "projected_ip": round(proj_ip, 1)}


def get_grade(salci: float) -> str:
    if salci >= 75: return "A"
    if salci >= 60: return "B"
    if salci >= 45: return "C"
    if salci >= 30: return "D"
    return "F"


# ─────────────────────────────────────────────────────────────────────────────
# BUILD PREDICTIONS
# ─────────────────────────────────────────────────────────────────────────────

def build_predictions(date_str: str) -> Dict:
    log(f"Building predictions for {date_str} …")
    games = get_games_by_date(date_str)
    log(f"  Found {len(games)} games")

    output = {
        "date":          date_str,
        "saved_at":      datetime.now().isoformat(),
        "model_version": "v1-standalone",
        "games_found":   len(games),
        "pitchers":      [],
    }

    for game in games:
        for side in ("home", "away"):
            opp_side = "away" if side == "home" else "home"
            pid          = game.get(f"{side}_pid")
            pitcher_name = game.get(f"{side}_pitcher", "TBD")
            team         = game.get(f"{side}_team")
            opp          = game.get(f"{opp_side}_team")
            opp_id       = game.get(f"{opp_side}_team_id")

            if not pid or pitcher_name == "TBD":
                continue

            log(f"  → {pitcher_name} ({team} vs {opp})")

            season_raw = get_player_season_stats(pid, CURRENT_SEASON)
            p_base     = parse_season_stats(season_raw) if season_raw else None
            p_rec      = get_recent_pitcher_stats(pid, 7)
            opp_stats  = get_team_batting_stats(opp_id, CURRENT_SEASON) if opp_id else None
            gp         = (p_rec or {}).get("games_sampled", 0)

            salci, breakdown, missing = compute_salci(
                p_rec, p_base, opp_stats, opp_stats, DEFAULT_WEIGHTS, gp
            )

            if salci is None:
                log(f"    Skipped (missing: {missing})")
                continue

            base_k9 = (p_base or p_rec or {}).get("K9", 9.0)
            proj    = project_lines(salci, base_k9)

            output["pitchers"].append({
                "pitcher_id":      pid,
                "pitcher_name":    pitcher_name,
                "pitcher_hand":    game.get(f"{side}_pitcher_hand", "R"),
                "team":            team,
                "opponent":        opp,
                "opponent_id":     opp_id,
                "game_pk":         game["game_pk"],
                "salci":           salci,
                "salci_grade":     get_grade(salci),
                "expected":        proj["expected"],
                "projected_ip":    proj["projected_ip"],
                "k_lines":         proj["lines"],
                "stuff_score":     None,
                "location_score":  None,
                "matchup_score":   None,
                "workload_score":  None,
                "is_statcast":     False,
                "breakdown":       breakdown,
                "missing_metrics": missing,
                "lineup_confirmed": False,
            })

    log(f"  {len(output['pitchers'])} pitchers ready")
    return output


# ─────────────────────────────────────────────────────────────────────────────
# PERSIST TO GITHUB
# ─────────────────────────────────────────────────────────────────────────────

def save_locally(date_str: str, data: Dict) -> str:
    ensure_dirs()
    path = os.path.join(PREDICTIONS_DIR, f"{date_str}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    log(f"  Saved → {path}")
    return path


def commit_to_github(local_path: str, repo_path: str, commit_msg: str) -> bool:
    """
    Push a file to GitHub via the Contents API.
    Requires env vars  GH_TOKEN  and  GH_REPO  (e.g. "username/salci-mlb").
    """
    token   = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    gh_repo = os.environ.get("GH_REPO")
    if not token or not gh_repo:
        log("  WARN: GH_TOKEN/GH_REPO not set — skipping GitHub commit")
        return False

    api_url = f"https://api.github.com/repos/{gh_repo}/contents/{repo_path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    # Check existing SHA (needed for updates)
    sha = None
    try:
        r = requests.get(api_url, headers=headers, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass

    payload = {"message": commit_msg, "content": content_b64}
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(api_url, headers=headers, json=payload, timeout=30)
        if r.status_code in (200, 201):
            log(f"  ✅ GitHub commit OK: {repo_path}")
            return True
        log(f"  ERROR: {r.status_code} — {r.text[:300]}")
        return False
    except Exception as e:
        log(f"  ERROR: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.today().strftime("%Y-%m-%d")
    log(f"=== save_predictions.py  date={date_str} ===")

    preds = build_predictions(date_str)
    if not preds["pitchers"]:
        log("No pitchers found — exiting")
        sys.exit(0)

    local = save_locally(date_str, preds)
    commit_to_github(
        local,
        f"data/predictions/{date_str}.json",
        f"chore(data): predictions {date_str} [{len(preds['pitchers'])} pitchers]",
    )
    log("=== Done ===")


if __name__ == "__main__":
    main()
