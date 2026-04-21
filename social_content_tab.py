#!/usr/bin/env python3
"""
SALCI Social Content Tab  ·  v1.0
===================================
Drop-in Streamlit tab that generates AI-powered X/Twitter content
from the same ``filtered_pitchers`` list that drives the Pitcher Cards view.

Usage in mlb_salci_full.py
--------------------------
    try:
        from social_content_tab import render_social_content_tab
        SOCIAL_CONTENT_AVAILABLE = True
    except ImportError:
        SOCIAL_CONTENT_AVAILABLE = False

    # Inside main() after filtered_pitchers is built:
    with tab_social:
        if SOCIAL_CONTENT_AVAILABLE:
            render_social_content_tab(filtered_pitchers)
        else:
            st.warning("social_content_tab.py not found.")

How it works
------------
1.  User clicks "Generate Content" button.
2.  Tab calls build_content_prompt() → sends to claude-sonnet-4-6 via
    the Anthropic API (key from st.secrets["ANTHROPIC_API_KEY"]).
3.  Response is parsed by parse_content_response().
4.  Falls back to local formatters if API call fails.
5.  Outputs are displayed in copyable st.code blocks.

Pro gate
--------
Set st.secrets["PRO_PASSWORD"] to require a password before showing content.
Leave unset (or empty) to make content public.
"""

import json
import time
import requests
import streamlit as st
from typing import Optional

# ---------------------------------------------------------------------------
# Import content engine (same directory as this file)
# ---------------------------------------------------------------------------
try:
    from content_engine import (
        build_content_prompt,
        parse_content_response,
        format_matchup_post,
        format_slate_post,
        derive_storylines,
        enrich_pitchers,
        edge_pct,
        resolve_model_prob,
    )
    CONTENT_ENGINE_OK = True
except ImportError as _e:
    CONTENT_ENGINE_OK = False
    _IMPORT_ERROR = str(_e)

# ---------------------------------------------------------------------------
# Anthropic API wrapper (single, self-contained function)
# ---------------------------------------------------------------------------

