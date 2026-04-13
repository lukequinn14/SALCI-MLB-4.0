#!/usr/bin/env python3
"""
SALCI: Fetch Team Pitching Stats (GitHub Actions script)
=========================================================
Runs daily at 6 AM ET via GitHub Actions.
GitHub Actions runners have unrestricted internet — can reach fangraphs.com.
Streamlit Cloud cannot reach fangraphs.com directly (proxy restriction).

This script:
  1. Scrapes FanGraphs team pitching leaderboards (overall + starter + bullpen)
  2. Saves to data/team_pitching/latest.json
  3. Commits & pushes to the repo via GitHub Contents API
  4. Streamlit app reads the JSON file at runtime — no live HTTP to FanGraphs needed

Usage:
  python scripts/fetch_team_pitching_action.py          # current season
  python scripts/fetch_team_pitching_action.py 2026     # specific season
"""

import base64
import json
import math
import os
import sys
import warnings
from datetime import datetime
from typing import Dict, List, Optional

import requests
import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

SEASON   = int(sys.argv[1]) if len(sys.argv) > 1 else datetime.today().year
FIP_CONSTANT = 3.10

REPO_ROOT   = os.path.join(os.path.dirname(__file__), "..")
DATA_DIR    = os.path.join(REPO_ROOT, "data", "team_pitching")
OUTPUT_FILE = os.path.join(DATA_DIR, "latest.json")

_FG_BASE = "https://www.fangraphs.com/leaders/major-league"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

# FanGraphs abbreviation → standard MLB abbreviation
_FG_TO_MLB = {
    "SDP": "SD",  "SFG": "SF",  "KCR": "KC",
    "WSN": "WAS", "CHW": "CWS", "TBR": "TB",
    "ATH": "OAK",
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

_TEAM_NAME_LOOKUP = {t["abbr"]: t["name"] for t in MLB_TEAMS}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _safe(val, digits: int = 2) -> Optional[float]:
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, digits)
    except Exception:
        return None


def _pct(val) -> Optional[float]:
    """Convert '22.4%' / 0.224 / 22.4 → 22.4."""
    try:
        s = str(val).strip().rstrip("%")
        f = float(s)
        return round(f if f > 2 else f * 100, 1)
    except Exception:
        return None


def _norm(raw: str) -> str:
    up = raw.strip().upper()
    return _FG_TO_MLB.get(up, up)


# ─────────────────────────────────────────────────────────────────────────────
# FANGRAPHS SCRAPER
# ─────────────────────────────────────────────────────────────────────────────

def _fg_url(stats: str, team: str, type_: int) -> str:
    today = datetime.today().strftime("%Y-%m-%d")
    return (
        f"{_FG_BASE}?pos=all&lg=all&qual=0&type={type_}"
        f"&season={SEASON}&month=1000&season1={SEASON}"
        f"&ind=0&rost=0&age=0&players=0"
        f"&stats={stats}&team={team}"
        f"&startdate={SEASON}-03-01&enddate={today}"
    )


def _scrape(url: str, label: str) -> Optional[pd.DataFrame]:
    log(f"  Fetching {label}…")
    try:
        r = requests.get(url, headers=_HEADERS, timeout=30)
        r.raise_for_status()
        tables = pd.read_html(r.text)
        for df in tables:
            cols = [str(c).strip() for c in df.columns]
            if "Team" in cols and ("ERA" in cols or "FIP" in cols):
                df.columns = cols
                df = df[df["Team"].notna()]
                df = df[~df["Team"].astype(str).str.contains("Team|#", na=False)]
                return df.reset_index(drop=True)
        log(f"    No matching table in {label}")
        return None
    except Exception as e:
        log(f"    Error scraping {label}: {e}")
        return None


