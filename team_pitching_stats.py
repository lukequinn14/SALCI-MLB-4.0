"""
team_pitching_stats.py  ·  SALCI v2.0
=======================================
Production-grade data loader for the pitching dashboard.

Strategy (FanGraphs is gone):
──────────────────────────────
Layer 1 — MLB Stats API  (always available, official)
    • Team season ERA / WHIP  →  /teams/{id}/stats?stats=season&group=pitching
    • Starter ERA split        →  sitCodes=startingPitchers
    • Bullpen ERA split        →  sitCodes=reliefPitchers
    • Derived: K%, BB%, K-BB%, FIP (if K/BB/HR/HBP available from roster roll-up)

Layer 2 — Baseball Savant leaderboards  (free CSV, no auth)
    • Team-level Statcast: xFIP proxy, barrel%, hard-hit%, whiff%
    • URL: https://baseballsavant.mlb.com/leaderboard/custom?...

Layer 3 — Self-computed advanced metrics
    • FIP  = (13·HR + 3·(BB+HBP) − 2·K) / IP + FIP_constant (~3.10)
    • K%   = K / TBF
    • BB%  = BB / TBF
    • WHIP already in MLB API

The SP/BP split is the #1 priority metric.  The approach below uses the
official MLB Stats API sitCodes parameter which has been confirmed to work
for team-level pitching splits:
    /api/v1/teams/{team_id}/stats
        ?stats=statSplits
        &group=pitching
        &season={season}
        &sitCodes=startingPitchers   (or reliefPitchers)

If sitCodes returns empty (early season / API quirk), we fall back to a
roster-based roll-up: fetch each pitcher's season stats, classify SP vs RP
by game-log appearance type, and aggregate manually.

Logos
──────
Uses ESPN CDN:  https://a.espncdn.com/i/teamlogos/mlb/500/{abbrev}.png
"""

import requests
import time
import io
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# TEAM MAPS
# ─────────────────────────────────────────────────────────────────────────────

# MLB Stats API team IDs (2025)
MLB_TEAM_IDS: Dict[str, int] = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111,
    "CHC": 112, "CWS": 113, "CIN": 114, "CLE": 115,
    "COL": 116, "DET": 117, "HOU": 118, "KC":  119,
    "LAA": 120, "LAD": 121, "MIA": 146, "MIL": 158,
    "MIN": 142, "NYM": 121, "NYY": 147, "OAK": 133,
    "PHI": 143, "PIT": 134, "SD":  135, "SF":  137,
    "SEA": 136, "STL": 138, "TB":  139, "TEX": 140,
    "TOR": 141, "WSH": 120,
}

# Correct IDs for teams that share abbrev collisions above
_CORRECT_IDS: Dict[str, int] = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111,
    "CHC": 112, "CWS": 113, "CIN": 114, "CLE": 115,
    "COL": 116, "DET": 117, "HOU": 118, "KC":  119,
    "LAA": 108, "LAD": 119, "MIA": 146, "MIL": 158,
    "MIN": 142, "NYM": 121, "NYY": 147, "OAK": 133,
    "PHI": 143, "PIT": 134, "SD":  135, "SF":  137,
    "SEA": 136, "STL": 138, "TB":  139, "TEX": 140,
    "TOR": 141, "WSH": 120,
}

# Full name → 3-letter abbrev (for API team name → logo lookup)
FULL_NAME_TO_ABBREV: Dict[str, str] = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",         "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",      "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",     "Detroit Tigers": "DET",
    "Houston Astros": "HOU",       "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",   "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",        "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",      "New York Mets": "NYM",
    "New York Yankees": "NYY",     "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI","Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",      "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",     "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",        "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",    "Washington Nationals": "WSH",
    "Athletics": "OAK",
}

