"""
data_loader.py — SALCI Smart Data Loader
=========================================
Reads pre-computed JSON files written by the nightly/day-of GitHub Actions
scripts instead of running live Statcast computation on every page load.

Priority:
  1. daily_final.json  — lineup-confirmed SALCI scores (most accurate)
  2. daily_base.json   — pre-computed without lineups (fast fallback)
  3. returns (None, "live") — caller runs live compute

Set SALCI_DATA_URL in Streamlit secrets to point at your GitHub repo's
raw-content base URL:
  SALCI_DATA_URL = "https://raw.githubusercontent.com/YOUR_USER/YOUR_REPO/main"
"""

import json
import os
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple

_GITHUB_RAW_BASE = os.environ.get("SALCI_DATA_URL", "")

BASE_FILE  = "daily_base.json"
FINAL_FILE = "daily_final.json"
REQUEST_TIMEOUT = 8


def _load_local(filename: str) -> Optional[Dict]:
    if os.path.exists(filename):
        try:
            with open(filename) as f:
                return json.load(f)
        except Exception as e:
            print(f"[data_loader] Local load failed for {filename}: {e}")
    return None


def _load_remote(filename: str) -> Optional[Dict]:
    if not _GITHUB_RAW_BASE:
        return None
    url = f"{_GITHUB_RAW_BASE.rstrip('/')}/{filename}"
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json()
        print(f"[data_loader] Remote HTTP {r.status_code} for {url}")
    except Exception as e:
        print(f"[data_loader] Remote load failed for {url}: {e}")
    return None


def _load(filename: str) -> Optional[Dict]:
    return _load_local(filename) or _load_remote(filename)


def load_todays_data(today: str) -> Tuple[Optional[Dict], str]:
    """
    Load the best available pre-computed data for today.

    Parameters
    ----------
    today : str  — date in YYYY-MM-DD format

    Returns
    -------
    (data, source)  where source is "final" | "base" | "live"
    "live" means no JSON found — caller should run live compute.
    """
    final = _load(FINAL_FILE)
    if final and final.get("date") == today:
        return final, "final"

    base = _load(BASE_FILE)
    if base and base.get("date") == today:
        return base, "base"

    return None, "live"


def get_pitchers(data: Dict) -> List[Dict]:
    """Extract pitcher list from a loaded data file."""
    return data.get("pitchers", [])


def data_freshness_label(data: Dict) -> str:
    ts = data.get("updated_at") or data.get("generated_at", "")
    if not ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(ts)
        minutes = int((datetime.now() - dt).total_seconds() / 60)
        if minutes < 1:    return "just now"
        if minutes < 60:   return f"{minutes}m ago"
        if minutes < 1440: return f"{minutes // 60}h ago"
        return f"{minutes // 1440}d ago"
    except Exception:
        return ts[:16]


def confirmed_lineup_count(data: Dict) -> int:
    return sum(1 for p in data.get("pitchers", []) if p.get("lineup_confirmed"))


def source_banner(data: Dict, source: str) -> Tuple[str, str]:
    """
    Returns (message, streamlit_level) for st.success / st.info / st.warning.
    """
    freshness = data_freshness_label(data)
    confirmed = confirmed_lineup_count(data)
    total     = len(data.get("pitchers", []))

    if source == "final":
        msg = (f"✅ Lineup-confirmed data · "
               f"{confirmed}/{total} lineups locked · updated {freshness}")
        return msg, "success"

    if source == "base":
        msg = (f"📊 Pre-computed base data · "
               f"lineups not yet confirmed · built {freshness}")
        return msg, "info"

    return "⚠️ No pre-computed data — running live calculations", "warning"
