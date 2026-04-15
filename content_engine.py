#!/usr/bin/env python3
"""
SALCI Content Engine  ·  v1.0
==============================
Pure-Python module — zero Streamlit imports.

Transforms a ``filtered_pitchers`` list (the same list that powers the
Pitcher Cards view) into production-ready social media content for X/Twitter.

ALL analytical logic lives here so it can be:
  • Called from social_content_tab.py (Streamlit UI)
  • Called from generate_daily_final.py (GitHub Actions / pre-compute)
  • Unit-tested independently

Public API
----------
build_content_prompt(filtered_pitchers)  → str
    Returns the system + user prompt ready for the Anthropic API.

parse_content_response(raw_json_str)     → dict | None
    Safely parses the model's JSON output.

format_matchup_post(pitcher_dict)        → str
    Local (no-API) fallback formatter for one pitcher.

format_slate_post(filtered_pitchers)     → str
    Local fallback for the full slate summary.

derive_storylines(filtered_pitchers)     → list[str]
    Heuristic storyline generation (no API required).

implied_prob(odds)                       → float
    Converts American odds → 0-1 implied probability.

edge(model_prob, odds)                   → float
    model_prob – implied_prob (both as fractions, result in percent).
"""

import json
import math
import re
from typing import Any


# ---------------------------------------------------------------------------
# Odds / probability helpers
# ---------------------------------------------------------------------------

def implied_prob(odds: int | float) -> float:
    """
    Convert American odds to implied probability [0, 1].

    Positive odds  (e.g. +130) → underdog
    Negative odds  (e.g. -150) → favourite
    """
    if odds is None:
        return 0.50
    odds = float(odds)
    if odds >= 0:
        return 100.0 / (odds + 100.0)
    else:
        abs_o = abs(odds)
        return abs_o / (abs_o + 100.0)


def edge_pct(model_prob_fraction: float, odds: int | float) -> float:
    """
    Return edge in PERCENTAGE POINTS (signed).

    model_prob_fraction : float in [0, 1]
    odds                : American integer/float
    """
    impl = implied_prob(odds)
    return (model_prob_fraction - impl) * 100.0


def resolve_model_prob(pitcher: dict) -> float | None:
    """
    Priority: model_prob  >  lines dict (matching k_line)  >  SALCI proxy.

    Returns a fraction [0, 1] or None if nothing is available.
    """
    # 1) Explicit model_prob
    mp = pitcher.get("model_prob")
    if mp is not None:
        try:
            mp = float(mp)
            if 0.0 < mp <= 1.0:
                return mp
            if 1.0 < mp <= 100.0:
                return mp / 100.0
        except (TypeError, ValueError):
            pass

    # 2) lines dict keyed by k_line
    k_line = pitcher.get("k_line") or pitcher.get("best_line")
    lines: dict = pitcher.get("lines") or pitcher.get("k_lines") or {}
    if k_line is not None and lines:
        # k_line may be "5.5" → try "5" and "6" as well as "5.5"
        for key in [str(k_line), str(int(float(k_line))), str(int(float(k_line)) + 1)]:
            val = lines.get(key)
            if val is not None:
                try:
                    val = float(val)
                    return val / 100.0 if val > 1.0 else val
                except (TypeError, ValueError):
                    pass

    # 3) SALCI proxy (directional only — calibration is rough)
    salci = pitcher.get("salci")
    if salci is not None:
        try:
            salci = float(salci)
            # Map SALCI 30-90 → ~40%-70% probability (very rough)
            return max(0.35, min(0.75, 0.35 + (salci - 30) / 200.0))
        except (TypeError, ValueError):
            pass

    return None


# ---------------------------------------------------------------------------
# System prompt (static — defines the AI persona and format)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a quantitative sports analyst and content engine for the SALCI v6.0 MLB Strikeout Prediction System.

Your role is to transform the filtered_pitchers list (already processed by data_loader.py and filtered by min_salci) into high-quality, data-driven, highly shareable social media content for X/Twitter.

## SYSTEM CONTEXT
- Data source: daily_final.json (lineup-confirmed, highest priority) or daily_base.json fallback
- Model: SALCI v4 Pure Strikeout Engine (Stuff 52%, Matchup 30%, Workload 10%, Location 8%)
- S-grade tier: 80+ SALCI = true ace K ceiling
- Lineup status is already in each pitcher dict (lineup_confirmed boolean)
- You will be called from social_content_tab.py (or mlb_salci_full.py) with the exact filtered_pitchers list that powers the Pitcher Cards view.

## OBJECTIVE
Generate exactly three things:
1. One data-heavy tweet for EACH pitcher in filtered_pitchers
2. One data-heavy summary tweet for the FULL slate
3. The top 3 storylines across the entire slate