def _call_claude(system_prompt: str, user_message: str, api_key: str) -> Optional[str]:
    """
    Call claude-sonnet-4-6 synchronously via the REST API.
    Returns the raw text content or None on error.
    """
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2048,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("content", [])
        text_blocks = [b["text"] for b in blocks if b.get("type") == "text"]
        return "\n".join(text_blocks) if text_blocks else None
    except requests.RequestException as exc:
        st.error(f"⚠️ Anthropic API request failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
<style>
.sct-header {
    display: flex; align-items: center; gap: 12px;
    padding: 14px 0 8px;
    border-bottom: 1px solid rgba(148,163,184,0.15);
    margin-bottom: 16px;
}
.sct-header h2 { margin: 0; font-size: 1.35rem; }
.sct-header p  { margin: 0; font-size: 0.8rem; color: #64748b; }

.edge-badge {
    display: inline-block;
    padding: 2px 8px; border-radius: 99px;
    font-size: 0.72rem; font-weight: 700;
    letter-spacing: 0.4px;
}
.edge-pos { background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid #10b98144; }
.edge-neg { background: rgba(239,68,68,0.15);  color: #ef4444; border: 1px solid #ef444444; }
.edge-neu { background: rgba(148,163,184,0.12); color: #94a3b8; border: 1px solid #94a3b844; }

.pitcher-row {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 12px; border-radius: 8px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(148,163,184,0.10);
    margin-bottom: 6px;
}
.pitcher-name { font-weight: 700; font-size: 0.9rem; }
.pitcher-meta { font-size: 0.75rem; color: #64748b; }
</style>
"""


# ---------------------------------------------------------------------------
# Pitcher summary bar (pre-generate overview)
# ---------------------------------------------------------------------------

def _render_pitcher_summary(filtered_pitchers: list) -> None:
    """Show a compact overview table of pitchers + pre-computed edges."""
    st.markdown("#### 📋 Pitchers in Scope")
    enriched = enrich_pitchers(filtered_pitchers)

    cols = st.columns([3, 1.2, 1.2, 1.5, 1.2, 1.2])
    headers = ["Pitcher", "SALCI", "Grade", "K Line / Odds", "Model%", "Edge"]
    for col, h in zip(cols, headers):
        col.markdown(f"<span style='font-size:0.72rem;color:#64748b;font-weight:600;text-transform:uppercase'>{h}</span>", unsafe_allow_html=True)

    for p in sorted(enriched, key=lambda x: x.get("salci", 0), reverse=True):
        ev = p.get("_edge_pct")
        if ev is None:
            badge = '<span class="edge-badge edge-neu">N/A</span>'
        elif ev >= 4.0:
            badge = f'<span class="edge-badge edge-pos">{ev:+.1f}%</span>'
        elif ev <= -4.0:
            badge = f'<span class="edge-badge edge-neg">{ev:+.1f}%</span>'
        else:
            badge = f'<span class="edge-badge edge-neu">{ev:+.1f}%</span>'

        k_line = p.get("k_line") or p.get("best_line") or "—"
        odds = p.get("odds")
        odds_str = f"({odds:+d})" if odds is not None else ""
        lineup_icon = "✅" if p.get("lineup_confirmed") else "⏳"
        model_pct = p.get("_model_prob_resolved")
        model_str = f"{model_pct:.1f}%" if model_pct is not None else "—"

        c = st.columns([3, 1.2, 1.2, 1.5, 1.2, 1.2])
        c[0].markdown(f"**{p.get('pitcher','?')}** {lineup_icon} <span style='color:#64748b;font-size:0.78rem'>vs {p.get('opponent','?')}</span>", unsafe_allow_html=True)
        c[1].markdown(f"`{p.get('salci', 0):.1f}`")
        c[2].markdown(f"`{p.get('salci_grade','?')}`")
        c[3].markdown(f"`{k_line}` {odds_str}")
        c[4].markdown(model_str)
        c[5].markdown(badge, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_social_content_tab(filtered_pitchers: list) -> None:
    """
    Main entry point — call this inside a ``with tab:`` block.
    """
    st.markdown(_CSS, unsafe_allow_html=True)

    if not CONTENT_ENGINE_OK:
        st.error(
            "❌ `content_engine.py` not found. "
            "Make sure it is in the same directory as `social_content_tab.py`."
        )
        return

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="sct-header">'
        '<span style="font-size:2rem">📣</span>'
        '<div><h2>Social Content Generator</h2>'
        '<p>AI-powered X/Twitter posts · SALCI v6.0 · Model-driven · No hype</p>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    # ── No pitchers guard ─────────────────────────────────────────────────────
    if not filtered_pitchers:
        st.info("ℹ️ No pitchers match your current SALCI filter. Lower the minimum SALCI threshold to include more pitchers.")
        return

    # ── Pro gate (optional) ───────────────────────────────────────────────────
    pro_pw = st.secrets.get("PRO_PASSWORD", "") if hasattr(st, "secrets") else ""
    if pro_pw:
        entered = st.text_input("🔒 Enter Pro password to access Social Content", type="password", key="sct_pw")
        if entered != pro_pw:
            st.warning("Content generator is a Pro feature. Enter the password above.")
            return

    # ── Pitcher overview ──────────────────────────────────────────────────────
    _render_pitcher_summary(filtered_pitchers)
    st.markdown("---")

    # ── Controls ──────────────────────────────────────────────────────────────
    col_l, col_r = st.columns([3, 1])
    with col_l:
        st.markdown(
            f"**{len(filtered_pitchers)} pitcher{'s' if len(filtered_pitchers) != 1 else ''}** ready to generate. "
            "Content uses real SALCI scores, model probabilities, and implied odds."
        )
    with col_r:
        gen_btn = st.button("🚀 Generate Content", type="primary", use_container_width=True, key="sct_gen")

    # ── API key lookup ────────────────────────────────────────────────────────
    api_key = ""
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        pass

    # ── Session state init ────────────────────────────────────────────────────
    if "sct_result" not in st.session_state:
        st.session_state["sct_result"] = None
    if "sct_pitcher_count" not in st.session_state:
        st.session_state["sct_pitcher_count"] = 0

    # ── Generation ────────────────────────────────────────────────────────────
    if gen_btn:
        st.session_state["sct_result"] = None  # clear previous

        system_prompt, user_message = build_content_prompt(filtered_pitchers)
        used_api = False

        if api_key:
            with st.spinner("⚙️ Generating content via Claude API…"):
                raw = _call_claude(system_prompt, user_message, api_key)

            if raw:
                parsed = parse_content_response(raw)
                if parsed:
                    st.session_state["sct_result"] = parsed
                    st.session_state["sct_pitcher_count"] = len(filtered_pitchers)
                    used_api = True
                else:
                    st.warning("⚠️ API response could not be parsed. Falling back to local generator.")
            else:
                st.warning("⚠️ API call returned no content. Using local generator.")

        if not used_api:
            # Local fallback — no API needed
            matchup_posts = [format_matchup_post(p) for p in filtered_pitchers]
            slate_post = format_slate_post(filtered_pitchers)
            storylines = derive_storylines(filtered_pitchers)
            st.session_state["sct_result"] = {
                "matchup_posts": matchup_posts,
                "slate_post": slate_post,
                "storylines": storylines,
                "_source": "local",
            }
            st.session_state["sct_pitcher_count"] = len(filtered_pitchers)

        st.rerun()

    # ── Display results ───────────────────────────────────────────────────────
    result = st.session_state.get("sct_result")
    if result is None:
        st.markdown(
            '<div style="padding:40px;text-align:center;color:#64748b;">'
            '📣 Click <strong>Generate Content</strong> to create today\'s posts'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    source_tag = "🤖 Claude API" if result.get("_source") != "local" else "📐 Local Engine"
    st.success(f"✅ Content generated ({source_tag}) · {st.session_state['sct_pitcher_count']} pitchers")

    # ── SECTION A: Individual Matchup Posts ───────────────────────────────────
    st.markdown("### 📊 A. Individual Matchup Posts")
    st.caption("One post per pitcher — copy and paste directly to X/Twitter")

    matchup_posts: list = result.get("matchup_posts", [])
    if not matchup_posts:
        st.info("No matchup posts generated.")
    else:
        # Pair posts with pitcher names for labelling
        pitcher_names = [p.get("pitcher", f"Pitcher {i+1}") for i, p in enumerate(filtered_pitchers)]
        for i, post in enumerate(matchup_posts):
            name = pitcher_names[i] if i < len(pitcher_names) else f"Pitcher {i+1}"
            char_count = len(post)
            color = "#10b981" if char_count <= 260 else ("#eab308" if char_count <= 280 else "#ef4444")
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;align-items:center;"
                f"margin-bottom:4px;'>"
                f"<span style='font-weight:700;font-size:0.9rem;'>🎯 {name}</span>"
                f"<span style='font-size:0.72rem;color:{color};'>{char_count} chars</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.code(post, language=None)

    # ── SECTION B: Slate Summary Post ────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📊 B. Full Slate Summary")
    st.caption("Top positive-edge picks — ranked by edge size")

    slate_post = result.get("slate_post", "")
    if slate_post:
        char_count = len(slate_post)
        st.markdown(
            f"<div style='text-align:right;font-size:0.72rem;color:#64748b;margin-bottom:4px;'>"
            f"{char_count} chars</div>",
            unsafe_allow_html=True,
        )
        st.code(slate_post, language=None)
    else:
        st.info("No slate post generated.")

    # ── SECTION C: Storylines ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📖 C. Top 3 Storylines")
    st.caption("Data-backed narratives for thread starters or analysis posts")

    storylines: list = result.get("storylines", [])
    if storylines:
        for s in storylines:
            st.markdown(
                f"<div style='background:rgba(255,255,255,0.03);border:1px solid rgba(148,163,184,0.12);"
                f"border-radius:8px;padding:12px 16px;margin-bottom:8px;"
                f"font-size:0.88rem;white-space:pre-wrap;'>{s}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.info("No storylines generated.")

    # ── Raw JSON export ───────────────────────────────────────────────────────
    with st.expander("🔧 Raw JSON output (debug / export)"):
        export = {k: v for k, v in result.items() if not k.startswith("_")}
        st.code(json.dumps(export, indent=2), language="json")

    # ── Regenerate button ─────────────────────────────────────────────────────
    st.markdown("---")
    if st.button("🔄 Regenerate", key="sct_regen"):
        st.session_state["sct_result"] = None
        st.rerun()
