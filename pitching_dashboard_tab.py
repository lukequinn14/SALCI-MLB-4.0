"""
SALCI Pitching Dashboard Tab  ·  v3.0
======================================
Drop-in replacement for the pitching tab.

Usage in mlb_salci_full.py:
    try:
        from pitching_dashboard_tab import render_pitching_dashboard
        PITCHING_DASH_AVAILABLE = True
    except ImportError:
        PITCHING_DASH_AVAILABLE = False

    with tab8:
        if PITCHING_DASH_AVAILABLE:
            render_pitching_dashboard()

Changes in v3.0
---------------
- ARI logo fix: ESPN uses full-city slugs (arizona, kansas-city, etc.)
- White pill on EVERY logo — HTML via _logo_html(), Plotly bar y-axis via _svg_pill_url()
- Dark navy ring on in-graph scatter logos via _svg_dark_ring_url() (Charts 1 & 3)
- Starter vs Bullpen redesigned as scatter (square, shareable) + team cards below
- Shareable cards for: Best Rotations, Best Bullpens, Worst Bullpens, Best K%, Regression
- Green → Red gradient bars throughout
- Plain #1 #2 #3 rank numbers (no medal emojis)
- Light/dark mode adaptive CSS
- Consistent chart titles + subtitle annotations
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from typing import List, Dict, Optional
import base64

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
# TEAM LOGO HELPERS
# ─────────────────────────────────────────────────────────────────────────────

# ── Abbreviation → ESPN CDN slug ─────────────────────────────────────────────
# IMPORTANT: CWS → "chw" on ESPN (not "cws"). All others match the abbrev
# lowercased EXCEPT the ones mapped explicitly here.
_ABBREV_TO_ESPN: Dict[str, str] = {
    "ARI": "ari", "ATL": "atl", "BAL": "bal", "BOS": "bos",
    "CHC": "chc", "CWS": "chw", "CIN": "cin",
    "CLE": "cle", "COL": "col", "DET": "det", "HOU": "hou",
    "KC":  "kc",  "LAA": "laa", "LAD": "lad", "MIA": "mia",
    "MIL": "mil", "MIN": "min", "NYM": "nym", "NYY": "nyy",
    "OAK": "oak", "PHI": "phi", "PIT": "pit", "SD":  "sd",
    "SF":  "sf",  "SEA": "sea", "STL": "stl",
    "TB":  "tb",  "TEX": "tex", "TOR": "tor", "WSH": "wsh",
}

# ── Name variants → canonical abbreviation ────────────────────────────────────
# Covers BOTH the full official name AND every short/alternate form the MLB
# Stats API, FanGraphs, or Baseball Savant might return.
# Add new aliases here — never touch _ABBREV_TO_ESPN.
_FULL_TO_ABBREV: Dict[str, str] = {
    # Full official names
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",         "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",      "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",     "Detroit Tigers": "DET",
    "Houston Astros": "HOU",       "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",   "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",        "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",      "New York Mets": "NYM",
    "New York Yankees": "NYY",     "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI","Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",      "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",     "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",        "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",    "Washington Nationals": "WSH",
    "Diamondbacks": "ARI",
    "D-backs": "ARI",
    "D-Backs": "ARI",
    "Arizona": "ARI",
    "AZ": "ARI",  
    "az": "ARi",
    # Other common short names
    "Athletics": "OAK",
    "ATH": "OAK",
    "A's": "OAK",
    "Guardians": "CLE",
    "Nationals": "WSH",
    "Cardinals": "STL",
    "Brewers": "MIL",
    "Padres": "SD",
    "Giants": "SF",
    "Mariners": "SEA",
    "Rockies": "COL",
    "Marlins": "MIA",
    "Twins": "MIN",
    "Rays": "TB",
    "Yankees": "NYY",
    "Mets": "NYM",
    "Cubs": "CHC",
    "White Sox": "CWS",
    "Red Sox": "BOS",
    "Blue Jays": "TOR",
    "Royals": "KC",
    "Angels": "LAA",
    "Dodgers": "LAD",
    "Phillies": "PHI",
    "Pirates": "PIT",
    "Rangers": "TEX",
    "Orioles": "BAL",
    "Braves": "ATL",
    "Reds": "CIN",
    "Tigers": "DET",
    "Astros": "HOU",
}

# ── Teams needing ESPN's /500-dark/ path on dark chart backgrounds ─────────────
# The dark variant is a lighter/higher-contrast version of the logo that ESPN
# serves at the /500-dark/ CDN path (rel=["full","dark"] in ESPN's logos API).
# Only add a team here if its *primary* logo is nearly invisible on navy/black.
#
#   COL - purple + black primary  → silver/white dark variant
#   SD  - brown/sand primary      → bright yellow dark variant
#   NYY - pure navy primary       → white-contrast dark variant
#   MIN - navy/red primary        → brighter dark variant
#   KC  - royal blue primary      → higher contrast dark variant
#   PIT - black/gold primary      → gold-prominent dark variant
#   MIL - navy/gold primary       → brighter dark variant
#   CWS - black primary           → white-contrast dark variant
#   SF  - black/orange primary    → white ring dark variant
#
# NOTE: ARI is intentionally NOT in this set — its red/black/teal serpiente
# logo renders fine on dark backgrounds via the standard scoreboard path.
_DARK_BACKGROUND_TEAMS = {
    "COL", "SD", "NYY", "MIN", "KC", "PIT", "MIL", "CWS", "SF"
}

# ── Hardcoded URL overrides — last-resort escape hatch ───────────────────────
# If ESPN ever restructures their CDN for a specific team, add an override here.
# These bypass all slug logic entirely and return a known-good URL directly.
# Format: abbrev → (standard_url, dark_bg_url)
_URL_OVERRIDES: Dict[str, tuple] = {
    # Example (not currently needed but here for reference):
    # "ARI": (
    #     "https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/ari.png",
    #     "https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/ari.png",
    # ),
}


def _resolve_abbrev(team: str) -> str:
    """
    Convert any team name/alias/abbreviation to a canonical 2-3 letter abbrev.

    Resolution order:
    1. Direct lookup in _FULL_TO_ABBREV (full names + aliases)
    2. Already an abbrev — passthrough if in _ABBREV_TO_ESPN
    3. Substring fuzzy match against _FULL_TO_ABBREV keys
    4. Fallback: uppercase the input and hope for the best
    """
    team_clean = team.strip()

    # 1. Direct alias match (most common path)
    if team_clean in _FULL_TO_ABBREV:
        return _FULL_TO_ABBREV[team_clean]

    # 2. Already a valid abbreviation
    upper = team_clean.upper()
    if upper in _ABBREV_TO_ESPN:
        return upper

    # 3. Case-insensitive alias match
    lower = team_clean.lower()
    for alias, abbrev in _FULL_TO_ABBREV.items():
        if alias.lower() == lower:
            return abbrev

    # 4. Substring fuzzy match — check if input is contained in a known full name
    #    or a known full name is contained in the input. Use the longest match
    #    to avoid "Cardinals" matching "White Sox Cardinals" type edge cases.
    best_match, best_len = None, 0
    for full_name, abbrev in _FULL_TO_ABBREV.items():
        full_lower = full_name.lower()
        if full_lower in lower or lower in full_lower:
            if len(full_name) > best_len:
                best_match, best_len = abbrev, len(full_name)
    if best_match:
        return best_match

    # 5. Last resort — uppercase passthrough (may produce a broken URL, but
    #    the onerror handler in the img tag will hide it gracefully)
    return upper


def get_team_logo_url(team: str, dark_bg: bool = False) -> str:
    """
    Return the ESPN CDN logo URL for any MLB team input.

    Parameters
    ----------
    team    : Any form — full name, nickname, abbreviation, or API short name.
              Examples: "Arizona Diamondbacks", "D-backs", "ARI", "ari"
    dark_bg : When True, use ESPN's /500-dark/ path for teams whose primary
              logo is hard to see on dark/navy chart backgrounds. Pass
              dark_bg=True for all Plotly scatter/bar in-graph logos.
              Pass dark_bg=False (default) for HTML card logos — the white
              pill wrapper provides its own contrast.

    ESPN CDN paths used
    -------------------
    Standard   : https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/{slug}.png
    Dark alt   : https://a.espncdn.com/i/teamlogos/mlb/500-dark/{slug}.png
    

    Both paths work in-browser (Streamlit). Direct server-side fetch returns 403
    (ESPN hotlink protection) — this is expected and harmless.
    """
    if not team:
        return ""

    abbrev = _resolve_abbrev(team)

    # Hardcoded override wins over all slug logic
    if abbrev in _URL_OVERRIDES:
        std_url, dark_url = _URL_OVERRIDES[abbrev]
        return dark_url if dark_bg and abbrev in _DARK_BACKGROUND_TEAMS else std_url

    slug = _ABBREV_TO_ESPN.get(abbrev, abbrev.lower())

    if dark_bg:
        if abbrev in _DARK_BACKGROUND_TEAMS:
            return f"https://a.espncdn.com/i/teamlogos/mlb/500-dark/{slug}.png"
        else:
            return f"https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/{slug}.png"


    return f"https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/{slug}.png"


def resolve_logo_url(team: str, cached_url: str | None, dark_bg: bool = False) -> str:
    """
    Safe wrapper for use inside chart loops where data rows may carry a
    pre-cached logo_url from team_pitching_stats.py.

    Validation rules for accepting a cached URL:
    1. Must contain the ESPN CDN hostname
    2. Must contain a known-good slug from _ABBREV_TO_ESPN values
       (rejects URLs with unresolved slugs like "diamondbacks", "d-backs", etc.)

    If validation fails, the URL is re-derived fresh from the team name.

    Usage:
        url = resolve_logo_url(d["team"], d.get("logo_url"), dark_bg=True)
    """
    ESPN_HOST = "espncdn.com/i/teamlogos/mlb"
    if cached_url and ESPN_HOST in cached_url:
        # Check that the URL contains one of our known valid slugs
        known_slugs = set(_ABBREV_TO_ESPN.values())  # e.g. {"ari", "atl", "chw", ...}
        url_lower = cached_url.lower()
        if any(f"/{slug}." in url_lower for slug in known_slugs):
            return cached_url
    return get_team_logo_url(team, dark_bg=(team in _DARK_BACKGROUND_TEAMS))



def _svg_pill_url(logo_url: str, size: int = 44) -> str:
    pad = size // 6
    inner = size - pad * 2
    cx = size // 2

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}">'
        f'<circle cx="{cx}" cy="{cx}" r="{cx}" fill="white"/>'
        f'<image href="{logo_url}" x="{pad}" y="{pad}" height="{inner}" '
        f'preserveAspectRatio="xMidYMid meet" />'
        f'</svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()



def _svg_dark_ring_url(logo_url: str, size: int = 44) -> str:
    pad = size // 6
    inner = size - pad * 2
    cx = size // 2
    r = cx - 1

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}">'
        f'<circle cx="{cx}" cy="{cx}" r="{r}" fill="rgba(13,27,42,0.85)" '
        f'stroke="#1D9E75" stroke-width="1.5" stroke-opacity="0.6"/>'
        f'<image href="{logo_url}" x="{pad}" y="{pad}" height="{inner}" '
        f'preserveAspectRatio="xMidYMid meet" />'
        f'</svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()



def _logo_html(team: str, size: int = 28) -> str:
    url  = get_team_logo_url(team, dark_bg=(team in _DARK_BACKGROUND_TEAMS))
    pill = size + 10
    return (
        f'<span style="display:inline-flex;align-items:center;justify-content:center;'
        f'background:#ffffff;border-radius:50%;width:{pill}px;height:{pill}px;'
        f'flex-shrink:0;box-shadow:0 1px 4px rgba(0,0,0,0.2);border:1px solid rgba(0,0,0,0.05);">'
        f'<img src="{url}" height="{size}" style="width:auto;max-width:{size}px;object-fit:contain;display:block;" '
        f'onerror="this.style.display=\'none\';"></span>'
    )

# ─────────────────────────────────────────────────────────────────────────────
# CSS — light/dark adaptive
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
<style>
:root {
    --s-bg-card:    rgba(30,41,59,0.70);
    --s-bg-insight: rgba(15,23,42,0.60);
    --s-bg-th:      rgba(15,23,42,0.50);
    --s-text:       #e2e8f0;
    --s-muted:      #94a3b8;
    --s-dim:        #64748b;
    --s-border:     rgba(148,163,184,0.15);
    --s-good:       #34d399;
    --s-bad:        #f87171;
    --s-hover:      rgba(29,158,117,0.08);
}
@media (prefers-color-scheme: light) {
    :root {
        --s-bg-card:    rgba(241,245,249,0.92);
        --s-bg-insight: rgba(226,232,240,0.70);
        --s-bg-th:      rgba(203,213,225,0.60);
        --s-text:       #1e293b;
        --s-muted:      #475569;
        --s-dim:        #64748b;
        --s-border:     rgba(30,41,59,0.15);
        --s-good:       #16a34a;
        --s-bad:        #dc2626;
        --s-hover:      rgba(29,158,117,0.06);
    }
}

.salci-header {
    display:flex; align-items:center; gap:14px;
    padding:18px 22px; border-radius:12px;
    background:linear-gradient(135deg,rgba(29,158,117,0.15) 0%,rgba(55,138,221,0.10) 100%);
    border:1px solid rgba(29,158,117,0.35); margin-bottom:6px;
}
.salci-header h2 { margin:0; font-size:1.55rem; font-weight:700;
    letter-spacing:-0.4px; color:var(--s-text); }
.salci-header p  { margin:2px 0 0; font-size:0.83rem; color:var(--s-muted); }

.fg-banner {
    display:flex; align-items:center; gap:12px; padding:12px 18px;
    border-radius:10px; font-size:0.88rem; font-weight:500;
    margin:10px 0 4px; color:var(--s-text);
}
.fg-banner.ok   { background:rgba(29,158,117,0.13); border:1px solid rgba(29,158,117,0.40); }
.fg-banner.warn { background:rgba(186,117,23,0.13);  border:1px solid rgba(186,117,23,0.40); }
.fg-banner .icon  { font-size:1.3rem; }
.fg-banner .label { font-size:0.78rem; color:var(--s-muted); font-weight:400; }

.perf-card {
    background:var(--s-bg-card); border:1px solid var(--s-border);
    border-radius:10px; padding:12px 10px 10px;
    text-align:center; transition:border-color 0.2s;
}
.perf-card:hover { border-color:rgba(29,158,117,0.50); }
.perf-card .team-abbr {
    font-size:0.78rem; font-weight:700; letter-spacing:1.2px;
    color:var(--s-muted); text-transform:uppercase; margin-top:6px; margin-bottom:2px;
}
.perf-card .stat-val { font-size:1.35rem; font-weight:800; color:#1D9E75; line-height:1.1; }
.perf-card .stat-lbl { font-size:0.72rem; color:var(--s-dim); margin-top:1px; }

.insight-box {
    background:var(--s-bg-insight); border-left:3px solid;
    border-radius:0 8px 8px 0; padding:10px 14px;
    font-size:0.85rem; line-height:1.5; color:var(--s-text);
}
.insight-box.green  { border-color:#1D9E75; }
.insight-box.orange { border-color:#D85A30; }
.insight-box.blue   { border-color:#378ADD; }

.salci-table { width:100%; border-collapse:collapse;
    font-size:0.83rem; font-family:'SF Mono','Fira Code',monospace; }
.salci-table th {
    text-align:left; padding:8px 12px; border-bottom:1px solid var(--s-border);
    color:var(--s-dim); font-size:0.75rem; letter-spacing:0.8px;
    text-transform:uppercase; font-weight:600; background:var(--s-bg-th);
}
.salci-table td {
    padding:7px 12px; border-bottom:1px solid rgba(148,163,184,0.07);
    color:var(--s-text); vertical-align:middle; white-space:nowrap;
}
.salci-table tr:hover td { background:var(--s-hover); }
.salci-table td.good { color:var(--s-good); font-weight:600; }
.salci-table td.bad  { color:var(--s-bad);  font-weight:600; }
.salci-table .badge {
    display:inline-block; padding:2px 7px; border-radius:4px;
    font-size:0.7rem; font-weight:700; letter-spacing:0.5px;
}
.salci-table .badge.fg   { background:rgba(29,158,117,0.20); color:#6ee7b7; }
.salci-table .badge.mlb  { background:rgba(55,138,221,0.20); color:#93c5fd; }
.salci-table .badge.miss { background:rgba(100,116,139,0.20); color:var(--s-muted); }

.section-divider {
    height:1px; margin:18px 0;
    background:linear-gradient(90deg,rgba(29,158,117,0.40) 0%,
        rgba(55,138,221,0.15) 50%,transparent 100%);
}
</style>
"""

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _load(season: int) -> List[Dict]:
    from team_pitching_stats import get_all_team_pitching
    return get_all_team_pitching(season)


