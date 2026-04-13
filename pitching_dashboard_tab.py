"""
SALCI Pitching Dashboard Tab
==============================
Drop-in Streamlit tab showing live team pitching stats for social posting.

Usage in mlb_salci_full.py:
    from pitching_dashboard_tab import render_pitching_dashboard

    with tab_new:           # add a new tab wherever you like
        render_pitching_dashboard()

Charts:
  1. Starter ERA vs Bullpen ERA   — all 30 teams
  2. Team Rankings                — switchable stat + Top/Bottom/All filter
  3. K% vs ERA+ scatter           — sustainability quadrant
  4. FIP − ERA gap                — regression radar
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from typing import List, Dict, Optional

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _load_pitching(season: int) -> List[Dict]:
    from team_pitching_stats import get_all_team_pitching
    return get_all_team_pitching(season)


def load_data(season: int) -> List[Dict]:
    with st.spinner("Fetching live team pitching stats…"):
        data = _load_pitching(season)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# CHART HELPERS
# ─────────────────────────────────────────────────────────────────────────────

TEAL   = "#1D9E75"
CORAL  = "#D85A30"
BLUE   = "#378ADD"
AMBER  = "#BA7517"
PURPLE = "#7F77DD"

def _base_layout(**kwargs):
    return dict(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        margin=dict(l=10, r=20, t=30, b=10),
        **kwargs
    )


def chart_starter_vs_bullpen(data: List[Dict]) -> go.Figure:
    """Grouped horizontal bar — Starter ERA vs Bullpen ERA, sorted by starter ERA."""
    sorted_data = sorted(
        [d for d in data if d.get("starter_era") and d.get("bullpen_era")],
        key=lambda x: x["starter_era"]
    )
    teams       = [d["team"]       for d in sorted_data]
    starter_era = [d["starter_era"] for d in sorted_data]
    bullpen_era = [d["bullpen_era"] for d in sorted_data]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=teams, x=starter_era, name="Starter ERA",
        orientation="h", marker_color=TEAL,
        text=[f"{v:.2f}" for v in starter_era],
        textposition="outside", textfont=dict(size=10),
    ))
    fig.add_trace(go.Bar(
        y=teams, x=bullpen_era, name="Bullpen ERA",
        orientation="h", marker_color=CORAL,
        text=[f"{v:.2f}" for v in bullpen_era],
        textposition="outside", textfont=dict(size=10),
    ))
    fig.update_layout(
        barmode="group",
        height=max(500, len(sorted_data) * 22 + 80),
        xaxis=dict(title="ERA", range=[1.5, 8], gridcolor="rgba(128,128,128,0.15)"),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        legend=dict(orientation="h", y=1.02, x=0),
        **_base_layout(),
    )
    return fig


def chart_rankings(data: List[Dict], stat_key: str, label: str,
                   lower_is_better: bool, n: int, top: bool) -> go.Figure:
    """Horizontal bar chart of top/bottom N teams for a given stat."""
    filtered = [d for d in data if d.get(stat_key) is not None]
    sorted_data = sorted(filtered, key=lambda x: x[stat_key],
                         reverse=not lower_is_better)
    subset = sorted_data[:n] if top else sorted_data[-n:]
    if not top:
        subset = list(reversed(subset))

    teams  = [d["team"]      for d in subset]
    values = [d[stat_key]    for d in subset]

    colors = []
    for i in range(len(subset)):
        if top:
            colors.append(TEAL if i < 3 else "#5DCAA5")
        else:
            colors.append(CORAL if i < 3 else "#F0997B")

    fmt = lambda v: f"{v:.1f}%" if "pct" in stat_key else f"{v:.2f}"

    fig = go.Figure(go.Bar(
        y=teams, x=values, orientation="h",
        marker_color=colors,
        text=[fmt(v) for v in values],
        textposition="outside", textfont=dict(size=11),
    ))
    title = f"{'Best' if top else 'Worst'} {n} — {label}"
    fig.update_layout(
        height=max(300, len(subset) * 40 + 80),
        xaxis=dict(gridcolor="rgba(128,128,128,0.15)"),
        yaxis=dict(autorange="reversed", tickfont=dict(size=12)),
        title=dict(text=title, font=dict(size=14), x=0),
        showlegend=False,
        **_base_layout(),
    )
    return fig


def chart_kpct_vs_era_plus(data: List[Dict]) -> go.Figure:
    """Scatter: K% on x-axis, ERA+ on y-axis. Top-right = elite."""
    filtered = [d for d in data if d.get("k_pct") and d.get("era_plus")]

    # Quadrant boundaries
    avg_k   = sum(d["k_pct"]   for d in filtered) / len(filtered)
    avg_era_plus = sum(d["era_plus"] for d in filtered) / len(filtered)

    def quad_color(d):
        if d["k_pct"] >= avg_k and d["era_plus"] >= avg_era_plus:
            return TEAL    # Elite — sustainable
        if d["k_pct"] < avg_k and d["era_plus"] < avg_era_plus:
            return CORAL   # Struggling
        return BLUE        # Mixed

    fig = go.Figure()

    # Quadrant shading lines
    fig.add_vline(x=avg_k,        line_dash="dot", line_color="rgba(128,128,128,0.4)")
    fig.add_hline(y=avg_era_plus, line_dash="dot", line_color="rgba(128,128,128,0.4)")

    fig.add_trace(go.Scatter(
        x=[d["k_pct"]   for d in filtered],
        y=[d["era_plus"] for d in filtered],
        mode="markers+text",
        text=[d["team"]  for d in filtered],
        textposition="top center",
        textfont=dict(size=10),
        marker=dict(
            color=[quad_color(d) for d in filtered],
            size=10,
            line=dict(color="white", width=1),
        ),
        hovertemplate=(
            "<b>%{text}</b><br>"
            "K%%: %{x:.1f}%%<br>"
            "ERA+: %{y:.0f}<extra></extra>"
        ),
    ))

    fig.add_annotation(x=avg_k + 0.3, y=max(d["era_plus"] for d in filtered) * 0.98,
                       text="Elite (high K%, high ERA+)", showarrow=False,
                       font=dict(size=10, color=TEAL))
    fig.add_annotation(x=avg_k - 2.5, y=min(d["era_plus"] for d in filtered) * 1.02,
                       text="Struggling", showarrow=False,
                       font=dict(size=10, color=CORAL))

    fig.update_layout(
        height=450,
        xaxis=dict(title="Starter K%", gridcolor="rgba(128,128,128,0.15)",
                   tickformat=".1f", ticksuffix="%"),
        yaxis=dict(title="ERA+", gridcolor="rgba(128,128,128,0.15)"),
        **_base_layout(),
    )
    return fig


def chart_fip_era_gap(data: List[Dict]) -> go.Figure:
    """
    Bar chart of (ERA − FIP) per team.
    Positive = ERA above FIP = pitcher has been unlucky or will regress.
    Negative = ERA below FIP = pitcher has been lucky or unsustainable.
    """
    filtered = [d for d in data if d.get("era") and d.get("fip")]
    gaps = [(d, round(d["era"] - d["fip"], 2)) for d in filtered]
    gaps_sorted = sorted(gaps, key=lambda x: x[1], reverse=True)

    teams  = [g[0]["team"] for g in gaps_sorted]
    values = [g[1]          for g in gaps_sorted]
    colors = [CORAL if v > 0 else TEAL for v in values]

    fig = go.Figure(go.Bar(
        y=teams, x=values, orientation="h",
        marker_color=colors,
        text=[f"{v:+.2f}" for v in values],
        textposition="outside", textfont=dict(size=10),
        hovertemplate="<b>%{y}</b><br>ERA − FIP: %{x:+.2f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color="rgba(128,128,128,0.5)", line_width=1)
    fig.update_layout(
        height=max(500, len(gaps_sorted) * 20 + 80),
        xaxis=dict(title="ERA − FIP  (positive = ERA above FIP = regression risk)",
                   gridcolor="rgba(128,128,128,0.15)"),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        showlegend=False,
        **_base_layout(),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDER
# ─────────────────────────────────────────────────────────────────────────────

def render_pitching_dashboard():
    season = datetime.today().year

    st.markdown("### ⚾ Team Pitching Dashboard")
    st.markdown(
        f"*Live {season} season stats — MLB Stats API + FanGraphs via pybaseball.*  \n"
        "Refreshes every hour. Use the charts below as post-ready visuals."
    )

    data = load_data(season)

    if not data:
        st.error("Could not load team pitching data. Check your internet connection.")
        return

    # Source indicator
    sources = set(d["source"] for d in data)
    if "FanGraphs + MLB API" in sources:
        st.success(
            f"✅ Data source: **FanGraphs + MLB Stats API** — "
            f"FIP, ERA+, K% from FanGraphs; ERA/WHIP from official MLB API. "
            f"{len(data)} teams loaded."
        )
    else:
        st.warning(
            "⚠️ pybaseball not available — using MLB Stats API only. "
            "FIP is calculated from raw components (HR, BB, K, IP). "
            "ERA+ is approximated without park factors. "
            "Install pybaseball for full FanGraphs data: `pip install pybaseball`"
        )

    st.markdown("---")

    # ── Tab selector ─────────────────────────────────────────────────────────
    chart_tab = st.radio(
        "Select chart",
        ["📊 Starter vs Bullpen ERA", "🏆 Team Rankings", "🎯 K% vs ERA+", "🔮 FIP − ERA Gap"],
        horizontal=True,
        key="pitching_chart_tab",
    )

    st.markdown("---")

    # ── Chart 1: Starter vs Bullpen ERA ──────────────────────────────────────
    if chart_tab == "📊 Starter vs Bullpen ERA":
        st.markdown("#### All 30 teams sorted by Starter ERA (best → worst)")
        st.markdown(
            "Green = Starter ERA · Orange = Bullpen ERA  \n"
            "*Big gap between the two = reliance risk or bullpen strength*"
        )
        fig = chart_starter_vs_bullpen(data)
        st.plotly_chart(fig, use_container_width=True)

        # Callout
        best = data[0]
        worst = data[-1]
        col1, col2 = st.columns(2)
        col1.metric("Best Starter ERA", f"{best['team']}  {best.get('starter_era','—')}")
        col2.metric("Worst Starter ERA", f"{worst['team']}  {worst.get('starter_era','—')}")

    # ── Chart 2: Rankings ─────────────────────────────────────────────────────
    elif chart_tab == "🏆 Team Rankings":
        c1, c2, c3 = st.columns(3)
        stat_options = {
            "Starter ERA":   ("starter_era",   True),
            "Bullpen ERA":   ("bullpen_era",    True),
            "Starter K%":    ("starter_k_pct",  False),
            "Overall WHIP":  ("whip",           True),
            "FIP":           ("fip",            True),
            "ERA+":          ("era_plus",        False),
        }
        stat_label  = c1.selectbox("Stat", list(stat_options.keys()), key="rank_stat")
        direction   = c2.selectbox("Show", ["Top 8 (Best)", "Bottom 8 (Worst)", "All 30"], key="rank_dir")
        n           = 8 if "8" in direction else 30
        top         = "Best" in direction or direction == "All 30"

        stat_key, lower_is_better = stat_options[stat_label]
        if direction == "All 30":
            # For "All 30" show full sorted list
            fig = chart_rankings(data, stat_key, stat_label, lower_is_better, 30, True)
        else:
            fig = chart_rankings(data, stat_key, stat_label, lower_is_better, n, top)

        st.plotly_chart(fig, use_container_width=True)

        # Twitter caption helper
        sorted_stat = sorted(
            [d for d in data if d.get(stat_key)],
            key=lambda x: x[stat_key],
            reverse=not lower_is_better
        )
        if sorted_stat:
            best_t = sorted_stat[0]
            worst_t = sorted_stat[-1]
            val_fmt = lambda v: f"{v:.1f}%" if "pct" in stat_key else f"{v:.2f}"
            st.info(
                f"📱 **Tweet caption idea:**  \n"
                f"\"Current 2026 {stat_label} Rankings  \n"
                f"Best: {best_t['team']} ({val_fmt(best_t[stat_key])})  \n"
                f"Worst: {worst_t['team']} ({val_fmt(worst_t[stat_key])})  \n"
                f"Full SALCI breakdown dropping soon #SALCI #MLB\""
            )

    # ── Chart 3: K% vs ERA+ Scatter ──────────────────────────────────────────
    elif chart_tab == "🎯 K% vs ERA+":
        st.markdown("#### K% vs ERA+ — sustainability quadrant")
        st.markdown(
            "**Top-right** = Elite (high K% + high ERA+) — sustainable dominance  \n"
            "**Bottom-left** = Struggling  \n"
            "**Top-left** = High ERA+ but low K% — possibly lucky, watch for regression  \n"
            "**Bottom-right** = High K% but poor results — could be due for a turnaround"
        )

        has_era_plus = any(d.get("era_plus") for d in data)
        if not has_era_plus:
            st.warning(
                "ERA+ requires pybaseball (FanGraphs data). "
                "Currently showing raw approximation — install pybaseball for accurate park-adjusted ERA+."
            )

        fig = chart_kpct_vs_era_plus(data)
        st.plotly_chart(fig, use_container_width=True)

    # ── Chart 4: FIP − ERA Gap ───────────────────────────────────────────────
    elif chart_tab == "🔮 FIP − ERA Gap":
        st.markdown("#### FIP − ERA gap (regression radar)")
        st.markdown(
            "**Orange (positive)** = ERA higher than FIP → pitcher has been unlucky or due for negative regression  \n"
            "**Green (negative)** = ERA lower than FIP → pitcher has been lucky or genuinely dominant  \n\n"
            "*FIP (Fielding Independent Pitching) strips out defense and luck — it's what ERA 'should' be based on true outcomes (HR, BB, K).*"
        )

        has_fip = any(d.get("fip") for d in data)
        if not has_fip:
            st.warning("FIP data unavailable — install pybaseball for FanGraphs FIP values.")
        else:
            fig = chart_fip_era_gap(data)
            st.plotly_chart(fig, use_container_width=True)

            # Regression candidates callout
            regression_risk = sorted(
                [d for d in data if d.get("era") and d.get("fip")
                 and (d["era"] - d["fip"]) > 0.30],
                key=lambda x: x["era"] - x["fip"], reverse=True
            )[:3]
            if regression_risk:
                names = ", ".join(f"{d['team']} (+{d['era']-d['fip']:.2f})" for d in regression_risk)
                st.info(f"⚠️ **Negative regression candidates:** {names} — ERA well above FIP")

    # ── Data table ────────────────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("📋 Full data table", expanded=False):
        import pandas as pd
        rows = []
        for d in data:
            rows.append({
                "Team":        d["team"],
                "Name":        d["name"],
                "Starter ERA": d.get("starter_era", "—"),
                "Bullpen ERA": d.get("bullpen_era",  "—"),
                "WHIP":        d.get("whip",         "—"),
                "K%":          f"{d['k_pct']:.1f}%" if d.get("k_pct") else "—",
                "FIP":         d.get("fip",          "—"),
                "ERA+":        d.get("era_plus",      "—"),
                "Source":      d.get("source",        "—"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(
        f"Data refreshes every hour. "
        f"ERA/WHIP: MLB Stats API (official). "
        f"FIP/ERA+/K%: FanGraphs via pybaseball."
    )