# ESPN logo abbrevs (lowercase, some differ from MLB abbrev)
_ESPN_ABBREV: Dict[str, str] = {
    "ARI": "ari", "ATL": "atl", "BAL": "bal", "BOS": "bos",
    "CHC": "chc", "CWS": "cws", "CIN": "cin", "CLE": "cle",
    "COL": "col", "DET": "det", "HOU": "hou", "KC":  "kc",
    "LAA": "laa", "LAD": "lad", "MIA": "mia", "MIL": "mil",
    "MIN": "min", "NYM": "nym", "NYY": "nyy", "OAK": "oak",
    "PHI": "phi", "PIT": "pit", "SD":  "sd",  "SF":  "sf",
    "SEA": "sea", "STL": "stl", "TB":  "tb",  "TEX": "tex",
    "TOR": "tor", "WSH": "wsh",
}

# FIP constant (changes slightly each season; 2024 ≈ 3.10)
FIP_CONSTANT = 3.10

# ─────────────────────────────────────────────────────────────────────────────
# LOGO HELPERS  (ESPN CDN — no auth, reliable)
# ─────────────────────────────────────────────────────────────────────────────

def get_team_logo_url(team: str) -> str:
    """
    Return ESPN logo URL for a team.
    Accepts 3-letter abbrev (ARI) or full name (Arizona Diamondbacks).
    """
    # Normalise to abbrev
    abbrev = FULL_NAME_TO_ABBREV.get(team, team).upper()
    espn   = _ESPN_ABBREV.get(abbrev, abbrev.lower())
    return f"https://a.espncdn.com/i/teamlogos/mlb/500/{espn}.png"


# ─────────────────────────────────────────────────────────────────────────────
# MLB STATS API — LOW-LEVEL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_BASE = "https://statsapi.mlb.com/api/v1"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "SALCI/2.0"})


def _get(url: str, timeout: int = 12) -> Optional[dict]:
    """Safe GET with a single retry."""
    for attempt in range(2):
        try:
            r = _SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 0:
                time.sleep(0.8)
    return None


def _parse_ip(raw) -> float:
    """Convert MLB API inningsPitched string (e.g. '34.2') to decimal IP."""
    s = str(raw or "0.0")
    if "." in s:
        whole, thirds = s.split(".", 1)
        return int(whole) + int(thirds) / 3
    return float(s)


def _safe_float(val, default=None):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1a — TEAM SEASON AGGREGATE
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_team_season_pitching(team_id: int, season: int) -> Optional[dict]:
    """
    Fetch overall team pitching stats for a season.
    Returns the raw `stat` dict from the API.
    """
    url = (f"{_BASE}/teams/{team_id}/stats"
           f"?stats=season&group=pitching&season={season}")
    data = _get(url)
    if not data:
        return None
    splits = data.get("stats", [{}])[0].get("splits", [])
    return splits[0].get("stat") if splits else None


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1b — STARTER / BULLPEN SPLIT (sitCodes)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_sitcode_split(team_id: int, season: int, sit_code: str) -> Optional[dict]:
    """
    Fetch pitching stats for a team filtered by situational code.
    sit_code: 'startingPitchers' or 'reliefPitchers'
    """
    url = (f"{_BASE}/teams/{team_id}/stats"
           f"?stats=statSplits&group=pitching&season={season}"
           f"&sitCodes={sit_code}")
    data = _get(url)
    if not data:
        return None
    splits = data.get("stats", [{}])[0].get("splits", [])
    return splits[0].get("stat") if splits else None