def _load_data(season: int) -> List[Dict]:
    with st.spinner("🔄  Fetching live pitching data — MLB API + Baseball Savant…"):
        return _load(season)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _base_layout(**kw) -> dict:
    defaults = dict(
        plot_bgcolor  = "rgba(0,0,0,0)",
        paper_bgcolor = "rgba(0,0,0,0)",
        font          = dict(family="'SF Pro Display','Helvetica Neue',sans-serif",
                             size=12, color=TEXT),
        margin        = dict(l=20, r=40, t=80, b=40),
        hoverlabel    = dict(bgcolor="rgba(15,23,42,0.95)",
                             bordercolor="rgba(148,163,184,0.3)",
                             font_color=TEXT, font_size=12),
    )
    defaults.update(kw)
    return defaults


def _subtitle(text: str) -> dict:
    return dict(
        text=text, x=0, y=1.06, xref="paper", yref="paper",
        showarrow=False, font=dict(size=11, color="#94a3b8"),
    )


def _fmt(val, key: str) -> str:
    if val is None:
        return "—"
    if "pct" in key:
        return f"{val:.1f}%"
    if key in ("era_plus", "era+"):
        return str(int(round(val)))
    return f"{val:.2f}"


def _valid(data: List[Dict], key: str) -> List[Dict]:
    return [d for d in data if d.get(key) is not None]


