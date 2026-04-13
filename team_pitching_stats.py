"""
SALCI Team Pitching Stats Module
==================================
Two data sources, merged per team:

  FanGraphs (pybaseball.fg_team_pitching_data):
      ERA, FIP, xFIP, SIERA, WHIP, K%, BB%, ERA-, K/9
      Park-adjusted, gold-standard accuracy.
      ERA- converted to ERA+: ERA+ = 200 - ERA-

  MLB Stats API (statsapi.mlb.com):
      Starter ERA / Bullpen ERA split (sitCodes parameter).
      FanGraphs does NOT publish team starter vs bullpen ERA splits,
      so the MLB API is the only source for these.

FIP fallback formula (when pybaseball unavailable):
    FIP = (13*HR + 3*(BB+HBP) - 2*K) / IP + 3.10
"""

import requests
import warnings
from datetime import datetime
from typing import Optional, Dict, List

warnings.filterwarnings("ignore")

SEASON = datetime.today().year
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

# FanGraphs uses different abbreviations for these teams
_FG_TO_MLB = {
    "WSN": "WAS", "CHW": "CWS", "KCR": "KC",
    "SDP": "SD",  "SFG": "SF",  "TBR": "TB",
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _safe(val, digits=2) -> Optional[float]:
    import math
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else round(f, digits)
    except Exception:
        return None


def _parse_ip(ip_str) -> float:
    try:
        parts = str(ip_str).split(".")
        return int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
    except Exception:
        return 0.0


def _fip(so, bb, hbp, hr, ip) -> Optional[float]:
    if not ip or ip <= 0:
        return None
    return round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONSTANT, 2)


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 1 — FanGraphs via pybaseball
# ─────────────────────────────────────────────────────────────────────────────

