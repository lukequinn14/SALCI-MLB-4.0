#!/usr/bin/env python3
"""
SALCI Data Loader  ·  v2.0
============================
Two-stage pre-compute fast-path for mlb_salci_full.py.

Stage 1  (Nightly · ~2 AM ET)
    generate_daily_base.py  → data/daily/YYYY-MM-DD_base.json
    Heavy Statcast metrics: Stuff+, Location+, workload baselines.
    No lineups yet — matchup_score uses team-level K%.

Stage 2  (Day-of · every 20 min from 11 AM ET)
    generate_daily_final.py → data/daily/YYYY-MM-DD_final.json
    Upgrades matchup_score to individual hitter K% once lineup confirmed.
    lineup_confirmed = True for at least one game.

Load priority
-------------
    daily_final.json  (highest quality)
    daily_base.json   (nightly fallback)
    None              (falls back to mlb_salci_full.py live compute)

Public API
----------
load_todays_data(date_str)  → (data_dict | None, source_label)
    Tries final → base → GitHub raw → None.

get_pitchers(data_dict)     → list[dict]
    Extracts the ``pitchers`` list from a loaded data dict.

source_banner(data, source, live_confirmed_count, total_pitchers)
    → (message, level)
    Returns a user-facing status message and a Streamlit level string
    ("success" | "info" | "warning").

save_precomputed(date_str, pitchers, stage, metadata)  → bool
    Writes a stage JSON file (used by GitHub Actions scripts).

Shared schema  (single pitcher dict)
--------------------------------------
{
    "pitcher":           str,
    "pitcher_id":        int,
    "team":              str,
    "opponent":          str,
    "opponent_id":       int,
    "game_pk":           int,
    "salci":             float,
    "salci_grade":       str,          # S / A / B+ / B / C / D / F
    "expected":          float,        # projected Ks
    "k_line":            str | None,   # e.g. "5.5" — best +EV line
    "odds":              int | None,   # American odds for k_line
    "model_prob":        float | None, # calibrated prob [0,1]
    "edge":              float | None, # model_prob – implied_prob (pct pts)
    "lines":             dict,         # {"5": 72, "6": 48, ...}
    "k_lines":           dict,         # alias of lines (backward compat)
    "stuff_score":       float | None,
    "matchup_score":     float | None,
    "workload_score":    float | None,
    "location_score":    float | None,
    "stuff_breakdown":   dict,         # per-pitch Stuff+ (optional)
    "profile_type":      str,
    "lineup_confirmed":  bool,
    "is_statcast":       bool,
    "stage":             str,          # "base" | "final"
    "generated_at":      str,          # ISO datetime
}
"""

import json
import os
import requests
from datetime import datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
DAILY_DIR = os.path.join(_HERE, "data", "daily")


def _local_path(date_str: str, stage: str) -> str:
    """Return local filesystem path for a given date + stage."""
    return os.path.join(DAILY_DIR, f"{date_str}_{stage}.json")


def _github_raw_url(date_str: str, stage: str) -> Optional[str]:
    """
    Build a GitHub raw URL if GH_REPO is set in env or st.secrets.
    Returns None if GH_REPO is not configured.
    """
    repo = os.environ.get("GH_REPO", "")
    if not repo:
        try:
            import streamlit as st  # noqa: F401 — optional dep
            repo = st.secrets.get("GH_REPO", "")
        except Exception:
            pass
    if not repo:
        return None
    return (
        f"https://raw.githubusercontent.com/{repo}/main/"
        f"data/daily/{date_str}_{stage}.json"
    )


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------

