"""
SALCI Team Pitching Stats Module
==================================
Fetches real, live team pitching data for the dashboard charts.

Data sources (in priority order):
  1. pybaseball.team_pitching()  — FanGraphs scrape: FIP, K%, ERA+, xFIP
  2. MLB Stats API               — Official: ERA, WHIP, K/9, BB/9
  3. Manual FIP calculation      — Derived from MLB API components when
                                   pybaseball is unavailable

FIP formula: FIP = ((13*HR + 3*(BB+HBP) - 2*K) / IP) + FIP_constant
FIP constant ≈ 3.10  (league-average, keeps FIP on ERA scale)

ERA+ formula: ERA+ = 100 * (lgERA / teamERA)   [park-adjusted in FanGraphs,
                                                  raw here without park factor]

Usage:
    from team_pitching_stats import get_all_team_pitching
    data = get_all_team_pitching(season=2026)
    # Returns list of dicts, one per team, sorted by starter ERA
"""

import requests
import os
from datetime import datetime
from typing import Optional, Dict, List

SEASON = datetime.today().year

# MLB Stats API team IDs — all 30 teams
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

FIP_CONSTANT = 3.10  # Approximation; FanGraphs recalculates annually


# ─────────────────────────────────────────────────────────────────────────────
# MLB Stats API  — ERA, WHIP, K9, BB9, raw components for FIP
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ip(ip_str: str) -> float:
    """Convert MLB API IP string (e.g. '84.2') to decimal innings."""
    try:
        parts = str(ip_str).split(".")
        full = int(parts[0])
        thirds = int(parts[1]) if len(parts) > 1 else 0
        return full + thirds / 3
    except Exception:
        return 0.0


