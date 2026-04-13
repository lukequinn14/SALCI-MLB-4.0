"""
SALCI Team Pitching Stats — MLB Stats API first, FanGraphs optional
====================================================================
Primary source:
- MLB Stats API for overall team pitching, starter split, and bullpen split.

Optional enhancement:
- FanGraphs direct HTML scraping for extra metrics when available.

This version keeps the same framework and output structure while making the
data pipeline much more reliable in Streamlit and local execution.
"""

import math
import warnings
from datetime import datetime, date
from typing import Dict, List, Optional

import requests
import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

SEASON = datetime.today().year
FIP_CONST = 3.10
FG_BASE = "https://www.fangraphs.com/leaders/major-league"

FG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

FG_TO_MLB: Dict[str, str] = {
    "WSN": "WAS",
    "CHW": "CWS",
    "KCR": "KC",
    "SDP": "SD",
    "SFG": "SF",
    "TBR": "TB",
    "ATH": "OAK",
}

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

TEAM_NAME_MAP = {t["abbr"]: t["name"] for t in MLB_TEAMS}

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ip(ip_str: str) -> float:
    try:
        parts = str(ip_str).split(".")
        return int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
    except Exception:
        return 0.0


def _safe(val, digits: int = 2) -> Optional[float]:
    try:
        f = float(str(val).replace("%", "").replace(",", "").strip())
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, digits)
    except Exception:
        return None


def _pct(val) -> Optional[float]:
    v = _safe(val)
    if v is None:
        return None
    return round(v * 100, 1) if v < 2 else round(v, 1)


def _to_abbr(fg_team: str) -> str:
    t = str(fg_team).upper().strip()
    return FG_TO_MLB.get(t, t)


def _fip(so, bb, hbp, hr, ip) -> Optional[float]:
    if not ip or ip <= 0:
        return None
    return round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONST, 2)


def _request_json(url: str, timeout: int = 12) -> Optional[dict]:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _mlb_split(team_id: int, season: int, sit_code: str) -> Optional[Dict]:
    """
    Starter or bullpen split from MLB Stats API.
    sit_code:
      - startingPitchers
      - reliefPitchers
    """
    url = (
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
        f"?stats=season&season={season}&group=pitching&sitCodes={sit_code}"
    )
    data = _request_json(url, timeout=12)
    if not data:
        return None

    splits = data.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return None

    s = splits[0].get("stat", {})
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

    era = _safe(s.get("era")) or (round(er / ip * 9, 2) if ip > 0 else None)
    whip = _safe(s.get("whip")) or (round((bb + h) / ip, 2) if ip > 0 else None)
    k_pct = round(so / tbf * 100, 1) if tbf > 0 else None

    return {
        "era": era,
        "whip": whip,
        "k_pct": k_pct,
        "fip": _fip(so, bb, hbp, hr, ip),
        "ip": round(ip, 1),
    }


def _mlb_overall(team_id: int, season: int) -> Optional[Dict]:
    """Overall team pitching stats from MLB Stats API."""
    url = (
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
        f"?stats=season&season={season}&group=pitching"
    )
    data = _request_json(url, timeout=12)
    if not data:
        return None

    splits = data.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return None

    s = splits[0].get("stat", {})
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

    era = _safe(s.get("era")) or round(er / ip * 9, 2)
    whip = _safe(s.get("whip")) or round((bb + h) / ip, 2)
    k_pct = round(so / tbf * 100, 1) if tbf > 0 else None

    return {
        "era": era,
        "whip": whip,
        "k_pct": k_pct,
        "fip": _fip(so, bb, hbp, hr, ip),
        "source": "mlb_api",
    }


def _league_era(season: int) -> float:
    url = (
        f"https://statsapi.mlb.com/api/v1/stats?stats=season&season={season}"
        f"&group=pitching&gameType=R&sportId=1&limit=1&playerPool=ALL"
    )
    data = _request_json(url, timeout=10)
    try:
        if data:
            sp = data.get("stats", [{}])[0].get("splits", [])
            if sp:
                return float(sp[0]["stat"].get("era", 4.20))
    except Exception:
        pass
    return 4.20


# ─────────────────────────────────────────────────────────────────────────────
# FANGRAPHS SCRAPER
# ─────────────────────────────────────────────────────────────────────────────

