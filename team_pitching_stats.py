"""
SALCI Team Pitching Stats — Direct FanGraphs Scraper
======================================================
Bypasses pybaseball entirely. pybaseball uses the old /leaders-legacy.aspx
endpoint which FanGraphs has blocked. This module calls the live
/leaders/major-league page directly and parses the HTML table.Three FanGraphs pages scraped (all confirmed working as of April 2026):Overall team pitching  → ERA, FIP, xFIP, xERA, WHIP, K/9, BB/9
Starters by team       → Starter ERA, FIP, K/9  (stats=sta & team=0,ts)
Relievers by team      → Bullpen ERA, FIP, K/9  (stats=rel & team=0,ts)

MLB Stats API provides K% (SO/TBF) as a cross-check and fallback.FanGraphs team abbreviation → MLB abbreviation map is applied before
returning so all keys match the rest of your codebase.
"""import math
import requests
import warnings
from datetime import datetime, date
from typing import Dict, List, Optionalimport pandas as pdwarnings.filterwarnings("ignore")# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

SEASON      = datetime.today().year
FIP_CONST   = 3.10          # approximate; FanGraphs recalculates yearly
FG_BASE     = "https://www.fangraphs.com/leaders/major-league"
FG_HEADERS  = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}# FanGraphs abbr → standard MLB abbr
FG_TO_MLB: Dict[str, str] = {
    "WSN": "WAS",
    "CHW": "CWS",
    "KCR": "KC",
    "SDP": "SD",
    "SFG": "SF",
    "TBR": "TB",
    "ATH": "OAK",   # Oakland relocated but FG uses ATH
}MLB_TEAMS = [
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
TEAM_NAME_MAP = {t["abbr"]: t["name"] for t in MLB_TEAMS}# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _safe(val, digits: int = 2) -> Optional[float]:
    """Convert to float, round, return None for NaN/None/inf."""
    try:
        f = float(str(val).replace("%", "").replace(",", "").strip())
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, digits)
    except Exception:
        return Nonedef _pct(val) -> Optional[float]:
    """Parse a percentage string like '22.4%' → 22.4, or 0.224 → 22.4."""
    v = _safe(val)
    if v is None:
        return None
    return round(v * 100, 1) if v < 2 else round(v, 1)def _to_abbr(fg_team: str) -> str:
    t = str(fg_team).upper().strip()
    return FG_TO_MLB.get(t, t)def _parse_ip(ip_str) -> float:
    try:
        parts = str(ip_str).split(".")
        return int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
    except Exception:
        return 0.0def _fip(so, bb, hbp, hr, ip) -> Optional[float]:
    if not ip or ip <= 0:
        return None
    return round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONST, 2)# ─────────────────────────────────────────────────────────────────────────────
# FANGRAPHS SCRAPER  (direct HTML, no pybaseball)
# ─────────────────────────────────────────────────────────────────────────────

def _fg_url(stats: str, team: str, season: int,
            start: str = "", end: str = "") -> str:
    """
    Build a FanGraphs team leaderboard URL.stats : 'pit' = all pitchers, 'sta' = starters, 'rel' = relievers
team  : '0,ts' = team aggregate totals  |  '0,ss' = league split (avoid)
"""
today = date.today().strftime("%Y-%m-%d")
sd = start or f"{season}-03-01"
ed = end   or today
return (
    f"{FG_BASE}?pos=all&lg=all&qual=0&type=8"
    f"&season={season}&season1={season}&ind=0"
    f"&rost=0&age=0&players=0"
    f"&stats={stats}&team={team}"
    f"&month=1000&startdate={sd}&enddate={ed}"
)def _scrape_fg_table(url: str, label: str) -> Optional[pd.DataFrame]:
    """
    Fetch a FanGraphs leaderboard page and return the data table as DataFrame.
    Tries pandas read_html first, falls back to manual column extraction.
    """
    try:
        r = requests.get(url, headers=FG_HEADERS, timeout=25)
        r.raise_for_status()
    except Exception as e:
        print(f"  FG fetch error [{label}]: {e}")
        return Nonehtml = r.text

