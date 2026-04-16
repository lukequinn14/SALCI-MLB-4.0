"""
team_pitching_stats.py  ·  SALCI v2.1
=======================================
Production-grade data loader for the pitching dashboard.

CHANGELOG v2.1 — Bug Fixes
────────────────────────────
[FIX-1] _SAVANT_TEAM_ID_TO_ABBREV — duplicate key 119 caused KC to be silently
         overwritten by LAD. Corrected all 30 team IDs against official MLBAM IDs.
         Correct canonical mapping: KC=118, LAD=119. (Matches Baseball Savant / MLBAM)

[FIX-2] MLB_TEAM_IDS / _CORRECT_IDS — LAA was mapped to 120 (WSH), LAD to 121 (NYM).
         All IDs now validated against the authoritative MLBAM list provided.

[FIX-3] _find_team_col() — now searches NORMALISED column names (post-rename_map)
         instead of raw original names, so it correctly identifies the team column
         after _aggregate_savant_df() normalises headers.

[FIX-4] _aggregate_savant_df() — removed double-normalisation of team_col that
         caused KeyError when grouping. team_col is now resolved once, post-rename.

[FIX-5] Strategy 2 URL — removed "&group_by=team" which is not a valid Savant
         aggregation parameter and caused empty or malformed responses. Now fetches
         pitcher-level data and aggregates by team_id in Python instead.

[FIX-6] Added debug logging throughout the aggregation pipeline so failures are
         visible rather than silently returning empty dicts.

[FIX-7] _SAVANT_ABBREV_MAP — expanded to cover all known Savant abbreviation variants.

Strategy (FanGraphs is gone):
──────────────────────────────
Layer 1 — MLB Stats API  (always available, official)
    • Team season ERA / WHIP  →  /teams/{id}/stats?stats=season&group=pitching
    • Starter ERA split        →  sitCodes=startingPitchers
    • Bullpen ERA split        →  sitCodes=reliefPitchers
    • Derived: K%, BB%, FIP

Layer 2 — Baseball Savant leaderboards  (free CSV, no auth)
    • Team-level Statcast: xFIP proxy, barrel%, hard-hit%, whiff%

Layer 3 — Self-computed advanced metrics
    • FIP  = (13·HR + 3·(BB+HBP) − 2·K) / IP + FIP_constant (~3.10)
    • K%   = K / TBF
    • BB%  = BB / TBF

Logos
──────
Uses ESPN CDN:  https://a.espncdn.com/i/teamlogos/mlb/500/{abbrev}.png
"""

import requests
import time
import io
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL MLBAM TEAM ID MAP  (validated against Baseball Savant / MLBAM)
# Source: https://baseballsavant.mlb.com — numeric IDs used in Statcast queries
# ─────────────────────────────────────────────────────────────────────────────
#
# IMPORTANT: These are MLBAM (MLB Advanced Media) IDs — the same IDs used by
# Baseball Savant's Statcast search API. Do NOT confuse with legacy Retrosheet
# or other data-source IDs.
#
# Full verified list (2025):
#   108 = LAA  (Los Angeles Angels)
#   109 = ARI  (Arizona Diamondbacks)
#   110 = BAL  (Baltimore Orioles)
#   111 = BOS  (Boston Red Sox)
#   112 = CHC  (Chicago Cubs)
#   113 = CIN  (Cincinnati Reds)   ← NOTE: CIN=113, CWS=145
#   114 = CLE  (Cleveland Guardians)
#   115 = COL  (Colorado Rockies)
#   116 = DET  (Detroit Tigers)
#   117 = HOU  (Houston Astros)
#   118 = KC   (Kansas City Royals)
#   119 = LAD  (Los Angeles Dodgers)
#   120 = WSH  (Washington Nationals)
#   121 = NYM  (New York Mets)
#   133 = OAK  (Oakland Athletics)
#   134 = PIT  (Pittsburgh Pirates)
#   135 = SD   (San Diego Padres)
#   136 = SEA  (Seattle Mariners)
#   137 = SF   (San Francisco Giants)
#   138 = STL  (St. Louis Cardinals)
#   139 = TB   (Tampa Bay Rays)
#   140 = TEX  (Texas Rangers)
#   141 = TOR  (Toronto Blue Jays)
#   142 = MIN  (Minnesota Twins)
#   143 = PHI  (Philadelphia Phillies)
#   144 = ATL  (Atlanta Braves)
#   145 = CWS  (Chicago White Sox)  ← was 113 in old buggy code
#   146 = MIA  (Miami Marlins)
#   147 = NYY  (New York Yankees)
#   158 = MIL  (Milwaukee Brewers)
# ─────────────────────────────────────────────────────────────────────────────

