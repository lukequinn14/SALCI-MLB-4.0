"""
SALCI Team Pitching Stats Module
==================================
ARCHITECTURE: Pre-compute on GitHub Actions, read at runtime.

WHY:
  Streamlit Cloud runs behind an egress proxy that blocks fangraphs.com.
  statsapi.mlb.com IS reachable from Streamlit Cloud.
  GitHub Actions runners have unrestricted internet access.

FLOW:
  1. GitHub Actions runs fetch_team_pitching_action.py daily at 6 AM ET
     → scrapes FanGraphs for ERA, FIP, xFIP, K%, starter/bullpen split
     → commits data/team_pitching/YYYY-MM-DD.json to the repo

  2. This module (runs inside Streamlit Cloud):
     → reads data/team_pitching/latest.json  (symlinked by the Action)
     → falls back to MLB Stats API if file is missing/stale
     → MLB API gives ERA, WHIP, K/9 — no FIP/xFIP but always live

RESULT: Streamlit Cloud gets FanGraphs-quality data without hitting fangraphs.com.
"""

import json
import math
import os
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

_REPO_ROOT   = os.path.join(os.path.dirname(__file__))
_DATA_DIR    = os.path.join(_REPO_ROOT, "data", "team_pitching")
_LATEST_FILE = os.path.join(_DATA_DIR, "latest.json")

SEASON       = datetime.today().year
FIP_CONSTANT = 3.10

MLB_TEAMS = [
    {"id": 109, "abbr": "ARI", "name": "Arizona Diamondbacks"},
    {"id": 144, "abbr": "ATL", "name": "Atlanta Braves"},
    {"id": 110, "abbr": "BAL", "name": "Baltimore Orioles"},
    {"id": 111, "abbr": "BOS", "name": "Boston Red Sox"},
    {"id": 112, "abbr": "CHC", "name": "Chicago Cubs"},
    {"id": 145, "abbr": "CWS", "name": "Chicago White Sox"},
    {"id": 113, "abbr": "CIN", "name": "Cincinnati Reds"},
    {"id": 114, "abbr": "CLE", "name": "Cleveland Guardians"},
    {"id": 115, "abbr": "COL", "name": "Colorado Rockies"},
    {"id": 116, "abbr": "DET", "name": "Detroit Tigers"},
    {"id": 117, "abbr": "HOU", "name": "Houston Astros"},
    {"id": 118, "abbr": "KC",  "name": "Kansas City Royals"},
    {"id": 108, "abbr": "LAA", "name": "Los Angeles Angels"},
    {"id": 119, "abbr": "LAD", "name": "Los Angeles Dodgers"},
    {"id": 146, "abbr": "MIA", "name": "Miami Marlins"},
    {"id": 158, "abbr": "MIL", "name": "Milwaukee Brewers"},
    {"id": 142, "abbr": "MIN", "name": "Minnesota Twins"},
    {"id": 121, "abbr": "NYM", "name": "New York Mets"},
    {"id": 147, "abbr": "NYY", "name": "New York Yankees"},
    {"id": 133, "abbr": "OAK", "name": "Oakland Athletics"},
    {"id": 143, "abbr": "PHI", "name": "Philadelphia Phillies"},
    {"id": 134, "abbr": "PIT", "name": "Pittsburgh Pirates"},
    {"id": 135, "abbr": "SD",  "name": "San Diego Padres"},
    {"id": 137, "abbr": "SF",  "name": "San Francisco Giants"},
    {"id": 136, "abbr": "SEA", "name": "Seattle Mariners"},
    {"id": 138, "abbr": "STL", "name": "St. Louis Cardinals"},
    {"id": 139, "abbr": "TB",  "name": "Tampa Bay Rays"},
    {"id": 140, "abbr": "TEX", "name": "Texas Rangers"},
    {"id": 141, "abbr": "TOR", "name": "Toronto Blue Jays"},
    {"id": 120, "abbr": "WAS", "name": "Washington Nationals"},
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _safe(val, digits: int = 2) -> Optional[float]:
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, digits)
    except Exception:
        return None


def _parse_ip(ip_str) -> float:
    try:
        parts = str(ip_str).split(".")
        return int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 1 — Pre-computed JSON (written by GitHub Actions)
# ─────────────────────────────────────────────────────────────────────────────