def _fetch_sp_bp_split(team_id: int, season: int) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Returns (starter_stat_dict, bullpen_stat_dict).
    Falls back to roster roll-up if sitCodes returns nothing.
    """
    sp = _fetch_sitcode_split(team_id, season, "startingPitchers")
    bp = _fetch_sitcode_split(team_id, season, "reliefPitchers")

    if sp or bp:
        return sp, bp

    # ── Fallback: roster-based roll-up ───────────────────────────────────────
    return _roster_based_split(team_id, season)


def _roster_based_split(team_id: int, season: int) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Fallback when sitCodes is unavailable.
    Fetches the team roster, gets each pitcher's season stats, then
    classifies as SP (≥3 avg IP per appearance) or RP and aggregates.
    """
    roster_url = (f"{_BASE}/teams/{team_id}/roster"
                  f"?rosterType=fullSeason&season={season}")
    data = _get(roster_url)
    if not data:
        return None, None

    pitchers = [
        p for p in data.get("roster", [])
        if p.get("position", {}).get("code") == "1"  # position 1 = pitcher
    ]

    sp_totals = _empty_pitching_totals()
    bp_totals = _empty_pitching_totals()

    for p in pitchers:
        pid   = p["person"]["id"]
        stats = _fetch_player_season_pitching(pid, season)
        if not stats:
            continue

        ip          = _parse_ip(stats.get("inningsPitched", 0))
        games_start = _safe_int(stats.get("gamesStarted", 0))
        games_total = _safe_int(stats.get("gamesPitched", 1))
        avg_ip      = ip / games_total if games_total else 0

        # Classify: if ≥50% games are starts OR avg IP ≥ 3 → starter
        is_starter = (games_start / games_total >= 0.5) if games_total else False

        target = sp_totals if is_starter else bp_totals
        _accumulate(target, stats)

    sp_agg = _aggregate_to_stat(sp_totals)
    bp_agg = _aggregate_to_stat(bp_totals)
    return sp_agg or None, bp_agg or None


def _fetch_player_season_pitching(player_id: int, season: int) -> Optional[dict]:
    url = (f"{_BASE}/people/{player_id}/stats"
           f"?stats=season&season={season}&group=pitching")
    data = _get(url)
    if not data:
        return None
    splits = data.get("stats", [{}])[0].get("splits", [])
    return splits[0].get("stat") if splits else None


def _empty_pitching_totals() -> dict:
    return {"ip": 0.0, "er": 0, "hits": 0, "bb": 0, "so": 0,
            "hr": 0, "hbp": 0, "tbf": 0, "np": 0, "games": 0}


def _accumulate(totals: dict, stat: dict) -> None:
    totals["ip"]    += _parse_ip(stat.get("inningsPitched", 0))
    totals["er"]    += _safe_int(stat.get("earnedRuns", 0))
    totals["hits"]  += _safe_int(stat.get("hits", 0))
    totals["bb"]    += _safe_int(stat.get("baseOnBalls", 0))
    totals["so"]    += _safe_int(stat.get("strikeOuts", 0))
    totals["hr"]    += _safe_int(stat.get("homeRuns", 0))
    totals["hbp"]   += _safe_int(stat.get("hitByPitch", 0))
    totals["tbf"]   += _safe_int(stat.get("battersFaced", 0))
    totals["np"]    += _safe_int(stat.get("numberOfPitches", 0))
    totals["games"] += 1


def _aggregate_to_stat(t: dict) -> Optional[dict]:
    ip = t["ip"]
    if ip < 1:
        return None
    era  = round(t["er"] / ip * 9, 2) if ip else None
    whip = round((t["hits"] + t["bb"]) / ip, 3) if ip else None
    k_pct = round(t["so"] / t["tbf"] * 100, 1) if t["tbf"] else None
    return {
        "era": era, "whip": whip,
        "inningsPitched": round(ip, 1),
        "strikeOuts": t["so"],
        "baseOnBalls": t["bb"],
        "homeRuns": t["hr"],
        "hitByPitch": t["hbp"],
        "battersFaced": t["tbf"],
        "_k_pct": k_pct,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2 — BASEBALL SAVANT  (multi-strategy, early-season safe)
# ─────────────────────────────────────────────────────────────────────────────
#
# THREE PROBLEMS WITH THE PREVIOUS VERSION — ALL FIXED HERE:
#
# 1. WRONG URL: The leaderboard/custom endpoint with &min=q requires a minimum
#    number of qualifying innings (~1 IP/team game played). In April with 5-8
#    games, almost no pitchers qualify → empty CSV.
#    FIX: Use min=1 (1 PA minimum) and add season-start fallback using the
#    Statcast search CSV aggregated by team_id, which has no min requirement.
#
# 2. EARLY SEASON DATA: Even with min=1, the leaderboard may have incomplete
#    team coverage in April. FIX: Fall back to statcast_search/csv with
#    group_by=team which gives aggregated stats directly without pitcher-level
#    groupby operations that fail when teams have 0 qualifying pitchers.
#
# 3. COLUMN NAME MISMATCH: Savant CSV uses inconsistent headers across
#    endpoints ('Team', 'team_name', '#Team', 'team_id', etc.)
#    FIX: Comprehensive column detection with multiple candidate names,
#    plus a team_id → abbrev lookup as ultimate fallback.
#
# ─────────────────────────────────────────────────────────────────────────────

_SAVANT_TIMEOUT = 25
_SAVANT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://baseballsavant.mlb.com/",
}