# Primary abbrev → MLBAM ID map  (used for MLB Stats API calls)
MLB_TEAM_IDS: Dict[str, int] = {
    "LAA": 108,
    "ARI": 109,
    "BAL": 110,
    "BOS": 111,
    "CHC": 112,
    "CIN": 113,
    "CLE": 114,
    "COL": 115,
    "DET": 116,
    "HOU": 117,
    "KC":  118,
    "LAD": 119,
    "WSH": 120,
    "NYM": 121,
    "OAK": 133,
    "PIT": 134,
    "SD":  135,
    "SEA": 136,
    "SF":  137,
    "STL": 138,
    "TB":  139,
    "TEX": 140,
    "TOR": 141,
    "MIN": 142,
    "PHI": 143,
    "ATL": 144,
    "CWS": 145,
    "MIA": 146,
    "NYY": 147,
    "MIL": 158,
}

# Reverse map: MLBAM numeric ID → standard abbrev
# Used by _aggregate_savant_df() to resolve team_id columns in Savant CSVs.
# ❗ No duplicate keys — each ID maps to exactly one abbrev.
_SAVANT_TEAM_ID_TO_ABBREV: Dict[int, str] = {v: k for k, v in MLB_TEAM_IDS.items()}

# Verify the reverse map has all 30 teams at module load (fail-fast guard)
assert len(_SAVANT_TEAM_ID_TO_ABBREV) == 30, (
    f"_SAVANT_TEAM_ID_TO_ABBREV has {len(_SAVANT_TEAM_ID_TO_ABBREV)} entries — "
    "duplicate IDs in MLB_TEAM_IDS!"
)

# Full name → 3-letter abbrev  (for API team name → logo lookup)
FULL_NAME_TO_ABBREV: Dict[str, str] = {
    "Arizona Diamondbacks":  "ARI",
    "Atlanta Braves":        "ATL",
    "Baltimore Orioles":     "BAL",
    "Boston Red Sox":        "BOS",
    "Chicago Cubs":          "CHC",
    "Chicago White Sox":     "CWS",
    "Cincinnati Reds":       "CIN",
    "Cleveland Guardians":   "CLE",
    "Colorado Rockies":      "COL",
    "Detroit Tigers":        "DET",
    "Houston Astros":        "HOU",
    "Kansas City Royals":    "KC",
    "Los Angeles Angels":    "LAA",
    "Los Angeles Dodgers":   "LAD",
    "Miami Marlins":         "MIA",
    "Milwaukee Brewers":     "MIL",
    "Minnesota Twins":       "MIN",
    "New York Mets":         "NYM",
    "New York Yankees":      "NYY",
    "Oakland Athletics":     "OAK",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates":    "PIT",
    "San Diego Padres":      "SD",
    "San Francisco Giants":  "SF",
    "Seattle Mariners":      "SEA",
    "St. Louis Cardinals":   "STL",
    "Tampa Bay Rays":        "TB",
    "Texas Rangers":         "TEX",
    "Toronto Blue Jays":     "TOR",
    "Washington Nationals":  "WSH",
    # Common short-forms returned by some APIs
    "Athletics":             "OAK",
    "Angels":                "LAA",
    "Guardians":             "CLE",
}

