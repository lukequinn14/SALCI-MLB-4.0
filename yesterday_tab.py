"""
SALCI Yesterday Tab
====================
Drop-in replacement for the Yesterday / Reflection tab in mlb_salci_full.py.

HOW IT WORKS
────────────
1. GitHub Actions runs `generate_reflection.py` nightly at ~11 PM ET.
2. That script commits `data/reflections/YYYY-MM-DD.json` to the repo.
3. Streamlit Cloud always deploys from the repo — so the file is always there.
4. This module reads that file and renders the full reflection UI.
5. Zero user action required. Survives all code updates (data is git-tracked).

USAGE  (in mlb_salci_full.py)
──────────────────────────────
    from yesterday_tab import render_yesterday_tab

    with tab6:
        render_yesterday_tab()
"""

import json
import os
import requests
import streamlit as st
from datetime import datetime, timedelta
from typing import Optional, Dict

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

# Relative to wherever mlb_salci_full.py lives
REFLECTIONS_DIR  = os.path.join(os.path.dirname(__file__), "data", "reflections")
PREDICTIONS_DIR  = os.path.join(os.path.dirname(__file__), "data", "predictions")

COLORS = {
    "elite":    "#10b981",
    "strong":   "#3b82f6",
    "average":  "#eab308",
    "below":    "#f97316",
    "poor":     "#ef4444",
    "over":     "#10b981",
    "under":    "#ef4444",
    "neutral":  "#94a3b8",
}


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_reflection(date_str: str) -> Optional[Dict]:
    """
    Load a reflection JSON for the given date.
    Tries local file first, then GitHub raw URL as fallback.
    """
    # ── Local file (works on Streamlit Cloud after deploy) ──────────────────
    local_path = os.path.join(REFLECTIONS_DIR, f"{date_str}.json")
    if os.path.exists(local_path):
        try:
            with open(local_path) as f:
                return json.load(f)
        except Exception:
            pass

    # ── GitHub raw fallback (useful during local dev) ────────────────────────
    gh_repo = os.environ.get("GH_REPO") or st.secrets.get("GH_REPO", "")
    if gh_repo:
        raw_url = (
            f"https://raw.githubusercontent.com/{gh_repo}/main/"
            f"data/reflections/{date_str}.json"
        )
        try:
            r = requests.get(raw_url, timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass

    return None


@st.cache_data(ttl=300)
def load_rolling_accuracy(days: int = 7) -> Dict:
    """Aggregate accuracy across the last N days of reflections."""
    all_comparisons = []
    days_with_data  = 0

    for i in range(1, days + 1):
        date_str   = (datetime.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        reflection = load_reflection(date_str)
        if reflection and reflection.get("comparisons"):
            all_comparisons.extend(reflection["comparisons"])
            days_with_data += 1

    if not all_comparisons:
        return {"days_analyzed": 0, "message": "No historical data yet"}

    n        = len(all_comparisons)
    hits     = sum(1 for c in all_comparisons if c["k_accuracy"] == "HIT")
    avg_delta = sum(c["k_delta"] for c in all_comparisons) / n

    return {
        "days_analyzed":   days_with_data,
        "games_analyzed":  n,
        "accuracy_pct":    round(hits / n * 100, 1),
        "avg_k_delta":     round(avg_delta, 2),
        "tendency":        (
            "OVER" if avg_delta > 0.5
            else "UNDER" if avg_delta < -0.5
            else "CALIBRATED"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _delta_color(delta: float) -> str:
    if delta > 1.5:   return COLORS["over"]
    if delta < -1.5:  return COLORS["under"]
    return COLORS["elite"]


def _accuracy_badge(pct: float) -> str:
    if pct >= 70: return f"🟢 {pct}%"
    if pct >= 50: return f"🟡 {pct}%"
    return f"🔴 {pct}%"


def _render_summary_metrics(summary: Dict):
    """Top-row KPI cards."""
    acc   = summary.get("accuracy_pct", 0)
    delta = summary.get("avg_k_delta", 0)
    hits  = summary.get("hits", 0)
    n     = hits + summary.get("overs", 0) + summary.get("unders", 0)
    tend  = summary.get("tendency", "N/A")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🎯 Accuracy", f"{acc}%", help="Predictions within ±1.5 Ks of actual")
    with col2:
        avg_pred   = summary.get("avg_predicted_ks", 0)
        avg_actual = summary.get("avg_actual_ks", 0)
        diff       = round(avg_actual - avg_pred, 1)
        st.metric("⚾ Avg Predicted Ks", f"{avg_pred}", delta=f"{diff:+.1f} vs actual")
    with col3:
        st.metric("📊 Model Tendency", tend,
                  help="OVER = model under-predicts Ks | UNDER = model over-predicts")
    with col4:
        st.metric(
            "✅ Hit / ⬆ Over / ⬇ Under",
            f"{hits} / {summary.get('overs',0)} / {summary.get('unders',0)}",
            help=f"Out of {n} pitchers tracked",
        )


def _render_performer_table(performers: list, label: str, color: str):
    """Render a compact over/underperformer table."""
    if not performers:
        st.info(f"No notable {label.lower()} today.")
        return

    st.markdown(f"#### {label}")
    header = "| Pitcher | Predicted | Actual | Δ Ks |"
    sep    = "|---------|-----------|--------|------|"
    rows   = [header, sep]
    for p in performers:
        delta = p["k_delta"]
        sign  = "+" if delta > 0 else ""
        rows.append(
            f"| **{p['pitcher_name']}** ({p['team']}) "
            f"| {p['predicted_ks']} "
            f"| {p['actual_ks']} "
            f"| <span style='color:{color};font-weight:bold'>{sign}{delta}</span> |"
        )
    st.markdown("\n".join(rows), unsafe_allow_html=True)


def _render_full_comparison_table(comparisons: list):
    """Expandable full table of all pitcher comparisons."""
    with st.expander(f"📋 Full Comparison Table ({len(comparisons)} pitchers)", expanded=False):
        header = "| Pitcher | Team | SALCI | Predicted Ks | Actual Ks | Δ | Result |"
        sep    = "|---------|------|-------|--------------|-----------|---|--------|"
        rows   = [header, sep]
        for c in sorted(comparisons, key=lambda x: x.get("predicted_salci") or 0, reverse=True):
            delta    = c["k_delta"]
            accuracy = c["k_accuracy"]
            sign     = "+" if delta > 0 else ""
            emoji    = "✅" if accuracy == "HIT" else ("📈" if accuracy == "OVER" else "📉")
            color    = _delta_color(delta)
            rows.append(
                f"| {c['pitcher_name']} "
                f"| {c['team']} "
                f"| {c.get('predicted_salci') or 'N/A'} "
                f"| {c['predicted_ks']} "
                f"| {c['actual_ks']} "
                f"| <span style='color:{color}'>{sign}{delta}</span> "
                f"| {emoji} {accuracy} |"
            )
        st.markdown("\n".join(rows), unsafe_allow_html=True)


def _render_rolling_accuracy():
    """7-day rolling accuracy sidebar widget."""
    st.markdown("---")
    st.markdown("### 📈 7-Day Rolling Accuracy")
    rolling = load_rolling_accuracy(7)

    if rolling.get("days_analyzed", 0) == 0:
        st.info("Not enough history yet. Accuracy builds up over the first week.")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Days Tracked",   rolling["days_analyzed"])
    with c2:
        st.metric("Games Analyzed", rolling["games_analyzed"])
    with c3:
        pct  = rolling["accuracy_pct"]
        tend = rolling["tendency"]
        st.metric("Accuracy", f"{pct}%", delta=tend)

    delta_val = rolling["avg_k_delta"]
    if abs(delta_val) > 0.5:
        direction = "under-predicting" if delta_val > 0 else "over-predicting"
        st.caption(
            f"📊 Over the last {rolling['days_analyzed']} days, SALCI is "
            f"{direction} strikeouts by an average of {abs(delta_val):.2f} Ks per pitcher."
        )
    else:
        st.caption(
            f"📊 Over the last {rolling['days_analyzed']} days, SALCI is "
            f"well-calibrated (avg Δ: {delta_val:+.2f} Ks)."
        )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDER FUNCTION  ← call this from mlb_salci_full.py
# ─────────────────────────────────────────────────────────────────────────────

def render_yesterday_tab():
    """
    Full Yesterday tab UI.
    Automatically loads the previous day's reflection from data/reflections/.
    Zero user action required.
    """
    yesterday     = datetime.today() - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    display_date  = yesterday.strftime("%A, %B %-d")  # e.g. "Sunday, April 13"

    st.markdown("### 📈 Yesterday's Reflection")
    st.markdown(
        f"*Predictions vs actual results — automatically generated every night.*  \n"
        f"**Date:** {display_date}"
    )
    st.markdown("---")

    # ── Date picker (optional — lets users browse history) ──────────────────
    with st.expander("🗓️ Browse a different date", expanded=False):
        selected = st.date_input(
            "Select date",
            value=yesterday,
            max_value=yesterday,
            key="reflection_date_picker",
        )
        if selected:
            yesterday_str = selected.strftime("%Y-%m-%d")
            display_date  = selected.strftime("%A, %B %-d")

    # ── Load reflection ──────────────────────────────────────────────────────
    reflection = load_reflection(yesterday_str)

    if reflection is None:
        st.warning(
            f"⏳ No reflection found for **{display_date}** yet.  \n\n"
            "Reflections are generated automatically each night after all games finish (~11 PM ET).  \n"
            "If you're seeing this during the day, yesterday's reflection will appear tonight."
        )
        _render_rolling_accuracy()
        return

    if reflection.get("status") == "no_overlap":
        st.info(
            f"ℹ️ Reflection for {display_date} exists but no predictions matched "
            "box-score results (possible off-day or data issue)."
        )
        _render_rolling_accuracy()
        return

    # ── Summary KPIs ─────────────────────────────────────────────────────────
    summary = reflection.get("summary", {})
    _render_summary_metrics(summary)
    st.markdown("---")

    # ── Profile insight ───────────────────────────────────────────────────────
    insight = summary.get("profile_insight")
    if insight:
        st.info(f"💡 **Model Insight:** {insight}")

    # ── Overperformers / Underperformers ─────────────────────────────────────
    col_over, col_under = st.columns(2)
    with col_over:
        _render_performer_table(
            reflection.get("overperformers", []),
            "🔥 Overperformers (beat projection)",
            COLORS["over"],
        )
    with col_under:
        _render_performer_table(
            reflection.get("underperformers", []),
            "❄️ Underperformers (missed projection)",
            COLORS["under"],
        )

    st.markdown("---")

    # ── Full comparison table ─────────────────────────────────────────────────
    comparisons = reflection.get("comparisons", [])
    if comparisons:
        _render_full_comparison_table(comparisons)

    # ── 7-day rolling accuracy ────────────────────────────────────────────────
    _render_rolling_accuracy()

    # ── Footer ───────────────────────────────────────────────────────────────
    generated_at = reflection.get("generated_at", "")
    if generated_at:
        try:
            dt = datetime.fromisoformat(generated_at)
            st.caption(f"Reflection generated at {dt.strftime('%I:%M %p ET on %B %-d, %Y')}")
        except Exception:
            st.caption(f"Reflection generated: {generated_at}")
