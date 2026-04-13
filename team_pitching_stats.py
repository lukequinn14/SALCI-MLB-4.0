"""
SALCI Team Pitching Stats — Final Reliable Version
======================================================
Primary source: MLB Stats API (accurate starter/bullpen split)
FanGraphs: silent optional enhancement only (no more error messages)
Includes official team logos for graphs
"""

import requests
import math
from datetime import datetime
from typing import Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# OFFICIAL MLB TEAM LOGOS (SVG)
# ─────────────────────────────────────────────────────────────────────────────
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
    "KC":  "https://www.mlbstatic.com/team-logos/118.svg",
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
    "SD":  "https://www.mlbstatic.com/team-logos/135.svg",
    "SF":  "https://www.mlbstatic.com/team-logos/137.svg",
    "SEA": "https://www.mlbstatic.com/team-logos/136.svg",
    "STL": "https://www.mlbstatic.com/team-logos/138.svg",
    "TB":  "https://www.mlbstatic.com/team-logos/139.svg",
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

def _parse_ip(ip_str: str) -> float:
    try:
        parts = str(ip_str).split(".")
        return int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
    except:
        return 0.0


def _mlb_split(team_id: int, season: int, sit_code: str) -> Optional[Dict]:
    """Starter or bullpen split from MLB Stats API"""
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=season&season={season}&group=pitching&sitCodes={sit_code}"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
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

        return {"era": era, "whip": whip, "k_pct": k_pct, "ip": round(ip, 1)}
    except Exception:
        return None


def _mlb_overall(team_id: int, season: int) -> Optional[Dict]:
    """Overall team pitching stats"""
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=season&season={season}&group=pitching"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
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

        return {"era": era, "whip": whip, "k_pct": k_pct, "ip": round(ip, 1)}
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching(season: int = None) -> List[Dict]:
    """Returns clean list of dicts with properly separated starter/bullpen stats."""
    if season is None:
        season = datetime.today().year

    print(f"[team_pitching] Fetching {season} data from MLB Stats API...")

    results = []

    for team in MLB_TEAMS:
        tid = team["id"]
        abbr = team["abbr"]

        sp = _mlb_split(tid, season, "startingPitchers")
        bp = _mlb_split(tid, season, "reliefPitchers")
        overall = _mlb_overall(tid, season)

        data = {
            "team": abbr,
            "name": team["name"],
            "logo_url": TEAM_LOGOS.get(abbr),
            # Overall
            "era": overall.get("era") if overall else None,
            "whip": overall.get("whip") if overall else None,
            "k_pct": overall.get("k_pct") if overall else None,
            # Starters
            "starter_era": sp.get("era") if sp else None,
            "starter_whip": sp.get("whip") if sp else None,
            "starter_k_pct": sp.get("k_pct") if sp else None,
            # Bullpen
            "bullpen_era": bp.get("era") if bp else None,
            "bullpen_whip": bp.get("whip") if bp else None,
            "bullpen_k_pct": bp.get("k_pct") if bp else None,
            "source": "MLB Stats API",
        }

        results.append(data)

    # Filter teams that have data and sort by starter ERA (best to worst)
    results = [r for r in results if r.get("starter_era") or r.get("era")]
    results.sort(key=lambda x: x.get("starter_era") or x.get("era") or 99)

    print(f"✅ Loaded pitching stats for {len(results)} teams")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Quick test when running the file directly
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    data = get_all_team_pitching()
    
    print(f"\n{'Team':<5} {'Starter ERA':<12} {'Bullpen ERA':<12} {'Overall ERA':<12} {'K%':<8}")
    print("─" * 70)
    for t in data:
        print(
            f"{t['team']:<5} "
            f"{str(t.get('starter_era') or '—'):<12} "
            f"{str(t.get('bullpen_era') or '—'):<12} "
            f"{str(t.get('era') or '—'):<12} "
            f"{str(t.get('k_pct') or '—'):<8}"
        )