All outputs must be analytical, repeatable, and credibility-first. No hype, no gambling slang.

## CORE RULES
1. Prioritize calibrated data: model_prob > lines dict > salci
2. Always show Model Probability, Market Implied Probability, and Edge
3. Negative edge → explicitly state the market is overpriced
4. Tone: disciplined quantitative analyst only
5. Structure is non-negotiable — use the exact formats below

## OUTPUT REQUIREMENTS

### A. MATCHUP POST (one per pitcher)
Format exactly:

📊 MODEL BREAKDOWN

🎯 {pitcher} vs {opponent}
K Line: {k_line} | Odds: {odds}

Model Probability: {probability}%
Market Implied: {implied_prob}%
Edge: {+/-X.X%}

Key Signal:
• {single strongest data-driven insight — one bullet only}

Constraints:
- Max 280 characters (ideally < 260)
- Only emojis allowed: 📊 and 🎯
- One key insight only

### B. SLATE SUMMARY POST
Format exactly:

📊 TOP MODEL EDGES — K PROPS (SALCI v6.0)

1. {pitcher} — {k_line} Ks ({odds})
   Model: {prob}% | Edge: {+X.X%}

2. ...

- Include only the top 4 positive edges (ranked strictly by edge size)
- If fewer than 4 positive edges, show only what exists
- End with: "Only +EV spots. Model-driven. SALCI v6.0"

### C. STORYLINES (Top 3)
Format exactly:
1. {Short headline}
   → {one-sentence data-backed explanation}

## ANALYTICAL LOGIC (MANDATORY)
Implied Probability:
- Positive odds: 100 / (odds + 100)
- Negative odds: |odds| / (|odds| + 100)

Edge = model_prob - implied_probability

Signal Strength:
- Edge ≥ +8.0% → Strong
- Edge +4.0% to +7.9% → Moderate
- Edge < +4.0% → Weak / deprioritize
- Negative edge → flag as overpriced

## FAILURE HANDLING
- Missing data → omit cleanly, never fabricate
- No positive edges → slate_post should read: "No +EV edges identified on current slate."
- Never exaggerate confidence

## FINAL OUTPUT FORMAT
Return valid JSON only:

{
  "matchup_posts": ["full tweet string 1", "full tweet string 2", ...],
  "slate_post": "full slate summary tweet string",
  "storylines": ["1. Headline\\n   → Explanation", "2. ...", "3. ..."]
}