def _rank_color(rank_idx: int, total: int, invert: bool = False) -> str:
    """Green (#1=best) → Amber → Red (#N=worst). Pass invert=True for worst-first lists."""
    t = rank_idx / max(total - 1, 1)
    if invert:
        t = 1 - t
    if t < 0.5:
        s = t * 2
        r = int(29  + s * (186 - 29))
        g = int(158 + s * (117 - 158))
        b = int(117 + s * (23  - 117))
    else:
        s = (t - 0.5) * 2
        r = int(186 + s * (216 - 186))
        g = int(117 + s * (90  - 117))
        b = int(23  + s * (48  - 23))
    return "rgb(" + str(r) + "," + str(g) + "," + str(b) + ")"


# ─────────────────────────────────────────────────────────────────────────────
# CHART 1: Starter vs Bullpen — scatter (square, shareable)
# ─────────────────────────────────────────────────────────────────────────────

def chart_starter_bullpen(data: List[Dict]) -> Optional[go.Figure]:
    """
    Scatter: x = Starter ERA, y = Bullpen ERA.
    Logos as SVG-pill data URIs pinned to data coordinates.
    Diagonal = equal rotation and bullpen quality.
    Above diagonal = bullpen worse than rotation.
    """
    rows = [d for d in data
            if d.get("starter_era") is not None and d.get("bullpen_era") is not None]
    if not rows:
        return None

    sp_vals  = [d["starter_era"] for d in rows]
    bp_vals  = [d["bullpen_era"] for d in rows]
    all_vals = sp_vals + bp_vals
    v_min    = min(all_vals) - 0.45
    v_max    = max(all_vals) + 0.45

    fig = go.Figure()

    # Invisible hover trace
    fig.add_trace(go.Scatter(
        x          = sp_vals, y = bp_vals, mode = "markers",
        marker     = dict(size=38, opacity=0, color="rgba(0,0,0,0)"),
        customdata = [[d["team"], d["starter_era"], d["bullpen_era"],
                       round(d["bullpen_era"] - d["starter_era"], 2)]
                      for d in rows],
        hovertemplate = (
            "<b>%{customdata[0]}</b><br>"
            "SP ERA: <b>%{customdata[1]:.2f}</b><br>"
            "BP ERA: <b>%{customdata[2]:.2f}</b><br>"
            "Gap (BP−SP): <b>%{customdata[3]:+.2f}</b>"
            "<extra></extra>"
        ),
        showlegend = False,
    ))

    # Diagonal reference line
    fig.add_shape(
        type="line", x0=v_min, y0=v_min, x1=v_max, y1=v_max,
        line=dict(dash="dot", color="rgba(148,163,184,0.40)", width=1.5),
        layer="below",
    )

    # Logo images — dark ring style (in-graph, dark background)
    # resolve_logo_url() validates any cached URL from team_pitching_stats
    # and re-derives from the team name if the cached URL looks bad.
    logo_size = (v_max - v_min) * 0.065
    images = []
    for d in rows:
        url = resolve_logo_url(d["team"], d.get("logo_url"), dark_bg=True)
        if not url:
            continue
        images.append(dict(
            source  = url,
            xref="x", yref="y",
            x=d["starter_era"], y=d["bullpen_era"],
            sizex=logo_size, sizey=logo_size,
            xanchor="center", yanchor="middle",
            layer="above",
        ))

    ann_cfg = dict(showarrow=False, font_size=9, font_color="rgba(148,163,184,0.55)")
    fig.update_layout(
        images      = images,
        annotations = [
            _subtitle("Above diagonal = weaker bullpen than rotation · hover for values"),
            dict(x=v_max-0.05, y=v_min+0.05, text="Strong Bullpen",
                 xanchor="right", yanchor="bottom", **ann_cfg),
            dict(x=v_min+0.05, y=v_max-0.05, text="Weak Bullpen",
                 xanchor="left", yanchor="top", **ann_cfg),
        ],
        height = 560,
        title  = dict(text="SP ERA vs BP ERA — Balance Map",
                      font=dict(size=16, color=TEXT), x=0, xanchor="left"),
        xaxis  = dict(title="Starter ERA  (lower = better →)", range=[v_min, v_max],
                      gridcolor=SLATE, zeroline=False, tickfont=dict(size=11)),
        yaxis  = dict(title="Bullpen ERA  (lower = better →)", range=[v_min, v_max],
                      gridcolor=SLATE, zeroline=False, tickfont=dict(size=11),
                      scaleanchor="x", scaleratio=1),
        **_base_layout(margin=dict(l=60, r=40, t=90, b=60)),
    )
    return fig



