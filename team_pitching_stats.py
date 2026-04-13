"""
SALCI Team Pitching Stats Module
==================================
Fetches real, live team pitching data directly from FanGraphs.

WHY NOT PYBASEBALL?
  pybaseball.fg_team_pitching_data() uses FanGraphs' old /leaders-legacy.aspx
  endpoint, which FanGraphs has blocked. This module calls the current live
  /leaders/major-league endpoint directly using requests + pandas.read_html.
  No pybaseball required for this module.

THREE FANGRAPHS SCRAPES:
  1. stats=pit  team=0,ts  → Overall team ERA, FIP, xFIP, K/9, BABIP, etc.
  2. stats=sta  team=0,ss  → Starter-only ERA, FIP, xFIP, K/9
  3. stats=rel  team=0,ts  → Bullpen-only ERA, FIP, xFIP, K/9

  FanGraphs abbreviations confirmed from live data:
    SDP=SD, SFG=SF, KCR=KC, WSN=WAS, CHW=CWS, TBR=TB, ATH=OAK

COLUMNS RETURNED (type=8 Dashboard):
  Team, ERA, xERA, FIP, xFIP, K/9, BB/9, HR/9, BABIP, LOB%, GB%, HR/FB, WAR

K% note:
  FanGraphs type=8 returns K/9, not K%. We derive K% via the Advanced tab
  (type=1) as a second fetch. Falls back to K/9→K% estimate if unavailable.
"""

import requests
import pandas as pd
import warnings
import math
from datetime import datetime
from typing import Optional, Dict, List

warnings.filterwarnings("ignore")

SEASON = datetime.today().year
FIP_CONSTANT = 3.10

# FanGraphs team abbreviation → standard MLB abbreviation
_FG_TO_MLB: Dict[str, str] = {
    "SDP": "SD",  "SFG": "SF",  "KCR": "KC",
    "WSN": "WAS", "CHW": "CWS", "TBR": "TB",
    "ATH": "OAK",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_FG_BASE = "https://www.fangraphs.com/leaders/major-league"

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

_MLB_NAMES: Dict[str, str] = {t["abbr"]: t["name"] for t in MLB_TEAMS}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _safe(val, digits: int = 2) -> Optional[float]:
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, digits)
    except Exception:
        return None


def _pct_to_float(val) -> Optional[float]:
    """Convert '22.4%' or 0.224 or 22.4 → 22.4 (always as percent value)."""
    try:
        s = str(val).strip().rstrip("%")
        f = float(s)
        return round(f if f > 2 else f * 100, 1)
    except Exception:
        return None


def _normalize_abbr(raw: str) -> str:
    """Map FanGraphs abbreviation to standard MLB abbreviation."""
    up = raw.strip().upper()
    return _FG_TO_MLB.get(up, up)


# ─────────────────────────────────────────────────────────────────────────────
# FANGRAPHS HTML SCRAPER
# ─────────────────────────────────────────────────────────────────────────────

def _build_fg_url(stats: str, team: str, stat_type: int, season: int) -> str:
    """
    Build a FanGraphs leaderboard URL.

    stats:     'pit' | 'sta' | 'rel'
    team:      '0,ts' (team totals) | '0,ss' (starter split)
    stat_type: 8 = Dashboard  |  1 = Advanced (has K%, BB%)
    """
    today = datetime.today().strftime("%Y-%m-%d")
    return (
        f"{_FG_BASE}"
        f"?pos=all&lg=all&qual=0&type={stat_type}"
        f"&season={season}&month=1000&season1={season}"
        f"&ind=0&rost=0&age=0&players=0"
        f"&stats={stats}&team={team}"
        f"&startdate={season}-03-01&enddate={today}"
    )