# pandas read_html finds all <table> elements
try:
    tables = pd.read_html(html)
    # Pick the table most likely to be the stats table:
    # it should have a "Team" or "Season" column AND ERA/FIP
    for t in tables:
        cols = [str(c).strip() for c in t.columns]
        has_team   = any(c in ("Team", "Season") for c in cols)
        has_stat   = any(c in ("ERA", "FIP", "xFIP") for c in cols)
        enough_rows = len(t) >= 10   # at least 10 teams
        if has_team and has_stat and enough_rows:
            # Rename duplicate/unnamed columns
            t.columns = [str(c).strip() for c in t.columns]
            # Drop rows where Team is NaN or is a header repeat
            if "Team" in t.columns:
                t = t[t["Team"].notna()]
                t = t[~t["Team"].astype(str).str.upper().isin(
                    {"TEAM", "NAN", "", "SEASON"}
                )]
            elif "Season" in t.columns:
                # starters page uses Season not Team
                pass
            print(f"  FG [{label}]: {len(t)} rows, cols: {list(t.columns[:8])}")
            return t.reset_index(drop=True)
except Exception as e:
    print(f"  FG parse error [{label}]: {e}")

return Nonedef _parse_fg_rows(df: pd.DataFrame, col_team: str) -> Dict[str, Dict]:
    """Extract key stats from a FanGraphs DataFrame into {abbr: {...}} dict."""
    result: Dict[str, Dict] = {}
    cols = [str(c).strip() for c in df.columns]
    df.columns = colsfor _, row in df.iterrows():
    raw_team = str(row.get(col_team, "")).strip()
    if not raw_team or raw_team.upper() in ("NAN", "", col_team.upper()):
        continue
    abbr = _to_abbr(raw_team)
    if len(abbr) > 5:          # skip aggregate rows
        continue

    result[abbr] = {
        "era":  _safe(row.get("ERA")),
        "fip":  _safe(row.get("FIP")),
        "xfip": _safe(row.get("xFIP")),
        "xera": _safe(row.get("xERA")),
        "whip": _safe(row.get("WHIP")),
        "k9":   _safe(row.get("K/9"), 1),
        "bb9":  _safe(row.get("BB/9"), 1),
        "babip": _safe(row.get("BABIP")),
        "lob_pct": _pct(row.get("LOB%")),
        "hr_fb":   _pct(row.get("HR/FB")),
    }
return resultdef fetch_fangraphs_all(season: int) -> Dict[str, Dict]:
    """
    Scrape three FanGraphs pages:
      - overall team pitching (ERA, FIP, xFIP)
      - starters  (starter ERA, FIP)
      - relievers (bullpen ERA, FIP)Returns merged dict keyed by team abbreviation.
"""
today = date.today().strftime("%Y-%m-%d")
start = f"{season}-03-01"

# ── 1. Overall ──────────────────────────────────────────────────────────
url_overall = _fg_url("pit", "0%2Cts", season, start, today)
df_overall  = _scrape_fg_table(url_overall, "overall")

# ── 2. Starters ─────────────────────────────────────────────────────────
url_sta = _fg_url("sta", "0%2Cts", season, start, today)
df_sta  = _scrape_fg_table(url_sta, "starters")

# ── 3. Relievers ────────────────────────────────────────────────────────
url_rel = _fg_url("rel", "0%2Cts", season, start, today)
df_rel  = _scrape_fg_table(url_rel, "relievers")

merged: Dict[str, Dict] = {}

# Overall
if df_overall is not None:
    col = "Team" if "Team" in df_overall.columns else df_overall.columns[0]
    for abbr, stats in _parse_fg_rows(df_overall, col).items():
        merged[abbr] = {**stats, "source": "fangraphs"}

# Starters overlay
if df_sta is not None:
    col = "Team" if "Team" in df_sta.columns else df_sta.columns[0]
    for abbr, stats in _parse_fg_rows(df_sta, col).items():
        if abbr not in merged:
            merged[abbr] = {"source": "fangraphs"}
        merged[abbr]["starter_era"]  = stats.get("era")
        merged[abbr]["starter_fip"]  = stats.get("fip")
        merged[abbr]["starter_xfip"] = stats.get("xfip")
        merged[abbr]["starter_k9"]   = stats.get("k9")
        merged[abbr]["starter_whip"] = stats.get("whip")

