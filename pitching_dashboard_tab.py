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

def _logo_html(team: str, size: int = 28) -> str:
    """White pill wrapper so every logo looks clean and professional."""
    url = get_team_logo_url(team)
    return (
        f'<span class="logo-pill" style="width:{size+8}px;height:{size+8}px;">'
        f'<img src="{url}" width="{size}" height="{size}" '
        f'style="display:block;object-fit:contain;" '
        f'alt="{team}" onerror="this.style.display=\'none\'">'
        f'</span>'
    )

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
<style>
.logo-pill {
    display: inline-flex; align-items: center; justify-content: center;
    background: #ffffff; border-radius: 50%; border: 1px solid rgba(0,0,0,0.1);
    padding: 3px; box-shadow: 0 1px 6px rgba(0,0,0,0.15); flex-shrink: 0;
}
.logo-pill img { display: block; object-fit: contain; }
/* Your existing CSS stays here — unchanged */
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
    with st.spinner("🔄 Fetching live pitching data…"):
        return _load(season)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _base_layout(**kw) -> dict:
    return dict(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="'SF Pro Display', 'Helvetica Neue', sans-serif", size=12, color=TEXT),
        margin=dict(l=10, r=40, t=44, b=16),
        **kw,
    )

def _fmt(val, key: str) -> str:
    if val is None: return "—"
    if "pct" in key: return f"{val:.1f}%"
    if key == "era_plus": return str(int(round(val)))
    return f"{val:.2f}"

def _valid(data: List[Dict], key: str) -> List[Dict]:
    return [d for d in data if d.get(key) is not None]