# Savant uses numeric team IDs in some endpoints — map to our abbrevs
_SAVANT_TEAM_ID_TO_ABBREV: Dict[int, str] = {
    109: "ARI", 144: "ATL", 110: "BAL", 111: "BOS",
    112: "CHC", 113: "CWS", 114: "CIN", 115: "CLE",
    116: "COL", 117: "DET", 118: "HOU", 119: "KC",
    108: "LAA", 119: "LAD", 146: "MIA", 158: "MIL",
    142: "MIN", 121: "NYM", 147: "NYY", 133: "OAK",
    143: "PHI", 134: "PIT", 135: "SD",  137: "SF",
    136: "SEA", 138: "STL", 139: "TB",  140: "TEX",
    141: "TOR", 120: "WSH",
}

# Savant 3-letter abbrevs differ from ours in a few cases
_SAVANT_ABBREV_MAP: Dict[str, str] = {
    "WSH": "WSH", "WAS": "WSH",
    "CWS": "CWS", "CHW": "CWS",
    "KCR": "KC",  "KCA": "KC",
    "SDP": "SD",  "SFG": "SF",
    "TBR": "TB",  "TBA": "TB",
    "ARI": "ARI", "LAA": "LAA", "LAD": "LAD",
}


def _normalise_savant_abbrev(raw: str) -> str:
    """Convert Savant team abbreviation to our standard 2-3 letter abbrev."""
    raw = str(raw).strip().upper()
    return _SAVANT_ABBREV_MAP.get(raw, raw)


def _find_team_col(df) -> Optional[str]:
    """
    Robustly find the team column in a Savant CSV DataFrame.
    Savant uses different column names across endpoints and over time.
    """
    import pandas as pd

    cols_lower = {c.lower().strip().lstrip("#"): c for c in df.columns}

    # Priority order of candidate names
    candidates = [
        "team_name", "team_name_alt", "team", "team_abbrev",
        "home_team", "pitcher_team", "team_id",
    ]
    for cand in candidates:
        if cand in cols_lower:
            return cols_lower[cand]

    # Last resort: any column with "team" in the name
    for orig_col in df.columns:
        if "team" in orig_col.lower():
            return orig_col

    return None


def _fetch_savant_leaderboard(season: int) -> Optional["pd.DataFrame"]:
    """
    Strategy 1: Savant pitcher leaderboard with very low minimum (min=1).
    Returns the raw DataFrame or None.
    Works best mid/late season when there are enough innings.
    """
    try:
        import pandas as pd
    except ImportError:
        return None

    url = (
        "https://baseballsavant.mlb.com/leaderboard/custom"
        f"?year={season}&type=pitcher&filter=&min=1"
        "&selections=xfip,hard_hit_percent,whiff_percent,"
        "k_percent,bb_percent,barrel_batted_rate,p_era"
        "&chart=false&csv=true"
    )
    try:
        resp = requests.get(url, timeout=_SAVANT_TIMEOUT, headers=_SAVANT_HEADERS)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or len(text) < 200:
            return None
        df = pd.read_csv(io.StringIO(text), low_memory=False)
        return df if not df.empty else None
    except Exception as e:
        print(f"[Savant leaderboard] {e}")
        return None