No extra text outside the JSON. No markdown fences."""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_content_prompt(filtered_pitchers: list[dict]) -> tuple[str, str]:
    """
    Build (system_prompt, user_message) ready for the Anthropic API.

    Enriches each pitcher dict with pre-computed implied_prob and edge
    so the model doesn't have to do arithmetic.
    """
    enriched = []
    for p in filtered_pitchers:
        item = dict(p)  # shallow copy — don't mutate original
        odds = item.get("odds")
        mp = resolve_model_prob(item)

        if mp is not None:
            item["_model_prob_resolved"] = round(mp * 100, 1)
            if odds is not None:
                item["_implied_prob_pct"] = round(implied_prob(odds) * 100, 1)
                item["_edge_pct"] = round(edge_pct(mp, odds), 1)
            else:
                item["_implied_prob_pct"] = None
                item["_edge_pct"] = None
        else:
            item["_model_prob_resolved"] = None
            item["_implied_prob_pct"] = None
            item["_edge_pct"] = None

        enriched.append(item)

    today = __import__("datetime").date.today().isoformat()
    user_msg = (
        f"Date: {today}\n"
        f"Pitcher count: {len(enriched)}\n\n"
        f"filtered_pitchers = {json.dumps(enriched, default=str)}"
    )
    return _SYSTEM_PROMPT, user_msg


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_content_response(raw: str) -> dict | None:
    """
    Safely parse the model's JSON response.

    Strips ```json ... ``` fences if present.
    Returns None on any parse failure.
    """
    if not raw:
        return None
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        data = json.loads(cleaned)
        # Validate required keys
        if not isinstance(data, dict):
            return None
        if "matchup_posts" not in data or "slate_post" not in data:
            return None
        return data
    except json.JSONDecodeError:
        # Try extracting first {...} block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Local (no-API) fallback formatters
# ---------------------------------------------------------------------------

def format_matchup_post(p: dict) -> str:
    """
    Build a single matchup tweet locally (no API).
    Used as fallback when API is unavailable.
    """
    odds = p.get("odds")
    k_line = p.get("k_line") or p.get("best_line") or "—"
    mp = resolve_model_prob(p)

    mp_pct_str = f"{mp * 100:.1f}%" if mp is not None else "N/A"
    impl_str = f"{implied_prob(odds) * 100:.1f}%" if odds is not None else "N/A"
    edge_val = edge_pct(mp, odds) if (mp is not None and odds is not None) else None
    edge_str = f"{edge_val:+.1f}%" if edge_val is not None else "N/A"

    # Key signal logic — priority: negative edge > grade > stuff > projection > lineup
    signal_parts = []
    salci = p.get("salci", 0)
    grade = p.get("salci_grade", "")
    expected = p.get("expected")
    stuff = p.get("stuff_score")
    lineup = p.get("lineup_confirmed", False)

    if edge_val is not None and edge_val < -5.0:
        signal_parts.append(f"Market overpriced ({edge_val:.1f}% negative edge)")
    elif grade == "S":
        signal_parts.append(f"S-grade ace ({salci:.0f} SALCI)")
    elif stuff and stuff >= 115:
        signal_parts.append(f"Elite Stuff ({stuff:.0f})")

    if expected and k_line and k_line != "—":
        try:
            diff = expected - float(k_line)
            if diff >= 0.5:
                signal_parts.append(f"Projects {expected:.1f} Ks vs {k_line} line")
        except (ValueError, TypeError):
            pass

    # Only highlight lineup confirmation when it's a positive signal
    if lineup and (edge_val is None or edge_val >= 0):
        signal_parts.append("Lineup confirmed")

    key_signal = signal_parts[0] if signal_parts else f"SALCI {salci:.0f} ({grade}-grade)"

    post = (
        f"📊 MODEL BREAKDOWN\n\n"
        f"🎯 {p.get('pitcher', 'Unknown')} vs {p.get('opponent', 'Unknown')}\n"
        f"K Line: {k_line} | Odds: {odds if odds else '—'}\n\n"
        f"Model Probability: {mp_pct_str}\n"
        f"Market Implied: {impl_str}\n"
        f"Edge: {edge_str}\n\n"
        f"Key Signal:\n• {key_signal}"
    )
    return post


def format_slate_post(filtered_pitchers: list[dict]) -> str:
    """
    Build the slate summary tweet locally (no API).
    Shows top 4 positive-edge pitchers ranked by edge size.
    """
    edges = []
    for p in filtered_pitchers:
        odds = p.get("odds")
        mp = resolve_model_prob(p)
        if mp is None or odds is None:
            continue
        ev = edge_pct(mp, odds)
        if ev > 0:
            edges.append({
                "pitcher": p.get("pitcher", "Unknown"),
                "k_line": p.get("k_line") or p.get("best_line") or "—",
                "odds": odds,
                "model_prob_pct": round(mp * 100, 1),
                "edge": round(ev, 1),
            })

    edges.sort(key=lambda x: x["edge"], reverse=True)
    top = edges[:4]

    header = "📊 TOP MODEL EDGES — K PROPS (SALCI v6.0)\n\n"
    if not top:
        return header + "No +EV edges identified on current slate.\n\nOnly +EV spots. Model-driven. SALCI v6.0"

    lines = []
    for i, e in enumerate(top, 1):
        lines.append(
            f"{i}. {e['pitcher']} — {e['k_line']} Ks ({e['odds']:+d})\n"
            f"   Model: {e['model_prob_pct']}% | Edge: {e['edge']:+.1f}%"
        )
    return header + "\n\n".join(lines) + "\n\nOnly +EV spots. Model-driven. SALCI v6.0"


def derive_storylines(filtered_pitchers: list[dict]) -> list[str]:
    """
    Heuristic storyline generator (no API).
    Identifies the 3 most analytically interesting narratives.
    """
    storylines = []

    # 1 — S-grade cluster
    s_grade = [p for p in filtered_pitchers if p.get("salci_grade") == "S" or (p.get("salci", 0) >= 80)]
    if len(s_grade) >= 2:
        names = " & ".join(p["pitcher"].split()[-1] for p in s_grade[:2])
        storylines.append(
            f"S-Grade Ace Cluster ({len(s_grade)} pitchers ≥80 SALCI)\n"
            f"   → {names} headline a rare multi-ace slate where SALCI projects 9+ Ks for each."
        )

    # 2 — Lineup-confirmed positive edges
    confirmed_pos = [
        p for p in filtered_pitchers
        if p.get("lineup_confirmed")
        and p.get("odds") is not None
        and resolve_model_prob(p) is not None
        and edge_pct(resolve_model_prob(p), p["odds"]) >= 4.0
    ]
    if confirmed_pos:
        best = max(confirmed_pos, key=lambda p: edge_pct(resolve_model_prob(p), p["odds"]))
        ev = edge_pct(resolve_model_prob(best), best["odds"])
        storylines.append(
            f"Lineup-Locked +EV Spot — {best['pitcher']}\n"
            f"   → Lineup confirmed adds precision: model shows {ev:+.1f}% edge vs market on {best.get('k_line','?')} K line."
        )

    # 3 — Stuff-dominant slate or heavy negative-edge warning
    stuff_elite = [p for p in filtered_pitchers if (p.get("stuff_score") or 0) >= 115]
    negative_edge = [
        p for p in filtered_pitchers
        if p.get("odds") is not None
        and resolve_model_prob(p) is not None
        and edge_pct(resolve_model_prob(p), p["odds"]) < -5.0
    ]

    if stuff_elite and len(storylines) < 3:
        names = ", ".join(p["pitcher"].split()[-1] for p in stuff_elite[:3])
        storylines.append(
            f"Stuff-Dominant Slate\n"
            f"   → {len(stuff_elite)} pitcher{'s' if len(stuff_elite) > 1 else ''} ({names}) register Stuff+ ≥115 — raw velocity and arsenal quality is the primary K driver today."
        )
    elif negative_edge and len(storylines) < 3:
        worst = min(negative_edge, key=lambda p: edge_pct(resolve_model_prob(p), p["odds"]))
        ev = edge_pct(resolve_model_prob(worst), worst["odds"])
        storylines.append(
            f"Overpriced Market Alert — {worst['pitcher']}\n"
            f"   → Model shows {ev:.1f}% negative edge on {worst.get('k_line','?')} K line — market pricing exceeds SALCI v6.0 projection."
        )

    # Pad to 3 if needed
    avg_proj = (
        sum(p.get("expected", 0) for p in filtered_pitchers) / len(filtered_pitchers)
        if filtered_pitchers else 0
    )
    while len(storylines) < 3:
        storylines.append(
            f"Slate Overview — {len(filtered_pitchers)} Pitchers\n"
            f"   → Average SALCI projection of {avg_proj:.1f} Ks/start across today's eligible slate."
        )

    # Apply numbered prefixes now that the list is final
    storylines = [f"{i+1}. {s}" for i, s in enumerate(storylines)]

    return storylines[:3]


# ---------------------------------------------------------------------------
# Convenience: enrich pitcher list with derived odds fields
# ---------------------------------------------------------------------------

def enrich_pitchers(pitchers: list[dict]) -> list[dict]:
    """
    Add _model_prob_resolved, _implied_prob_pct, _edge_pct to each pitcher dict.
    Returns a NEW list — originals are not mutated.
    """
    result = []
    for p in pitchers:
        item = dict(p)
        odds = item.get("odds")
        mp = resolve_model_prob(item)
        item["_model_prob_resolved"] = round(mp * 100, 1) if mp is not None else None
        item["_implied_prob_pct"] = round(implied_prob(odds) * 100, 1) if odds is not None else None
        item["_edge_pct"] = round(edge_pct(mp, odds), 1) if (mp is not None and odds is not None) else None
        result.append(item)
    return result


if __name__ == "__main__":
    # Quick smoke test
    demo = [
        {
            "pitcher": "Corbin Burnes",
            "opponent": "NYY",
            "team": "BAL",
            "salci": 83.2,
            "salci_grade": "S",
            "expected": 7.8,
            "k_line": "6.5",
            "odds": -130,
            "model_prob": 0.72,
            "edge": 7.4,
            "lines": {"6": 78, "7": 55, "8": 32},
            "stuff_score": 118,
            "matchup_score": 64,
            "workload_score": 58,
            "location_score": 102,
            "lineup_confirmed": True,
            "game_pk": 12345,
            "is_statcast": True,
        },
        {
            "pitcher": "Zack Wheeler",
            "opponent": "MIA",
            "team": "PHI",
            "salci": 71.5,
            "salci_grade": "A",
            "expected": 6.4,
            "k_line": "5.5",
            "odds": 110,
            "model_prob": 0.61,
            "edge": 2.3,
            "lines": {"5": 72, "6": 48, "7": 24},
            "stuff_score": 109,
            "matchup_score": 55,
            "workload_score": 61,
            "location_score": 98,
            "lineup_confirmed": False,
            "game_pk": 12346,
            "is_statcast": True,
        },
    ]

    print("=== MATCHUP POST ===")
    print(format_matchup_post(demo[0]))
    print()
    print("=== SLATE SUMMARY ===")
    print(format_slate_post(demo))
    print()
    print("=== STORYLINES ===")
    for s in derive_storylines(demo):
        print(s)
        print()