def _parse(df: Optional[pd.DataFrame]) -> Dict[str, Dict]:
    if df is None or df.empty:
        return {}
    result: Dict[str, Dict] = {}
    for _, row in df.iterrows():
        raw = str(row.get("Team", "")).strip()
        if not raw or raw.lower() in ("team", "nan", ""):
            continue
        abbr  = _norm(raw)
        entry: Dict = {}
        for col in df.columns:
            c = col.strip()
            v = row[col]
            if c == "ERA":       entry["era"]     = _safe(v)
            elif c == "xERA":    entry["xera"]    = _safe(v)
            elif c == "FIP":     entry["fip"]     = _safe(v)
            elif c == "xFIP":    entry["xfip"]    = _safe(v)
            elif c in ("K/9","K9"):  entry["k9"]  = _safe(v, 1)
            elif c in ("BB/9","BB9"): entry["bb9"] = _safe(v, 1)
            elif c == "WHIP":    entry["whip"]    = _safe(v)
            elif c == "BABIP":   entry["babip"]   = _safe(v)
            elif c in ("LOB%","LOB"): entry["lob_pct"] = _pct(v)
            elif c in ("GB%","GB"):   entry["gb_pct"]  = _pct(v)
            elif c in ("HR/FB","HRFB"): entry["hr_fb"] = _pct(v)
            elif c == "WAR":     entry["war"]     = _safe(v, 1)
            elif c == "K%":      entry["k_pct"]   = _pct(v)
            elif c == "BB%":     entry["bb_pct"]  = _pct(v)
            elif c in ("ERA-","ERA_MINUS"): entry["era_minus"] = _safe(v, 1)
        if entry.get("era_minus"):
            entry["era_plus"] = round(200 - entry["era_minus"], 0)
        if not entry.get("k_pct") and entry.get("k9"):
            # Approximate K% from K/9: K/9 ÷ 9 * ~26.5 PA/G  ≈ K%
            entry["k_pct"] = round(entry["k9"] / 9 * 26.5, 1)
        result[abbr] = entry
    return result


def fetch_fangraphs() -> Dict[str, Dict]:
    merged: Dict[str, Dict] = {}

    # Overall Dashboard
    df = _scrape(_fg_url("pit", "0,ts", 8), "overall Dashboard")
    for abbr, d in _parse(df).items():
        merged.setdefault(abbr, {}).update(d)

    # Advanced (K%, BB%)
    df_adv = _scrape(_fg_url("pit", "0,ts", 1), "overall Advanced")
    for abbr, d in _parse(df_adv).items():
        for k in ("k_pct", "bb_pct", "era_minus", "era_plus"):
            if d.get(k) is not None:
                merged.setdefault(abbr, {})[k] = d[k]

    # Starter split
    df_sp = _scrape(_fg_url("sta", "0,ss", 8), "starter split")
    for abbr, d in _parse(df_sp).items():
        tgt = merged.setdefault(abbr, {})
        for k, v in d.items():
            tgt[f"starter_{k}"] = v

    # Bullpen split
    df_bp = _scrape(_fg_url("rel", "0,ts", 8), "bullpen split")
    for abbr, d in _parse(df_bp).items():
        tgt = merged.setdefault(abbr, {})
        for k, v in d.items():
            tgt[f"bullpen_{k}"] = v

    for abbr in merged:
        merged[abbr]["source"] = "fangraphs"

    log(f"  FanGraphs: {len(merged)} teams scraped")
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# MLB Stats API fallback (used if FanGraphs scrape fails)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ip(ip_str) -> float:
    try:
        parts = str(ip_str).split(".")
        return int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
    except Exception:
        return 0.0


def _mlb_split(team_id: int, sit_code: str) -> Optional[Dict]:
    url = (
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
        f"?stats=season&season={SEASON}&group=pitching&sitCodes={sit_code}"
    )
    try:
        r = requests.get(url, timeout=12)
        sp = r.json().get("stats", [{}])[0].get("splits", [])
        if not sp:
            return None
        s   = sp[0]["stat"]
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
        era  = _safe(s.get("era")) or round(er / ip * 9, 2)
        whip = _safe(s.get("whip")) or round((bb + h) / ip, 2)
        return {
            "era":   era,
            "whip":  whip,
            "k_pct": round(so / tbf * 100, 1) if tbf > 0 else None,
            "k9":    round(so / ip * 9, 1),
            "fip":   round((13*hr + 3*(bb+hbp) - 2*so) / ip + FIP_CONSTANT, 2),
        }
    except Exception:
        return None


def fetch_mlb_api() -> Dict[str, Dict]:
    log("  FanGraphs failed — fetching from MLB API…")
    result: Dict[str, Dict] = {}
    for team in MLB_TEAMS:
        tid  = team["id"]
        abbr = team["abbr"]
        sp   = _mlb_split(tid, "startingPitchers")
        bp   = _mlb_split(tid, "reliefPitchers")
        if sp:
            result.setdefault(abbr, {}).update({f"starter_{k}": v for k, v in sp.items()})
        if bp:
            result.setdefault(abbr, {}).update({f"bullpen_{k}": v for k, v in bp.items()})
        # Overall
        try:
            r = requests.get(
                f"https://statsapi.mlb.com/api/v1/teams/{tid}/stats"
                f"?stats=season&season={SEASON}&group=pitching",
                timeout=10
            )
            splits = r.json().get("stats", [{}])[0].get("splits", [])
            if splits:
                s  = splits[0]["stat"]
                ip = _parse_ip(s.get("inningsPitched", "0.0"))
                if ip > 0:
                    so  = int(s.get("strikeOuts",  0))
                    bb  = int(s.get("baseOnBalls", 0))
                    hbp = int(s.get("hitBatsmen",  0))
                    hr  = int(s.get("homeRuns",    0))
                    er  = int(s.get("earnedRuns",  0))
                    h   = int(s.get("hits",        0))
                    tbf = int(s.get("battersFaced", 1))
                    result.setdefault(abbr, {}).update({
                        "era":   _safe(s.get("era")) or round(er / ip * 9, 2),
                        "whip":  _safe(s.get("whip")) or round((bb + h) / ip, 2),
                        "k_pct": round(so / tbf * 100, 1) if tbf > 0 else None,
                        "k9":    round(so / ip * 9, 1),
                        "fip":   round((13*hr+3*(bb+hbp)-2*so)/ip + FIP_CONSTANT, 2),
                        "source": "mlb_api",
                    })
        except Exception:
            pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# BUILD FINAL PAYLOAD