# Relievers overlay
if df_rel is not None:
    col = "Team" if "Team" in df_rel.columns else df_rel.columns[0]
    for abbr, stats in _parse_fg_rows(df_rel, col).items():
        if abbr not in merged:
            merged[abbr] = {"source": "fangraphs"}
        merged[abbr]["bullpen_era"]  = stats.get("era")
        merged[abbr]["bullpen_fip"]  = stats.get("fip")
        merged[abbr]["bullpen_xfip"] = stats.get("xfip")
        merged[abbr]["bullpen_k9"]   = stats.get("k9")
        merged[abbr]["bullpen_whip"] = stats.get("whip")

return merged# ─────────────────────────────────────────────────────────────────────────────
# MLB STATS API  (K%, ERA split cross-check, fallback)
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
        tbf = int(s.get("battersFaced",1))
        era  = _safe(s.get("era")) or (round(er/ip*9,2) if ip>0 else None)
        whip = _safe(s.get("whip")) or (round((bb+h)/ip,2) if ip>0 else None)
        k_pct = round(so/tbf*100,1) if tbf > 0 else None
        return {
            "era": era, "whip": whip,
            "k_pct": k_pct, "fip": _fip(so,bb,hbp,hr,ip),
            "ip": round(ip,1),
        }
    except Exception:
        return Nonedef _mlb_overall(team_id: int, season: int) -> Optional[Dict]:
    url = (
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
        f"?stats=season&season={season}&group=pitching"
    )
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        splits = r.json().get("stats",[{}])[0].get("splits",[])
        if not splits:
            return None
        s   = splits[0]["stat"]
        ip  = _parse_ip(s.get("inningsPitched","0.0"))
        if ip < 1:
            return None
        so  = int(s.get("strikeOuts",  0))
        bb  = int(s.get("baseOnBalls", 0))
        hbp = int(s.get("hitBatsmen",  0))
        hr  = int(s.get("homeRuns",    0))
        er  = int(s.get("earnedRuns",  0))
        h   = int(s.get("hits",        0))
        tbf = int(s.get("battersFaced",1))
        era  = _safe(s.get("era")) or round(er/ip*9,2)
        whip = _safe(s.get("whip")) or round((bb+h)/ip,2)
        k_pct = round(so/tbf*100,1) if tbf>0 else None
        return {
            "era": era, "whip": whip, "k_pct": k_pct,
            "fip": _fip(so,bb,hbp,hr,ip), "source": "mlb_api",
        }
    except Exception as e:
        print(f"  MLB API error team {team_id}: {e}")
        return Nonedef _league_era(season: int) -> float:
    url = (
        f"https://statsapi.mlb.com/api/v1/stats?stats=season&season={season}"
        f"&group=pitching&gameType=R&sportId=1&limit=1&playerPool=ALL"
    )
    try:
        r = requests.get(url, timeout=10)
        sp = r.json().get("stats",[{}])[0].get("splits",[])
        if sp:
            return float(sp[0]["stat"].get("era", 4.20))
    except Exception:
        pass
    return 4.20# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def get_all_team_pitching(season: int = None) -> List[Dict]:
    """
    Returns list of dicts (one per team, sorted by starter ERA) containing:
      team, name,
      era, fip, xfip, xera, whip, k9, bb9,          ← FanGraphs overall
      starter_era, starter_fip, starter_whip, starter_k9,
      bullpen_era,  bullpen_fip,  bullpen_whip,  bullpen_k9,
      k_pct,                                          ← MLB API (SO/TBF)
      era_plus,                                       ← calculated
      source
    """
    if season is None:
        season = SEASONprint(f"[team_pitching] Season {season} — fetching FanGraphs…")
fg = fetch_fangraphs_all(season)
print(f"  FanGraphs: {len(fg)} teams loaded")

lg_era = _league_era(season)
print(f"  League ERA (MLB API): {lg_era}")

results: List[Dict] = []