def _fg_url(stats: str, team: str, season: int, start: str = "", end: str = "") -> str:
    today = date.today().strftime("%Y-%m-%d")
    sd = start or f"{season}-03-01"
    ed = end or today
    return (
        f"{FG_BASE}?pos=all&lg=all&qual=0&type=8"
        f"&season={season}&season1={season}&ind=0"
        f"&rost=0&age=0&players=0"
        f"&stats={stats}&team={team}"
        f"&month=1000&startdate={sd}&enddate={ed}"
    )


def _scrape_fg_table(url: str, label: str) -> Optional[pd.DataFrame]:
    try:
        r = requests.get(url, headers=FG_HEADERS, timeout=25)
        r.raise_for_status()
        tables = pd.read_html(r.text)
    except Exception:
        return None

    for t in tables:
        cols = [str(c).strip() for c in t.columns]
        has_team = any(c in ("Team", "Season") for c in cols)
        has_stat = any(c in ("ERA", "FIP", "xFIP") for c in cols)
        if has_team and has_stat and len(t) >= 10:
            t.columns = [str(c).strip() for c in t.columns]
            if "Team" in t.columns:
                t = t[t["Team"].notna()]
                t = t[~t["Team"].astype(str).str.upper().isin({"TEAM", "NAN", "", "SEASON"})]
            return t.reset_index(drop=True)

    return None


def _parse_fg_rows(df: pd.DataFrame, col_team: str) -> Dict[str, Dict]:
    result: Dict[str, Dict] = {}
    df.columns = [str(c).strip() for c in df.columns]

    for _, row in df.iterrows():
        raw_team = str(row.get(col_team, "")).strip()
        if not raw_team or raw_team.upper() in ("NAN", "", col_team.upper()):
            continue

        abbr = _to_abbr(raw_team)
        if len(abbr) > 5:
            continue

        result[abbr] = {
            "era": _safe(row.get("ERA")),
            "fip": _safe(row.get("FIP")),
            "xfip": _safe(row.get("xFIP")),
            "xera": _safe(row.get("xERA")),
            "whip": _safe(row.get("WHIP")),
            "k9": _safe(row.get("K/9"), 1),
            "bb9": _safe(row.get("BB/9"), 1),
            "babip": _safe(row.get("BABIP")),
            "lob_pct": _pct(row.get("LOB%")),
            "hr_fb": _pct(row.get("HR/FB")),
        }

    return result


