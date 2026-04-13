"""
SALCI Pitching Dashboard Tab
==============================
Add to mlb_salci_full.py:

    try:
        from pitching_dashboard_tab import render_pitching_dashboard
        PITCHING_DASH_AVAILABLE = True
    except ImportError:
        PITCHING_DASH_AVAILABLE = False

    # In your tabs:
    with tab8:
        if PITCHING_DASH_AVAILABLE:
            render_pitching_dashboard()
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from typing import List, Dict, Optional

TEAL   = "#1D9E75"
CORAL  = "#D85A30"
BLUE   = "#378ADD"
AMBER  = "#BA7517"
PURPLE = "#7F77DD"


# ─────────────────────────────────────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _load(season: int) -> List[Dict]:
    from team_pitching_stats import get_all_team_pitching
    return get_all_team_pitching(season)


def _load_data(season: int) -> List[Dict]:
    with st.spinner("Fetching live team pitching stats from FanGraphs + MLB API…"):
        return _load(season)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _layout(**kw):
    return dict(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        margin=dict(l=10, r=30, t=30, b=10),
        **kw,
    )


def _fmt(val, key: str) -> str:
    if val is None:
        return "—"
    if "pct" in key:
        return f"{val:.1f}%"
    if key == "era_plus":
        return str(int(val))
    return f"{val:.2f}"


def _valid(data: List[Dict], key: str) -> List[Dict]:
    """Return rows where key is a non-None number."""
    return [d for d in data if d.get(key) is not None]


# ─────────────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────────────

def chart_starter_bullpen(data: List[Dict]) -> go.Figure:
    rows = [d for d in data if d.get("starter_era") is not None and d.get("bullpen_era") is not None]
    if not rows:
        return None
    rows = sorted(rows, key=lambda x: x["starter_era"])

    teams = [d["team"]        for d in rows]
    sp    = [d["starter_era"] for d in rows]
    bp    = [d["bullpen_era"] for d in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=teams, x=sp, name="Starter ERA", orientation="h",
        marker_color=TEAL,
        text=[f"{v:.2f}" for v in sp], textposition="outside", textfont=dict(size=10),
    ))
    fig.add_trace(go.Bar(
        y=teams, x=bp, name="Bullpen ERA", orientation="h",
        marker_color=CORAL,
        text=[f"{v:.2f}" for v in bp], textposition="outside", textfont=dict(size=10),
    ))
    fig.update_layout(
        barmode="group",
        height=max(520, len(rows) * 22 + 80),
        xaxis=dict(title="ERA", range=[1.5, 8.5], gridcolor="rgba(128,128,128,0.12)"),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        legend=dict(orientation="h", y=1.02, x=0),
        **_layout(),
    )
    return fig


def chart_rankings(data: List[Dict], stat_key: str, label: str,
                   lower_is_better: bool, n: int, best_first: bool) -> go.Figure:
    rows = _valid(data, stat_key)
    if not rows:
        return None
    rows = sorted(rows, key=lambda x: x[stat_key], reverse=not lower_is_better)
    subset = rows[:n] if best_first else rows[-n:]
    if not best_first:
        subset = list(reversed(subset))

    teams  = [d["team"]     for d in subset]
    values = [d[stat_key]   for d in subset]
    colors = [
        (TEAL if i < 3 else "#5DCAA5") if best_first
        else (CORAL if i < 3 else "#F0997B")
        for i in range(len(subset))
    ]

    fig = go.Figure(go.Bar(
        y=teams, x=values, orientation="h",
        marker_color=colors,
        text=[_fmt(v, stat_key) for v in values],
        textposition="outside", textfont=dict(size=11),
    ))
    fig.update_layout(
        height=max(300, len(subset) * 42 + 80),
        title=dict(text=f"{'Best' if best_first else 'Worst'} {len(subset)} — {label}",
                   font=dict(size=14), x=0),
        xaxis=dict(gridcolor="rgba(128,128,128,0.12)"),
        yaxis=dict(autorange="reversed", tickfont=dict(size=12)),
        showlegend=False,
        **_layout(),
    )
    return fig


def chart_kpct_vs_era_plus(data: List[Dict]) -> Optional[go.Figure]:
    rows = [d for d in data if d.get("k_pct") is not None and d.get("era_plus") is not None]
    if len(rows) < 2:
        return None

    avg_k  = sum(d["k_pct"]   for d in rows) / len(rows)
    avg_ep = sum(d["era_plus"] for d in rows) / len(rows)

    def color(d):
        if d["k_pct"] >= avg_k and d["era_plus"] >= avg_ep:
            return TEAL
        if d["k_pct"] < avg_k and d["era_plus"] < avg_ep:
            return CORAL
        return BLUE

    fig = go.Figure()
    fig.add_vline(x=avg_k,  line_dash="dot", line_color="rgba(128,128,128,0.4)")
    fig.add_hline(y=avg_ep, line_dash="dot", line_color="rgba(128,128,128,0.4)")

    fig.add_trace(go.Scatter(
        x=[d["k_pct"]    for d in rows],
        y=[d["era_plus"] for d in rows],
        mode="markers+text",
        text=[d["team"]  for d in rows],
        textposition="top center",
        textfont=dict(size=10),
        marker=dict(color=[color(d) for d in rows], size=10,
                    line=dict(color="white", width=1)),
        hovertemplate="<b>%{text}</b><br>K%%: %{x:.1f}%%<br>ERA+: %{y:.0f}<extra></extra>",
    ))

    k_vals  = [d["k_pct"]   for d in rows]
    ep_vals = [d["era_plus"] for d in rows]
    pad_k   = (max(k_vals) - min(k_vals)) * 0.12
    pad_ep  = (max(ep_vals) - min(ep_vals)) * 0.12

    fig.update_layout(
        height=460,
        xaxis=dict(title="Team K%", tickformat=".1f", ticksuffix="%",
                   range=[min(k_vals) - pad_k, max(k_vals) + pad_k],
                   gridcolor="rgba(128,128,128,0.12)"),
        yaxis=dict(title="ERA+",
                   range=[min(ep_vals) - pad_ep, max(ep_vals) + pad_ep],
                   gridcolor="rgba(128,128,128,0.12)"),
        **_layout(),
    )
    return fig


def chart_fip_era_gap(data: List[Dict]) -> Optional[go.Figure]:
    rows = [d for d in data if d.get("era") is not None and d.get("fip") is not None]
    if not rows:
        return None
    rows = sorted(rows, key=lambda x: x["era"] - x["fip"], reverse=True)

    teams  = [d["team"]                     for d in rows]
    gaps   = [round(d["era"] - d["fip"], 2) for d in rows]
    colors = [CORAL if g > 0 else TEAL      for g in gaps]

    fig = go.Figure(go.Bar(
        y=teams, x=gaps, orientation="h",
        marker_color=colors,
        text=[f"{g:+.2f}" for g in gaps],
        textposition="outside", textfont=dict(size=10),
        hovertemplate="<b>%{y}</b><br>ERA − FIP: %{x:+.2f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color="rgba(128,128,128,0.4)", line_width=1)
    fig.update_layout(
        height=max(520, len(rows) * 20 + 80),
        xaxis=dict(title="ERA − FIP", gridcolor="rgba(128,128,128,0.12)"),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        showlegend=False,
        **_layout(),
    )
    return fig


def chart_fip_xfip(data: List[Dict]) -> Optional[go.Figure]:
    """FIP vs xFIP — shows which teams are getting lucky on HR/FB rate."""
    rows = [d for d in data if d.get("fip") is not None and d.get("xfip") is not None]
    if not rows:
        return None
    rows = sorted(rows, key=lambda x: x["fip"])

    teams = [d["team"] for d in rows]
    fip   = [d["fip"]  for d in rows]
    xfip  = [d["xfip"] for d in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=teams, x=fip, name="FIP", orientation="h",
        marker_color=BLUE,
        text=[f"{v:.2f}" for v in fip], textposition="outside", textfont=dict(size=10),
    ))
    fig.add_trace(go.Bar(
        y=teams, x=xfip, name="xFIP", orientation="h",
        marker_color=PURPLE,
        text=[f"{v:.2f}" for v in xfip], textposition="outside", textfont=dict(size=10),
    ))
    fig.update_layout(
        barmode="group",
        height=max(520, len(rows) * 22 + 80),
        xaxis=dict(title="ERA scale", range=[2.0, 6.5], gridcolor="rgba(128,128,128,0.12)"),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        legend=dict(orientation="h", y=1.02, x=0),
        **_layout(),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDER
# ─────────────────────────────────────────────────────────────────────────────

def render_pitching_dashboard():
    season = datetime.today().year
    st.markdown("### ⚾ Team Pitching Dashboard")
    st.markdown(
        f"*Live {season} data — FanGraphs (ERA, FIP, xFIP, K%, ERA+) "
        "merged with MLB API starter/bullpen split.*"
    )

    data = _load_data(season)

    if not data:
        st.error("No data loaded. Check your internet connection.")
        return

    # ── Source badge ──────────────────────────────────────────────────────────
    fg_count = sum(1 for d in data if "FanGraphs" in d.get("source", ""))
    if fg_count > 0:
        st.success(f"✅ Live FanGraphs data loaded for {fg_count}/30 teams — ERA, FIP, xFIP, starter/bullpen split")
    else:
        st.warning("⚠️ FanGraphs scrape failed — showing MLB Stats API data only.")

    st.markdown("---")

    # ── Chart selector ────────────────────────────────────────────────────────
    view = st.radio(
        "Select chart",
        ["📊 Starter vs Bullpen ERA", "🏆 Rankings", "🎯 K% vs ERA+",
         "🔮 FIP − ERA Gap", "📐 FIP vs xFIP"],
        horizontal=True,
        key="pitching_view",
    )
    st.markdown("---")

    # ─── VIEW 1: Starter vs Bullpen ERA ───────────────────────────────────────
    if view == "📊 Starter vs Bullpen ERA":
        st.markdown("#### Starter ERA vs Bullpen ERA — all 30 teams")
        st.caption(
            "Source: MLB Stats API sitCodes split (startingPitchers / reliefPitchers).  "
            "Sorted by Starter ERA best → worst."
        )
        has_split = any(d.get("starter_era") for d in data)
        if not has_split:
            st.warning("Starter/bullpen split not available yet — likely too early in the season.")
        else:
            fig = chart_starter_bullpen(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            sp_rows = _valid(data, "starter_era")
            if sp_rows:
                best  = min(sp_rows, key=lambda x: x["starter_era"])
                worst = max(sp_rows, key=lambda x: x["starter_era"])
                c1, c2 = st.columns(2)
                c1.metric("Best Starter ERA",  f"{best['team']}  {best['starter_era']:.2f}")
                c2.metric("Worst Starter ERA", f"{worst['team']}  {worst['starter_era']:.2f}")

                # Biggest gap teams (bullpen >> starter or vice versa)
                gap_rows = [d for d in data if d.get("starter_era") and d.get("bullpen_era")]
                if gap_rows:
                    best_gap  = max(gap_rows, key=lambda x: x["bullpen_era"] - x["starter_era"])
                    worst_gap = min(gap_rows, key=lambda x: x["bullpen_era"] - x["starter_era"])
                    c3, c4 = st.columns(2)
                    diff = best_gap["bullpen_era"] - best_gap["starter_era"]
                    c3.metric(
                        "Biggest bullpen risk",
                        f"{best_gap['team']}",
                        delta=f"BP {best_gap['bullpen_era']:.2f} vs SP {best_gap['starter_era']:.2f} (+{diff:.2f})",
                        delta_color="inverse",
                    )
                    diff2 = worst_gap["bullpen_era"] - worst_gap["starter_era"]
                    c4.metric(
                        "Strongest bullpen",
                        f"{worst_gap['team']}",
                        delta=f"BP {worst_gap['bullpen_era']:.2f} vs SP {worst_gap['starter_era']:.2f} ({diff2:.2f})",
                    )

    # ─── VIEW 2: Rankings ────────────────────────────────────────────────────
    elif view == "🏆 Rankings":
        stat_map = {
            "Starter ERA":    ("starter_era",  True),
            "Bullpen ERA":    ("bullpen_era",   True),
            "Overall ERA":    ("era",           True),
            "FIP":            ("fip",           True),
            "xFIP":           ("xfip",          True),
            "WHIP":           ("whip",          True),
            "K%":             ("k_pct",         False),
            "ERA+":           ("era_plus",      False),
        }
        c1, c2, c3 = st.columns(3)
        stat_label = c1.selectbox("Stat",   list(stat_map.keys()), key="rank_stat")
        direction  = c2.selectbox("Show",   ["Best 8", "Worst 8", "All 30"],  key="rank_dir")
        stat_key, lower_is_better = stat_map[stat_label]

        n         = 8 if "8" in direction else 30
        best_first = "Best" in direction or "All" in direction

        rows_with_stat = _valid(data, stat_key)
        if not rows_with_stat:
            st.info(f"No data available for {stat_label} yet.")
        else:
            fig = chart_rankings(rows_with_stat, stat_key, stat_label,
                                  lower_is_better, n, best_first)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            # Tweet caption
            sorted_rows = sorted(rows_with_stat, key=lambda x: x[stat_key],
                                  reverse=not lower_is_better)
            if sorted_rows:
                top = sorted_rows[0]
                bot = sorted_rows[-1]
                st.info(
                    f"📱 **Twitter caption:**\n"
                    f"\"2026 {stat_label} rankings — "
                    f"Best: {top['team']} ({_fmt(top[stat_key], stat_key)})  "
                    f"| Worst: {bot['team']} ({_fmt(bot[stat_key], stat_key)})  "
                    f"#SALCI #MLB\""
                )

    # ─── VIEW 3: K% vs ERA+ ──────────────────────────────────────────────────
    elif view == "🎯 K% vs ERA+":
        st.markdown("#### K% vs ERA+ — sustainability quadrant")
        st.caption(
            "ERA+ from FanGraphs (park-adjusted). Top-right = elite sustainable pitching. "
            "Top-left = high ERA+ but low K% = possibly BABIP lucky."
        )
        has_kpct = any(d.get("k_pct") for d in data)
        has_erap = any(d.get("era_plus") for d in data)
        if not has_kpct or not has_erap:
            st.warning(
                "K% and/or ERA+ not yet available — needs FanGraphs data (pybaseball). "
                "Early in the season data may not be available yet."
            )
        else:
            fig = chart_kpct_vs_era_plus(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Not enough data points to render scatter plot yet.")

    # ─── VIEW 4: FIP − ERA gap ───────────────────────────────────────────────
    elif view == "🔮 FIP − ERA Gap":
        st.markdown("#### ERA − FIP gap (regression radar)")
        st.markdown(
            "**Orange** = ERA higher than FIP → pitching worse than true skill, "
            "due for improvement  \n"
            "**Green** = ERA lower than FIP → getting lucky or truly elite, "
            "watch for regression"
        )
        has_fip = any(d.get("fip") for d in data)
        if not has_fip:
            st.warning("FIP not available. Ensure pybaseball is installed.")
        else:
            fig = chart_fip_era_gap(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            # Callouts
            gap_rows = [d for d in data if d.get("era") and d.get("fip")]
            if gap_rows:
                regression = sorted(
                    [d for d in gap_rows if d["era"] - d["fip"] < -0.25],
                    key=lambda x: x["era"] - x["fip"]
                )[:3]
                lucky = sorted(
                    [d for d in gap_rows if d["era"] - d["fip"] > 0.25],
                    key=lambda x: x["era"] - x["fip"], reverse=True
                )[:3]
                if regression:
                    names = ", ".join(
                        f"{d['team']} ({d['era'] - d['fip']:+.2f})" for d in regression
                    )
                    st.success(f"🟢 **Regression risk** (ERA well below FIP): {names}")
                if lucky:
                    names2 = ", ".join(
                        f"{d['team']} ({d['era'] - d['fip']:+.2f})" for d in lucky
                    )
                    st.warning(f"🟠 **Due for improvement** (ERA above FIP): {names2}")

    # ─── VIEW 5: FIP vs xFIP ─────────────────────────────────────────────────
    elif view == "📐 FIP vs xFIP":
        st.markdown("#### FIP vs xFIP — HR/FB luck detector")
        st.markdown(
            "xFIP normalises home runs to league average HR/FB rate.  \n"
            "**FIP > xFIP** = giving up more HRs than expected → likely to improve  \n"
            "**FIP < xFIP** = suppressing HRs → could regress"
        )
        has_xfip = any(d.get("xfip") for d in data)
        if not has_xfip:
            st.warning("xFIP requires FanGraphs data (pybaseball).")
        else:
            fig = chart_fip_xfip(data)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

    # ─── Data table ──────────────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("📋 Full data table", expanded=False):
        rows = []
        for d in data:
            rows.append({
                "Team":        d["team"],
                "SP ERA":      _fmt(d.get("starter_era"), "era"),
                "BP ERA":      _fmt(d.get("bullpen_era"),  "era"),
                "ERA":         _fmt(d.get("era"),          "era"),
                "FIP":         _fmt(d.get("fip"),          "fip"),
                "xFIP":        _fmt(d.get("xfip"),         "xfip"),
                "SIERA":       _fmt(d.get("siera"),        "siera"),
                "WHIP":        _fmt(d.get("whip"),         "whip"),
                "K%":          _fmt(d.get("k_pct"),        "k_pct"),
                "ERA+":        _fmt(d.get("era_plus"),     "era_plus"),
                "Source":      d.get("source", "—"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(
        "ERA/WHIP/SP split/BP split: MLB Stats API (official). "
        "FIP/xFIP/SIERA/K%/ERA+: FanGraphs via pybaseball. "
        "Refreshes hourly."
    )