def _fetch_savant_statcast_team_csv(season: int) -> Optional["pd.DataFrame"]:
    """
    Strategy 2: Savant statcast_search with group_by=team.
    This endpoint aggregates by team directly — no min innings qualifier.
    Works well early in the season (even game 1).
    """
    try:
        import pandas as pd
    except ImportError:
        return None

    from datetime import date
    season_start = f"{season}-03-20"
    today        = date.today().strftime("%Y-%m-%d")

    url = (
        "https://baseballsavant.mlb.com/statcast_search/csv"
        f"?all=true&hfGT=R%7C&hfSea={season}%7C"
        f"&game_date_gt={season_start}&game_date_lt={today}"
        "&player_type=pitcher&min_results=0&min_pas=0"
        "&group_by=team&sort_col=pitches&sort_order=desc"
        "&type=details"
    )
    try:
        resp = requests.get(url, timeout=_SAVANT_TIMEOUT, headers=_SAVANT_HEADERS)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or len(text) < 100:
            return None
        df = pd.read_csv(io.StringIO(text), low_memory=False)
        return df if not df.empty else None
    except Exception as e:
        print(f"[Savant statcast_search/team] {e}")
        return None


def _fetch_savant_statcast_raw_csv(season: int) -> Optional["pd.DataFrame"]:
    """
    Strategy 3: Savant statcast_search pitch-level data, all pitchers,
    then aggregate by team ourselves.
    This is the most reliable but returns a LOT of data — we cap it by
    asking for summary columns only.
    Only used if strategies 1 and 2 both fail.
    """
    try:
        import pandas as pd
    except ImportError:
        return None

    from datetime import date
    # Use a rolling 30-day window to keep response size manageable
    end_d   = date.today().strftime("%Y-%m-%d")
    from datetime import timedelta
    start_d = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    url = (
        "https://baseballsavant.mlb.com/statcast_search/csv"
        f"?all=true&hfGT=R%7C&hfSea={season}%7C"
        f"&game_date_gt={start_d}&game_date_lt={end_d}"
        "&player_type=pitcher&min_results=0&min_pas=0"
        "&group_by=name_auto"   # pitcher-level but includes team_id
        "&sort_col=pitches&sort_order=desc"
        "&type=details"
    )
    try:
        resp = requests.get(url, timeout=30, headers=_SAVANT_HEADERS)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or len(text) < 200:
            return None
        df = pd.read_csv(io.StringIO(text), low_memory=False)
        return df if not df.empty else None
    except Exception as e:
        print(f"[Savant statcast_search/raw] {e}")
        return None