def fetch_team_stats_mlb_api(team_id: int, season: int) -> Optional[Dict]:
    """
    Fetch season pitching stats for one team from the official MLB Stats API.
    Returns a dict with ERA, WHIP, K9, BB9, and raw counting stats for FIP.
    """
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
        s = splits[0]["stat"]

        ip = _parse_ip(s.get("inningsPitched", "0.0"))
        if ip < 1:
            return None

        so  = int(s.get("strikeOuts",    0))
        bb  = int(s.get("baseOnBalls",   0))
        hbp = int(s.get("hitBatsmen",    0))
        hr  = int(s.get("homeRuns",      0))
        er  = int(s.get("earnedRuns",    0))
        h   = int(s.get("hits",          0))
        tbf = int(s.get("battersFaced",  1))

        era  = float(s.get("era",  0)) or (er / ip * 9 if ip > 0 else 0)
        whip = float(s.get("whip", 0)) or ((bb + h) / ip if ip > 0 else 0)
        k9   = so / ip * 9
        bb9  = bb / ip * 9
        k_pct = so / tbf if tbf > 0 else 0

        # FIP from components
        fip = ((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONSTANT) if ip > 0 else None

        return {
            "era":   round(era,  2),
            "whip":  round(whip, 2),
            "k9":    round(k9,   1),
            "bb9":   round(bb9,  1),
            "k_pct": round(k_pct * 100, 1),
            "fip":   round(fip, 2) if fip is not None else None,
            "ip":    round(ip, 1),
            "so":    so,
            "bb":    bb,
            "hr":    hr,
            "source": "mlb_api",
        }
    except Exception as e:
        print(f"  MLB API error team {team_id}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Starter vs Bullpen split
# The MLB Stats API exposes a `startingPitchers` stat split.
# ─────────────────────────────────────────────────────────────────────────────

def fetch_starter_bullpen_split(team_id: int, season: int) -> Dict:
    """
    Returns {"starter_era", "bullpen_era", "starter_whip", "bullpen_whip",
             "starter_k_pct", "starter_fip"} by querying the 'startingPitchers'
    and 'reliefPitchers' stat split from the MLB Stats API.
    Falls back to overall ERA if split is unavailable.
    """
    result = {}
    for role in ("startingPitchers", "reliefPitchers"):
        url = (
            f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
            f"?stats=season&season={season}&group=pitching"
            f"&sitCodes={role}"
        )
        try:
            r = requests.get(url, timeout=12)
            splits = r.json().get("stats", [{}])[0].get("splits", [])
            if not splits:
                continue
            s   = splits[0]["stat"]
            ip  = _parse_ip(s.get("inningsPitched", "0.0"))
            if ip < 1:
                continue
            so  = int(s.get("strikeOuts",   0))
            bb  = int(s.get("baseOnBalls",  0))
            hbp = int(s.get("hitBatsmen",   0))
            hr  = int(s.get("homeRuns",     0))
            er  = int(s.get("earnedRuns",   0))
            h   = int(s.get("hits",         0))
            tbf = int(s.get("battersFaced", 1))

            era  = float(s.get("era", 0)) or (er / ip * 9 if ip > 0 else 0)
            whip = float(s.get("whip", 0)) or ((bb + h) / ip if ip > 0 else 0)
            k_pct = so / tbf * 100 if tbf > 0 else 0
            fip   = (13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONSTANT if ip > 0 else None

            prefix = "starter" if role == "startingPitchers" else "bullpen"
            result[f"{prefix}_era"]   = round(era,  2)
            result[f"{prefix}_whip"]  = round(whip, 2)
            result[f"{prefix}_k_pct"] = round(k_pct, 1)
            if fip is not None:
                result[f"{prefix}_fip"] = round(fip, 2)
        except Exception:
            continue
    return result


# ─────────────────────────────────────────────────────────────────────────────
# pybaseball / FanGraphs  — FIP, xFIP, ERA+, K%, BB%
# ─────────────────────────────────────────────────────────────────────────────

def fetch_fangraphs_team_pitching(season: int) -> Optional[Dict]:
    """
    Use pybaseball.team_pitching() to get FanGraphs team stats.
    Returns dict keyed by team abbreviation: {abbr: {fip, xfip, era_plus, k_pct, ...}}
    Returns None if pybaseball is not installed.
    """
    try:
        from pybaseball import team_pitching
        df = team_pitching(season)
        if df is None or df.empty:
            return None

        result = {}
        for _, row in df.iterrows():
            # FanGraphs uses different team abbreviations — map the common ones
            fg_team = str(row.get("Team", ""))
            abbr = _fg_to_mlb_abbr(fg_team)

            result[abbr] = {
                "fip":      _safe_float(row.get("FIP")),
                "xfip":     _safe_float(row.get("xFIP")),
                "era_plus": _safe_float(row.get("ERA+")),
                "k_pct":    _safe_float(row.get("K%")),   # already as pct (e.g. 22.4)
                "bb_pct":   _safe_float(row.get("BB%")),
                "era":      _safe_float(row.get("ERA")),
                "whip":     _safe_float(row.get("WHIP")),
                "source":   "fangraphs",
            }
        return result if result else None
    except ImportError:
        return None
    except Exception as e:
        print(f"  pybaseball error: {e}")
        return None


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return None if (f != f) else round(f, 2)  # NaN check
    except Exception:
        return None


# FanGraphs uses slightly different abbreviations for a handful of teams
_FG_ABBR_MAP = {
    "WSN": "WAS", "CHW": "CWS", "KCR": "KC",  "SDP": "SD",
    "SFG": "SF",  "TBR": "TB",  "LAA": "LAA", "NYY": "NYY",
}

def _fg_to_mlb_abbr(fg: str) -> str:
    return _FG_ABBR_MAP.get(fg.upper(), fg.upper())


# ─────────────────────────────────────────────────────────────────────────────
# League ERA for ERA+ calculation  (when FanGraphs not available)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_league_era(season: int) -> float:
    """Fetch MLB-wide ERA from the stats API for ERA+ calculation."""
    url = (
        f"https://statsapi.mlb.com/api/v1/stats"
        f"?stats=season&season={season}&group=pitching&gameType=R"
        f"&sportId=1&limit=1&playerPool=ALL"
    )
    try:
        r = requests.get(url, timeout=10)
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            era = float(splits[0]["stat"].get("era", 4.20))
            return era
    except Exception:
        pass
    return 4.20  # 2026 approximate fallback


# ─────────────────────────────────────────────────────────────────────────────
# MAIN: Combine both sources into one clean record per team
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching(season: int = None) -> List[Dict]:
    """
    Fetch and merge team pitching stats from MLB API + FanGraphs.

    Returns a list of dicts sorted by starter ERA (ascending), each containing:
      team, name, era, starter_era, bullpen_era, whip, starter_whip,
      bullpen_whip, fip, k_pct, starter_k_pct, era_plus, source_note
    """
    if season is None:
        season = SEASON

    print(f"Fetching team pitching stats for {season}...")

    # Step 1: Try FanGraphs (best source for FIP, ERA+, K%)
    fg_data = fetch_fangraphs_team_pitching(season)
    if fg_data:
        print(f"  FanGraphs data loaded for {len(fg_data)} teams")
    else:
        print("  pybaseball unavailable — using MLB API only")

    # Step 2: League ERA for ERA+ calc
    lg_era = fetch_league_era(season)
    print(f"  League ERA: {lg_era}")

    results = []
    for team in MLB_TEAMS:
        tid   = team["id"]
        abbr  = team["abbr"]
        name  = team["name"]

        # Overall stats from MLB API
        overall = fetch_team_stats_mlb_api(tid, season)

        # Starter / bullpen split from MLB API
        split = fetch_starter_bullpen_split(tid, season)

        # FanGraphs overlay
        fg = (fg_data or {}).get(abbr, {})

        if not overall and not split:
            print(f"  No data for {abbr} — skipping")
            continue

        # Merge: prefer FanGraphs for FIP/K%/ERA+, MLB API for ERA/WHIP
        era         = (overall or {}).get("era")
        whip        = (overall or {}).get("whip")
        fip         = fg.get("fip") or (overall or {}).get("fip")
        k_pct       = fg.get("k_pct") or (overall or {}).get("k_pct")
        era_plus    = fg.get("era_plus") or (
            round(100 * lg_era / era, 0) if era and era > 0 else None
        )

        starter_era   = split.get("starter_era",   era)
        bullpen_era   = split.get("bullpen_era",    era)
        starter_whip  = split.get("starter_whip",  whip)
        bullpen_whip  = split.get("bullpen_whip",   whip)
        starter_k_pct = split.get("starter_k_pct", k_pct)
        starter_fip   = split.get("starter_fip",   fip)

        source_note = "FanGraphs + MLB API" if fg else "MLB API"

        results.append({
            "team":          abbr,
            "name":          name,
            # Overall
            "era":           era,
            "whip":          whip,
            "fip":           fip,
            "k_pct":         k_pct,
            "era_plus":      era_plus,
            # Starter split
            "starter_era":   starter_era,
            "starter_whip":  starter_whip,
            "starter_k_pct": starter_k_pct,
            "starter_fip":   starter_fip,
            # Bullpen split
            "bullpen_era":   bullpen_era,
            "bullpen_whip":  bullpen_whip,
            # Meta
            "source":        source_note,
            "season":        season,
        })

    # Sort by starter ERA ascending (best first)
    results.sort(key=lambda x: (x.get("starter_era") or 99))
    print(f"  Done — {len(results)} teams loaded")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit-cached wrapper  (import this in your Streamlit tab)
# ─────────────────────────────────────────────────────────────────────────────

def get_team_pitching_cached(season: int = None):
    """
    Call this from Streamlit with @st.cache_data on the calling side, e.g.:

        @st.cache_data(ttl=3600)
        def load_pitching():
            return get_team_pitching_cached()

    Separated so the module stays importable in non-Streamlit scripts too.
    """
    return get_all_team_pitching(season)


if __name__ == "__main__":
    data = get_all_team_pitching(2026)
    print(f"\n{'Team':<5} {'Starter ERA':<13} {'Bullpen ERA':<13} {'FIP':<7} {'K%':<7} {'ERA+'}")
    print("-" * 55)
    for t in data:
        print(
            f"{t['team']:<5} "
            f"{str(t.get('starter_era','—')):<13} "
            f"{str(t.get('bullpen_era','—')):<13} "
            f"{str(t.get('fip','—')):<7} "
            f"{str(t.get('k_pct','—')):<7} "
            f"{t.get('era_plus','—')}"
        )
