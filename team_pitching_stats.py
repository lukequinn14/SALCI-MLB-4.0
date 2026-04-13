"""
SALCI Team Pitching Stats — MLB Stats API Primary (FanGraphs DISABLED)
========================================================================
⚠️  FanGraphs DISABLED by default due to 2026 anti-bot blocking.
✅ MLB Stats API provides: ERA, WHIP, K%, starter/bullpen splits, FIP
✅ Reliable in Streamlit, local, and deployed environments.
✅ Toggle FANGRAPHS_ENABLED = True to attempt optional enhancement.
"""

import math
import warnings
from datetime import datetime
from typing import Dict, List, Optional

import requests
import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
FANGRAPHS_ENABLED = False  # Set True to attempt FanGraphs (will likely fail)

SEASON = datetime.today().year
FIP_CONST = 3.10

# Team logos and MLB teams (unchanged)
TEAM_LOGOS = {
    "ARI": "https://www.mlbstatic.com/team-logos/109.svg",
    "ATL": "https://www.mlbstatic.com/team-logos/144.svg",
    "BAL": "https://www.mlbstatic.com/team-logos/110.svg",
    "BOS": "https://www.mlbstatic.com/team-logos/111.svg",
    "CHC": "https://www.mlbstatic.com/team-logos/112.svg",
    "CWS": "https://www.mlbstatic.com/team-logos/145.svg",
    "CIN": "https://www.mlbstatic.com/team-logos/113.svg",
    "CLE": "https://www.mlbstatic.com/team-logos/114.svg",
    "COL": "https://www.mlbstatic.com/team-logos/115.svg",
    "DET": "https://www.mlbstatic.com/team-logos/116.svg",
    "HOU": "https://www.mlbstatic.com/team-logos/117.svg",
    "KC": "https://www.mlbstatic.com/team-logos/118.svg",
    "LAA": "https://www.mlbstatic.com/team-logos/108.svg",
    "LAD": "https://www.mlbstatic.com/team-logos/119.svg",
    "MIA": "https://www.mlbstatic.com/team-logos/146.svg",
    "MIL": "https://www.mlbstatic.com/team-logos/158.svg",
    "MIN": "https://www.mlbstatic.com/team-logos/142.svg",
    "NYM": "https://www.mlbstatic.com/team-logos/121.svg",
    "NYY": "https://www.mlbstatic.com/team-logos/147.svg",
    "OAK": "https://www.mlbstatic.com/team-logos/133.svg",
    "PHI": "https://www.mlbstatic.com/team-logos/143.svg",
    "PIT": "https://www.mlbstatic.com/team-logos/134.svg",
    "SD": "https://www.mlbstatic.com/team-logos/135.svg",
    "SF": "https://www.mlbstatic.com/team-logos/137.svg",
    "SEA": "https://www.mlbstatic.com/team-logos/136.svg",
    "STL": "https://www.mlbstatic.com/team-logos/138.svg",
    "TB": "https://www.mlbstatic.com/team-logos/139.svg",
    "TEX": "https://www.mlbstatic.com/team-logos/140.svg",
    "TOR": "https://www.mlbstatic.com/team-logos/141.svg",
    "WAS": "https://www.mlbstatic.com/team-logos/120.svg",
}

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
    {"id": 118, "abbr": "KC", "name": "Kansas City Royals"},
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
    {"id": 135, "abbr": "SD", "name": "San Diego Padres"},
    {"id": 137, "abbr": "SF", "name": "San Francisco Giants"},
    {"id": 136, "abbr": "SEA", "name": "Seattle Mariners"},
    {"id": 138, "abbr": "STL", "name": "St. Louis Cardinals"},
    {"id": 139, "abbr": "TB", "name": "Tampa Bay Rays"},
    {"id": 140, "abbr": "TEX", "name": "Texas Rangers"},
    {"id": 141, "abbr": "TOR", "name": "Toronto Blue Jays"},
    {"id": 120, "abbr": "WAS", "name": "Washington Nationals"},
]

# ─────────────────────────────────────────────────────────────────────────────
# CORE HELPERS (MLB Stats API)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ip(ip_str: str) -> float:
    """Parse innings pitched like '123.2' → 123.666"""
    try:
        parts = str(ip_str).split(".")
        return int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
    except:
        return 0.0

def _request_json(url: str, timeout: int = 12) -> Optional[dict]:
    """Safe JSON request wrapper."""
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except:
        return None

def _mlb_split(team_id: int, season: int, sit_code: str) -> Optional[Dict]:
    """Starter or bullpen split from MLB Stats API."""
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=season&season={season}&group=pitching&sitCodes={sit_code}"
    data = _request_json(url)
    if not data:
        return None

    splits = data.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return None

    s = splits[0]["stat"]
    ip = _parse_ip(s.get("inningsPitched", "0.0"))
    if ip < 1:
        return None

    so = int(s.get("strikeOuts", 0))
    bb = int(s.get("baseOnBalls", 0))
    hbp = int(s.get("hitBatsmen", 0))
    hr = int(s.get("homeRuns", 0))
    er = int(s.get("earnedRuns", 0))
    h = int(s.get("hits", 0))
    tbf = int(s.get("battersFaced", 1))

    era = round(er / ip * 9, 2) if ip > 0 else None
    whip = round((bb + h) / ip, 2) if ip > 0 else None
    k_pct = round(so / tbf * 100, 1) if tbf > 0 else None
    fip = round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONST, 2) if ip > 0 else None

    return {
        "era": era,
        "whip": whip,
        "k_pct": k_pct,
        "fip": fip,
        "ip": round(ip, 1),
    }