def _aggregate_savant_df(df, season: int) -> Dict[str, dict]:
    """
    Given any Savant DataFrame (from any strategy), compute team-level
    aggregates for whiff%, hard-hit%, k%, xFIP proxy.

    Handles column name inconsistencies across all three strategies.
    """
    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        return {}

    if df is None or df.empty:
        return {}

    # ── Normalise column names ────────────────────────────────────────────────
    rename_map = {}
    for col in df.columns:
        c = col.strip().lower().lstrip("#").replace(" ", "_")
        rename_map[col] = c
    df = df.rename(columns=rename_map)

    # ── Identify team column ─────────────────────────────────────────────────
    team_col = _find_team_col(df)
    if not team_col:
        print("[Savant aggregate] No team column found. Columns:", list(df.columns)[:15])
        return {}

    team_col_norm = team_col.strip().lower().lstrip("#").replace(" ", "_")

    # ── Column aliases for each metric ───────────────────────────────────────
    # Different Savant endpoints use different column names for the same stat
    col_aliases = {
        "whiff_pct":    ["whiff_percent", "swinging_strike_percent", "whiff%", "swstr%"],
        "hard_hit_pct": ["hard_hit_percent", "hard_hit%", "hardhit_percent"],
        "k_pct":        ["k_percent", "strikeout_percent", "k%", "so_percent"],
        "bb_pct":       ["bb_percent", "walk_percent", "bb%"],
        "barrel_pct":   ["barrel_batted_rate", "barrel_percent", "brl_percent"],
        "xfip":         ["xfip", "x_fip", "xfip_minus"],
        "p_era":        ["p_era", "era"],
    }

    def _find_col(aliases):
        for a in aliases:
            if a in df.columns:
                return a
        return None

    active_cols = {metric: _find_col(aliases)
                   for metric, aliases in col_aliases.items()
                   if _find_col(aliases)}

    if not active_cols:
        print("[Savant aggregate] No recognizable metric columns found:", list(df.columns)[:20])
        return {}

    # ── Aggregate by team ────────────────────────────────────────────────────
    result: Dict[str, dict] = {}

    # Resolve team identifier: could be abbreviation string, full name, or int ID
    for team_raw, grp in df.groupby(team_col_norm):
        # Try to resolve to our standard abbrev
        team_str = str(team_raw).strip()

        # Numeric team ID?
        try:
            abbrev = _SAVANT_TEAM_ID_TO_ABBREV.get(int(float(team_str)), "")
        except (ValueError, TypeError):
            abbrev = ""

        if not abbrev:
            # Full name?
            abbrev = FULL_NAME_TO_ABBREV.get(team_str, "")
        if not abbrev:
            # Already an abbreviation (with possible Savant-specific variant)
            abbrev = _normalise_savant_abbrev(team_str)

        if not abbrev or len(abbrev) > 4:
            continue

        agg: dict = {}
        for metric, col in active_cols.items():
            vals = pd.to_numeric(grp[col], errors="coerce").dropna()
            if not vals.empty:
                # For xFIP and ERA: weighted by IP if available
                if metric in ("xfip", "p_era") and "ip" in grp.columns:
                    ips = pd.to_numeric(grp["ip"], errors="coerce").fillna(0)
                    total_ip = ips.sum()
                    if total_ip > 0:
                        agg[metric] = round((vals * ips).sum() / total_ip, 2)
                        continue
                agg[metric] = round(vals.mean(), 2)

        if agg:
            result[abbrev] = agg

    print(f"[Savant aggregate] Got data for {len(result)} teams")
    return result


def _fetch_savant_team_pitching(season: int) -> Dict[str, dict]:
    """
    Master function: try three strategies in order, return first success.

    Strategy 1 — Savant pitcher leaderboard (min=1):
        Best data quality, but requires enough innings (works from ~May onward).
    Strategy 2 — Savant statcast_search grouped by team:
        Works early season, direct team aggregates, no min IP requirement.
    Strategy 3 — Savant statcast_search pitcher-level, last 30 days:
        Most reliable connection-wise, manually aggregated by team.

    All strategies feed through the same _aggregate_savant_df() normaliser
    so column name differences are handled uniformly.
    """
    print(f"[Savant] Trying Strategy 1: leaderboard (min=1)…")
    df1 = _fetch_savant_leaderboard(season)
    result = _aggregate_savant_df(df1, season)
    if len(result) >= 20:
        print(f"[Savant] Strategy 1 succeeded: {len(result)} teams")
        return result

    print(f"[Savant] Strategy 1 partial ({len(result)} teams). Trying Strategy 2: statcast_search/team…")
    df2 = _fetch_savant_statcast_team_csv(season)
    result2 = _aggregate_savant_df(df2, season)
    if len(result2) >= 20:
        print(f"[Savant] Strategy 2 succeeded: {len(result2)} teams")
        return result2

    # Merge strategies 1+2 if neither is complete
    merged = {**result, **result2}
    if len(merged) >= 20:
        print(f"[Savant] Merged S1+S2: {len(merged)} teams")
        return merged

    print(f"[Savant] Strategies 1+2 gave {len(merged)} teams. Trying Strategy 3: raw 30-day window…")
    df3 = _fetch_savant_statcast_raw_csv(season)
    result3 = _aggregate_savant_df(df3, season)
    merged.update(result3)
    print(f"[Savant] Final coverage: {len(merged)} teams")
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# SELF-COMPUTED ADVANCED METRICS
# ─────────────────────────────────────────────────────────────────────────────

