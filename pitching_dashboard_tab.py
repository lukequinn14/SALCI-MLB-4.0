"""
SALCI Pitching Dashboard Tab  ·  v2.1
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

Changes in v2.1 (this version)
--------------------------------
- Logos: switched from mlbstatic SVGs to ESPN CDN PNGs (more reliable)
  Uses get_team_logo_url() from team_pitching_stats — or local fallback map
- Data source banner: FanGraphs → "MLB API + Baseball Savant"
- Source badge: "FG" label renamed to "Savant" to match new backend
- xFIP/whiff/hard-hit now fed from Baseball Savant leaderboard CSV
- FIP is now self-computed (13·HR + 3·(BB+HBP) − 2·K) / IP + 3.10
  so it always shows even when Savant is down
- SP/BP split explanation updated with correct API endpoint info

Changes in v2.0
---------------
- Radio selector → st.tabs (persistent, navigable)
- Team logos in header summary strip + full data table
- Prominent data-source banner at the top
- Every chart: improved titles, axis labels, hover templates
- Quadrant labels on K% vs ERA+ scatter
- FIP–ERA gap: callout cards for regression candidates
- Dark-mode friendly: transparent plot backgrounds, subdued grids
- Key Insights section at the top (expandable)
- Data table: logo column rendered via HTML, colour-coded Source column
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from typing import List, Dict, Optional

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE  (SALCI brand colours)
# ─────────────────────────────────────────────────────────────────────────────
TEAL   = "#1D9E75"
CORAL  = "#D85A30"
BLUE   = "#378ADD"
AMBER  = "#BA7517"
PURPLE = "#7F77DD"
SLATE  = "rgba(148,163,184,0.15)"   # subtle grid lines
TEXT   = "#e2e8f0"

# ─────────────────────────────────────────────────────────────────────────────
# TEAM LOGOS  (ESPN CDN — reliable PNG, 500px, no auth required)
# Matches the same helper used in team_pitching_stats.py.
# team_pitching_stats.get_team_logo_url() is the canonical source;
# this local map is a fast zero-import fallback.
# ─────────────────────────────────────────────────────────────────────────────
_ESPN_BASE = "https://a.espncdn.com/i/teamlogos/mlb/500"
TEAM_LOGOS: Dict[str, str] = {
    "ARI": f"{_ESPN_BASE}/ari.png", "ATL": f"{_ESPN_BASE}/atl.png",
    "BAL": f"{_ESPN_BASE}/bal.png", "BOS": f"{_ESPN_BASE}/bos.png",
    "CHC": f"{_ESPN_BASE}/chc.png", "CWS": f"{_ESPN_BASE}/cws.png",
    "CIN": f"{_ESPN_BASE}/cin.png", "CLE": f"{_ESPN_BASE}/cle.png",
    "COL": f"{_ESPN_BASE}/col.png", "DET": f"{_ESPN_BASE}/det.png",
    "HOU": f"{_ESPN_BASE}/hou.png", "KC":  f"{_ESPN_BASE}/kc.png",
    "LAA": f"{_ESPN_BASE}/laa.png", "LAD": f"{_ESPN_BASE}/lad.png",
    "MIA": f"{_ESPN_BASE}/mia.png", "MIL": f"{_ESPN_BASE}/mil.png",
    "MIN": f"{_ESPN_BASE}/min.png", "NYM": f"{_ESPN_BASE}/nym.png",
    "NYY": f"{_ESPN_BASE}/nyy.png", "OAK": f"{_ESPN_BASE}/oak.png",
    "PHI": f"{_ESPN_BASE}/phi.png", "PIT": f"{_ESPN_BASE}/pit.png",
    "SD":  f"{_ESPN_BASE}/sd.png",  "SF":  f"{_ESPN_BASE}/sf.png",
    "SEA": f"{_ESPN_BASE}/sea.png", "STL": f"{_ESPN_BASE}/stl.png",
    "TB":  f"{_ESPN_BASE}/tb.png",  "TEX": f"{_ESPN_BASE}/tex.png",
    "TOR": f"{_ESPN_BASE}/tor.png", "WSH": f"{_ESPN_BASE}/wsh.png",
}

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS  (injected once per render)
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
<style>
/* ── Dashboard header ─────────────────────────────────────── */
.salci-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 18px 22px;
    border-radius: 12px;
    background: linear-gradient(135deg,
        rgba(29,158,117,0.18) 0%,
        rgba(55,138,221,0.12) 100%);
    border: 1px solid rgba(29,158,117,0.35);
    margin-bottom: 6px;
}
.salci-header h2 {
    margin: 0;
    font-size: 1.55rem;
    font-weight: 700;
    letter-spacing: -0.4px;
    color: #f1f5f9;
}
.salci-header p {
    margin: 2px 0 0;
    font-size: 0.83rem;
    color: #94a3b8;
}

/* ── FanGraphs status banner ──────────────────────────────── */
.fg-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 18px;
    border-radius: 10px;
    font-size: 0.88rem;
    font-weight: 500;
    margin: 10px 0 4px;
}
.fg-banner.ok {
    background: rgba(29,158,117,0.15);
    border: 1px solid rgba(29,158,117,0.4);
    color: #6ee7b7;
}
.fg-banner.warn {
    background: rgba(186,117,23,0.15);
    border: 1px solid rgba(186,117,23,0.4);
    color: #fcd34d;
}
.fg-banner .icon { font-size: 1.3rem; }
.fg-banner .label { font-size: 0.78rem; color: #94a3b8; font-weight: 400; }

/* ── Top performers strip ─────────────────────────────────── */
.perf-card {
    background: rgba(30,41,59,0.7);
    border: 1px solid rgba(148,163,184,0.12);
    border-radius: 10px;
    padding: 12px 10px 10px;
    text-align: center;
    transition: border-color 0.2s;
}
.perf-card:hover { border-color: rgba(29,158,117,0.5); }
.perf-card .team-abbr {
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 1.2px;
    color: #94a3b8;
    text-transform: uppercase;
    margin-top: 6px;
    margin-bottom: 2px;
}
.perf-card .stat-val {
    font-size: 1.35rem;
    font-weight: 800;
    color: #1D9E75;
    line-height: 1.1;
}
.perf-card .stat-lbl {
    font-size: 0.72rem;
    color: #64748b;
    margin-top: 1px;
}

/* ── Insight cards ────────────────────────────────────────── */
.insight-box {
    background: rgba(15,23,42,0.6);
    border-left: 3px solid;
    border-radius: 0 8px 8px 0;
    padding: 10px 14px;
    font-size: 0.85rem;
    line-height: 1.5;
    color: #cbd5e1;
}
.insight-box.green  { border-color: #1D9E75; }
.insight-box.orange { border-color: #D85A30; }
.insight-box.blue   { border-color: #378ADD; }

/* ── Data table ───────────────────────────────────────────── */
.salci-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.83rem;
    font-family: 'SF Mono', 'Fira Code', monospace;
}
.salci-table th {
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid rgba(148,163,184,0.2);
    color: #64748b;
    font-size: 0.75rem;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    font-weight: 600;
    background: rgba(15,23,42,0.5);
}
.salci-table td {
    padding: 7px 12px;
    border-bottom: 1px solid rgba(148,163,184,0.07);
    color: #e2e8f0;
    vertical-align: middle;
    white-space: nowrap;
}
.salci-table tr:hover td { background: rgba(29,158,117,0.06); }
.salci-table td.good { color: #34d399; font-weight: 600; }
.salci-table td.bad  { color: #f87171; font-weight: 600; }
.salci-table .badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.5px;
}
.salci-table .badge.fg   { background: rgba(29,158,117,0.2); color: #6ee7b7; }
.salci-table .badge.mlb  { background: rgba(55,138,221,0.2); color: #93c5fd; }
.salci-table .badge.miss { background: rgba(100,116,139,0.2); color: #94a3b8; }

/* ── Section divider ──────────────────────────────────────── */
.section-divider {
    height: 1px;
    background: linear-gradient(90deg,
        rgba(29,158,117,0.4) 0%,
        rgba(55,138,221,0.15) 50%,
        transparent 100%);
    margin: 18px 0;
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
    """Shared Plotly layout — dark-mode, transparent, SALCI brand."""
    return dict(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="'SF Pro Display', 'Helvetica Neue', sans-serif",
                  size=12, color=TEXT),
        margin=dict(l=10, r=40, t=44, b=16),
        hoverlabel=dict(bgcolor="rgba(15,23,42,0.95)",
                        bordercolor="rgba(148,163,184,0.3)",
                        font_color=TEXT, font_size=12),
        **kw,
    )


def _fmt(val, key: str) -> str:
    if val is None:
        return "—"
    if "pct" in key:
        return f"{val:.1f}%"
    if key in ("era_plus", "era+"):
        return str(int(round(val)))  # kept for future ERA+ support
    return f"{val:.2f}"


def _valid(data: List[Dict], key: str) -> List[Dict]:
    return [d for d in data if d.get(key) is not None]


def _logo_html(team: str, size: int = 28) -> str:
    url = TEAM_LOGOS.get(team, "")
    if not url:
        return f"<span style='font-size:0.75rem;color:#64748b'>{team}</span>"
    return (
        f'<img src="{url}" width="{size}" height="{size}" '
        f'style="vertical-align:middle;object-fit:contain;" '
        f'alt="{team}" onerror="this.style.display=\'none\'">'
    )


# ─────────────────────────────────────────────────────────────────────────────
# CHART: Starter vs Bullpen ERA
# ─────────────────────────────────────────────────────────────────────────────

def chart_starter_bullpen(data: List[Dict]) -> Optional[go.Figure]:
    rows = [d for d in data
            if d.get("starter_era") is not None and d.get("bullpen_era") is not None]
    if not rows:
        return None
    rows = sorted(rows, key=lambda x: x["starter_era"])

    teams = [d["team"]        for d in rows]
    sp    = [d["starter_era"] for d in rows]
    bp    = [d["bullpen_era"] for d in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=teams, x=sp, name="Starter ERA", orientation="h",
        marker=dict(color=TEAL, opacity=0.88),
        text=[f"{v:.2f}" for v in sp],
        textposition="outside", textfont=dict(size=10, color=TEXT),
        hovertemplate="<b>%{y}</b><br>Starter ERA: <b>%{x:.2f}</b><extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=teams, x=bp, name="Bullpen ERA", orientation="h",
        marker=dict(color=CORAL, opacity=0.88),
        text=[f"{v:.2f}" for v in bp],
        textposition="outside", textfont=dict(size=10, color=TEXT),
        hovertemplate="<b>%{y}</b><br>Bullpen ERA: <b>%{x:.2f}</b><extra></extra>",
    ))
    fig.update_layout(
        barmode="group",
        height=max(560, len(rows) * 24 + 100),
        title=dict(text="Starter ERA vs Bullpen ERA — All 30 Teams",
                   font=dict(size=15, color=TEXT), x=0, pad=dict(b=6)),
        xaxis=dict(title="ERA", range=[1.2, 9.0],
                   gridcolor=SLATE, zeroline=False,
                   tickfont=dict(size=11)),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        legend=dict(orientation="h", y=1.04, x=0,
                    bgcolor="rgba(0,0,0,0)", borderwidth=0),
        **_base_layout(),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# CHART: Rankings  (logo-native horizontal bars)
# ─────────────────────────────────────────────────────────────────────────────

def chart_rankings(data: List[Dict], stat_key: str, label: str,
                   lower_is_better: bool, n: int,
                   best_first: bool) -> Optional[go.Figure]:
    """
    Horizontal bar chart where each y-axis tick IS the team logo.

    How logos work in Plotly:
      - We blank out the y-axis tick labels (replaced by logo images).
      - Each team gets a go.layout.Image placed at its bar's y-position,
        anchored to the left edge of the plot area (x=0 in paper coords).
      - Logo size is fixed at ~32px regardless of chart height.
    """
    rows = _valid(data, stat_key)
    if not rows:
        return None
    rows = sorted(rows, key=lambda x: x[stat_key], reverse=not lower_is_better)
    subset = rows[:n] if best_first else rows[-n:]
    if not best_first:
        subset = list(reversed(subset))

    teams  = [d["team"]   for d in subset]
    values = [d[stat_key] for d in subset]
    logos  = [d.get("logo_url") or TEAM_LOGOS.get(d["team"], "") for d in subset]

    # Medal colouring: gold / silver / bronze for top 3, then faded
    medal   = ["#FFD700", "#C0C0C0", "#CD7F32"]
    if best_first:
        bar_colors = [
            (medal[i] if i < 3 else "#3a7d6b")
            for i in range(len(subset))
        ]
    else:
        bar_colors = [
            (medal[i] if i < 3 else "#8b3a1e")
            for i in range(len(subset))
        ]

    suffix = "%" if "pct" in stat_key else ""
    row_h  = 52          # px per row
    height = max(400, len(subset) * row_h + 80)

    fig = go.Figure(go.Bar(
        y=teams, x=values, orientation="h",
        marker=dict(color=bar_colors, opacity=0.85,
                    line=dict(color="rgba(255,255,255,0.06)", width=0.5)),
        text=[f"  {_fmt(v, stat_key)}" for v in values],
        textposition="outside",
        textfont=dict(size=12, color=TEXT, family="'SF Mono','Fira Code',monospace"),
        hovertemplate=(
            f"<b>%{{y}}</b><br>"
            f"{label}: <b>%{{x:.2f}}{suffix}</b>"
            f"<extra></extra>"
        ),
        # Invisible customdata for rank tooltip
        customdata=list(range(1, len(subset) + 1)),
    ))

    # ── Place logos as layout images ─────────────────────────────────────────
    # Plotly layout images in 'paper' xref / 'y' yref allow us to pin an image
    # to a specific data-y value, left-aligned at the plot edge.
    images = []
    for i, (team, logo_url) in enumerate(zip(teams, logos)):
        if not logo_url:
            continue
        images.append(dict(
            source   = logo_url,
            xref     = "paper",
            yref     = "y",
            x        = -0.01,          # just left of the plot area
            y        = team,           # data coordinate = team name
            sizex    = 0.08,           # fraction of paper width (~32px at 400px)
            sizey    = 0.75,           # fraction of row height in data units
            xanchor  = "right",
            yanchor  = "middle",
            layer    = "above",
        ))

    # Rank medal annotations on the left of each bar
    rank_annotations = []
    for i, team in enumerate(teams):
        rank_annotations.append(dict(
            x         = 0,
            y         = team,
            xref      = "x",
            yref      = "y",
            text      = f"<b>#{i+1}</b>",
            showarrow = False,
            xanchor   = "right",
            font      = dict(size=10,
                             color=medal[i] if i < 3 else "rgba(148,163,184,0.6)"),
            xshift    = -4,
        ))

    fig.update_layout(
        height      = height,
        images      = images,
        annotations = rank_annotations,
        title       = dict(
            text = (
                f"{'🏆 Best' if best_first else '⚠️ Worst'} {len(subset)} "
                f"— {label}"
            ),
            font = dict(size=15, color=TEXT), x=0,
        ),
        xaxis = dict(
            gridcolor  = SLATE,
            zeroline   = False,
            tickfont   = dict(size=11),
            title      = dict(text=label, font=dict(size=11, color="#94a3b8")),
        ),
        yaxis = dict(
            autorange  = "reversed",
            tickfont   = dict(size=11, color=TEXT),
            # Push tick labels right to leave room for logo
            ticklabelposition = "outside right",
        ),
        showlegend  = False,
        **_base_layout(margin=dict(l=80, r=60, t=48, b=20)),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# CHART: K% vs ERA+ scatter
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# CHART: K% vs ERA scatter  (team logos instead of dots)
# ─────────────────────────────────────────────────────────────────────────────

def chart_kpct_vs_era_plus(data: List[Dict]) -> Optional[go.Figure]:
    """
    K% (x) vs ERA (y, inverted) scatter where each point IS the team logo.

    Technique:
      - An invisible go.Scatter trace handles hover tooltips and click events.
        Its markers are fully transparent (opacity=0).
      - Each team gets a go.layout.Image pinned to its (k_pct, era) coordinate
        in data-space (xref='x', yref='y'), sized in pixels via sizex/sizey.
      - Quadrant shading via add_shape rectangles.
      - Quadrant labels via add_annotation.
    """
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

    x_min = min(k_vals)  - pad_k
    x_max = max(k_vals)  + pad_k
    y_min = min(er_vals) - pad_er   # best ERA (visually at top because axis inverted)
    y_max = max(er_vals) + pad_er   # worst ERA (visually at bottom)

    # ── Quadrant background shading ──────────────────────────────────────────
    # NB: y-axis is INVERTED (low ERA = top = good), so:
    #   "elite" quadrant = right half, upper half visually = right, low ERA
    quad_shapes = [
        # Top-right visually = high K, low ERA = elite (teal tint)
        dict(type="rect", xref="x", yref="y",
             x0=avg_k, x1=x_max, y0=y_min, y1=avg_er,
             fillcolor="rgba(29,158,117,0.07)", line_width=0, layer="below"),
        # Bottom-left visually = low K, high ERA = struggling (coral tint)
        dict(type="rect", xref="x", yref="y",
             x0=x_min, x1=avg_k, y0=avg_er, y1=y_max,
             fillcolor="rgba(216,90,48,0.07)", line_width=0, layer="below"),
    ]

    # ── Invisible scatter trace for hover/tooltip ────────────────────────────
    fig = go.Figure()

    for shape in quad_shapes:
        fig.add_shape(**shape)

    # Cross-hair lines
    fig.add_vline(x=avg_k,  line_dash="dot",
                  line_color="rgba(148,163,184,0.25)", line_width=1)
    fig.add_hline(y=avg_er, line_dash="dot",
                  line_color="rgba(148,163,184,0.25)", line_width=1)

    fig.add_trace(go.Scatter(
        x       = k_vals,
        y       = er_vals,
        mode    = "markers",
        marker  = dict(size=30, opacity=0, color="rgba(0,0,0,0)"),
        text    = [d["team"] for d in rows],
        customdata = [[d["team"], d["k_pct"], d["era"],
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
        showlegend = False,
    ))

    # ── Logo images pinned to data coordinates ───────────────────────────────
    # sizex / sizey are in data units. We compute a fixed logo size as a
    # fraction of the axis range so logos don't overlap at default zoom.
    logo_w = (x_max - x_min) * 0.055   # ~5.5% of x-range
    logo_h = (y_max - y_min) * 0.12    # ~12% of y-range (ERA axis)

    images = []
    for d in rows:
        logo = d.get("logo_url") or TEAM_LOGOS.get(d["team"], "")
        if not logo:
            continue
        images.append(dict(
            source  = logo,
            xref    = "x",
            yref    = "y",
            x       = d["k_pct"],
            y       = d["era"],
            sizex   = logo_w,
            sizey   = logo_h,
            xanchor = "center",
            yanchor = "middle",
            layer   = "above",
        ))

    # ── Quadrant label annotations ───────────────────────────────────────────
    ann_cfg = dict(showarrow=False, font_size=9,
                   font_color="rgba(148,163,184,0.60)")
    annotations = [
        dict(x=x_max - pad_k*0.3, y=y_min + pad_er*0.4,
             text="⭐ Elite", xanchor="right", yanchor="bottom", **ann_cfg),
        dict(x=x_min + pad_k*0.3, y=y_min + pad_er*0.4,
             text="Low K / Low ERA", xanchor="left", yanchor="bottom", **ann_cfg),
        dict(x=x_max - pad_k*0.3, y=y_max - pad_er*0.4,
             text="High K / High ERA", xanchor="right", yanchor="top", **ann_cfg),
        dict(x=x_min + pad_k*0.3, y=y_max - pad_er*0.4,
             text="⚠️ Struggling", xanchor="left", yanchor="top", **ann_cfg),
    ]

    fig.update_layout(
        height      = 540,
        images      = images,
        annotations = annotations,
        title       = dict(text="K% vs ERA — Dominance Quadrant  (hover for full stats)",
                           font=dict(size=15, color=TEXT), x=0),
        xaxis = dict(
            title      = "Team K%",
            tickformat = ".1f", ticksuffix="%",
            range      = [x_min, x_max],
            gridcolor  = SLATE, zeroline=False,
        ),
        yaxis = dict(
            title  = "Team ERA  ↑ better",
            range  = [y_max, y_min],   # inverted: low ERA at top
            gridcolor = SLATE, zeroline=False,
        ),
        **_base_layout(),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# CHART: FIP − ERA gap
# ─────────────────────────────────────────────────────────────────────────────

def chart_fip_era_gap(data: List[Dict]) -> Optional[go.Figure]:
    rows = [d for d in data
            if d.get("era") is not None and d.get("fip") is not None]
    if not rows:
        return None
    rows = sorted(rows, key=lambda x: x["era"] - x["fip"], reverse=True)

    teams  = [d["team"] for d in rows]
    gaps   = [round(d["era"] - d["fip"], 2) for d in rows]
    colors = [CORAL if g > 0 else TEAL for g in gaps]

    fig = go.Figure(go.Bar(
        y=teams, x=gaps, orientation="h",
        marker=dict(color=colors, opacity=0.9),
        text=[f"{g:+.2f}" for g in gaps],
        textposition="outside", textfont=dict(size=10, color=TEXT),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "ERA − FIP: <b>%{x:+.2f}</b><br>"
            "<i>Positive = ERA above FIP (due for improvement)</i>"
            "<extra></extra>"
        ),
    ))
    fig.add_vline(x=0, line_color="rgba(148,163,184,0.4)", line_width=1)
    fig.update_layout(
        height=max(540, len(rows) * 20 + 80),
        title=dict(text="ERA − FIP Gap  (Regression Radar)",
                   font=dict(size=15, color=TEXT), x=0),
        xaxis=dict(title="ERA minus FIP  (orange → due for improvement)",
                   gridcolor=SLATE, zeroline=False),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        showlegend=False,
        **_base_layout(),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# CHART: FIP vs xFIP
# ─────────────────────────────────────────────────────────────────────────────

def chart_fip_xfip(data: List[Dict]) -> Optional[go.Figure]:
    rows = [d for d in data
            if d.get("fip") is not None and d.get("xfip") is not None]
    if not rows:
        return None
    rows = sorted(rows, key=lambda x: x["fip"])

    teams = [d["team"] for d in rows]
    fip   = [d["fip"]  for d in rows]
    xfip  = [d["xfip"] for d in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=teams, x=fip, name="FIP", orientation="h",
        marker=dict(color=BLUE, opacity=0.88),
        text=[f"{v:.2f}" for v in fip],
        textposition="outside", textfont=dict(size=10, color=TEXT),
        hovertemplate="<b>%{y}</b><br>FIP: <b>%{x:.2f}</b><extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=teams, x=xfip, name="xFIP", orientation="h",
        marker=dict(color=PURPLE, opacity=0.88),
        text=[f"{v:.2f}" for v in xfip],
        textposition="outside", textfont=dict(size=10, color=TEXT),
        hovertemplate="<b>%{y}</b><br>xFIP: <b>%{x:.2f}</b><extra></extra>",
    ))
    fig.update_layout(
        barmode="group",
        height=max(540, len(rows) * 24 + 100),
        title=dict(text="FIP vs xFIP — HR/FB Luck Detector",
                   font=dict(size=15, color=TEXT), x=0),
        xaxis=dict(title="ERA-scale metric", range=[2.0, 6.8],
                   gridcolor=SLATE, zeroline=False),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        legend=dict(orientation="h", y=1.04, x=0,
                    bgcolor="rgba(0,0,0,0)", borderwidth=0),
        **_base_layout(),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────────────────────────────────────

def _render_header(season: int) -> None:
    st.markdown(
        f"""
        <div class="salci-header">
            <span style="font-size:2.2rem">⚾</span>
            <div>
                <h2>SALCI Pitching Dashboard</h2>
                <p>{season} Season · MLB Stats API splits · FIP self-computed · xFIP/Whiff% from Baseball Savant</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_fg_banner(savant_count: int) -> None:
    """
    Render the data-source status banner.
    savant_count = number of teams that have Baseball Savant overlay data.
    FIP and K% are always shown (self-computed from MLB API),
    so even 0 Savant teams is a degraded-but-functional state.
    """
    fg_count = savant_count   # kept as parameter name for callers
    if fg_count >= 20:
        cls, icon, msg = (
            "ok", "✅",
            f"<strong>MLB API + Baseball Savant</strong> — "
            f"{fg_count}/30 teams with full advanced metrics "
            f"(FIP self-computed · xFIP, whiff%, hard-hit% from Savant)"
            f"<br><span class='label'>Starter/Bullpen split: MLB Stats API "
            f"sitCodes · Savant leaderboard CSV · refreshes hourly</span>",
        )
    elif fg_count > 0:
        cls, icon, msg = (
            "warn", "⚠️",
            f"<strong>Savant partial</strong> — "
            f"{fg_count}/30 teams · FIP & K% available for all (self-computed)"
            f"<br><span class='label'>xFIP / whiff% / hard-hit% limited · "
            f"check Baseball Savant availability</span>",
        )
    else:
        cls, icon, msg = (
            "warn", "🔌",
            "<strong>Savant offline</strong> — "
            "MLB API data only (ERA, WHIP, Starter/Bullpen split, FIP, K%)"
            "<br><span class='label'>Self-computed FIP and K% are still shown · "
            "xFIP / whiff% / hard-hit% unavailable until Savant responds</span>",
        )
    st.markdown(
        f'<div class="fg-banner {cls}">'
        f'<span class="icon">{icon}</span>'
        f'<div>{msg}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_top_performers(data: List[Dict]) -> None:
    st.markdown(
        '<div class="section-divider"></div>'
        '<p style="font-size:0.78rem;color:#64748b;letter-spacing:1px;'
        'text-transform:uppercase;font-weight:600;margin:0 0 10px 2px">'
        "🏆 Top 6 Starter ERAs</p>",
        unsafe_allow_html=True,
    )
    sp_rows = sorted(_valid(data, "starter_era"), key=lambda x: x["starter_era"])[:6]
    if not sp_rows:
        st.caption("No starter ERA data available yet.")
        return

    cols = st.columns(6)
    for i, team in enumerate(sp_rows):
        abbr = team["team"]
        era  = team["starter_era"]
        logo = TEAM_LOGOS.get(abbr, "")
        with cols[i]:
            st.markdown(
                f'<div class="perf-card">'
                f'{"<img src=" + chr(34) + logo + chr(34) + " width=40 height=40 style=object-fit:contain>" if logo else ""}'
                f'<div class="team-abbr">{abbr}</div>'
                f'<div class="stat-val">{era:.2f}</div>'
                f'<div class="stat-lbl">SP ERA</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _render_key_insights(data: List[Dict]) -> None:
    with st.expander("💡 Key Insights & Methodology", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                '<div class="insight-box green">'
                "<strong>What is ERA+?</strong><br>"
                "Park-adjusted ERA relative to league average (100 = league avg, "
                "120 = 20% better than average). When ERA+ unavailable, K% vs ERA is used."
                "</div>",
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(
                '<div class="insight-box blue">'
                "<strong>FIP vs xFIP</strong><br>"
                "FIP removes defence. xFIP also normalises HR/FB rate to league average. "
                "<em>FIP &gt; xFIP</em> = giving up too many HRs, likely to improve."
                "</div>",
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                '<div class="insight-box orange">'
                "<strong>ERA − FIP gap</strong><br>"
                "Positive gap (orange) = ERA exceeds FIP → pitching worse than true skill, "
                "regression candidate. Negative (teal) = outperforming, watch for decline."
                "</div>",
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(
                '<div class="insight-box green">'
                "<strong>K% Quadrant</strong><br>"
                "Top-right of the K% vs ERA+ chart = sustainable elite pitching. "
                "High ERA+ with low K% often signals BABIP luck, not true dominance."
                "</div>",
                unsafe_allow_html=True,
            )
        st.markdown(
            "<br><small style='color:#475569'>"
            "Sources · ERA / WHIP / SP split / BP split: MLB Stats API (official). "
            "FIP (self-computed) · xFIP / whiff% / hard-hit%: Baseball Savant leaderboard CSV. "
            "Data refreshes every 60 minutes."
            "</small>",
            unsafe_allow_html=True,
        )


def _render_data_table(data: List[Dict]) -> None:
    with st.expander("📋 Full 30-Team Data Table", expanded=False):
        # Determine colour thresholds
        sp_vals = [d["starter_era"] for d in data if d.get("starter_era")]
        sp_med  = sorted(sp_vals)[len(sp_vals) // 2] if sp_vals else 4.5

        rows_html = ""
        for d in sorted(data, key=lambda x: x.get("starter_era") or 99):
            abbr     = d["team"]
            logo     = _logo_html(abbr, 26)
            sp_era   = d.get("starter_era")
            bp_era   = d.get("bullpen_era")
            era      = d.get("era")
            fip      = d.get("fip")
            xfip     = d.get("xfip")
            whip     = d.get("whip")
            k_pct    = d.get("k_pct")
            source   = d.get("source", "—")

            def _td(val, key, invert=False):
                fmt = _fmt(val, key)
                if val is None:
                    return f"<td style='color:#475569'>{fmt}</td>"
                # colour hint for key ERA columns
                if key in ("era", "fip", "xfip") and val is not None:
                    cls = "good" if val < 3.80 else ("bad" if val > 4.80 else "")
                    return f'<td class="{cls}">{fmt}</td>'
                # era_plus colouring kept for future use
                return f"<td>{fmt}</td>"

            if "Savant" in source:
                badge = '<span class="badge fg">MLB+SV</span>'
            elif "MLB" in source:
                badge = '<span class="badge mlb">MLB</span>'
            else:
                badge = '<span class="badge miss">—</span>'

            rows_html += (
                f"<tr>"
                f"<td>{logo}</td>"
                f"<td style='font-weight:700;letter-spacing:0.5px'>{abbr}</td>"
                + _td(sp_era,  "era")
                + _td(bp_era,  "era")
                + _td(era,     "era")
                + _td(fip,     "fip")
                + _td(xfip,    "xfip")
                + _td(whip,    "whip")
                + _td(k_pct,   "k_pct")
                + _td(d.get("whiff_pct"),    "k_pct")
                + _td(d.get("hard_hit_pct"), "k_pct")
                + f"<td>{badge}</td>"
                + "</tr>"
            )

        headers = ["", "Team", "SP ERA", "BP ERA", "ERA",
                   "FIP", "xFIP", "WHIP", "K%", "Whiff%", "Hard-Hit%", "Source"]
        th_html = "".join(f"<th>{h}</th>" for h in headers)

        table_html = (
            f'<div style="overflow-x:auto;border-radius:8px;'
            f'border:1px solid rgba(148,163,184,0.12);padding:0">'
            f'<table class="salci-table">'
            f"<thead><tr>{th_html}</tr></thead>"
            f"<tbody>{rows_html}</tbody>"
            f"</table></div>"
        )
        st.markdown(table_html, unsafe_allow_html=True)
        st.caption(
            "🟢 Green = strong / 🔴 Red = weak  ·  "
            "MLB+SV badge = MLB API + Savant overlay  ·  "
            "MLB badge = MLB Stats API only  ·  "
            "Sorted by Starter ERA best → worst"
        )


# ─────────────────────────────────────────────────────────────────────────────
# SHAREABLE RANKINGS CARD
# ─────────────────────────────────────────────────────────────────────────────

def _render_rankings_card(rows: List[Dict], stat_key: str, stat_label: str,
                           best_first: bool, season: int) -> None:
    """
    Renders a screenshot-ready HTML card — dark background, team logos,
    medal colouring, SALCI branding. No external dependencies beyond st.markdown.

    Design: vertical stack of rows, each row = rank medal + logo + team name
    + stat value + a proportional bar.
    """
    if not rows:
        return

    values = [d.get(stat_key) for d in rows if d.get(stat_key) is not None]
    if not values:
        return

    val_max = max(values)
    val_min = min(values)
    val_range = val_max - val_min or 1

    medal_emoji = ["🥇", "🥈", "🥉"]
    direction_label = "Best" if best_first else "Worst"
    suffix = "%" if "pct" in stat_key else ""

    def _bar_pct(v):
        # Bars show relative magnitude. For lower-is-better stats, invert.
        if val_range == 0:
            return 60
        if best_first:  # lower is better → shorter bar = worse
            return max(8, int((1 - (v - val_min) / val_range) * 88 + 12))
        else:           # higher is better → longer bar = worse
            return max(8, int((v - val_min) / val_range * 88 + 12))

    bar_color_good = "#1D9E75"
    bar_color_ok   = "#378ADD"
    bar_color_warn = "#D85A30"

    def _bar_color(i):
        if i < 3:
            return bar_color_good if best_first else bar_color_warn
        return bar_color_ok

    rows_html = ""
    for i, d in enumerate(rows):
        val = d.get(stat_key)
        if val is None:
            continue
        logo_url = d.get("logo_url") or TEAM_LOGOS.get(d["team"], "")
        rank_badge = medal_emoji[i] if i < 3 else f"#{i+1}"
        bar_w  = _bar_pct(val)
        bar_cl = _bar_color(i)
        fmt_val = _fmt(val, stat_key)

        logo_html = (
            f'<img src="{logo_url}" width="36" height="36" '
            f'style="object-fit:contain;border-radius:4px;'
            f'background:rgba(255,255,255,0.06);padding:2px;" '
            f'onerror="this.style.display=\'none\'">'
        ) if logo_url else ""

        rows_html += f"""
        <div style="display:flex;align-items:center;gap:10px;
                    padding:7px 14px;border-radius:8px;
                    background:{'rgba(29,158,117,0.10)' if i < 3 else 'rgba(255,255,255,0.03)'};
                    margin-bottom:4px;">
          <!-- rank -->
          <div style="font-size:1.1rem;min-width:28px;text-align:center">{rank_badge}</div>
          <!-- logo -->
          <div style="min-width:40px;display:flex;align-items:center;justify-content:center">
            {logo_html}
          </div>
          <!-- team name -->
          <div style="min-width:36px;font-size:0.82rem;font-weight:700;
                      letter-spacing:0.8px;color:#e2e8f0;text-transform:uppercase">
            {d["team"]}
          </div>
          <!-- bar -->
          <div style="flex:1;background:rgba(148,163,184,0.08);
                      border-radius:4px;height:8px;overflow:hidden">
            <div style="width:{bar_w}%;height:100%;
                        background:{bar_cl};border-radius:4px;
                        box-shadow:0 0 6px {bar_cl}88;
                        transition:width 0.3s ease"></div>
          </div>
          <!-- value -->
          <div style="min-width:52px;text-align:right;font-size:1.05rem;
                      font-weight:800;font-family:'SF Mono','Fira Code',monospace;
                      color:{'#34d399' if i==0 else '#e2e8f0'}">
            {fmt_val}
          </div>
        </div>"""

    card_html = f"""
    <div style="
        background: linear-gradient(145deg, #0f1a2e 0%, #0d1b2a 100%);
        border: 1px solid rgba(29,158,117,0.30);
        border-radius: 16px;
        padding: 20px 18px 16px;
        max-width: 580px;
        font-family: 'SF Pro Display','Helvetica Neue',sans-serif;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    ">
      <!-- Header -->
      <div style="display:flex;align-items:center;justify-content:space-between;
                  margin-bottom:16px;padding-bottom:12px;
                  border-bottom:1px solid rgba(148,163,184,0.12)">
        <div>
          <div style="font-size:0.68rem;letter-spacing:1.8px;color:#64748b;
                      text-transform:uppercase;font-weight:600;margin-bottom:3px">
            SALCI · {season} MLB SEASON
          </div>
          <div style="font-size:1.2rem;font-weight:800;color:#f1f5f9;
                      letter-spacing:-0.3px">
            {direction_label} {len(rows)} — {stat_label}
          </div>
        </div>
        <div style="font-size:2rem">⚾</div>
      </div>
      <!-- Rows -->
      {rows_html}
      <!-- Footer -->
      <div style="margin-top:12px;padding-top:10px;
                  border-top:1px solid rgba(148,163,184,0.08);
                  font-size:0.68rem;color:#475569;
                  display:flex;justify-content:space-between">
        <span>#SALCI #MLB</span>
        <span>Data: MLB Stats API · Baseball Savant</span>
      </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)
    st.caption("💡 Take a screenshot of this card to share on social media.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDER FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def render_pitching_dashboard() -> None:
    # Inject CSS once
    st.markdown(_CSS, unsafe_allow_html=True)

    season = datetime.today().year
    _render_header(season)

    # ── Load data ─────────────────────────────────────────────────────────────
    data = _load_data(season)
    if not data:
        st.error("❌ No data loaded. Check your internet connection or data pipeline.")
        return

    # ── Data-source banner ────────────────────────────────────────────────────
    savant_count = sum(1 for d in data if "Savant" in d.get("source", ""))
    _render_fg_banner(savant_count)

    # ── Top performers strip ──────────────────────────────────────────────────
    _render_top_performers(data)

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # ── Key insights (collapsed by default) ───────────────────────────────────
    _render_key_insights(data)

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────────────────
    # TABS  (replaces radio selector)
    # ─────────────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊  Starter vs Bullpen",
        "🏆  Rankings",
        "🎯  K% vs ERA+",
        "🔮  FIP – ERA Gap",
        "📐  FIP vs xFIP",
    ])

    # ── TAB 1: Starter vs Bullpen ERA ────────────────────────────────────────
    with tab1:
        st.markdown(
            "**Starter ERA vs Bullpen ERA** — sorted by starter ERA (best → worst). "
            "Source: MLB Stats API `sitCodes` split (`startingPitchers` / `reliefPitchers`)."
        )
        has_split = any(d.get("starter_era") for d in data)
        if not has_split:
            st.warning("⏳ Starter/bullpen split not available yet — likely too early in the season.")
        else:
            fig = chart_starter_bullpen(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            sp_rows = _valid(data, "starter_era")
            if sp_rows:
                best  = min(sp_rows, key=lambda x: x["starter_era"])
                worst = max(sp_rows, key=lambda x: x["starter_era"])
                gap_rows = [d for d in data
                            if d.get("starter_era") and d.get("bullpen_era")]

                c1, c2, c3, c4 = st.columns(4)
                c1.metric(
                    "Best Starter ERA",
                    f"{best['starter_era']:.2f}",
                    delta=best["team"],
                    delta_color="off",
                )
                c2.metric(
                    "Worst Starter ERA",
                    f"{worst['starter_era']:.2f}",
                    delta=worst["team"],
                    delta_color="off",
                )
                if gap_rows:
                    biggest_risk = max(
                        gap_rows,
                        key=lambda x: x["bullpen_era"] - x["starter_era"],
                    )
                    strongest_bp = min(
                        gap_rows,
                        key=lambda x: x["bullpen_era"] - x["starter_era"],
                    )
                    diff_risk = biggest_risk["bullpen_era"] - biggest_risk["starter_era"]
                    diff_bp   = strongest_bp["bullpen_era"] - strongest_bp["starter_era"]
                    c3.metric(
                        "Biggest Bullpen Risk",
                        biggest_risk["team"],
                        delta=f"BP {biggest_risk['bullpen_era']:.2f} vs SP {biggest_risk['starter_era']:.2f} (+{diff_risk:.2f})",
                        delta_color="inverse",
                    )
                    c4.metric(
                        "Strongest Bullpen",
                        strongest_bp["team"],
                        delta=f"Gap: {diff_bp:.2f}",
                    )

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
        stat_label = c1.selectbox("Stat", list(stat_map.keys()), key="rank_stat")
        direction  = c2.selectbox("Show", ["Best 8", "Worst 8", "All 30"], key="rank_dir")

        stat_key, lower_is_better = stat_map[stat_label]
        n          = 8 if "8" in direction else 30
        best_first = "Best" in direction or "All" in direction

        rows_with_stat = _valid(data, stat_key)
        if not rows_with_stat:
            st.info(f"No {stat_label} data available yet — requires Baseball Savant overlay.")
        else:
            # ── Plotly chart (interactive, with logos) ────────────────────────
            fig = chart_rankings(rows_with_stat, stat_key, stat_label,
                                  lower_is_better, n, best_first)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            # ── Shareable card  ───────────────────────────────────────────────
            sorted_rows = sorted(rows_with_stat,
                                  key=lambda x: x[stat_key],
                                  reverse=not lower_is_better)
            subset_card = sorted_rows[:n] if best_first else sorted_rows[-n:]
            if not best_first:
                subset_card = list(reversed(subset_card))

            with st.expander("📤 Shareable Card  (screenshot-ready)", expanded=False):
                _render_rankings_card(subset_card, stat_key, stat_label,
                                       best_first, season)


    # ── TAB 3: K% vs ERA+ ────────────────────────────────────────────────────
    with tab3:
        st.markdown(
            "**Dominance quadrant.** "
            "X-axis = K% (higher → more strikeouts). "
            "Y-axis = ERA (lower → better). "
            "Top-right on this chart = high K% and low ERA = elite sustainable pitching."
        )
        if not any(d.get("k_pct") for d in data):
            st.warning("⚠️ K% not yet available — may be early in the season.")
        else:
            fig = chart_kpct_vs_era_plus(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Not enough data points yet.")

    # ── TAB 4: FIP − ERA Gap ─────────────────────────────────────────────────
    with tab4:
        st.markdown(
            "**Regression radar.** "
            "🟠 Orange (positive) = ERA above FIP → pitching worse than true skill, "
            "due for improvement.  "
            "🟢 Teal (negative) = ERA below FIP → outperforming, watch for decline."
        )
        if not any(d.get("fip") for d in data):
            st.warning("FIP not available yet — MLB API may be returning incomplete stats early in the season.")
        else:
            fig = chart_fip_era_gap(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            gap_rows = [d for d in data if d.get("era") and d.get("fip")]
            if gap_rows:
                improvement = sorted(
                    [d for d in gap_rows if d["era"] - d["fip"] > 0.25],
                    key=lambda x: x["era"] - x["fip"], reverse=True,
                )[:4]
                regression = sorted(
                    [d for d in gap_rows if d["era"] - d["fip"] < -0.25],
                    key=lambda x: x["era"] - x["fip"],
                )[:4]

                if improvement:
                    names = "  ·  ".join(
                        f"**{d['team']}** (+{d['era'] - d['fip']:.2f})"
                        for d in improvement
                    )
                    st.warning(f"🟠 **Due for improvement** (ERA well above FIP): {names}")
                if regression:
                    names2 = "  ·  ".join(
                        f"**{d['team']}** ({d['era'] - d['fip']:+.2f})"
                        for d in regression
                    )
                    st.success(f"🟢 **Regression risk** (ERA well below FIP): {names2}")

    # ── TAB 5: FIP vs xFIP ───────────────────────────────────────────────────
    with tab5:
        st.markdown(
            "**HR/FB luck detector.** "
            "xFIP normalises home runs allowed to league-average HR/FB rate.  \n"
            "**FIP > xFIP** → allowing more HRs than expected, likely to improve.  \n"
            "**FIP < xFIP** → suppressing HRs above average, potential regression."
        )
        if not any(d.get("xfip") for d in data):
            st.warning("xFIP requires Baseball Savant overlay. Check network or try again later.")
        else:
            fig = chart_fip_xfip(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            xfip_rows = [d for d in data if d.get("fip") and d.get("xfip")]
            if xfip_rows:
                hr_unlucky = sorted(
                    [d for d in xfip_rows if d["fip"] - d["xfip"] > 0.20],
                    key=lambda x: x["fip"] - x["xfip"], reverse=True,
                )[:3]
                hr_lucky = sorted(
                    [d for d in xfip_rows if d["xfip"] - d["fip"] > 0.20],
                    key=lambda x: x["xfip"] - x["fip"], reverse=True,
                )[:3]
                if hr_unlucky:
                    names = "  ·  ".join(
                        f"**{d['team']}** (FIP {d['fip']:.2f} > xFIP {d['xfip']:.2f})"
                        for d in hr_unlucky
                    )
                    st.success(f"📈 **HR regression candidates** (FIP > xFIP): {names}")
                if hr_lucky:
                    names2 = "  ·  ".join(
                        f"**{d['team']}** (xFIP {d['xfip']:.2f} > FIP {d['fip']:.2f})"
                        for d in hr_lucky
                    )
                    st.warning(f"⚠️ **HR luck beneficiaries** (xFIP > FIP): {names2}")

    # ─────────────────────────────────────────────────────────────────────────
    # Full data table (always visible at bottom)
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    _render_data_table(data)