# ─────────────────────────────────────────────────────────────────────────────

def build_payload(raw: Dict[str, Dict]) -> dict:
    teams: List[Dict] = []
    for team in MLB_TEAMS:
        abbr = team["abbr"]
        d    = raw.get(abbr, {})
        if not d:
            continue
        teams.append({
            "team":  abbr,
            "name":  team["name"],
            "era":         d.get("era"),
            "fip":         d.get("fip"),
            "xfip":        d.get("xfip"),
            "xera":        d.get("xera"),
            "whip":        d.get("whip"),
            "k9":          d.get("k9"),
            "k_pct":       d.get("k_pct"),
            "bb_pct":      d.get("bb_pct"),
            "babip":       d.get("babip"),
            "lob_pct":     d.get("lob_pct"),
            "gb_pct":      d.get("gb_pct"),
            "hr_fb":       d.get("hr_fb"),
            "war":         d.get("war"),
            "era_minus":   d.get("era_minus"),
            "era_plus":    d.get("era_plus"),
            "starter_era":   d.get("starter_era"),
            "starter_fip":   d.get("starter_fip"),
            "starter_xfip":  d.get("starter_xfip"),
            "starter_whip":  d.get("starter_whip"),
            "starter_k9":    d.get("starter_k9"),
            "starter_k_pct": d.get("starter_k_pct"),
            "bullpen_era":   d.get("bullpen_era"),
            "bullpen_fip":   d.get("bullpen_fip"),
            "bullpen_xfip":  d.get("bullpen_xfip"),
            "bullpen_whip":  d.get("bullpen_whip"),
            "bullpen_k9":    d.get("bullpen_k9"),
            "bullpen_k_pct": d.get("bullpen_k_pct"),
            "source": d.get("source", "unknown"),
        })
    teams.sort(key=lambda x: (x.get("starter_era") or x.get("era") or 99))
    return {
        "saved_at": datetime.now().isoformat(),
        "season":   SEASON,
        "teams":    teams,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SAVE & COMMIT
# ─────────────────────────────────────────────────────────────────────────────

def save_locally(payload: dict) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    log(f"  Saved → {OUTPUT_FILE}")
    return OUTPUT_FILE


def commit_to_github(local_path: str) -> bool:
    token   = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    gh_repo = os.environ.get("GH_REPO")
    if not token or not gh_repo:
        log("  WARN: GH_TOKEN/GH_REPO not set — skipping commit")
        return False

    repo_path = "data/team_pitching/latest.json"
    api_url   = f"https://api.github.com/repos/{gh_repo}/contents/{repo_path}"
    headers   = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    sha = None
    try:
        r = requests.get(api_url, headers=headers, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass

    payload = {
        "message": f"chore(data): team pitching stats {datetime.today().strftime('%Y-%m-%d')}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(api_url, headers=headers, json=payload, timeout=30)
        if r.status_code in (200, 201):
            log(f"  ✅ Committed {repo_path}")
            return True
        log(f"  ERROR commit: {r.status_code} — {r.text[:200]}")
        return False
    except Exception as e:
        log(f"  ERROR commit: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log(f"=== fetch_team_pitching_action.py  season={SEASON} ===")

    raw = fetch_fangraphs()
    if len(raw) < 20:
        log(f"  FanGraphs only returned {len(raw)} teams — supplementing with MLB API")
        mlb_raw = fetch_mlb_api()
        for abbr, d in mlb_raw.items():
            if abbr not in raw:
                raw[abbr] = d

    payload = build_payload(raw)
    source = payload["teams"][0]["source"] if payload["teams"] else "unknown"
    log(f"  {len(payload['teams'])} teams built (source: {source})")

    local = save_locally(payload)
    commit_to_github(local)
    log("=== Done ===")


if __name__ == "__main__":
    main()