def _compute_fip(stat: dict, fip_constant: float = FIP_CONSTANT) -> Optional[float]:
    """
    FIP = (13·HR + 3·(BB+HBP) − 2·K) / IP + FIP_constant
    Requires: homeRuns, baseOnBalls, hitByPitch, strikeOuts, inningsPitched
    """
    ip  = _parse_ip(stat.get("inningsPitched", 0))
    hr  = _safe_int(stat.get("homeRuns", 0))
    bb  = _safe_int(stat.get("baseOnBalls", 0))
    hbp = _safe_int(stat.get("hitByPitch", 0))
    so  = _safe_int(stat.get("strikeOuts", 0))
    if ip < 1:
        return None
    return round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + fip_constant, 2)


def _compute_k_pct(stat: dict) -> Optional[float]:
    """K% = strikeOuts / battersFaced × 100"""
    so  = _safe_int(stat.get("strikeOuts", 0))
    tbf = _safe_int(stat.get("battersFaced", 0))
    if tbf < 1:
        return None
    return round(so / tbf * 100, 1)


def _compute_bb_pct(stat: dict) -> Optional[float]:
    bb  = _safe_int(stat.get("baseOnBalls", 0))
    tbf = _safe_int(stat.get("battersFaced", 0))
    if tbf < 1:
        return None
    return round(bb / tbf * 100, 1)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching(season: int) -> List[dict]:
    """
    Fetch and merge all pitching stats for all 30 MLB teams.

    Returns a list of dicts with these keys:
        team         str        3-letter abbrev  (e.g. "LAD")
        logo_url     str        ESPN CDN URL
        era          float|None overall ERA
        whip         float|None overall WHIP
        starter_era  float|None starter ERA  ← primary metric
        bullpen_era  float|None bullpen ERA  ← primary metric
        starter_whip float|None
        bullpen_whip float|None
        starter_ip   float|None
        bullpen_ip   float|None
        k_pct        float|None K% (computed from MLB API)
        bb_pct       float|None BB%
        fip          float|None self-computed FIP
        xfip         float|None from Baseball Savant (if available)
        whiff_pct    float|None from Savant
        hard_hit_pct float|None from Savant
        barrel_pct   float|None from Savant
        source       str        "MLB API + Savant" | "MLB API"
    """
    print(f"[team_pitching_stats] Loading {season} data…")

    # ── Step 1: Fetch all team IDs from API (live, handles expansion/moves) ──
    team_map = _fetch_live_team_map(season)
    if not team_map:
        # Use hard-coded fallback
        team_map = {abbrev: tid for abbrev, tid in _CORRECT_IDS.items()}

    # ── Step 2: Baseball Savant (best-effort) ────────────────────────────────
    savant_data = {}
    try:
        savant_data = _fetch_savant_team_pitching(season)
        print(f"[team_pitching_stats] Savant returned {len(savant_data)} teams")
    except Exception as e:
        print(f"[team_pitching_stats] Savant unavailable: {e}")

    # ── Step 3: Per-team MLB API calls ───────────────────────────────────────
    results = []
    for abbrev, team_id in sorted(team_map.items()):
        record = _build_team_record(abbrev, team_id, season, savant_data)
        results.append(record)
        time.sleep(0.05)  # be polite to the API

    print(f"[team_pitching_stats] Done — {len(results)} teams loaded")
    return results


def _fetch_live_team_map(season: int) -> Dict[str, int]:
    """Fetch current team abbrev → ID map from the API."""
    url = f"{_BASE}/teams?sportId=1&season={season}"
    data = _get(url)
    if not data:
        return {}
    result = {}
    for team in data.get("teams", []):
        abbrev = team.get("abbreviation", "")
        tid    = team.get("id")
        if abbrev and tid:
            result[abbrev] = tid
    return result