def _scrape_fg_table(url: str) -> Optional[pd.DataFrame]:
    """
    Fetch a FanGraphs leaderboard page and parse the data table.
    Returns a DataFrame with Team as first column, or None on failure.
    """
    try:
        r = requests.get(url, headers=_HEADERS, timeout=25)
        r.raise_for_status()

        # pandas.read_html finds all tables; we want the one with 'Team' + stat cols
        tables = pd.read_html(r.text)
        for df in tables:
            cols = [str(c).strip() for c in df.columns]
            if "Team" in cols and ("ERA" in cols or "FIP" in cols):
                df.columns = cols
                # Drop rows where Team is NaN or looks like a header repeat
                df = df[df["Team"].notna()]
                df = df[~df["Team"].astype(str).str.contains("Team|#", na=False)]
                df = df.reset_index(drop=True)
                return df

        print(f"  No matching table found at {url[:80]}…")
        return None

    except Exception as e:
        print(f"  FanGraphs scrape error ({url[:60]}…): {e}")
        return None


def _parse_fg_table(df: pd.DataFrame) -> Dict[str, Dict]:
    """
    Convert a scraped FanGraphs DataFrame into a dict keyed by MLB abbreviation.
    Handles both Dashboard (type=8) and Advanced (type=1) column sets.
    """
    result: Dict[str, Dict] = {}
    if df is None or df.empty:
        return result

    cols = list(df.columns)

    for _, row in df.iterrows():
        raw_team = str(row.get("Team", "")).strip()
        if not raw_team or raw_team.lower() in ("team", "nan", ""):
            continue

        abbr = _normalize_abbr(raw_team)

        entry: Dict = {}

        # Dashboard stats (type=8)
        for col in cols:
            c = col.strip()
            if c == "ERA":
                entry["era"]   = _safe(row[col])
            elif c == "xERA":
                entry["xera"]  = _safe(row[col])
            elif c == "FIP":
                entry["fip"]   = _safe(row[col])
            elif c == "xFIP":
                entry["xfip"]  = _safe(row[col])
            elif c in ("K/9", "K9"):
                entry["k9"]    = _safe(row[col], 1)
            elif c in ("BB/9", "BB9"):
                entry["bb9"]   = _safe(row[col], 1)
            elif c in ("HR/9", "HR9"):
                entry["hr9"]   = _safe(row[col], 2)
            elif c == "WHIP":
                entry["whip"]  = _safe(row[col])
            elif c == "BABIP":
                entry["babip"] = _safe(row[col])
            elif c in ("LOB%", "LOB"):
                entry["lob_pct"] = _pct_to_float(row[col])
            elif c in ("GB%", "GB"):
                entry["gb_pct"]  = _pct_to_float(row[col])
            elif c in ("HR/FB", "HRFB"):
                entry["hr_fb"]   = _pct_to_float(row[col])
            elif c == "WAR":
                entry["war"]   = _safe(row[col], 1)
            # Advanced stats (type=1)
            elif c == "K%":
                entry["k_pct"] = _pct_to_float(row[col])
            elif c == "BB%":
                entry["bb_pct"] = _pct_to_float(row[col])
            elif c in ("ERA-", "ERA_MINUS"):
                entry["era_minus"] = _safe(row[col], 1)

        # Derive K% from K/9 if not available (K/9 / 9 * ~27 PA/G ≈ K%)
        if "k_pct" not in entry and entry.get("k9"):
            entry["k_pct"] = round(entry["k9"] / 9 * 27 / 100 * 100, 1)

        # ERA+ from ERA- if present
        if "era_minus" in entry and entry["era_minus"]:
            entry["era_plus"] = round(200 - entry["era_minus"], 0)

        result[abbr] = entry

    return result


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_fangraphs_all(season: int) -> Dict[str, Dict]:
    """
    Scrape three FanGraphs pages and merge into one dict per team:
      overall (all pitchers), starter split, bullpen split.

    Returns dict keyed by MLB abbreviation:
      { "ATL": { era, fip, xfip, k9, k_pct, starter_era, bullpen_era, ... } }
    """
    result: Dict[str, Dict] = {}

    # ── 1. Overall team pitching (Dashboard) ─────────────────────────────────
    url_all = _build_fg_url("pit", "0,ts", 8, season)
    print(f"  Fetching overall team pitching…")
    df_all = _scrape_fg_table(url_all)
    overall = _parse_fg_table(df_all)
    for abbr, stats in overall.items():
        result.setdefault(abbr, {}).update(stats)

    # ── 2. Advanced tab for K%, BB% ──────────────────────────────────────────
    url_adv = _build_fg_url("pit", "0,ts", 1, season)
    print(f"  Fetching advanced stats (K%, BB%)…")
    df_adv = _scrape_fg_table(url_adv)
    adv = _parse_fg_table(df_adv)
    for abbr, stats in adv.items():
        if abbr in result:
            for k in ("k_pct", "bb_pct", "era_minus", "era_plus"):
                if stats.get(k) is not None:
                    result[abbr][k] = stats[k]

    # ── 3. Starter split ─────────────────────────────────────────────────────
    url_sp = _build_fg_url("sta", "0,ss", 8, season)
    print(f"  Fetching starter split…")
    df_sp = _scrape_fg_table(url_sp)
    sp = _parse_fg_table(df_sp)
    for abbr, stats in sp.items():
        tgt = result.setdefault(abbr, {})
        for k, v in stats.items():
            tgt[f"starter_{k}"] = v

    # ── 4. Bullpen split ─────────────────────────────────────────────────────
    url_bp = _build_fg_url("rel", "0,ts", 8, season)
    print(f"  Fetching bullpen split…")
    df_bp = _scrape_fg_table(url_bp)
    bp = _parse_fg_table(df_bp)
    for abbr, stats in bp.items():
        tgt = result.setdefault(abbr, {})
        for k, v in stats.items():
            tgt[f"bullpen_{k}"] = v

    # ── Mark source ──────────────────────────────────────────────────────────
    for abbr in result:
        result[abbr]["source"] = "fangraphs_direct"

    return result