# ─────────────────────────────────────────────────────────────────────────────
# CHART 2: Rankings — logo bars, green→red gradient
# ─────────────────────────────────────────────────────────────────────────────


def chart_rankings(data: List[Dict], stat_key: str, label: str,
                   lower_is_better: bool, n: int,
                   best_first: bool) -> Optional[go.Figure]:
    rows = _valid(data, stat_key)
    if not rows:
        return None
    rows   = sorted(rows, key=lambda x: x[stat_key], reverse=not lower_is_better)
    subset = rows[:n] if best_first else rows[-n:]
    if not best_first:
        subset = list(reversed(subset))

    teams  = [d["team"]   for d in subset]
    values = [d[stat_key] for d in subset]
    logos  = [resolve_logo_url(d["team"], d.get("logo_url"), dark_bg=True)
              for d in subset]

    bar_colors = [_rank_color(i, len(subset), invert=not best_first)
                  for i in range(len(subset))]
    suffix = "%" if "pct" in stat_key else ""
    height = max(420, len(subset) * 54 + 100)

    fig = go.Figure(go.Bar(
        y=teams, x=values, orientation="h",
        marker=dict(color=bar_colors, opacity=0.88,
                    line=dict(color="rgba(255,255,255,0.05)", width=0.5)),
        text=[f"  {_fmt(v, stat_key)}" for v in values],
        textposition="outside",
        textfont=dict(size=12, color=TEXT, family="'SF Mono','Fira Code',monospace"),
        hovertemplate=f"<b>%{{y}}</b><br>{label}: <b>%{{x:.2f}}{suffix}</b><extra></extra>",
    ))

    images = []
    for team, logo_url in zip(teams, logos):
        if not logo_url:
            continue
        images.append(dict(
            source=logo_url,
            xref="paper", yref="y",
            x=-0.01, y=team,
            sizex=0.075, sizey=0.80,
            xanchor="right", yanchor="middle",
            layer="above",
        ))

    rank_anns = [dict(
        x=0, y=team, xref="x", yref="y",
        text="<b>#" + str(i+1) + "</b>", showarrow=False,
        xanchor="right", xshift=-6,
        font=dict(size=10, color="rgba(148,163,184,0.70)"),
    ) for i, team in enumerate(teams)]

    title_text = ("🏆 Best " if best_first else "⚠️ Worst ") + str(len(subset)) + " — " + label

    fig.update_layout(
        height=height, images=images,
        annotations=[_subtitle("MLB · " + str(datetime.today().year) + " Season")] + rank_anns,
        title=dict(text=title_text, font=dict(size=16, color=TEXT), x=0, xanchor="left"),
        xaxis=dict(gridcolor=SLATE, zeroline=False, tickfont=dict(size=11),
                   title=dict(text=label, font=dict(size=11, color="#94a3b8"))),
        yaxis=dict(autorange="reversed", showticklabels=False),
        showlegend=False,
        **_base_layout(margin=dict(l=72, r=60, t=90, b=20)),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# CHART 3: K% vs ERA scatter — logo dots with white pills
# ─────────────────────────────────────────────────────────────────────────────

def chart_kpct_vs_era_plus(data: List[Dict]) -> Optional[go.Figure]:
    rows = [d for d in data
            if d.get("k_pct") is not None and d.get("era") is not None]
    if len(rows) < 2:
        return None

    k_vals  = [d["k_pct"] for d in rows]
    er_vals = [d["era"]   for d in rows]
    avg_k   = sum(k_vals)  / len(k_vals)
    avg_er  = sum(er_vals) / len(er_vals)

    pad_k  = (max(k_vals)  - min(k_vals))  * 0.14
    pad_er = (max(er_vals) - min(er_vals)) * 0.18
    x_min, x_max = min(k_vals)-pad_k,  max(k_vals)+pad_k
    y_min, y_max = min(er_vals)-pad_er, max(er_vals)+pad_er

    fig = go.Figure()

    # Quadrant shading
    fig.add_shape(type="rect", xref="x", yref="y",
                  x0=avg_k, x1=x_max, y0=y_min, y1=avg_er,
                  fillcolor="rgba(29,158,117,0.07)", line_width=0, layer="below")
    fig.add_shape(type="rect", xref="x", yref="y",
                  x0=x_min, x1=avg_k, y0=avg_er, y1=y_max,
                  fillcolor="rgba(216,90,48,0.07)", line_width=0, layer="below")

    fig.add_vline(x=avg_k,  line_dash="dot", line_color="rgba(148,163,184,0.25)", line_width=1)
    fig.add_hline(y=avg_er, line_dash="dot", line_color="rgba(148,163,184,0.25)", line_width=1)

    # Invisible hover trace
    fig.add_trace(go.Scatter(
        x=k_vals, y=er_vals, mode="markers",
        marker=dict(size=34, opacity=0, color="rgba(0,0,0,0)"),
        customdata=[[d["team"], d["k_pct"], d["era"],
                     d.get("fip", "—"), d.get("whiff_pct", "—")]
                    for d in rows],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "K%%: <b>%{customdata[1]:.1f}%%</b><br>"
            "ERA: <b>%{customdata[2]:.2f}</b><br>"
            "FIP: <b>%{customdata[3]}</b><br>"
            "Whiff%%: <b>%{customdata[4]}</b>"
            "<extra></extra>"
        ),
        showlegend=False,
    ))

    # Logo SVG dark rings (in-graph, dark background)
    # dark_bg=True → ESPN's /500-dark/ variant for dark-primary-logo teams
    lw = (x_max - x_min) * 0.058
    lh = (y_max - y_min) * 0.13
    images = []
    for d in rows:
        url = resolve_logo_url(d["team"], d.get("logo_url"), dark_bg=True)
        if not url:
            continue
        images.append(dict(
            source=url, xref="x", yref="y",
            x=d["k_pct"], y=d["era"],
            sizex=lw, sizey=lh,
            xanchor="center", yanchor="middle", layer="above",
        ))

    ann_cfg = dict(showarrow=False, font_size=9, font_color="rgba(148,163,184,0.60)")
    annotations = [
        _subtitle("MLB · " + str(datetime.today().year) + "  ·  hover logos for full stats"),
        dict(x=x_max-pad_k*0.3,  y=y_min+pad_er*0.4,  text="⭐ Elite",
             xanchor="right", yanchor="bottom", **ann_cfg),
        dict(x=x_min+pad_k*0.3,  y=y_min+pad_er*0.4,  text="Low K / Low ERA",
             xanchor="left",  yanchor="bottom", **ann_cfg),
        dict(x=x_max-pad_k*0.3,  y=y_max-pad_er*0.4,  text="High K / High ERA",
             xanchor="right", yanchor="top",    **ann_cfg),
        dict(x=x_min+pad_k*0.3,  y=y_max-pad_er*0.4,  text="⚠️ Struggling",
             xanchor="left",  yanchor="top",    **ann_cfg),
    ]

    fig.update_layout(
        height=560, images=images, annotations=annotations,
        title=dict(text="K% vs ERA — Dominance Quadrant",
                   font=dict(size=16, color=TEXT), x=0, xanchor="left"),
        xaxis=dict(title="Team K%", tickformat=".1f", ticksuffix="%",
                   range=[x_min, x_max], gridcolor=SLATE, zeroline=False),
        yaxis=dict(title="Team ERA  ↑ better", range=[y_max, y_min],
                   gridcolor=SLATE, zeroline=False),
        **_base_layout(),
    )
    return fig