for team in MLB_TEAMS:
    tid  = team["id"]
    abbr = team["abbr"]
    name = team["name"]

    fg_t = fg.get(abbr, {})

    # MLB API K% split (more reliable than estimating from K/9)
    sp_split = _mlb_split(tid, season, "startingPitchers")
    bp_split = _mlb_split(tid, season, "reliefPitchers")
    mlb_all  = _mlb_overall(tid, season) if not fg_t else None

    # Prefer FanGraphs overall; MLB API as fallback
    era  = fg_t.get("era")  or (mlb_all or {}).get("era")
    whip = fg_t.get("whip") or (mlb_all or {}).get("whip")
    fip  = fg_t.get("fip")  or (mlb_all or {}).get("fip")
    xfip = fg_t.get("xfip")
    xera = fg_t.get("xera")
    k9   = fg_t.get("k9")
    bb9  = fg_t.get("bb9")

    # K% — MLB API (SO/TBF) is more accurate than deriving from K/9
    k_pct = (mlb_all or {}).get("k_pct") or (sp_split or {}).get("k_pct")

    # ERA+ — park-adjusted needs FanGraphs membership; use raw approximation
    era_plus = round(100 * lg_era / era, 0) if (era and era > 0) else None

    # Starter / bullpen split — prefer FanGraphs if available
    starter_era  = fg_t.get("starter_era")  or (sp_split or {}).get("era")
    starter_fip  = fg_t.get("starter_fip")  or (sp_split or {}).get("fip")
    starter_whip = fg_t.get("starter_whip") or (sp_split or {}).get("whip")
    starter_k9   = fg_t.get("starter_k9")
    starter_kpct = (sp_split or {}).get("k_pct")

    bullpen_era  = fg_t.get("bullpen_era")  or (bp_split or {}).get("era")
    bullpen_fip  = fg_t.get("bullpen_fip")  or (bp_split or {}).get("fip")
    bullpen_whip = fg_t.get("bullpen_whip") or (bp_split or {}).get("whip")
    bullpen_k9   = fg_t.get("bullpen_k9")
    bullpen_kpct = (bp_split or {}).get("k_pct")

    if not any([era, starter_era, bullpen_era]):
        print(f"  {abbr}: no data — skipping")
        continue

    source = fg_t.get("source", "mlb_api")
    if starter_era and fg_t.get("starter_era"):
        source = "FanGraphs"
    elif starter_era:
        source = "FanGraphs + MLB API"

    results.append({
        "team": abbr,
        "name": name,
        # Overall (FanGraphs)
        "era":   era,
        "whip":  whip,
        "fip":   fip,
        "xfip":  xfip,
        "xera":  xera,
        "k9":    k9,
        "bb9":   bb9,
        "k_pct": k_pct,
        "era_plus": era_plus,
        # Starters
        "starter_era":  starter_era,
        "starter_fip":  starter_fip,
        "starter_whip": starter_whip,
        "starter_k9":   starter_k9,
        "starter_k_pct": starter_kpct,
        # Bullpen
        "bullpen_era":  bullpen_era,
        "bullpen_fip":  bullpen_fip,
        "bullpen_whip": bullpen_whip,
        "bullpen_k9":   bullpen_k9,
        "bullpen_k_pct": bullpen_kpct,
        "source": source,
    })

results.sort(key=lambda x: (x.get("starter_era") or x.get("era") or 99))
print(f"  {len(results)} teams ready")
return resultsif __name__ == "__main__":
    data = get_all_team_pitching()
    if not data:
        print("No data returned!")
    else:
        print(f"\n{'Team':<5} {'SP ERA':<9} {'BP ERA':<9} {'ERA':<7} {'FIP':<7} {'xFIP':<7} {'Source'}")
        print("─" * 65)
        for t in data:
            print(
                f"{t['team']:<5}"
                f"{str(t.get('starter_era') or '—'):<9}"
                f"{str(t.get('bullpen_era')  or '—'):<9}"
                f"{str(t.get('era')          or '—'):<7}"
                f"{str(t.get('fip')          or '—'):<7}"
                f"{str(t.get('xfip')         or '—'):<7}"
                f"{t.get('source','?')}"
            )