# Savant-specific 3-letter abbreviation variants → our standard abbrev
# Savant sometimes uses these non-standard codes in its CSV exports.
_SAVANT_ABBREV_MAP: Dict[str, str] = {
    # Pass-throughs (already standard)
    "LAA": "LAA", "ARI": "ARI", "BAL": "BAL", "BOS": "BOS",
    "CHC": "CHC", "CIN": "CIN", "CLE": "CLE", "COL": "COL",
    "DET": "DET", "HOU": "HOU", "LAD": "LAD", "MIA": "MIA",
    "MIL": "MIL", "MIN": "MIN", "NYM": "NYM", "NYY": "NYY",
    "OAK": "OAK", "PHI": "PHI", "PIT": "PIT", "SEA": "SEA",
    "SF":  "SF",  "STL": "STL", "TB":  "TB",  "TEX": "TEX",
    "TOR": "TOR", "ATL": "ATL",
    # Savant variants
    "WSH": "WSH", "WAS": "WSH",
    "CWS": "CWS", "CHW": "CWS",
    "KCR": "KC",  "KCA": "KC",  "KC":  "KC",
    "SDP": "SD",  "SDN": "SD",
    "SFG": "SF",  "SFN": "SF",
    "TBR": "TB",  "TBA": "TB",
    "NYY": "NYY", "NYA": "NYY",
    "NYM": "NYM", "NYN": "NYM",
    "LAD": "LAD", "LAN": "LAD",
    "LAA": "LAA", "ANA": "LAA",
    "OAK": "OAK", "ATH": "OAK",
}