# ─────────────────────────────────────────────────────────────────────────────
# CHART 4: FIP − ERA gap
# ─────────────────────────────────────────────────────────────────────────────

def chart_fip_era_gap(data: List[Dict]) -> Optional[go.Figure]:
    rows = [d for d in data
            if d.get("era") is not None and d.get("fip") is not None]
    if not rows:
        return None
    rows   = sorted(rows, key=lambda x: x["era"] - x["fip"], reverse=True)
    teams  = [d["team"] for d in rows]
    gaps   = [round(d["era"] - d["fip"], 2) for d in rows]
    colors = [CORAL if g > 0 else TEAL for g in gaps]

    fig = go.Figure(go.Bar(
        y=teams, x=gaps, orientation="h",
        marker=dict(color=colors, opacity=0.9),
        text=[f"{g:+.2f}" for g in gaps],
        textposition="outside", textfont=dict(size=10, color=TEXT),
        hovertemplate=(
            "<b>%{y}</b><br>ERA − FIP: <b>%{x:+.2f}</b><br>"
            "<i>Positive = ERA above FIP (due for improvement)</i><extra></extra>"
        ),
    ))
    fig.add_vline(x=0, line_color="rgba(148,163,184,0.4)", line_width=1)
    fig.update_layout(
        height=max(540, len(rows) * 20 + 80),
        annotations=[_subtitle("MLB · " + str(datetime.today().year) + " Season")],
        title=dict(text="ERA − FIP Gap  (Regression Radar)",
                   font=dict(size=16, color=TEXT), x=0, xanchor="left"),
        xaxis=dict(title="ERA minus FIP  (orange = due for improvement)",
                   gridcolor=SLATE, zeroline=False),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        showlegend=False,
        **_base_layout(),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# CHART 5: FIP vs xFIP
# ─────────────────────────────────────────────────────────────────────────────

def chart_fip_xfip(data: List[Dict]) -> Optional[go.Figure]:
    rows = [d for d in data
            if d.get("fip") is not None and d.get("xfip") is not None]
    if not rows:
        return None
    rows  = sorted(rows, key=lambda x: x["fip"])
    teams = [d["team"] for d in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=teams, x=[d["fip"] for d in rows], name="FIP", orientation="h",
        marker=dict(color=BLUE, opacity=0.88),
        text=[f"{d['fip']:.2f}" for d in rows],
        textposition="outside", textfont=dict(size=10, color=TEXT),
        hovertemplate="<b>%{y}</b><br>FIP: <b>%{x:.2f}</b><extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=teams, x=[d["xfip"] for d in rows], name="xFIP", orientation="h",
        marker=dict(color=PURPLE, opacity=0.88),
        text=[f"{d['xfip']:.2f}" for d in rows],
        textposition="outside", textfont=dict(size=10, color=TEXT),
        hovertemplate="<b>%{y}</b><br>xFIP: <b>%{x:.2f}</b><extra></extra>",
    ))
    fig.update_layout(
        barmode="group",
        height=max(540, len(rows) * 24 + 100),
        annotations=[_subtitle("MLB · " + str(datetime.today().year) + " Season")],
        title=dict(text="FIP vs xFIP — HR/FB Luck Detector",
                   font=dict(size=16, color=TEXT), x=0, xanchor="left"),
        xaxis=dict(title="ERA-scale metric", range=[2.0, 6.8],
                   gridcolor=SLATE, zeroline=False),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        legend=dict(orientation="h", y=1.04, x=0,
                    bgcolor="rgba(0,0,0,0)", borderwidth=0),
        **_base_layout(),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# SHAREABLE CARD — reusable component used everywhere
# ─────────────────────────────────────────────────────────────────────────────

def _render_stat_card(rows: List[Dict], stat_key: str, stat_label: str,
                      card_title: str, season: int,
                      best_first: bool = True) -> None:
    """
    Screenshot-ready dark card: rank number + white-pill logo + gradient bar + value.
    best_first=True  → #1 is green (e.g. lowest ERA)
    best_first=False → #1 is red  (e.g. highest/worst ERA)
    """
    vals = [d.get(stat_key) for d in rows if d.get(stat_key) is not None]
    if not vals:
        st.caption("No data available yet.")
        return

    v_min   = min(vals)
    v_max   = max(vals)
    v_range = v_max - v_min or 1
    n_rows  = len(vals)

    def _bw(v: float) -> int:
        if v_range == 0:
            return 60
        if best_first:
            return max(8, int((1 - (v - v_min) / v_range) * 86 + 14))
        return max(8, int((v - v_min) / v_range * 86 + 14))

    rows_html = ""
    for i, d in enumerate(rows):
        val = d.get(stat_key)
        if val is None:
            continue
        url       = resolve_logo_url(d["team"], d.get("logo_url"), dark_bg=False)
        rank_num  = "#" + str(i + 1)
        bar_pct   = _bw(val)
        bar_col   = _rank_color(i, n_rows, invert=not best_first)
        fmt_val   = _fmt(val, stat_key)
        row_bg    = "rgba(29,158,117,0.11)" if i == 0 else "rgba(255,255,255,0.03)"
        val_color = "#34d399" if i == 0 else "#e2e8f0"

        if url:
            logo_html = (
                '<span style="display:inline-flex;align-items:center;justify-content:center;'
                'background:#fff;border-radius:50%;width:40px;height:40px;flex-shrink:0;'
                'box-shadow:0 1px 4px rgba(0,0,0,0.22);">'
                '<img src="' + url + '" width="30" height="30" '
                'style="display:block;object-fit:contain;" '
                'onerror="this.style.display=\'none\';">'
                '</span>'
            )
        else:
            logo_html = (
                '<span style="display:inline-flex;align-items:center;justify-content:center;'
                'width:40px;height:40px;font-size:0.7rem;font-weight:700;color:#94a3b8;">'
                + d["team"] + '</span>'
            )

        rows_html += (
            '<div style="display:flex;align-items:center;gap:10px;'
            'padding:6px 14px;border-radius:8px;background:' + row_bg + ';margin-bottom:3px;">'

            '<div style="font-size:0.82rem;font-weight:700;min-width:28px;'
            'text-align:center;color:rgba(148,163,184,0.80);'
            'font-family:\'SF Mono\',monospace;">' + rank_num + '</div>'

            + logo_html +

            '<div style="flex:1;background:rgba(148,163,184,0.10);'
            'border-radius:4px;height:7px;overflow:hidden;">'
            '<div style="width:' + str(bar_pct) + '%;height:100%;background:' + bar_col + ';'
            'border-radius:4px;box-shadow:0 0 5px ' + bar_col + '99;"></div></div>'

            '<div style="min-width:52px;text-align:right;font-size:1.0rem;'
            'font-weight:800;font-family:\'SF Mono\',\'Fira Code\',monospace;'
            'color:' + val_color + ';">' + fmt_val + '</div>'
            '</div>'
        )

    card_html = (
        '<div style="background:linear-gradient(145deg,#0f1a2e 0%,#0d1b2a 100%);'
        'border:1px solid rgba(29,158,117,0.28);border-radius:16px;'
        'padding:18px 16px 14px;max-width:560px;'
        'font-family:\'SF Pro Display\',\'Helvetica Neue\',sans-serif;'
        'box-shadow:0 8px 32px rgba(0,0,0,0.5);">'

        '<div style="display:flex;align-items:center;justify-content:space-between;'
        'margin-bottom:14px;padding-bottom:10px;'
        'border-bottom:1px solid rgba(148,163,184,0.10);">'
        '<div>'
        '<div style="font-size:0.62rem;letter-spacing:1.8px;color:#64748b;'
        'text-transform:uppercase;font-weight:600;margin-bottom:2px;">'
        'SALCI · ' + str(season) + ' MLB SEASON</div>'
        '<div style="font-size:1.15rem;font-weight:800;color:#f1f5f9;'
        'letter-spacing:-0.3px;">' + card_title + '</div>'
        '</div>'
        '<div style="font-size:1.8rem;">⚾</div>'
        '</div>'

        + rows_html +

        '<div style="margin-top:10px;padding-top:8px;'
        'border-top:1px solid rgba(148,163,184,0.08);'
        'font-size:0.62rem;color:#475569;'
        'display:flex;justify-content:space-between;">'
        '<span>#SALCI #MLB</span>'
        '<span>Data: MLB Stats API · Baseball Savant</span>'
        '</div></div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)
    st.caption("💡 Screenshot to share on X / social media.")


# ─────────────────────────────────────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────────────────────────────────────

def _render_header(season: int) -> None:
    st.markdown(
        '<div class="salci-header">'
        '<span style="font-size:2.2rem">⚾</span>'
        '<div><h2>SALCI Pitching Dashboard</h2>'
        '<p>' + str(season) + ' Season · MLB Stats API · FIP self-computed · Savant overlay</p>'
        '</div></div>',
        unsafe_allow_html=True,
    )


def _render_fg_banner(savant_count: int) -> None:
    if savant_count >= 20:
        cls, icon = "ok", "✅"
        msg = (
            "<strong>MLB API + Baseball Savant</strong> — "
            + str(savant_count) + "/30 teams · FIP self-computed · xFIP/whiff%/hard-hit% from Savant"
            + "<br><span class='label'>SP/BP split: MLB sitCodes API · refreshes hourly</span>"
        )
    elif savant_count > 0:
        cls, icon = "warn", "⚠️"
        msg = (
            "<strong>Savant partial</strong> — "
            + str(savant_count) + "/30 teams · FIP & K% available (self-computed)"
            + "<br><span class='label'>xFIP / whiff% / hard-hit% limited</span>"
        )
    else:
        cls, icon = "warn", "🔌"
        msg = (
            "<strong>Savant offline</strong> — MLB API only (ERA, WHIP, SP/BP split, FIP, K%)"
            "<br><span class='label'>FIP and K% still shown — self-computed from MLB data</span>"
        )
    st.markdown(
        '<div class="fg-banner ' + cls + '">'
        '<span class="icon">' + icon + '</span>'
        '<div>' + msg + '</div></div>',
        unsafe_allow_html=True,
    )


def _render_top_performers(data: List[Dict]) -> None:
    st.markdown(
        '<div class="section-divider"></div>'
        '<p style="font-size:0.78rem;color:#64748b;letter-spacing:1px;'
        'text-transform:uppercase;font-weight:600;margin:0 0 10px 2px">'
        '🏆 Top 6 Starter ERAs</p>',
        unsafe_allow_html=True,
    )
    sp_rows = sorted(_valid(data, "starter_era"), key=lambda x: x["starter_era"])[:6]
    if not sp_rows:
        st.caption("No starter ERA data available yet.")
        return
    cols = st.columns(6)
    for i, team in enumerate(sp_rows):
        with cols[i]:
            st.markdown(
                '<div class="perf-card">'
                + _logo_html(team["team"], 42)
                + '<div class="team-abbr">' + team["team"] + '</div>'
                + '<div class="stat-val">' + f"{team['starter_era']:.2f}" + '</div>'
                + '<div class="stat-lbl">SP ERA</div>'
                + '</div>',
                unsafe_allow_html=True,
            )


def _render_key_insights(data: List[Dict]) -> None:
    with st.expander("💡 Key Insights & Methodology", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                '<div class="insight-box green"><strong>SP/BP Split</strong><br>'
                'Starter and bullpen ERAs come from the MLB Stats API sitCodes split — '
                'official data, same source the league uses.</div>',
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(
                '<div class="insight-box blue"><strong>FIP vs xFIP</strong><br>'
                'FIP removes defence. xFIP also normalises HR/FB to league average. '
                '<em>FIP &gt; xFIP</em> = too many HRs allowed, likely to improve.</div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                '<div class="insight-box orange"><strong>ERA − FIP Gap</strong><br>'
                'Positive = ERA above FIP → regression candidate. '
                'Negative = outperforming FIP, watch for decline.</div>',
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(
                '<div class="insight-box green"><strong>K% Quadrant</strong><br>'
                'Top-right (high K%, low ERA) = elite sustainable pitching. '
                'High ERA but low K% often signals BABIP luck.</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            "<br><small style='color:#475569'>"
            "ERA/WHIP/SP–BP: MLB Stats API · "
            "FIP: self-computed · xFIP/Whiff%/Hard-Hit%: Baseball Savant · refreshes hourly"
            "</small>",
            unsafe_allow_html=True,
        )


def _render_data_table(data: List[Dict]) -> None:
    with st.expander("📋 Full 30-Team Data Table", expanded=False):
        rows_html = ""
        for d in sorted(data, key=lambda x: x.get("starter_era") or 99):
            abbr   = d["team"]
            source = d.get("source", "—")

            def _td(val, key):
                fmt = _fmt(val, key)
                if val is None:
                    return "<td style='color:#475569'>" + fmt + "</td>"
                if key in ("era", "fip", "xfip"):
                    cls = "good" if val < 3.80 else ("bad" if val > 4.80 else "")
                    return '<td class="' + cls + '">' + fmt + "</td>"
                return "<td>" + fmt + "</td>"

            badge = (
                '<span class="badge fg">MLB+SV</span>'  if "Savant" in source else
                '<span class="badge mlb">MLB</span>'    if "MLB"    in source else
                '<span class="badge miss">—</span>'
            )

            rows_html += (
                "<tr>"
                "<td>" + _logo_html(abbr, 24) + "</td>"
                "<td style='font-weight:700;letter-spacing:0.5px'>" + abbr + "</td>"
                + _td(d.get("starter_era"), "era")
                + _td(d.get("bullpen_era"), "era")
                + _td(d.get("era"),         "era")
                + _td(d.get("fip"),         "fip")
                + _td(d.get("xfip"),        "xfip")
                + _td(d.get("whip"),        "whip")
                + _td(d.get("k_pct"),       "k_pct")
                + _td(d.get("whiff_pct"),   "k_pct")
                + _td(d.get("hard_hit_pct"),"k_pct")
                + "<td>" + badge + "</td>"
                + "</tr>"
            )

        headers = ["", "Team", "SP ERA", "BP ERA", "ERA",
                   "FIP", "xFIP", "WHIP", "K%", "Whiff%", "Hard-Hit%", "Source"]
        th = "".join("<th>" + h + "</th>" for h in headers)
        st.markdown(
            '<div style="overflow-x:auto;border-radius:8px;'
            'border:1px solid rgba(148,163,184,0.12);padding:0">'
            '<table class="salci-table">'
            "<thead><tr>" + th + "</tr></thead>"
            "<tbody>" + rows_html + "</tbody>"
            "</table></div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "🟢 Green = strong  🔴 Red = weak  ·  "
            "MLB+SV = MLB API + Savant  ·  Sorted by SP ERA best → worst"
        )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDER FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def render_pitching_dashboard() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    season = datetime.today().year
    _render_header(season)

    data = _load_data(season)
    if not data:
        st.error("❌ No data loaded. Check your internet connection or data pipeline.")
        return

    savant_count = sum(1 for d in data if "Savant" in d.get("source", ""))
    _render_fg_banner(savant_count)
    _render_top_performers(data)
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    _render_key_insights(data)
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊  Starter vs Bullpen",
        "🏆  Rankings",
        "🎯  K% vs ERA",
        "🔮  FIP – ERA Gap",
        "📐  FIP vs xFIP",
    ])

    # ── TAB 1: Starter vs Bullpen ─────────────────────────────────────────────
    with tab1:
        st.markdown(
            "**Balance Map** — each logo = a team. "
            "X-axis = Starter ERA, Y-axis = Bullpen ERA. "
            "Above the diagonal = bullpen is weaker than the rotation. Hover for exact numbers."
        )
        has_split = any(d.get("starter_era") for d in data)
        if not has_split:
            st.warning("⏳ SP/BP split not available — likely too early in the season.")
        else:
            fig = chart_starter_bullpen(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            sp_rows  = _valid(data, "starter_era")
            gap_rows = [d for d in data if d.get("starter_era") and d.get("bullpen_era")]
            if sp_rows:
                best_sp  = min(sp_rows, key=lambda x: x["starter_era"])
                worst_sp = max(sp_rows, key=lambda x: x["starter_era"])
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Best SP ERA",  f"{best_sp['starter_era']:.2f}",
                          delta=best_sp["team"], delta_color="off")
                c2.metric("Worst SP ERA", f"{worst_sp['starter_era']:.2f}",
                          delta=worst_sp["team"], delta_color="off")
                if gap_rows:
                    worst_bp = max(gap_rows, key=lambda x: x["bullpen_era"] - x["starter_era"])
                    best_bp  = min(gap_rows, key=lambda x: x["bullpen_era"] - x["starter_era"])
                    c3.metric("Biggest Bullpen Risk", worst_bp["team"],
                              delta=f"BP {worst_bp['bullpen_era']:.2f} vs SP {worst_bp['starter_era']:.2f}",
                              delta_color="inverse")
                    c4.metric("Strongest Bullpen", best_bp["team"],
                              delta=f"Gap {best_bp['bullpen_era'] - best_bp['starter_era']:+.2f}")

            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
            st.markdown("**📤 Shareable Cards**")

            col_a, col_b = st.columns(2)
            with col_a:
                best_sp_8 = sorted(_valid(data, "starter_era"),
                                   key=lambda x: x["starter_era"])[:8]
                with st.expander("🟢 Best Rotations", expanded=True):
                    _render_stat_card(best_sp_8, "starter_era", "SP ERA",
                                      "Best Rotations — SP ERA", season, best_first=True)
            with col_b:
                best_bp_8 = sorted(_valid(data, "bullpen_era"),
                                   key=lambda x: x["bullpen_era"])[:8]
                with st.expander("🟢 Best Bullpens", expanded=True):
                    _render_stat_card(best_bp_8, "bullpen_era", "BP ERA",
                                      "Best Bullpens — BP ERA", season, best_first=True)

            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
            worst_bp_8 = sorted(_valid(data, "bullpen_era"),
                                 key=lambda x: x["bullpen_era"], reverse=True)[:8]
            with st.expander("🔴 Worst Bullpens (Danger Zone)", expanded=False):
                _render_stat_card(worst_bp_8, "bullpen_era", "BP ERA",
                                  "Worst Bullpens — BP ERA", season, best_first=False)

    # ── TAB 2: Rankings ──────────────────────────────────────────────────────
    with tab2:
        stat_map = {
            "Starter ERA":  ("starter_era", True),
            "Bullpen ERA":  ("bullpen_era",  True),
            "Overall ERA":  ("era",          True),
            "FIP":          ("fip",          True),
            "xFIP":         ("xfip",         True),
            "WHIP":         ("whip",         True),
            "K%":           ("k_pct",        False),
            "Whiff%":       ("whiff_pct",    False),
            "Hard-Hit%":    ("hard_hit_pct", False),
        }
        c1, c2 = st.columns([2, 2])
        stat_label   = c1.selectbox("Stat", list(stat_map.keys()), key="rank_stat")
        direction    = c2.selectbox("Show", ["Best 8", "Worst 8", "All 30"], key="rank_dir")
        stat_key_r, lower_is_better = stat_map[stat_label]
        n_r          = 8 if "8" in direction else 30
        best_first_r = "Best" in direction or "All" in direction

        rows_r = _valid(data, stat_key_r)
        if not rows_r:
            st.info(f"No {stat_label} data yet — requires Baseball Savant overlay.")
        else:
            fig = chart_rankings(rows_r, stat_key_r, stat_label,
                                  lower_is_better, n_r, best_first_r)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            sorted_r = sorted(rows_r, key=lambda x: x[stat_key_r],
                               reverse=not lower_is_better)
            card_rows = sorted_r[:n_r] if best_first_r else sorted_r[-n_r:]
            if not best_first_r:
                card_rows = list(reversed(card_rows))

            with st.expander("📤 Shareable Card  (screenshot-ready)", expanded=False):
                lbl = ("Best " if best_first_r else "Worst ") + str(n_r) + " — " + stat_label
                _render_stat_card(card_rows, stat_key_r, stat_label,
                                   lbl, season, best_first=best_first_r)

    # ── TAB 3: K% vs ERA ─────────────────────────────────────────────────────
    with tab3:
        st.markdown(
            "**Dominance quadrant.** Right = high K%. Top = low ERA (good). "
            "Top-right ⭐ = elite sustainable. Hover logos for full stats."
        )
        if not any(d.get("k_pct") for d in data):
            st.warning("⚠️ K% not yet available — may be early in the season.")
        else:
            fig = chart_kpct_vs_era_plus(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

        k_rows = sorted(_valid(data, "k_pct"), key=lambda x: x["k_pct"], reverse=True)[:8]
        with st.expander("📤 Best Strikeout Rates — Shareable Card", expanded=False):
            _render_stat_card(k_rows, "k_pct", "K%",
                               "Best Strikeout Rates — K%", season, best_first=False)

    # ── TAB 4: FIP − ERA Gap ─────────────────────────────────────────────────
    with tab4:
        st.markdown(
            "**Regression radar.** "
            "🟠 Orange = ERA above FIP → due for improvement.  "
            "🟢 Teal = ERA below FIP → outperforming, watch for decline."
        )
        if not any(d.get("fip") for d in data):
            st.warning("FIP not available yet — MLB API may need a few more games.")
        else:
            fig = chart_fip_era_gap(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            gap_rows = [d for d in data if d.get("era") and d.get("fip")]
            if gap_rows:
                due    = sorted([d for d in gap_rows if d["era"] - d["fip"] > 0.20],
                                 key=lambda x: x["era"] - x["fip"], reverse=True)[:4]
                lucky  = sorted([d for d in gap_rows if d["era"] - d["fip"] < -0.20],
                                 key=lambda x: x["era"] - x["fip"])[:4]
                if due:
                    st.warning("🟠 **Due for improvement**: " +
                               "  ·  ".join(
                                   "**" + d["team"] + "** (+" + f"{d['era']-d['fip']:.2f}" + ")"
                                   for d in due))
                if lucky:
                    st.success("🟢 **Regression risk**: " +
                               "  ·  ".join(
                                   "**" + d["team"] + "** (" + f"{d['era']-d['fip']:+.2f}" + ")"
                                   for d in lucky))

                due8 = sorted(gap_rows, key=lambda x: x["era"] - x["fip"], reverse=True)[:8]
                for d in due8:
                    d["era_fip_gap"] = round(d["era"] - d["fip"], 2)
                with st.expander("📤 Regression Radar — Shareable Card", expanded=False):
                    _render_stat_card(due8, "era_fip_gap", "ERA−FIP Gap",
                                       "Due for Improvement — ERA−FIP Gap",
                                       season, best_first=False)

    # ── TAB 5: FIP vs xFIP ───────────────────────────────────────────────────
    with tab5:
        st.markdown(
            "**HR/FB luck detector.** "
            "xFIP normalises HRs to league-average HR/FB rate.  \n"
            "**FIP > xFIP** = too many HRs, likely to improve.  \n"
            "**FIP < xFIP** = suppressing HRs, potential regression."
        )
        if not any(d.get("xfip") for d in data):
            st.warning("xFIP requires Baseball Savant. Check network or try again later.")
        else:
            fig = chart_fip_xfip(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            xr = [d for d in data if d.get("fip") and d.get("xfip")]
            if xr:
                improve = sorted([d for d in xr if d["fip"]-d["xfip"] > 0.15],
                                  key=lambda x: x["fip"]-x["xfip"], reverse=True)[:3]
                regress = sorted([d for d in xr if d["xfip"]-d["fip"] > 0.15],
                                  key=lambda x: x["xfip"]-x["fip"], reverse=True)[:3]
                if improve:
                    st.success("📈 **HR regression candidates** (FIP > xFIP): " +
                               "  ·  ".join(
                                   "**" + d["team"] + "** (FIP " + f"{d['fip']:.2f}" +
                                   " > xFIP " + f"{d['xfip']:.2f}" + ")"
                                   for d in improve))
                if regress:
                    st.warning("⚠️ **HR luck beneficiaries** (xFIP > FIP): " +
                               "  ·  ".join(
                                   "**" + d["team"] + "** (xFIP " + f"{d['xfip']:.2f}" +
                                   " > FIP " + f"{d['fip']:.2f}" + ")"
                                   for d in regress))

    # ── Full data table ───────────────────────────────────────────────────────
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    _render_data_table(data)
