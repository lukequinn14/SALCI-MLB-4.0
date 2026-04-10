"""
data_loader.py  —  SALCI Smart Data Loader
===========================================
Reads pre-computed JSON files instead of doing live Statcast computation.
The app loads in under 3 seconds because all the heavy work is already done.

Priority order:
  1. daily_final.json  (lineup-confirmed SALCI scores — most accurate)
  2. daily_base.json   (pre-computed without lineups — fast fallback)
  3. "live" signal     (neither file found — app falls back to live compute)

The files are read locally when running on your machine, and from GitHub
raw URLs when deployed on Streamlit Cloud. Set the SALCI_DATA_URL env var
to point at your GitHub repo's raw content base URL.

Example env var (put in Streamlit secrets or shell):
    SALCI_DATA_URL = "https://raw.githubusercontent.com/YOUR_USER/YOUR_REPO/main"
"""

import json
import os
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ── Config ───────────────────────────────────────────────────────────────────
# Override this via Streamlit secrets or environment variable.
# Default assumes the app and JSON files are in the same directory (local dev).
_GITHUB_RAW_BASE = os.environ.get("SALCI_DATA_URL", "")

BASE_FILE  = "daily_base.json"
FINAL_FILE = "daily_final.json"

REQUEST_TIMEOUT = 8  # seconds — keeps UI snappy


# ── Internal loaders ─────────────────────────────────────────────────────────

def _load_local(filename: str) -> Optional[Dict]:
    """Try to load a file from the local filesystem."""
    if os.path.exists(filename):
        try:
            with open(filename) as f:
                return json.load(f)
        except Exception as e:
            print(f"[data_loader] Local load failed for {filename}: {e}")
    return None


def _load_remote(filename: str) -> Optional[Dict]:
    """Try to load a file from GitHub raw URL."""
    if not _GITHUB_RAW_BASE:
        return None
    url = f"{_GITHUB_RAW_BASE.rstrip('/')}/{filename}"
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json()
        print(f"[data_loader] Remote load got HTTP {r.status_code} for {url}")
    except Exception as e:
        print(f"[data_loader] Remote load failed for {url}: {e}")
    return None


def _load(filename: str) -> Optional[Dict]:
    """Load from local disk first, then GitHub raw URL."""
    return _load_local(filename) or _load_remote(filename)


# ── Public API ───────────────────────────────────────────────────────────────

def load_todays_data(today: str) -> Tuple[Optional[Dict], str]:
    """
    Load the best available pre-computed data for today.

    Parameters
    ----------
    today : str
        Date string in YYYY-MM-DD format (e.g. "2026-04-12").

    Returns
    -------
    (data, source)
        data   : Dict or None
        source : "final" | "base" | "live"
                 "live" means no JSON found — caller should run live compute.
    """
    # Try lineup-confirmed final first
    final = _load(FINAL_FILE)
    if final and final.get("date") == today:
        return final, "final"

    # Fall back to base (no lineups yet)
    base = _load(BASE_FILE)
    if base and base.get("date") == today:
        return base, "base"

    # Nothing found — signal the app to compute live
    return None, "live"


def get_pitchers(data: Dict) -> List[Dict]:
    """Extract the list of pitcher result dicts from a loaded data file."""
    return data.get("pitchers", [])


def data_freshness_label(data: Dict) -> str:
    """
    Human-readable freshness string, e.g. "12m ago" or "2h ago".
    Uses 'updated_at' (final) or 'generated_at' (base).
    """
    ts = data.get("updated_at") or data.get("generated_at", "")
    if not ts:
        return "unknown"
    try:
        dt      = datetime.fromisoformat(ts)
        minutes = int((datetime.now() - dt).total_seconds() / 60)
        if minutes < 1:    return "just now"
        if minutes < 60:   return f"{minutes}m ago"
        if minutes < 1440: return f"{minutes // 60}h ago"
        return f"{minutes // 1440}d ago"
    except Exception:
        return ts[:16]


def confirmed_lineup_count(data: Dict) -> int:
    """Return the number of pitchers with confirmed opponent lineups."""
    return sum(1 for p in data.get("pitchers", []) if p.get("lineup_confirmed"))


def source_banner(data: Dict, source: str) -> Tuple[str, str]:
    """
    Returns (message, streamlit_level) for displaying a status banner.
    streamlit_level is one of: "success", "info", "warning"
    """
    freshness = data_freshness_label(data)
    confirmed = confirmed_lineup_count(data)
    total     = len(data.get("pitchers", []))

    if source == "final":
        msg = (
            f"✅ Lineup-confirmed data · "
            f"{confirmed}/{total} lineups locked · "
            f"updated {freshness}"
        )
        return msg, "success"

    if source == "base":
        msg = (
            f"📊 Pre-computed base data · "
            f"lineups not yet confirmed · "
            f"built {freshness}"
        )
        return msg, "info"

    return "⚠️ No pre-computed data — running live calculations", "warning"


# ── Pro gate helpers ──────────────────────────────────────────────────────────

# Fields that are hidden from free users
PRO_FIELDS = {
    "k_lines",
    "floor",
    "floor_confidence",
    "stuff_breakdown",
    "matchup_score",
    "workload_score",
    "location_score",
    "stuff_score",
    "volatility",
    "lineup",
}


def strip_pro_fields(pitcher: Dict) -> Dict:
    """Return a copy of the pitcher dict with Pro fields removed/blanked."""
    stripped = {k: v for k, v in pitcher.items() if k not in PRO_FIELDS}
    # Keep k_lines key but empty it so card rendering doesn't break
    stripped["k_lines"] = {}
    return stripped


def check_pro_password(entered: str) -> bool:
    """
    Validate the entered password against st.secrets["PATREON_PASSWORD"].
    Returns True in dev mode (no secret configured).
    Import streamlit here to avoid circular deps when running scripts standalone.
    """
    try:
        import streamlit as st
        pro_pass = st.secrets.get("PATREON_PASSWORD", "")
        if not pro_pass:
            return True  # No gate configured — dev/local mode
        return entered.strip() == pro_pass.strip()
    except Exception:
        return True  # If streamlit isn't available (e.g. CLI), allow all