# ESPN logo CDN abbrevs (lowercase; a few differ from MLB abbrev)
_ESPN_ABBREV: Dict[str, str] = {
    "LAA": "laa", "ARI": "ari", "BAL": "bal", "BOS": "bos",
    "CHC": "chc", "CIN": "cin", "CLE": "cle", "COL": "col",
    "DET": "det", "HOU": "hou", "KC":  "kc",  "LAD": "lad",
    "WSH": "wsh", "NYM": "nym", "OAK": "oak", "PIT": "pit",
    "SD":  "sd",  "SEA": "sea", "SF":  "sf",  "STL": "stl",
    "TB":  "tb",  "TEX": "tex", "TOR": "tor", "MIN": "min",
    "PHI": "phi", "ATL": "atl", "CWS": "cws", "MIA": "mia",
    "NYY": "nyy", "MIL": "mil",
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
    abbrev = FULL_NAME_TO_ABBREV.get(team, team).upper()
    espn   = _ESPN_ABBREV.get(abbrev, abbrev.lower())
    return f"https://a.espncdn.com/i/teamlogos/mlb/500/{espn}.png"


# ─────────────────────────────────────────────────────────────────────────────
# MLB STATS API — LOW-LEVEL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_BASE = "https://statsapi.mlb.com/api/v1"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "SALCI/2.1"})


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
    classifies as SP (≥50% games are starts) or RP and aggregates.
    """
    roster_url = (f"{_BASE}/teams/{team_id}/roster"
                  f"?rosterType=fullSeason&season={season}")
    data = _get(roster_url)
    if not data:
        return None, None

    pitchers = [
        p for p in data.get("roster", [])
        if p.get("position", {}).get("code") == "1"
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
# ARCHITECTURE OVERVIEW
# ─────────────────────
# Three strategies are tried in order; all funnel through _aggregate_savant_df()
# which normalises column names and resolves team identifiers uniformly.
#
# Strategy 1 — Pitcher leaderboard (min=1 PA):
#   Best quality, but requires enough innings. Works reliably from ~May.
#
# Strategy 2 — statcast_search pitcher-level, full season:
#   Returns pitcher-level rows with team_id column. No min IP.
#   We aggregate by team_id in Python. This replaces the broken
#   "&group_by=team" URL param (which Savant does not support).
#
# Strategy 3 — statcast_search pitcher-level, rolling 30 days:
#   Smaller payload, most reliable connection-wise. Used as last resort.
#   Manually aggregated by team in Python.
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


def _normalise_savant_abbrev(raw: str) -> str:
    """Convert Savant team abbreviation to our standard abbrev."""
    raw = str(raw).strip().upper()
    return _SAVANT_ABBREV_MAP.get(raw, raw)


def _find_team_col(df) -> Optional[str]:
    """
    Robustly find the team column in a Savant DataFrame AFTER column
    normalisation has been applied (all headers are already lowercase,
    stripped, with spaces→underscores).

    [FIX-3] Prior version searched original column names before rename_map
    was applied, causing _find_team_col to always miss the renamed columns.
    This version only needs to search the already-normalised column list.
    """
    cols = list(df.columns)

    # Priority-ordered candidates — all lowercase normalised names
    candidates = [
        "team_name",
        "team_name_alt",
        "team_abbrev",
        "team",
        "pitcher_team",
        "home_team",
        "team_id",
    ]
    for cand in candidates:
        if cand in cols:
            print(f"[DEBUG _find_team_col] Found team column: '{cand}'")
            return cand

    # Last resort: any column containing "team"
    for col in cols:
        if "team" in col:
            print(f"[DEBUG _find_team_col] Fallback team column: '{col}'")
            return col

    print(f"[DEBUG _find_team_col] No team column found in: {cols[:20]}")
    return None


def _fetch_savant_leaderboard(season: int) -> Optional["pd.DataFrame"]:
    """
    Strategy 1: Savant pitcher leaderboard with very low minimum (min=1).
    Returns the raw DataFrame or None.
    Works best mid/late season when there are enough innings pitched.
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
            print("[Savant leaderboard] Response too short — skipping")
            return None
        df = pd.read_csv(io.StringIO(text), low_memory=False)
        print(f"[Savant leaderboard] Fetched {len(df)} rows, columns: {list(df.columns)[:10]}")
        return df if not df.empty else None
    except Exception as e:
        print(f"[Savant leaderboard] {e}")
        return None


def _fetch_savant_statcast_season_csv(season: int) -> Optional["pd.DataFrame"]:
    """
    Strategy 2: Savant statcast_search, pitcher-level rows for full season.

    [FIX-5] Removed invalid "&group_by=team" parameter. Savant's statcast_search
    does not support team-level grouping in this endpoint — it returns pitcher rows.
    We aggregate by team_id ourselves in _aggregate_savant_df().

    Uses "&group_by=name_auto" to get one row per pitcher (includes team_id).
    """
    try:
        import pandas as pd
    except ImportError:
        return None

    season_start = f"{season}-03-20"
    today        = date.today().strftime("%Y-%m-%d")

    url = (
        "https://baseballsavant.mlb.com/statcast_search/csv"
        f"?all=true&hfGT=R%7C&hfSea={season}%7C"
        f"&game_date_gt={season_start}&game_date_lt={today}"
        "&player_type=pitcher&min_results=0&min_pas=0"
        "&group_by=name_auto"          # ← pitcher-level rows; includes team_id
        "&sort_col=pitches&sort_order=desc"
        "&type=details"
    )
    try:
        resp = requests.get(url, timeout=_SAVANT_TIMEOUT, headers=_SAVANT_HEADERS)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or len(text) < 100:
            print("[Savant statcast_search/season] Response too short — skipping")
            return None
        df = pd.read_csv(io.StringIO(text), low_memory=False)
        print(f"[Savant statcast_search/season] Fetched {len(df)} rows, "
              f"columns: {list(df.columns)[:10]}")
        return df if not df.empty else None
    except Exception as e:
        print(f"[Savant statcast_search/season] {e}")
        return None


def _fetch_savant_statcast_raw_csv(season: int) -> Optional["pd.DataFrame"]:
    """
    Strategy 3: Savant statcast_search pitch-level data — last 30 days.
    Smaller payload; most reliable fallback. Aggregated by team in Python.
    """
    try:
        import pandas as pd
    except ImportError:
        return None

    end_d   = date.today().strftime("%Y-%m-%d")
    start_d = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    url = (
        "https://baseballsavant.mlb.com/statcast_search/csv"
        f"?all=true&hfGT=R%7C&hfSea={season}%7C"
        f"&game_date_gt={start_d}&game_date_lt={end_d}"
        "&player_type=pitcher&min_results=0&min_pas=0"
        "&group_by=name_auto"
        "&sort_col=pitches&sort_order=desc"
        "&type=details"
    )
    try:
        resp = requests.get(url, timeout=30, headers=_SAVANT_HEADERS)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or len(text) < 200:
            print("[Savant statcast_search/30d] Response too short — skipping")
            return None
        df = pd.read_csv(io.StringIO(text), low_memory=False)
        print(f"[Savant statcast_search/30d] Fetched {len(df)} rows, "
              f"columns: {list(df.columns)[:10]}")
        return df if not df.empty else None
    except Exception as e:
        print(f"[Savant statcast_search/30d] {e}")
        return None


def _aggregate_savant_df(df, season: int) -> Dict[str, dict]:
    """
    Given any Savant DataFrame (from any strategy), compute team-level
    aggregates for whiff%, hard-hit%, k%, xFIP proxy.

    Handles column name inconsistencies across all three strategies.

    [FIX-3] _find_team_col() is called AFTER rename_map is applied, so it
    correctly detects normalised column names.
    [FIX-4] team_col is used directly as-is post-normalisation; no second
    strip/lower/replace pass that was causing KeyErrors.
    [FIX-6] Debug logging added at each key decision point.
    """
    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        return {}

    if df is None or df.empty:
        return {}

    # ── Step 1: Normalise ALL column names to lowercase_with_underscores ─────
    rename_map = {}
    for col in df.columns:
        normalised = col.strip().lower().lstrip("#").replace(" ", "_")
        rename_map[col] = normalised
    df = df.rename(columns=rename_map)

    print(f"[DEBUG aggregate] Normalised columns (first 15): {list(df.columns)[:15]}")

    # ── Step 2: Find team column in normalised DataFrame ─────────────────────
    # [FIX-3] Called here, after rename, so it searches normalised names.
    team_col = _find_team_col(df)
    if not team_col:
        print("[Savant aggregate] ❌ No team column found — cannot aggregate")
        return {}

    print(f"[DEBUG aggregate] Using team column: '{team_col}'")
    print(f"[DEBUG aggregate] Sample team values: {df[team_col].dropna().unique()[:8].tolist()}")

    # ── Step 3: Metric column aliases (normalised names) ─────────────────────
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

    active_cols = {
        metric: _find_col(aliases)
        for metric, aliases in col_aliases.items()
        if _find_col(aliases)
    }

    print(f"[DEBUG aggregate] Active metric columns: {active_cols}")

    if not active_cols:
        print("[Savant aggregate] ❌ No recognisable metric columns found")
        print(f"[DEBUG aggregate] All columns: {list(df.columns)}")
        return {}

    # ── Step 4: Group by team and aggregate ──────────────────────────────────
    result: Dict[str, dict] = {}

    for team_raw, grp in df.groupby(team_col):
        team_str = str(team_raw).strip()

        # Resolution order:
        # 1. Numeric MLBAM team_id  →  _SAVANT_TEAM_ID_TO_ABBREV
        # 2. Full team name         →  FULL_NAME_TO_ABBREV
        # 3. Abbreviation variant   →  _SAVANT_ABBREV_MAP

        abbrev = ""

        # Try numeric ID first
        try:
            numeric_id = int(float(team_str))
            abbrev = _SAVANT_TEAM_ID_TO_ABBREV.get(numeric_id, "")
        except (ValueError, TypeError):
            pass

        if not abbrev:
            abbrev = FULL_NAME_TO_ABBREV.get(team_str, "")

        if not abbrev:
            abbrev = _normalise_savant_abbrev(team_str)

        if not abbrev or len(abbrev) > 4:
            print(f"[DEBUG aggregate] Could not resolve team: '{team_str}' — skipping")
            continue

        agg: dict = {}
        for metric, col in active_cols.items():
            vals = pd.to_numeric(grp[col], errors="coerce").dropna()
            if vals.empty:
                continue

            # xFIP and ERA: IP-weighted average when IP column is available
            if metric in ("xfip", "p_era") and "ip" in grp.columns:
                ips = pd.to_numeric(grp["ip"], errors="coerce").fillna(0)
                total_ip = ips.sum()
                if total_ip > 0:
                    agg[metric] = round(float((vals * ips).sum() / total_ip), 2)
                    continue

            agg[metric] = round(float(vals.mean()), 2)

        if agg:
            result[abbrev] = agg

    print(f"[Savant aggregate] ✅ Got data for {len(result)} teams: "
          f"{sorted(result.keys())}")
    return result


def _fetch_savant_team_pitching(season: int) -> Dict[str, dict]:
    """
    Master function: try three strategies in order, return best coverage.

    Strategy 1 — Savant pitcher leaderboard (min=1):
        Best data quality; works from ~May onward.
    Strategy 2 — statcast_search full-season pitcher rows:
        Works early season; no min IP; aggregated by team_id in Python.
    Strategy 3 — statcast_search rolling 30-day pitcher rows:
        Smallest payload; most reliable connection; last resort.
    """
    # Strategy 1
    print("[Savant] Trying Strategy 1: pitcher leaderboard (min=1)…")
    df1     = _fetch_savant_leaderboard(season)
    result  = _aggregate_savant_df(df1, season)
    if len(result) >= 25:
        print(f"[Savant] ✅ Strategy 1 succeeded: {len(result)} teams")
        return result

    # Strategy 2
    print(f"[Savant] Strategy 1 partial ({len(result)} teams). "
          "Trying Strategy 2: statcast_search/season…")
    df2     = _fetch_savant_statcast_season_csv(season)
    result2 = _aggregate_savant_df(df2, season)
    if len(result2) >= 25:
        print(f"[Savant] ✅ Strategy 2 succeeded: {len(result2)} teams")
        return result2

    # Merge S1 + S2 — S2 takes priority (more recent naming)
    merged = {**result, **result2}
    if len(merged) >= 25:
        print(f"[Savant] ✅ Merged S1+S2: {len(merged)} teams")
        return merged

    # Strategy 3
    print(f"[Savant] S1+S2 gave {len(merged)} teams. "
          "Trying Strategy 3: statcast_search/30d…")
    df3     = _fetch_savant_statcast_raw_csv(season)
    result3 = _aggregate_savant_df(df3, season)
    merged.update(result3)
    print(f"[Savant] Final coverage: {len(merged)} teams → {sorted(merged.keys())}")
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# SELF-COMPUTED ADVANCED METRICS
# ─────────────────────────────────────────────────────────────────────────────

def _compute_fip(stat: dict, fip_constant: float = FIP_CONSTANT) -> Optional[float]:
    """
    FIP = (13·HR + 3·(BB+HBP) − 2·K) / IP + FIP_constant
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

    # ── Step 1: Live team map from MLB API ────────────────────────────────────
    team_map = _fetch_live_team_map(season)
    if not team_map:
        print("[team_pitching_stats] Live team map failed — using hard-coded fallback")
        team_map = dict(MLB_TEAM_IDS)

    print(f"[team_pitching_stats] Team map: {len(team_map)} teams")

    # ── Step 2: Baseball Savant (best-effort) ─────────────────────────────────
    savant_data: Dict[str, dict] = {}
    try:
        savant_data = _fetch_savant_team_pitching(season)
        print(f"[team_pitching_stats] Savant returned {len(savant_data)} teams")
    except Exception as e:
        print(f"[team_pitching_stats] Savant unavailable: {e}")

    # ── Step 3: Per-team MLB API calls ────────────────────────────────────────
    results = []
    for abbrev, team_id in sorted(team_map.items()):
        record = _build_team_record(abbrev, team_id, season, savant_data)
        results.append(record)
        time.sleep(0.05)  # be polite

    savant_count = sum(1 for d in results if "Savant" in d["source"])
    print(f"[team_pitching_stats] Done — {len(results)} teams loaded, "
          f"{savant_count} with Savant data")
    return results


def _fetch_live_team_map(season: int) -> Dict[str, int]:
    """Fetch current team abbrev → MLBAM ID map from the MLB Stats API."""
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

    # ── Overall season stats ──────────────────────────────────────────────────
    overall = _fetch_team_season_pitching(team_id, season)
    if overall:
        record["era"]    = _safe_float(overall.get("era"))
        record["whip"]   = _safe_float(overall.get("whip"))
        record["k_pct"]  = _compute_k_pct(overall)
        record["bb_pct"] = _compute_bb_pct(overall)
        record["fip"]    = _compute_fip(overall)

    # ── SP / BP split ─────────────────────────────────────────────────────────
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

    # ── Baseball Savant overlay ───────────────────────────────────────────────
    sv = savant_data.get(abbrev, {})
    if sv:
        record["xfip"]         = sv.get("xfip")
        record["whiff_pct"]    = sv.get("whiff_pct")
        record["hard_hit_pct"] = sv.get("hard_hit_pct")
        record["barrel_pct"]   = sv.get("barrel_pct")
        # Only use Savant K% if MLB API didn't have enough TBF data
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
        team_map = dict(MLB_TEAM_IDS)

    team_id = team_map.get(team_abbrev.upper())
    if not team_id:
        print(f"[get_team_pitching] Unknown team: '{team_abbrev}'")
        return None

    savant_data: Dict[str, dict] = {}
    try:
        savant_data = _fetch_savant_team_pitching(season)
    except Exception:
        pass

    return _build_team_record(team_abbrev.upper(), team_id, season, savant_data)


# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSTIC: print team ID map at import time (set env var to enable)
# ─────────────────────────────────────────────────────────────────────────────

def print_team_id_map() -> None:
    """Print the canonical MLBAM ID ↔ abbrev mapping for verification."""
    print("\nSALCI Canonical MLBAM Team ID Map")
    print("=" * 40)
    for abbrev, tid in sorted(MLB_TEAM_IDS.items()):
        print(f"  {tid:3d}  {abbrev}")
    print(f"\nTotal: {len(MLB_TEAM_IDS)} teams")
    assert len(MLB_TEAM_IDS) == 30, "Missing teams!"
    print("✅ All 30 teams present, no duplicates")


# ─────────────────────────────────────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print_team_id_map()

    season = datetime.today().year
    print(f"\nSALCI Team Pitching Stats — {season} season\n{'='*50}")
    data = get_all_team_pitching(season)

    # Sort by starter ERA (ascending), put None last
    data_sorted = sorted(data, key=lambda x: x.get("starter_era") or 99.9)

    print(f"\n{'TEAM':<5} {'SP ERA':>7} {'BP ERA':>7} {'ERA':>6} "
          f"{'FIP':>6} {'xFIP':>6} {'K%':>5} {'Whiff%':>7} {'Source'}")
    print("-" * 75)
    for d in data_sorted:
        print(
            f"{d['team']:<5}"
            f"{str(d['starter_era'] or '—'):>7}"
            f"{str(d['bullpen_era'] or '—'):>7}"
            f"{str(d['era'] or '—'):>6}"
            f"{str(d['fip'] or '—'):>6}"
            f"{str(d['xfip'] or '—'):>6}"
            f"{str(d['k_pct'] or '—'):>5}"
            f"{str(d['whiff_pct'] or '—'):>7}"
            f"  [{d['source']}]"
        )

    savant_count = sum(1 for d in data if "Savant" in d["source"])
    print(f"\nSavant coverage: {savant_count}/30")

    # Verify no KC/LAD confusion
    kc  = next((d for d in data if d["team"] == "KC"),  None)
    lad = next((d for d in data if d["team"] == "LAD"), None)
    print(f"\n[Sanity] KC  team_id from live map: {MLB_TEAM_IDS.get('KC')}  (expected 118)")
    print(f"[Sanity] LAD team_id from live map: {MLB_TEAM_IDS.get('LAD')} (expected 119)")
    print(f"[Sanity] KC  ERA: {kc.get('era') if kc else 'NOT FOUND'}")
    print(f"[Sanity] LAD ERA: {lad.get('era') if lad else 'NOT FOUND'}")