# ─────────────────────────────────────────────────────────────────────────────
# MLB Stats API fallback (starter/bullpen split + ERA when FG fails)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ip(ip_str) -> float:
    try:
        parts = str(ip_str).split(".")
        return int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
    except Exception:
        return 0.0


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
        tbf = int(s.get("battersFaced",1))
        era  = _safe(s.get("era")) or (round(er / ip * 9, 2) if ip > 0 else None)
        whip = _safe(s.get("whip")) or (round((bb + h) / ip, 2) if ip > 0 else None)
        k_pct = round(so / tbf * 100, 1) if tbf > 0 else None
        fip = round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONSTANT, 2) if ip > 0 else None
        return {"era": era, "whip": whip, "k_pct": k_pct, "fip": fip, "ip": round(ip, 1)}
    except Exception:
        return None


def fetch_mlb_api_splits(season: int) -> Dict[str, Dict]:
    """Fallback: get starter/bullpen ERA split from MLB Stats API."""
    result: Dict[str, Dict] = {}
    for team in MLB_TEAMS:
        tid  = team["id"]
        abbr = team["abbr"]
        sp   = _mlb_split(tid, season, "startingPitchers")
        bp   = _mlb_split(tid, season, "reliefPitchers")
        if sp:
            result.setdefault(abbr, {}).update({f"starter_{k}": v for k, v in sp.items()})
        if bp:
            result.setdefault(abbr, {}).update({f"bullpen_{k}": v for k, v in bp.items()})
        if sp or bp:
            result[abbr]["source"] = "mlb_api_only"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching(season: int = None) -> List[Dict]:
    """
    Returns a list of dicts (one per team) sorted by starter ERA, containing:
      team, name, era, fip, xfip, xera, k9, k_pct, bb_pct, whip, babip,
      lob_pct, gb_pct, hr_fb, war, era_minus, era_plus,
      starter_era, starter_fip, starter_xfip, starter_k9, starter_k_pct,
      bullpen_era, bullpen_fip, bullpen_xfip, bullpen_k9, bullpen_k_pct,
      source
    """
    if season is None:
        season = SEASON

    print(f"[team_pitching] Loading {season} season data…")

    # Primary: FanGraphs direct scrape
    fg = fetch_fangraphs_all(season)
    print(f"  FanGraphs: {len(fg)} teams scraped")

    # If FG failed entirely, fall back to MLB API
    if not fg:
        print("  FanGraphs failed — falling back to MLB API")
        fg = fetch_mlb_api_splits(season)
    else:
        # Supplement missing starter/bullpen splits from MLB API if FG gave them
        # (FG does provide them via sta/rel pages, but double-check)
        missing_splits = [
            t["abbr"] for t in MLB_TEAMS
            if fg.get(t["abbr"], {}).get("starter_era") is None
        ]
        if missing_splits:
            print(f"  Filling {len(missing_splits)} missing splits from MLB API…")
            for team in MLB_TEAMS:
                if team["abbr"] in missing_splits:
                    sp = _mlb_split(team["id"], season, "startingPitchers")
                    bp = _mlb_split(team["id"], season, "reliefPitchers")
                    tgt = fg.setdefault(team["abbr"], {})
                    if sp:
                        for k, v in sp.items():
                            tgt.setdefault(f"starter_{k}", v)
                    if bp:
                        for k, v in bp.items():
                            tgt.setdefault(f"bullpen_{k}", v)

    # Build final list
    results: List[Dict] = []
    for team in MLB_TEAMS:
        abbr = team["abbr"]
        d    = fg.get(abbr, {})
        if not d:
            continue

        results.append({
            "team":  abbr,
            "name":  team["name"],
            # Overall
            "era":       d.get("era"),
            "fip":       d.get("fip"),
            "xfip":      d.get("xfip"),
            "xera":      d.get("xera"),
            "whip":      d.get("whip"),
            "k9":        d.get("k9"),
            "k_pct":     d.get("k_pct"),
            "bb_pct":    d.get("bb_pct"),
            "babip":     d.get("babip"),
            "lob_pct":   d.get("lob_pct"),
            "gb_pct":    d.get("gb_pct"),
            "hr_fb":     d.get("hr_fb"),
            "war":       d.get("war"),
            "era_minus": d.get("era_minus"),
            "era_plus":  d.get("era_plus"),
            # Starter split
            "starter_era":   d.get("starter_era"),
            "starter_fip":   d.get("starter_fip"),
            "starter_xfip":  d.get("starter_xfip"),
            "starter_whip":  d.get("starter_whip"),
            "starter_k9":    d.get("starter_k9"),
            "starter_k_pct": d.get("starter_k_pct"),
            # Bullpen split
            "bullpen_era":   d.get("bullpen_era"),
            "bullpen_fip":   d.get("bullpen_fip"),
            "bullpen_xfip":  d.get("bullpen_xfip"),
            "bullpen_whip":  d.get("bullpen_whip"),
            "bullpen_k9":    d.get("bullpen_k9"),
            "bullpen_k_pct": d.get("bullpen_k_pct"),
            "source": d.get("source", "unknown"),
        })

    # Sort by starter ERA (best first); teams without split go by overall ERA
    results.sort(key=lambda x: (
        x.get("starter_era") or x.get("era") or 99
    ))

    print(f"  Done — {len(results)} teams ready")
    return results


if __name__ == "__main__":
    data = get_all_team_pitching()
    print(f"\n{'Team':<5} {'SP ERA':<9} {'BP ERA':<9} {'FIP':<7} {'xFIP':<7} {'K%':<7} {'K/9'}")
    print("─" * 60)
    for t in data:
        print(
            f"{t['team']:<5}"
            f"{str(t.get('starter_era') or '—'):<9}"
            f"{str(t.get('bullpen_era') or '—'):<9}"
            f"{str(t.get('fip') or '—'):<7}"
            f"{str(t.get('xfip') or '—'):<7}"
            f"{(str(t.get('k_pct'))+'%') if t.get('k_pct') else '—':<7}"
            f"{t.get('k9') or '—'}"
        )