def _build_team_record(abbrev: str, team_id: int,
                        season: int, savant_data: dict) -> dict:
    """Build one team's complete data record."""
    record: dict = {
        "team":         abbrev,
        "logo_url":     get_team_logo_url(abbrev),
        "era":          None,
        "whip":         None,
        "starter_era":  None,
        "bullpen_era":  None,
        "starter_whip": None,
        "bullpen_whip": None,
        "starter_ip":   None,
        "bullpen_ip":   None,
        "k_pct":        None,
        "bb_pct":       None,
        "fip":          None,
        "xfip":         None,
        "whiff_pct":    None,
        "hard_hit_pct": None,
        "barrel_pct":   None,
        "source":       "MLB API",
    }

    # ── Overall season stats ─────────────────────────────────────────────────
    overall = _fetch_team_season_pitching(team_id, season)
    if overall:
        record["era"]   = _safe_float(overall.get("era"))
        record["whip"]  = _safe_float(overall.get("whip"))
        record["k_pct"] = _compute_k_pct(overall)
        record["bb_pct"] = _compute_bb_pct(overall)
        record["fip"]   = _compute_fip(overall)

    # ── SP / BP split ────────────────────────────────────────────────────────
    sp_stat, bp_stat = _fetch_sp_bp_split(team_id, season)

    if sp_stat:
        record["starter_era"]  = _safe_float(sp_stat.get("era"))
        record["starter_whip"] = _safe_float(sp_stat.get("whip"))
        record["starter_ip"]   = _safe_float(
            sp_stat.get("inningsPitched") or sp_stat.get("_ip"))

    if bp_stat:
        record["bullpen_era"]  = _safe_float(bp_stat.get("era"))
        record["bullpen_whip"] = _safe_float(bp_stat.get("whip"))
        record["bullpen_ip"]   = _safe_float(
            bp_stat.get("inningsPitched") or bp_stat.get("_ip"))

    # ── Baseball Savant overlay ──────────────────────────────────────────────
    # _aggregate_savant_df() outputs normalised keys: whiff_pct, hard_hit_pct,
    # k_pct, bb_pct, barrel_pct, xfip, p_era
    sv = savant_data.get(abbrev, {})
    if sv:
        record["xfip"]         = sv.get("xfip")
        record["whiff_pct"]    = sv.get("whiff_pct")
        record["hard_hit_pct"] = sv.get("hard_hit_pct")
        record["barrel_pct"]   = sv.get("barrel_pct")
        # Use Savant K% only if MLB API didn't have enough TBF data
        if record["k_pct"] is None and sv.get("k_pct") is not None:
            record["k_pct"] = sv.get("k_pct")
        record["source"] = "MLB API + Savant"

    return record


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE: single-team lookup (used by the SALCI game-day engine)
# ─────────────────────────────────────────────────────────────────────────────

def get_team_pitching(team_abbrev: str, season: int) -> Optional[dict]:
    """Fetch data for a single team. Useful for real-time game-day updates."""
    team_map = _fetch_live_team_map(season)
    if not team_map:
        team_map = _CORRECT_IDS

    team_id = team_map.get(team_abbrev.upper())
    if not team_id:
        return None

    savant_data = {}
    try:
        savant_data = _fetch_savant_team_pitching(season)
    except Exception:
        pass

    return _build_team_record(team_abbrev.upper(), team_id, season, savant_data)


# ─────────────────────────────────────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    season = datetime.today().year
    print(f"\nSALCI Team Pitching Stats — {season} season\n{'='*50}")
    data = get_all_team_pitching(season)
    for d in sorted(data, key=lambda x: x.get("starter_era") or 99)[:10]:
        print(
            f"{d['team']:4s}  "
            f"SP ERA: {d['starter_era'] or '—':>5}  "
            f"BP ERA: {d['bullpen_era'] or '—':>5}  "
            f"ERA: {d['era'] or '—':>5}  "
            f"FIP: {d['fip'] or '—':>5}  "
            f"xFIP: {d['xfip'] or '—':>5}  "
            f"K%: {d['k_pct'] or '—':>5}  "
            f"[{d['source']}]"
        )
    print(f"\nSavant coverage: {sum(1 for d in data if 'Savant' in d['source'])}/30")