def fetch_fangraphs_all(season: int) -> Dict[str, Dict]:
    today = date.today().strftime("%Y-%m-%d")
    start = f"{season}-03-01"

    merged: Dict[str, Dict] = {}

    try:
        df_overall = _scrape_fg_table(_fg_url("pit", "0%2Cts", season, start, today), "overall")
        df_sta = _scrape_fg_table(_fg_url("sta", "0%2Cts", season, start, today), "starters")
        df_rel = _scrape_fg_table(_fg_url("rel", "0%2Cts", season, start, today), "relievers")
    except Exception:
        return merged

    if df_overall is not None:
        col = "Team" if "Team" in df_overall.columns else df_overall.columns[0]
        for abbr, stats in _parse_fg_rows(df_overall, col).items():
            merged[abbr] = {**stats, "source": "fangraphs"}

    if df_sta is not None:
        col = "Team" if "Team" in df_sta.columns else df_sta.columns[0]
        for abbr, stats in _parse_fg_rows(df_sta, col).items():
            if abbr not in merged:
                merged[abbr] = {"source": "fangraphs"}
            merged[abbr]["starter_era"] = stats.get("era")
            merged[abbr]["starter_fip"] = stats.get("fip")
            merged[abbr]["starter_xfip"] = stats.get("xfip")
            merged[abbr]["starter_k9"] = stats.get("k9")
            merged[abbr]["starter_whip"] = stats.get("whip")

    if df_rel is not None:
        col = "Team" if "Team" in df_rel.columns else df_rel.columns[0]
        for abbr, stats in _parse_fg_rows(df_rel, col).items():
            if abbr not in merged:
                merged[abbr] = {"source": "fangraphs"}
            merged[abbr]["bullpen_era"] = stats.get("era")
            merged[abbr]["bullpen_fip"] = stats.get("fip")
            merged[abbr]["bullpen_xfip"] = stats.get("xfip")
            merged[abbr]["bullpen_k9"] = stats.get("k9")
            merged[abbr]["bullpen_whip"] = stats.get("whip")

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching(season: int = None) -> List[Dict]:
    """
    Returns list of dicts, one per team, containing:
      team, name, logo_url,
      era, whip, fip,
      xfip, xera, k9, bb9,
      starter_era, starter_fip, starter_whip, starter_k9, starter_k_pct,
      bullpen_era, bullpen_fip, bullpen_whip, bullpen_k9, bullpen_k_pct,
      k_pct, era_plus, source
    """
    if season is None:
        season = SEASON

    print(f"[team_pitching] Season {season} — fetching MLB Stats API...")
    lg_era = _league_era(season)

    print(f"[team_pitching] League ERA: {lg_era}")
    fg = fetch_fangraphs_all(season)
    print(f"[team_pitching] FanGraphs rows loaded: {len(fg)}")

    results: List[Dict] = []

    for team in MLB_TEAMS:
        tid = team["id"]
        abbr = team["abbr"]

        fg_t = fg.get(abbr, {})

        overall = _mlb_overall(tid, season)
        sp = _mlb_split(tid, season, "startingPitchers")
        bp = _mlb_split(tid, season, "reliefPitchers")

        era = fg_t.get("era") if fg_t.get("era") is not None else (overall or {}).get("era")
        whip = fg_t.get("whip") if fg_t.get("whip") is not None else (overall or {}).get("whip")
        fip = fg_t.get("fip") if fg_t.get("fip") is not None else (overall or {}).get("fip")

        xfip = fg_t.get("xfip")
        xera = fg_t.get("xera")
        k9 = fg_t.get("k9")
        bb9 = fg_t.get("bb9")

        k_pct = (overall or {}).get("k_pct")

        era_plus = round(100 * lg_era / era, 0) if (era and era > 0) else None

        starter_era = fg_t.get("starter_era") if fg_t.get("starter_era") is not None else (sp or {}).get("era")
        starter_fip = fg_t.get("starter_fip") if fg_t.get("starter_fip") is not None else (sp or {}).get("fip")
        starter_whip = fg_t.get("starter_whip") if fg_t.get("starter_whip") is not None else (sp or {}).get("whip")
        starter_k9 = fg_t.get("starter_k9")
        starter_kpct = (sp or {}).get("k_pct")

        bullpen_era = fg_t.get("bullpen_era") if fg_t.get("bullpen_era") is not None else (bp or {}).get("era")
        bullpen_fip = fg_t.get("bullpen_fip") if fg_t.get("bullpen_fip") is not None else (bp or {}).get("fip")
        bullpen_whip = fg_t.get("bullpen_whip") if fg_t.get("bullpen_whip") is not None else (bp or {}).get("whip")
        bullpen_k9 = fg_t.get("bullpen_k9")
        bullpen_kpct = (bp or {}).get("k_pct")

        if not any([era, starter_era, bullpen_era]):
            continue

        source = "MLB Stats API"
        if fg_t:
            source = "MLB Stats API + FanGraphs"

        results.append({
            "team": abbr,
            "name": team["name"],
            "logo_url": TEAM_LOGOS.get(abbr),
            "era": era,
            "whip": whip,
            "fip": fip,
            "xfip": xfip,
            "xera": xera,
            "k9": k9,
            "bb9": bb9,
            "k_pct": k_pct,
            "era_plus": era_plus,
            "starter_era": starter_era,
            "starter_fip": starter_fip,
            "starter_whip": starter_whip,
            "starter_k9": starter_k9,
            "starter_k_pct": starter_kpct,
            "bullpen_era": bullpen_era,
            "bullpen_fip": bullpen_fip,
            "bullpen_whip": bullpen_whip,
            "bullpen_k9": bullpen_k9,
            "bullpen_k_pct": bullpen_kpct,
            "source": source,
        })

    results.sort(key=lambda x: (x.get("starter_era") or x.get("era") or 99))
    print(f"[team_pitching] Loaded pitching stats for {len(results)} teams")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL: DataFrame helper for Streamlit / charts
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching_df(season: int = None) -> pd.DataFrame:
    data = get_all_team_pitching(season)
    return pd.DataFrame(data)


# ─────────────────────────────────────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    data = get_all_team_pitching()
    if not data:
        print("No data returned!")
    else:
        print(f"\\n{'Team':<5} {'Starter ERA':<12} {'Bullpen ERA':<12} {'Overall ERA':<12} {'K%':<8} {'ERA+':<8} {'Source'}")
        print("─" * 90)
        for t in data:
            print(
                f"{t['team']:<5} "
                f"{str(t.get('starter_era') or '—'):<12} "
                f"{str(t.get('bullpen_era') or '—'):<12} "
                f"{str(t.get('era') or '—'):<12} "
                f"{str(t.get('k_pct') or '—'):<8} "
                f"{str(t.get('era_plus') or '—'):<8} "
                f"{t.get('source','?')}"
            )