def _load_precomputed() -> Optional[List[Dict]]:
    """
    Load the pre-computed team pitching data from data/team_pitching/latest.json.
    Returns None if the file doesn't exist or is more than 2 days stale.
    """
    if not os.path.exists(_LATEST_FILE):
        print(f"  [team_pitching] No precomputed file at {_LATEST_FILE}")
        return None

    try:
        with open(_LATEST_FILE) as f:
            data = json.load(f)

        # Staleness check — if saved_at is more than 2 days ago, flag it
        saved_at = data.get("saved_at", "")
        if saved_at:
            age = datetime.now() - datetime.fromisoformat(saved_at)
            if age > timedelta(days=2):
                print(f"  [team_pitching] Precomputed file is {age.days}d old — may be stale")

        teams = data.get("teams", [])
        if teams:
            print(f"  [team_pitching] Loaded {len(teams)} teams from precomputed file "
                  f"(saved {saved_at[:10]})")
            return teams

    except Exception as e:
        print(f"  [team_pitching] Error reading precomputed file: {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 2 — MLB Stats API (live fallback, always reachable from Streamlit Cloud)
# ─────────────────────────────────────────────────────────────────────────────

def _mlb_split(team_id: int, season: int, sit_code: str) -> Optional[Dict]:
    url = (
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
        f"?stats=season&season={season}&group=pitching&sitCodes={sit_code}"
    )
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        s   = splits[0]["stat"]
        ip  = _parse_ip(s.get("inningsPitched", "0.0"))
        if ip < 1:
            return None
        so  = int(s.get("strikeOuts",  0))
        bb  = int(s.get("baseOnBalls", 0))
        hbp = int(s.get("hitBatsmen",  0))
        hr  = int(s.get("homeRuns",    0))
        er  = int(s.get("earnedRuns",  0))
        h   = int(s.get("hits",        0))
        tbf = int(s.get("battersFaced", 1))
        era   = _safe(s.get("era")) or (round(er / ip * 9, 2) if ip > 0 else None)
        whip  = _safe(s.get("whip")) or (round((bb + h) / ip, 2) if ip > 0 else None)
        k_pct = round(so / tbf * 100, 1) if tbf > 0 else None
        k9    = round(so / ip * 9, 1) if ip > 0 else None
        fip   = round((13*hr + 3*(bb+hbp) - 2*so) / ip + FIP_CONSTANT, 2) if ip > 0 else None
        return {
            "era": era, "whip": whip, "k_pct": k_pct,
            "k9": k9, "fip": fip, "ip": round(ip, 1),
        }
    except Exception:
        return None


def _mlb_overall(team_id: int, season: int) -> Optional[Dict]:
    url = (
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
        f"?stats=season&season={season}&group=pitching"
    )
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        s  = splits[0]["stat"]
        ip = _parse_ip(s.get("inningsPitched", "0.0"))
        if ip < 1:
            return None
        so  = int(s.get("strikeOuts",  0))
        bb  = int(s.get("baseOnBalls", 0))
        hbp = int(s.get("hitBatsmen",  0))
        hr  = int(s.get("homeRuns",    0))
        er  = int(s.get("earnedRuns",  0))
        h   = int(s.get("hits",        0))
        tbf = int(s.get("battersFaced", 1))
        era   = _safe(s.get("era")) or round(er / ip * 9, 2)
        whip  = _safe(s.get("whip")) or round((bb + h) / ip, 2)
        k_pct = round(so / tbf * 100, 1) if tbf > 0 else None
        k9    = round(so / ip * 9, 1)
        fip   = round((13*hr + 3*(bb+hbp) - 2*so) / ip + FIP_CONSTANT, 2)
        return {
            "era": era, "whip": whip, "k_pct": k_pct,
            "k9": k9, "fip": fip, "source": "mlb_api",
        }
    except Exception as e:
        print(f"  MLB API error team {team_id}: {e}")
        return None


def _fetch_league_era(season: int) -> float:
    try:
        r = requests.get(
            f"https://statsapi.mlb.com/api/v1/stats"
            f"?stats=season&season={season}&group=pitching"
            f"&gameType=R&sportId=1&limit=1&playerPool=ALL",
            timeout=10
        )
        sp = r.json().get("stats", [{}])[0].get("splits", [])
        if sp:
            return float(sp[0]["stat"].get("era", 4.20))
    except Exception:
        pass
    return 4.20


def _build_from_mlb_api(season: int) -> List[Dict]:
    """Full fallback: build all 30 teams from MLB Stats API alone."""
    print("  Building from MLB Stats API (FanGraphs data unavailable)…")
    lg_era = _fetch_league_era(season)
    results = []
    for team in MLB_TEAMS:
        tid  = team["id"]
        abbr = team["abbr"]
        overall = _mlb_overall(tid, season)
        sp      = _mlb_split(tid, season, "startingPitchers")
        bp      = _mlb_split(tid, season, "reliefPitchers")
        if not overall and not sp:
            continue
        era = (overall or {}).get("era")
        era_plus = round(100 * lg_era / era, 0) if era and era > 0 else None
        results.append({
            "team":  abbr,
            "name":  team["name"],
            "era":   era,
            "whip":  (overall or {}).get("whip"),
            "fip":   (overall or {}).get("fip"),
            "xfip":  None,
            "k_pct": (overall or {}).get("k_pct"),
            "k9":    (overall or {}).get("k9"),
            "era_plus":  era_plus,
            "era_minus": None,
            "starter_era":   (sp or {}).get("era"),
            "starter_whip":  (sp or {}).get("whip"),
            "starter_fip":   (sp or {}).get("fip"),
            "starter_k_pct": (sp or {}).get("k_pct"),
            "starter_k9":    (sp or {}).get("k9"),
            "bullpen_era":   (bp or {}).get("era"),
            "bullpen_whip":  (bp or {}).get("whip"),
            "bullpen_fip":   (bp or {}).get("fip"),
            "bullpen_k_pct": (bp or {}).get("k_pct"),
            "bullpen_k9":    (bp or {}).get("k9"),
            "source": "mlb_api_only",
        })
    results.sort(key=lambda x: (x.get("starter_era") or x.get("era") or 99))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching(season: int = None) -> List[Dict]:
    """
    Returns team pitching data list sorted by starter ERA.

    Priority:
      1. data/team_pitching/latest.json  (FanGraphs data, written by GitHub Actions)
      2. MLB Stats API live fallback      (ERA, WHIP, FIP from components only)
    """
    if season is None:
        season = SEASON

    print(f"[team_pitching] Loading {season}…")

    # Try pre-computed FanGraphs data first
    precomputed = _load_precomputed()
    if precomputed:
        return precomputed

    # Fall back to live MLB API
    return _build_from_mlb_api(season)