def _try_load_local(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _try_load_remote(url: str) -> Optional[dict]:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def load_todays_data(date_str: Optional[str] = None) -> tuple[Optional[dict], str]:
    """
    Load pre-computed pitcher data for a given date.

    Priority: local final → remote final → local base → remote base → None.

    Returns
    -------
    (data_dict, source_label)
        data_dict   : loaded JSON dict or None
        source_label: "daily_final" | "daily_base" | "none"
    """
    if date_str is None:
        date_str = datetime.today().strftime("%Y-%m-%d")

    for stage in ("final", "base"):
        # Local first (Streamlit Cloud deploy → files are in the repo)
        data = _try_load_local(_local_path(date_str, stage))
        if data:
            return data, f"daily_{stage}"

        # Remote GitHub raw fallback (useful during local development)
        url = _github_raw_url(date_str, stage)
        if url:
            data = _try_load_remote(url)
            if data:
                return data, f"daily_{stage}"

    return None, "none"


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def get_pitchers(data: dict) -> list:
    """Extract the pitchers list from a loaded data dict."""
    if not data:
        return []
    return data.get("pitchers", [])


def get_metadata(data: dict) -> dict:
    """Return the metadata block from a loaded data dict."""
    if not data:
        return {}
    return data.get("metadata", {})


# ---------------------------------------------------------------------------
# Status banner
# ---------------------------------------------------------------------------

def source_banner(
    data: dict,
    source: str,
    live_confirmed_count: int = 0,
    total_pitchers: int = 0,
) -> tuple[str, str]:
    """
    Build a user-facing status message for the data source.

    Returns (message_str, streamlit_level).
    streamlit_level is one of: "success", "info", "warning".
    """
    if source == "none" or data is None:
        return (
            "⚠️ No pre-computed data found — running live compute (slower).",
            "warning",
        )

    meta = get_metadata(data)
    gen_at = meta.get("generated_at", "unknown")
    lineup_count = meta.get("lineup_confirmed_count", 0)
    statcast_count = meta.get("statcast_count", 0)
    stage = meta.get("stage", source.replace("daily_", ""))

    # Try to make the timestamp human-friendly
    try:
        dt = datetime.fromisoformat(gen_at)
        gen_at_str = dt.strftime("%-I:%M %p ET")
    except Exception:
        gen_at_str = gen_at[:16] if gen_at else "unknown"

    pitcher_str = f"{total_pitchers} pitchers" if total_pitchers else ""
    statcast_str = f" · {statcast_count} Statcast" if statcast_count else ""

    if stage == "final":
        confirmed_str = f"{live_confirmed_count} lineups confirmed" if live_confirmed_count else f"{lineup_count} lineups confirmed at build time"
        msg = (
            f"✅ **Pre-computed (Stage 2 — Final)** · Built {gen_at_str}"
            f" · {confirmed_str}{statcast_str}"
            + (f" · {pitcher_str}" if pitcher_str else "")
        )
        return msg, "success"
    else:
        msg = (
            f"📦 **Pre-computed (Stage 1 — Nightly Base)** · Built {gen_at_str}"
            f" · lineups not yet confirmed{statcast_str}"
            + (f" · {pitcher_str}" if pitcher_str else "")
            + " · Will upgrade to Final once lineups drop."
        )
        return msg, "info"


# ---------------------------------------------------------------------------
# Writer (used by GitHub Actions scripts)
# ---------------------------------------------------------------------------

def save_precomputed(
    date_str: str,
    pitchers: list,
    stage: str,
    metadata: Optional[dict] = None,
) -> bool:
    """
    Write a stage JSON file.

    Parameters
    ----------
    date_str   : "YYYY-MM-DD"
    pitchers   : list of pitcher dicts (see schema above)
    stage      : "base" | "final"
    metadata   : optional extra metadata to include

    Returns True on success.
    """
    os.makedirs(DAILY_DIR, exist_ok=True)
    path = _local_path(date_str, stage)

    meta = {
        "date": date_str,
        "stage": stage,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "pitcher_count": len(pitchers),
        "lineup_confirmed_count": sum(1 for p in pitchers if p.get("lineup_confirmed")),
        "statcast_count": sum(1 for p in pitchers if p.get("is_statcast")),
    }
    if metadata:
        meta.update(metadata)

    payload = {
        "metadata": meta,
        "pitchers": pitchers,
    }

    try:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        return True
    except Exception as exc:
        print(f"[data_loader] save_precomputed failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Cleanup helper (keep last N days, prune old files)
# ---------------------------------------------------------------------------

def prune_old_files(keep_days: int = 7) -> int:
    """Delete daily JSON files older than keep_days. Returns count deleted."""
    if not os.path.exists(DAILY_DIR):
        return 0
    cutoff = datetime.today() - timedelta(days=keep_days)
    deleted = 0
    for fname in os.listdir(DAILY_DIR):
        if not fname.endswith(".json"):
            continue
        date_part = fname[:10]  # "YYYY-MM-DD"
        try:
            fdate = datetime.strptime(date_part, "%Y-%m-%d")
            if fdate < cutoff:
                os.remove(os.path.join(DAILY_DIR, fname))
                deleted += 1
        except ValueError:
            pass
    return deleted


if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.today().strftime("%Y-%m-%d")
    data, source = load_todays_data(date)
    msg, level = source_banner(data, source, total_pitchers=len(get_pitchers(data)))
    print(f"Source  : {source}")
    print(f"Level   : {level}")
    print(f"Message : {msg}")
    if data:
        print(f"Pitchers: {len(get_pitchers(data))}")
        print(f"Metadata: {get_metadata(data)}")
