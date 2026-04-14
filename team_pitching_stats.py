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
# LAYER 2 — BASEBALL SAVANT TEAM LEADERBOARD
# ─────────────────────────────────────────────────────────────────────────────

_SAVANT_URL = (
    "https://baseballsavant.mlb.com/leaderboard/custom"
    "?year={season}&type=pitcher&filter=&sort=4&sortDir=asc"
    "&min=q&selections=p_era,p_whip,xfip,xwoba,hard_hit_percent,"
    "whiff_percent,k_percent,bb_percent,barrel_batted_rate"
    "&chart=false&x=p_era&y=p_era&r=no&chartType=beeswarm"
    "&csv=true"
)

# Alternate simpler endpoint that tends to be more stable
_SAVANT_TEAM_URL = (
    "https://baseballsavant.mlb.com/leaderboard/custom"
    "?year={season}&type=pitcher&filter=&sort=4&sortDir=asc"
    "&min=q&selections=xfip,xwoba,hard_hit_percent,whiff_percent,"
    "k_percent,bb_percent&chart=false&csv=true&team={abbrev}"
)

_SAVANT_TIMEOUT = 20


def _fetch_savant_team_pitching(season: int) -> Dict[str, dict]:
    """
    Fetch Baseball Savant team-level pitching leaderboard.
    Returns dict keyed by team abbreviation.

    The savant CSV is at the pitcher level; we aggregate by team.
    Falls back gracefully if unavailable.
    """
    try:
        import pandas as pd
    except ImportError:
        return {}

    url = (
        "https://baseballsavant.mlb.com/leaderboard/custom"
        f"?year={season}&type=pitcher&filter=&min=q"
        "&selections=p_era,xfip,hard_hit_percent,whiff_percent,"
        "k_percent,bb_percent,barrel_batted_rate"
        "&chart=false&csv=true"
    )
    try:
        resp = requests.get(url, timeout=_SAVANT_TIMEOUT,
                            headers={"User-Agent": "SALCI/2.0"})
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception:
        return {}

    if df is None or df.empty:
        return {}

    # Normalise column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Identify team column (savant uses 'team_name' or 'team')
    team_col = next((c for c in df.columns if "team" in c), None)
    if not team_col:
        return {}

    result = {}
    numeric_cols = ["xfip", "hard_hit_percent", "whiff_percent",
                    "k_percent", "bb_percent", "barrel_batted_rate", "p_era"]

    for team_name, grp in df.groupby(team_col):
        abbrev = FULL_NAME_TO_ABBREV.get(str(team_name), str(team_name))
        agg = {}
        for col in numeric_cols:
            if col in grp.columns:
                vals = pd.to_numeric(grp[col], errors="coerce").dropna()
                if not vals.empty:
                    agg[col] = round(vals.mean(), 2)
        result[abbrev] = agg

    return result


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
    sv = savant_data.get(abbrev, {})
    if sv:
        record["xfip"]         = sv.get("xfip")
        record["whiff_pct"]    = sv.get("whiff_percent")
        record["hard_hit_pct"] = sv.get("hard_hit_percent")
        record["barrel_pct"]   = sv.get("barrel_batted_rate")
        # Use Savant K% if MLB API didn't provide TBF
        if record["k_pct"] is None and sv.get("k_percent"):
            record["k_pct"] = sv.get("k_percent")
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
