import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from typing import List, Dict, Optional

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE
# ─────────────────────────────────────────────────────────────────────────────
TEAL   = "#1D9E75"
CORAL  = "#D85A30"
BLUE   = "#378ADD"
AMBER  = "#BA7517"
PURPLE = "#7F77DD"
SLATE  = "rgba(148,163,184,0.15)"
TEXT   = "#e2e8f0"

# ─────────────────────────────────────────────────────────────────────────────
# TEAM LOGOS — your exact function
# ─────────────────────────────────────────────────────────────────────────────
MLB_TEAM_ABBREV = {
    "Arizona Diamondbacks": "ari", "Atlanta Braves": "atl", "Baltimore Orioles": "bal",
    "Boston Red Sox": "bos", "Chicago Cubs": "chc", "Chicago White Sox": "cws",
    "Cincinnati Reds": "cin", "Cleveland Guardians": "cle", "Colorado Rockies": "col",
    "Detroit Tigers": "det", "Houston Astros": "hou", "Kansas City Royals": "kc",
    "Los Angeles Angels": "laa", "Los Angeles Dodgers": "lad", "Miami Marlins": "mia",
    "Milwaukee Brewers": "mil", "Minnesota Twins": "min", "New York Mets": "nym",
    "New York Yankees": "nyy", "Oakland Athletics": "oak", "Philadelphia Phillies": "phi",
    "Pittsburgh Pirates": "pit", "San Diego Padres": "sd", "San Francisco Giants": "sf",
    "Seattle Mariners": "sea", "St. Louis Cardinals": "stl", "Tampa Bay Rays": "tb",
    "Texas Rangers": "tex", "Toronto Blue Jays": "tor", "Washington Nationals": "was",
    "Athletics": "oak",
}

def get_team_logo_url(team_name: str) -> str:
    """Official ESPN MLB logos — works with full name or 3-letter abbr."""
    if len(team_name) == 3:
        abbr = team_name.lower()
    else:
        abbr = MLB_TEAM_ABBREV.get(team_name, team_name.lower())
    return f"https://a.espncdn.com/i/teamlogos/mlb/500/{abbr}.png"


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS (your existing beautiful styling)
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """<style> ... (your full CSS from before) ... </style>"""   # keep your existing CSS here

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING (already handles FanGraphs fallback)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load(season: int) -> List[Dict]:
    from team_pitching_stats import get_all_team_pitching
    return get_all_team_pitching(season)

def _load_data(season: int) -> List[Dict]:
    with st.spinner("🔄 Fetching live pitching data…"):
        return _load(season)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS + CHARTS (unchanged except logo usage)
# ─────────────────────────────────────────────────────────────────────────────
def _logo_html(team: str, size: int = 28) -> str:
    url = get_team_logo_url(team)
    return f'<img src="{url}" width="{size}" height="{size}" style="vertical-align:middle;object-fit:contain;" alt="{team}" onerror="this.style.display=\'none\'">'

# (All your chart functions — chart_starter_bullpen, chart_rankings, etc. — stay exactly the same)

def render_pitching_dashboard() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    season = datetime.today().year
    st.markdown("### ⚾ **SALCI Pitching Dashboard**")
    st.caption(f"Live {season} • FanGraphs advanced metrics + MLB Stats API splits")

    data = _load_data(season)
    if not data:
        st.error("❌ No data loaded.")
        return

    # ── FanGraphs Status Banner ─────────────────────────────────────────────
    fg_count = sum(1 for d in data if "FanGraphs" in d.get("source", ""))
    if fg_count >= 20:
        st.success(f"✅ **FanGraphs connected** — {fg_count}/30 teams with FIP, xFIP, ERA+, K%")
    elif fg_count > 0:
        st.warning(f"⚠️ **FanGraphs partial** — {fg_count}/30 teams. Some advanced metrics missing.")
    else:
        st.info("🔌 **FanGraphs offline** — showing MLB Stats API data only (starter/bullpen splits, ERA, WHIP)")

    # ── Top Performers with Logos ───────────────────────────────────────────
    sp_rows = sorted([d for d in data if d.get("starter_era")], key=lambda x: x["starter_era"])[:6]
    if sp_rows:
        st.markdown("**🏆 Top 6 Starter ERAs**")
        cols = st.columns(6)
        for i, team in enumerate(sp_rows):
            with cols[i]:
                st.image(get_team_logo_url(team["team"]), width=48)
                st.caption(f"**{team['team']}**")
                st.metric("SP ERA", f"{team['starter_era']:.2f}")

    st.markdown("---")

    # ── Tabs (your clean tabbed layout) ─────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Starter vs Bullpen", "🏆 Rankings", "🎯 K% vs ERA+",
        "🔮 FIP–ERA Gap", "📐 FIP vs xFIP"
    ])

    with tab1:
        # your chart_starter_bullpen code
        pass   # (keep your existing tab content)

    # (keep the rest of your tabs exactly as you had them)

    # ── Full Data Table with Logos ──────────────────────────────────────────
    with st.expander("📋 Full 30-Team Data Table", expanded=False):
        rows = []
        for d in sorted(data, key=lambda x: x.get("starter_era") or 99):
            rows.append({
                "Logo": _logo_html(d["team"]),
                "Team": d["team"],
                "SP ERA": _fmt(d.get("starter_era"), "era"),
                "BP ERA": _fmt(d.get("bullpen_era"), "era"),
                "ERA": _fmt(d.get("era"), "era"),
                "FIP": _fmt(d.get("fip"), "fip"),
                "xFIP": _fmt(d.get("xfip"), "xfip"),
                "K%": _fmt(d.get("k_pct"), "k_pct"),
                "ERA+": _fmt(d.get("era_plus"), "era_plus"),
                "Source": d.get("source", "MLB API"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption("MLB Stats API = starter/bullpen splits • FanGraphs = advanced metrics (when available)")
