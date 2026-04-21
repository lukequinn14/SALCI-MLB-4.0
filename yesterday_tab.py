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
import pandas as pd
import json
import os
import requests
import streamlit as st
from datetime import datetime, timedelta
from typing import Optional, Dict, List

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

def fetch_actual_results_for_date(date_str: str) -> List[Dict]:
    """Pull real box scores from MLB API for any completed date."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=linescore,decisions"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        if not data.get("dates"):
            return []
        results = []
        for game in data["dates"][0].get("games", []):
            if game.get("status", {}).get("abstractGameState", "") != "Final":
                continue
            game_pk = game.get("gamePk")
            try:
                box = requests.get(
                    f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore", timeout=15
                ).json()
            except Exception:
                continue
            for side in ("home", "away"):
                team_data = box.get("teams", {}).get(side, {})
                pitchers  = team_data.get("pitchers", [])
                players   = team_data.get("players", {})
                if not pitchers:
                    continue
                # Only starting pitcher (first in list)
                starter_id   = pitchers[0]
                starter_data = players.get(f"ID{starter_id}", {})
                stats        = starter_data.get("stats", {}).get("pitching", {})
                if not stats:
                    continue
                ip_raw = str(stats.get("inningsPitched", "0.0"))
                parts  = ip_raw.split(".")
                ip     = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
                # Skip bulk relievers (< 2 IP and < 6 BF = not a starter)
                tbf = int(stats.get("battersFaced", 0))
                if ip < 1.0 and tbf < 5:
                    continue
                results.append({
                    "pitcher_name": starter_data.get("person", {}).get("fullName", "Unknown"),
                    "team":         team_data.get("team", {}).get("name", ""),
                    "actual_ks":    int(stats.get("strikeOuts", 0)),
                    "actual_ip":    round(ip, 1),
                    "pitch_count":  int(stats.get("numberOfPitches", 0)),
                    "opponent":     box.get("teams", {}).get(
                        "away" if side == "home" else "home", {}
                    ).get("team", {}).get("name", ""),
                })
        return results
    except Exception as e:
        return []


def render_yesterday_tab():
    yesterday     = datetime.today() - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")

    st.markdown("### 📈 Yesterday's Reflection")
    st.markdown("*Actual pitcher results + SALCI analysis for any date.*")
    st.markdown("---")

    # ── Date picker ──────────────────────────────────────────────────────────
    selected = st.date_input(
        "📅 Select date to analyze",
        value=yesterday,
        max_value=yesterday,
        key="reflection_date_picker",
    )
    date_str     = selected.strftime("%Y-%m-%d")
    display_date = selected.strftime("%A, %B %-d, %Y")
    st.markdown(f"**Showing:** {display_date}")
    st.markdown("---")

    # ── Try cached reflection first, then compute live ───────────────────────
    reflection = load_reflection(date_str)

    if reflection is None:
        with st.spinner(f"Fetching MLB box scores for {display_date}…"):
            results = fetch_actual_results_for_date(date_str)

        if not results:
            st.warning(
                f"No completed games found for **{display_date}**. "
                "Either games haven't finished yet, or it was an off-day."
            )
            return

        # Build a live reflection from box scores alone (no saved predictions needed)
        reflection = {
            "date":         date_str,
            "status":       "live_computed",
            "games_tracked": len(results),
            "comparisons":  [],   # no predictions to compare against
            "live_results": results,
        }

    # ── Display ──────────────────────────────────────────────────────────────
    live_results = reflection.get("live_results") or []
    comparisons  = reflection.get("comparisons", [])
    summary      = reflection.get("summary", {})
    n            = reflection.get("games_tracked", 0)

    st.markdown(f"#### ⚾ {display_date} — {n} starters")

    # If we have full comparison data (predictions existed)
    if comparisons and summary:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🎯 Accuracy",        f"{summary.get('accuracy_pct', 0)}%")
        col2.metric("📊 Avg Predicted Ks", summary.get("avg_predicted_ks", "—"))
        col3.metric("⚾ Avg Actual Ks",    summary.get("avg_actual_ks", "—"))
        col4.metric("⚖️ Avg Δ Ks",         f"{summary.get('avg_k_delta', 0):+.2f}")

        insight = summary.get("profile_insight")
        if insight:
            st.info(f"💡 {insight}")

        st.markdown("---")
        col_o, col_u = st.columns(2)
        with col_o:
            st.markdown("#### 🔥 Overperformers")
            for p in reflection.get("overperformers", []):
                st.markdown(
                    f"<div style='background:#d1fae5;border-left:4px solid #10b981;"
                    f"border-radius:6px;padding:0.5rem 1rem;margin-bottom:0.4rem;'>"
                    f"<strong>{p['pitcher_name']}</strong> ({p['team']})<br>"
                    f"Predicted {p['predicted_ks']} → Actual <strong>{p['actual_ks']}</strong> "
                    f"<span style='color:#10b981;font-weight:bold;'>+{p['k_delta']}</span></div>",
                    unsafe_allow_html=True,
                )
        with col_u:
            st.markdown("#### ❄️ Underperformers")
            for p in reflection.get("underperformers", []):
                st.markdown(
                    f"<div style='background:#fee2e2;border-left:4px solid #ef4444;"
                    f"border-radius:6px;padding:0.5rem 1rem;margin-bottom:0.4rem;'>"
                    f"<strong>{p['pitcher_name']}</strong> ({p['team']})<br>"
                    f"Predicted {p['predicted_ks']} → Actual <strong>{p['actual_ks']}</strong> "
                    f"<span style='color:#ef4444;font-weight:bold;'>{p['k_delta']}</span></div>",
                    unsafe_allow_html=True,
                )

        st.markdown("---")
        st.markdown("#### 📋 Full Comparison")
        rows = []
        for c in sorted(comparisons, key=lambda x: x.get("actual_ks", 0), reverse=True):
            acc = c.get("k_accuracy", "")
            rows.append({
                "Pitcher":      c["pitcher_name"],
                "Team":         c.get("team", ""),
                "SALCI":        c.get("predicted_salci", "—"),
                "Predicted Ks": c.get("predicted_ks", "—"),
                "Actual Ks":    c.get("actual_ks", "—"),
                "IP":           c.get("actual_ip", "—"),
                "Δ Ks":         f"{c.get('k_delta', 0):+.1f}",
                "Result":       "✅ HIT" if acc == "HIT" else ("📈 OVER" if acc == "OVER" else "📉 UNDER"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    else:
        # No saved predictions — show actual box score results only
        st.info("💡 No saved predictions for this date. Showing actual results only. SALCI comparison will appear once GitHub Actions has been running for a day.")

        rows = []
        for r in sorted(live_results, key=lambda x: x.get("actual_ks", 0), reverse=True):
            rows.append({
                "Pitcher":     r["pitcher_name"],
                "Team":        r["team"],
                "Opponent":    r.get("opponent", ""),
                "Actual Ks":   r["actual_ks"],
                "IP":          r["actual_ip"],
                "Pitch Count": r.get("pitch_count", "—"),
            })

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # Quick summary stats from actuals
            total_ks  = sum(r["actual_ks"]  for r in live_results)
            total_ip  = sum(r["actual_ip"]  for r in live_results)
            avg_ks    = total_ks / len(live_results)
            top       = max(live_results, key=lambda x: x["actual_ks"])

            st.markdown("---")
            c1, c2, c3 = st.columns(3)
            c1.metric("⚾ Avg Ks / Starter", f"{avg_ks:.1f}")
            c2.metric("🏆 K Leader",          f"{top['pitcher_name']} ({top['actual_ks']} Ks)")
            c3.metric("📋 Starters Tracked",  len(live_results))

    # ── Rolling accuracy (only if we have history) ───────────────────────────
    _render_rolling_accuracy()