def fetch_fangraphs(season: int) -> Optional[Dict[str, Dict]]:
    """
    Returns dict keyed by MLB abbreviation with FanGraphs team pitching stats.
    Uses fg_team_pitching_data with specific stat columns confirmed to exist.
    """
    try:
        from pybaseball import fg_team_pitching_data
        from pybaseball.enums.fangraphs import FangraphsPitchingStats as FPS

        # These column names were verified against the FangraphsPitchingStats enum
        cols = [
            FPS.ERA, FPS.FIP, FPS.XFIP, FPS.SIERA, FPS.WHIP,
            FPS.K_PCT, FPS.BB_PCT, FPS.ERA_MINUS, FPS.K_9,
        ]

        df = fg_team_pitching_data(start_season=season, end_season=season, stat_columns=cols)
        if df is None or df.empty:
            return None

        result: Dict[str, Dict] = {}
        for _, row in df.iterrows():
            fg_abbr = str(row.get("Team", "")).upper()
            abbr = _FG_TO_MLB.get(fg_abbr, fg_abbr)

            # ERA- is lower-is-better (100 = average)
            # Convert to ERA+ (higher-is-better): ERA+ ≈ 200 - ERA-
            era_minus = _safe(row.get("ERA-"))
            era_plus  = round(200 - era_minus, 0) if era_minus else None

            # K% from FanGraphs comes as decimal (0.224) — convert to percent
            k_pct = _safe(row.get("K%"))
            if k_pct is not None and k_pct < 2:   # 0.224 not 22.4
                k_pct = round(k_pct * 100, 1)

            bb_pct = _safe(row.get("BB%"))
            if bb_pct is not None and bb_pct < 2:
                bb_pct = round(bb_pct * 100, 1)

            result[abbr] = {
                "era":       _safe(row.get("ERA")),
                "fip":       _safe(row.get("FIP")),
                "xfip":      _safe(row.get("xFIP")),
                "siera":     _safe(row.get("SIERA")),
                "whip":      _safe(row.get("WHIP")),
                "k_pct":     k_pct,
                "bb_pct":    bb_pct,
                "k9":        _safe(row.get("K/9"), 1),
                "era_minus": era_minus,
                "era_plus":  era_plus,
                "source":    "fangraphs",
            }

        return result or None

    except ImportError:
        return None
    except Exception as e:
        print(f"  FanGraphs error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 2 — MLB Stats API
# ─────────────────────────────────────────────────────────────────────────────

def _mlb_split(team_id: int, season: int, sit_code: str) -> Optional[Dict]:
    """Fetch one role split (startingPitchers / reliefPitchers)."""
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
        tbf = int(s.get("battersFaced",1))

        era  = _safe(s.get("era")) or (round(er / ip * 9, 2) if ip > 0 else None)
        whip = _safe(s.get("whip")) or (round((bb + h) / ip, 2) if ip > 0 else None)
        k_pct = round(so / tbf * 100, 1) if tbf > 0 else None

        return {
            "era":   era,
            "whip":  whip,
            "k_pct": k_pct,
            "fip":   _fip(so, bb, hbp, hr, ip),
            "ip":    round(ip, 1),
        }
    except Exception:
        return None


def fetch_split(team_id: int, season: int) -> Dict:
    starter = _mlb_split(team_id, season, "startingPitchers")
    bullpen = _mlb_split(team_id, season, "reliefPitchers")
    out = {}
    if starter:
        out.update({f"starter_{k}": v for k, v in starter.items()})
    if bullpen:
        out.update({f"bullpen_{k}": v for k, v in bullpen.items()})
    return out


def fetch_mlb_overall(team_id: int, season: int) -> Optional[Dict]:
    """Overall fallback when FanGraphs is unavailable."""
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
        tbf = int(s.get("battersFaced",1))

        era   = _safe(s.get("era")) or round(er / ip * 9, 2)
        whip  = _safe(s.get("whip")) or round((bb + h) / ip, 2)
        k_pct = round(so / tbf * 100, 1) if tbf > 0 else None

        return {
            "era": era, "whip": whip, "k_pct": k_pct,
            "fip": _fip(so, bb, hbp, hr, ip),
            "source": "mlb_api",
        }
    except Exception as e:
        print(f"  MLB API error {team_id}: {e}")
        return None


def fetch_league_era(season: int) -> float:
    url = (
        f"https://statsapi.mlb.com/api/v1/stats?stats=season&season={season}"
        f"&group=pitching&gameType=R&sportId=1&limit=1&playerPool=ALL"
    )
    try:
        r = requests.get(url, timeout=10)
        sp = r.json().get("stats", [{}])[0].get("splits", [])
        if sp:
            return float(sp[0]["stat"].get("era", 4.20))
    except Exception:
        pass
    return 4.20


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching(season: int = None) -> List[Dict]:
    if season is None:
        season = SEASON

    print(f"[team_pitching] Loading {season}…")
    fg      = fetch_fangraphs(season)
    lg_era  = fetch_league_era(season)

    if fg:
        print(f"  FanGraphs: {len(fg)} teams ✓")
    else:
        print("  FanGraphs unavailable — MLB API fallback")

    results = []
    for team in MLB_TEAMS:
        tid  = team["id"]
        abbr = team["abbr"]

        split    = fetch_split(tid, season)
        fg_t     = (fg or {}).get(abbr, {})
        mlb_fall = None if fg_t else fetch_mlb_overall(tid, season)

        if not fg_t and not mlb_fall and not split:
            continue

        era      = fg_t.get("era")       or (mlb_fall or {}).get("era")
        whip     = fg_t.get("whip")      or (mlb_fall or {}).get("whip")
        fip      = fg_t.get("fip")       or (mlb_fall or {}).get("fip")
        xfip     = fg_t.get("xfip")
        siera    = fg_t.get("siera")
        k_pct    = fg_t.get("k_pct")     or (mlb_fall or {}).get("k_pct")
        bb_pct   = fg_t.get("bb_pct")
        era_minus= fg_t.get("era_minus")
        era_plus = fg_t.get("era_plus") or (
            round(100 * lg_era / era, 0) if (era and era > 0) else None
        )

        results.append({
            "team":  abbr,
            "name":  team["name"],
            "era":   era, "whip": whip, "fip": fip,
            "xfip":  xfip, "siera": siera,
            "k_pct": k_pct, "bb_pct": bb_pct,
            "era_minus": era_minus, "era_plus": era_plus,
            **split,
            "source": "FanGraphs + MLB API" if fg_t else "MLB API only",
        })

    results.sort(key=lambda x: (x.get("starter_era") or x.get("era") or 99))
    print(f"  {len(results)} teams ready")
    return results