# ─────────────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────────────
def chart_starter_bullpen(data: List[Dict]) -> Optional[go.Figure]:
    rows = [d for d in data if d.get("starter_era") is not None and d.get("bullpen_era") is not None]
    if not rows: return None
    rows = sorted(rows, key=lambda x: x["starter_era"])

    teams = [d["team"] for d in rows]
    sp = [d["starter_era"] for d in rows]
    bp = [d["bullpen_era"] for d in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(y=teams, x=sp, name="Starter ERA", orientation="h",
                         marker_color=TEAL, text=[f"{v:.2f}" for v in sp],
                         textposition="outside", textfont=dict(size=10, color=TEXT)))
    fig.add_trace(go.Bar(y=teams, x=bp, name="Bullpen ERA", orientation="h",
                         marker_color=CORAL, text=[f"{v:.2f}" for v in bp],
                         textposition="outside", textfont=dict(size=10, color=TEXT)))
    fig.update_layout(
        barmode="group",
        height=max(560, len(rows) * 24 + 100),
        title=dict(text="Starter ERA vs Bullpen ERA — All 30 Teams", font=dict(size=15, color=TEXT), x=0),
        xaxis=dict(title="ERA", range=[1.2, 9.0], gridcolor=SLATE, zeroline=False),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        legend=dict(orientation="h", y=1.04, x=0),
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

    # Green → Red gradient: rank 1 = green, rank N = red.
    # If best_first: #1 is green (best ERA), #N is red (worst).
    # If not best_first: #1 is red (worst ERA), #N is green (best).
    def _rank_color(rank_idx: int, total: int) -> str:
        """Interpolate green (#1D9E75) → amber (#BA7517) → red (#D85A30)."""
        t = rank_idx / max(total - 1, 1)   # 0.0 = best, 1.0 = worst
        if not best_first:
            t = 1 - t                       # flip for worst-first lists
        # Green → Amber → Red (two-segment lerp)
        if t < 0.5:
            s = t * 2          # 0→1 across first half
            r = int(29  + s * (186 - 29))
            g = int(158 + s * (117 - 158))
            b = int(117 + s * (23  - 117))
        else:
            s = (t - 0.5) * 2  # 0→1 across second half
            r = int(186 + s * (216 - 186))
            g = int(117 + s * (90  - 117))
            b = int(23  + s * (48  - 23))
        return f"rgb({r},{g},{b})"

    bar_colors = [_rank_color(i, len(subset)) for i in range(len(subset))]

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

    # Rank number annotations to the left of each bar
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
            font      = dict(size=10, color="rgba(148,163,184,0.75)"),
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
            autorange      = "reversed",
            showticklabels = False,   # logos replace text labels entirely
        ),
        showlegend  = False,
        **_base_layout(margin=dict(l=72, r=60, t=48, b=20)),
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
                '<div class="perf-card">'
                + _logo_html(abbr, 44)
                + '<div class="team-abbr">' + abbr + '</div>'
                + '<div class="stat-val">' + f"{era:.2f}" + '</div>'
                + '<div class="stat-lbl">SP ERA</div>'
                + '</div>',
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
    rank numbers (#1–#N), green→red gradient bars, SALCI branding.
    No external dependencies beyond st.markdown.

    Design: vertical stack of rows, each row = rank # + logo pill + stat value + bar.
    """
    if not rows:
        return

    values = [d.get(stat_key) for d in rows if d.get(stat_key) is not None]
    if not values:
        return

    val_max = max(values)
    val_min = min(values)
    val_range = val_max - val_min or 1

    direction_label = "Best" if best_first else "Worst"
    suffix = "%" if "pct" in stat_key else ""
    n_rows = len([d for d in rows if d.get(stat_key) is not None])

    def _bar_pct(v):
        """Bar width proportional to rank quality (best = widest)."""
        if val_range == 0:
            return 60
        if best_first:  # lower-is-better: best (smallest val) gets widest bar
            return max(8, int((1 - (v - val_min) / val_range) * 88 + 12))
        else:           # higher-is-better: largest val gets widest bar
            return max(8, int((v - val_min) / val_range * 88 + 12))

    def _card_bar_color(rank_idx: int) -> str:
        """Green (#1) → Amber → Red (#N), same gradient as chart."""
        t = rank_idx / max(n_rows - 1, 1)
        if not best_first:
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
        return f"rgb({r},{g},{b})"

    rows_html = ""
    for i, d in enumerate(rows):
        val = d.get(stat_key)
        if val is None:
            continue

        # Pre-compute everything — no conditional expressions inside the HTML string
        logo_url   = d.get("logo_url") or TEAM_LOGOS.get(d["team"], "")
        card_fb    = MLB_FALLBACK_LOGOS.get(d["team"], "")
        card_oerr  = ("this.src='" + card_fb + "';this.onerror=null;") if card_fb else "this.style.display='none';"
        rank_badge = "#" + str(i + 1)
        bar_w      = _bar_pct(val)
        bar_cl     = _card_bar_color(i)
        fmt_val    = _fmt(val, stat_key)
        team_name  = d["team"]
        row_bg     = "rgba(29,158,117,0.10)" if i == 0 else "rgba(255,255,255,0.03)"
        val_color  = "#34d399" if i == 0 else "#e2e8f0"

        # Logo wrapped in white pill so dark SVGs show on the dark card bg
        if logo_url:
            logo_html = (
                '<span style="display:inline-flex;align-items:center;justify-content:center;'
                'background:#fff;border-radius:50%;width:42px;height:42px;flex-shrink:0;'
                'box-shadow:0 1px 4px rgba(0,0,0,0.2);">'
                '<img src="' + logo_url + '" width="32" height="32" '
                'style="display:block;object-fit:contain;" '
                'onerror="' + card_oerr + '"></span>'
            )
        else:
            logo_html = ('<span style="display:inline-flex;align-items:center;justify-content:center;'
                         'width:42px;height:42px;font-size:0.75rem;font-weight:700;color:#94a3b8;">'
                         + team_name + '</span>')

        row = (
            '<div style="display:flex;align-items:center;gap:10px;'
            'padding:7px 14px;border-radius:8px;'
            'background:' + row_bg + ';margin-bottom:4px;">'

            # rank badge
            '<div style="font-size:1.1rem;min-width:28px;text-align:center">' + rank_badge + '</div>'

            # logo
            '<div style="min-width:46px;display:flex;align-items:center;justify-content:center">'
            + logo_html + '</div>'

            # bar
            '<div style="flex:1;background:rgba(148,163,184,0.10);border-radius:4px;height:8px;overflow:hidden">'
            '<div style="width:' + str(bar_w) + '%;height:100%;background:' + bar_cl + ';'
            'border-radius:4px;box-shadow:0 0 6px ' + bar_cl + '88"></div></div>'

            # value
            '<div style="min-width:56px;text-align:right;font-size:1.05rem;'
            'font-weight:800;font-family:\'SF Mono\',\'Fira Code\',monospace;'
            'color:' + val_color + '">' + fmt_val + '</div>'
            '</div>'
        )
        rows_html += row

    card_html = (
        '<div style="'
        'background:linear-gradient(145deg,#0f1a2e 0%,#0d1b2a 100%);'
        'border:1px solid rgba(29,158,117,0.30);border-radius:16px;'
        'padding:20px 18px 16px;max-width:580px;'
        'font-family:\'SF Pro Display\',\'Helvetica Neue\',sans-serif;'
        'box-shadow:0 8px 32px rgba(0,0,0,0.5);">'

        # header
        '<div style="display:flex;align-items:center;justify-content:space-between;'
        'margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid rgba(148,163,184,0.12)">'
        '<div>'
        '<div style="font-size:0.68rem;letter-spacing:1.8px;color:#64748b;'
        'text-transform:uppercase;font-weight:600;margin-bottom:3px">'
        'SALCI · ' + str(season) + ' MLB SEASON</div>'
        '<div style="font-size:1.2rem;font-weight:800;color:#f1f5f9;letter-spacing:-0.3px">'
        + direction_label + ' ' + str(len(rows)) + ' — ' + stat_label + '</div>'
        '</div>'
        '<div style="font-size:2rem">⚾</div>'
        '</div>'

        # rows
        + rows_html +

        # footer
        '<div style="margin-top:12px;padding-top:10px;'
        'border-top:1px solid rgba(148,163,184,0.08);'
        'font-size:0.68rem;color:#475569;'
        'display:flex;justify-content:space-between">'
        '<span>#SALCI #MLB</span>'
        '<span>Data: MLB Stats API · Baseball Savant</span>'
        '</div>'
        '</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)
    st.caption("💡 Take a screenshot of this card to share on social media.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDER FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def render_pitching_dashboard() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    season = datetime.today().year
    st.markdown("### ⚾ **SALCI Pitching Dashboard**")
    st.caption(f"Live {season} Season • MLB Stats API + Baseball Savant")

    data = _load_data(season)
    if not data:
        st.error("❌ No data loaded.")
        return

    # FanGraphs / Savant banner
    savant_count = sum(1 for d in data if "Savant" in d.get("source", ""))
    if savant_count >= 20:
        st.success(f"✅ **MLB API + Baseball Savant** — {savant_count}/30 teams with full advanced metrics")
    elif savant_count > 0:
        st.warning(f"⚠️ **Partial data** — {savant_count}/30 teams with Savant metrics")
    else:
        st.info("🔌 **MLB API only** — FIP & K% self-computed, xFIP unavailable")

    st.markdown("---")

    # Top 6 performers with white-pill logos
    sp_rows = sorted([d for d in data if d.get("starter_era")], key=lambda x: x["starter_era"])[:6]
    if sp_rows:
        st.markdown("**🏆 Top 6 Starter ERAs**")
        cols = st.columns(6)
        for i, team in enumerate(sp_rows):
            with cols[i]:
                st.markdown(_logo_html(team["team"], 44), unsafe_allow_html=True)
                st.caption(f"**{team['team']}**")
                st.metric("SP ERA", f"{team['starter_era']:.2f}")

    st.markdown("---")

    # TABS
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Starter vs Bullpen", "🏆 Rankings", "🎯 K% vs ERA+",
        "🔮 FIP–ERA Gap", "📐 FIP vs xFIP"
    ])

    with tab1:
        st.markdown("**Starter ERA vs Bullpen ERA**")
        col_sp, col_bp = st.columns(2)
        with col_sp:
            st.caption("Starter ERA")
            fig_sp = chart_starter_bullpen(data)
            if fig_sp:
                st.plotly_chart(fig_sp, use_container_width=True)
        with col_bp:
            st.caption("Bullpen ERA")
            fig_bp = chart_starter_bullpen(data)
            if fig_bp:
                st.plotly_chart(fig_bp, use_container_width=True)

        with st.expander("📤 Shareable Card (X-ready vertical)", expanded=False):
            st.markdown(
                f'<div style="background:#0f172a;border-radius:16px;padding:24px;color:white;text-align:center;max-width:520px;margin:0 auto;">'
                f'<h3 style="margin:0 0 16px">Starter vs Bullpen ERA • {season}</h3>'
                f'<p style="margin:0 0 20px;color:#94a3b8">MLB Stats API — sorted by Starter ERA</p>'
                f'</div>',
                unsafe_allow_html=True
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

        with st.expander("📤 Shareable Card (screenshot-ready)", expanded=False):
            _render_rankings_card(...)

        st.markdown("---")
        _render_data_table(data)


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