def _mlb_overall(team_id: int, season: int) -> Optional[Dict]:
    """Overall team pitching stats."""
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=season&season={season}&group=pitching"
    data = _request_json(url)
    if not data:
        return None

    splits = data.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return None

    s = splits[0]["stat"]
    ip = _parse_ip(s.get("inningsPitched", "0.0"))
    if ip < 1:
        return None

    so = int(s.get("strikeOuts", 0))
    bb = int(s.get("baseOnBalls", 0))
    hbp = int(s.get("hitBatsmen", 0))
    hr = int(s.get("homeRuns", 0))
    er = int(s.get("earnedRuns", 0))
    h = int(s.get("hits", 0))
    tbf = int(s.get("battersFaced", 1))

    era = round(er / ip * 9, 2) if ip > 0 else None
    whip = round((bb + h) / ip, 2) if ip > 0 else None
    k_pct = round(so / tbf * 100, 1) if tbf > 0 else None
    fip = round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONST, 2) if ip > 0 else None

    return {
        "era": era,
        "whip": whip,
        "k_pct": k_pct,
        "fip": fip,
        "ip": round(ip, 1),
    }

def _league_era(season: int) -> float:
    """Get league average ERA for ERA+ calculation."""
    url = f"https://statsapi.mlb.com/api/v1/stats?stats=season&season={season}&group=pitching&gameType=R&sportId=1&limit=1&playerPool=ALL"
    data = _request_json(url)
    try:
        if data and data.get("stats"):
            return float(data["stats"][0]["splits"][0]["stat"].get("era", 4.20))
    except:
        pass
    return 4.20

# ─────────────────────────────────────────────────────────────────────────────
# MAIN FUNCTION (MLB API ONLY)
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching(season: int = None) -> List[Dict]:
    """Returns complete team pitching stats from MLB Stats API."""
    if season is None:
        season = SEASON

    print(f"⚾ [team_pitching] Loading {season} MLB Stats API data...")
    lg_era = _league_era(season)
    print(f"   League ERA: {lg_era:.2f}")

    if FANGRAPHS_ENABLED:
        print("   FanGraphs: SKIPPED (disabled due to blocking)")
    else:
        print("   FanGraphs: DISABLED (set FANGRAPHS_ENABLED = True to attempt)")

    results: List[Dict] = []

    for team in MLB_TEAMS:
        tid = team["id"]
        abbr = team["abbr"]
        name = team["name"]

        # Get all three splits
        overall = _mlb_overall(tid, season)
        starters = _mlb_split(tid, season, "startingPitchers")
        bullpen = _mlb_split(tid, season, "reliefPitchers")

        # Skip teams with no data
        if not any([overall, starters, bullpen]):
            continue

        # Build result dict
        result = {
            "team": abbr,
            "name": name,
            "logo_url": TEAM_LOGOS.get(abbr),
            # Overall stats
            "era": overall.get("era"),
            "whip": overall.get("whip"),
            "fip": overall.get("fip"),
            "k_pct": overall.get("k_pct"),
            "era_plus": round(100 * lg_era / overall.get("era", 1), 0) if overall and overall.get("era") else None,
            # Starters
            "starter_era": starters.get("era"),
            "starter_whip": starters.get("whip"),
            "starter_fip": starters.get("fip"),
            "starter_k_pct": starters.get("k_pct"),
            # Bullpen
            "bullpen_era": bullpen.get("era"),
            "bullpen_whip": bullpen.get("whip"),
            "bullpen_fip": bullpen.get("fip"),
            "bullpen_k_pct": bullpen.get("k_pct"),
            "source": "MLB Stats API",
        }
        results.append(result)

    # Sort by starter ERA
    results.sort(key=lambda x: x.get("starter_era") or x.get("era") or 99)
    print(f"✅ Loaded {len(results)} teams from MLB Stats API")
    return results

# Streamlit DataFrame helper
def get_all_team_pitching_df(season: int = None) -> pd.DataFrame:
    return pd.DataFrame(get_all_team_pitching(season))

# ─────────────────────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    data = get_all_team_pitching()
    print("\n" + "="*90)
    print(f"{'Team':<5} {'SP ERA':<8} {'BP ERA':<8} {'ERA':<6} {'FIP':<6} {'K%':<6} {'ERA+':<6}")
    print("="*90)
    for team in data[:10]:  # Show top 10
        print(f"{team['team']:<5} "
              f"{team.get('starter_era', '—'):<8.2f} "
              f"{team.get('bullpen_era', '—'):<8.2f} "
              f"{team.get('era', '—'):<6.2f} "
              f"{team.get('fip', '—'):<6.2f} "
              f"{team.get('k_pct', '—'):<6.1f} "
              f"{team.get('era_plus', '—')}")
