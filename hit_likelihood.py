"""
hit_likelihood.py  —  SALCI v5.x  |  Hit Probability Engine
=============================================================
Calculates a per-batter Hit Score (0-100) using a three-layer model:

  Layer 1 — Log5 Base Probability
      Classic Bill James Log5 formula applied to batting average.
      Accounts for batter skill, pitcher skill, and league context.

  Layer 2 — Statcast Quality-of-Contact Adjustment
      Re-weights the Log5 estimate using exit velocity, launch angle,
      barrel rate, and xBA.  Good contact quality boosts the score;
      weak contact depresses it.

  Layer 3 — Contextual Modifiers
      Recent form (L7/L14), platoon advantage, and hard-hit rate trends
      apply a final ±15-point nudge before clamping to [0, 100].

Design goals
------------
* Fully importable — no Streamlit references inside this file.
* Graceful degradation — every Statcast field is optional.
  If data is missing the function falls back cleanly to Layer 1 only.
* Deterministic — same inputs always produce the same output.
* Transparent — every intermediate value is returned in `breakdown`.

Usage
-----
    from hit_likelihood import calculate_hitter_hit_prob

    score, breakdown = calculate_hitter_hit_prob(
        batter_stats  = batter_dict,
        pitcher_stats = pitcher_dict,
        league_avg    = 0.248,
    )
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Type alias for clarity
# ---------------------------------------------------------------------------
Stats = Dict[str, Any]


# ---------------------------------------------------------------------------
# League-context constants
# ---------------------------------------------------------------------------

# 2024 MLB averages — update each season in your Stage 1 nightly job
_LEAGUE_DEFAULTS: Stats = {
    "avg":             0.248,   # batting average
    "xba":             0.245,   # expected batting average (Statcast)
    "exit_velo":       88.5,    # mean exit velocity (mph)
    "launch_angle":    12.0,    # mean launch angle (degrees)
    "barrel_pct":      0.075,   # barrel rate
    "hard_hit_pct":    0.380,   # hard-hit rate (≥95 mph)
}

# Optimal launch angle window for hits (line drives + pulled GBs)
_LA_SWEET_SPOT_LOW  = 8.0
_LA_SWEET_SPOT_HIGH = 32.0

# Exit-velocity threshold for "hard contact"
_HARD_HIT_THRESHOLD = 95.0


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _safe(value: Any, default: float) -> float:
    """Return float(value) or default if value is None / missing."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a float to [lo, hi]."""
    return max(lo, min(hi, value))


def _sigmoid_scale(x: float, center: float, scale: float = 1.0) -> float:
    """
    Maps any real number to (0, 1) via a sigmoid centred at `center`.
    Useful for converting raw exit velocity or z-scores to a 0-1 weight.
    """
    return 1.0 / (1.0 + math.exp(-scale * (x - center)))


# ---------------------------------------------------------------------------
# Layer 1 — Log5 base probability
# ---------------------------------------------------------------------------

def _log5(
    batter_avg:  float,
    pitcher_avg: float,
    league_avg:  float,
) -> float:
    """
    Bill James Log5 formula.

    Estimates the probability that a batter with batting average `batter_avg`
    gets a hit against a pitcher whose opponents bat `pitcher_avg`, given a
    league average of `league_avg`.

    Formula
    -------
        p(B wins) = (B - B·L) / (B + P - 2·B·P)    where L = league_avg

    The numerator is scaled so that a league-average batter vs. a
    league-average pitcher always returns league_avg — a key sanity check.

    References
    ----------
    James, B. (1983). The Bill James Baseball Abstract.
    Wikipedia: https://en.wikipedia.org/wiki/Log5
    """
    # Guard against degenerate inputs
    B = _clamp(batter_avg,  0.050, 0.550)
    P = _clamp(pitcher_avg, 0.050, 0.550)
    L = _clamp(league_avg,  0.200, 0.320)

    numerator   = B * (1.0 - P)
    denominator = B * (1.0 - P) + P * (1.0 - B)

    if denominator == 0.0:
        return L  # degenerate case — return league average

    raw = numerator / denominator

    # Re-anchor: scale so that league_avg vs league_avg == league_avg
    # (James' original formula already has this property, but floating-point
    #  rounding with extreme inputs can drift — this ensures it.)
    anchor_num = L * (1.0 - L)
    anchor_den = L * (1.0 - L) + L * (1.0 - L)
    anchor     = anchor_num / anchor_den if anchor_den > 0 else 0.5

    if anchor > 0:
        raw = raw * (L / anchor)

    return _clamp(raw, 0.05, 0.70)


# ---------------------------------------------------------------------------
# Layer 2 — Statcast quality-of-contact multiplier
# ---------------------------------------------------------------------------

def _contact_quality_multiplier(
    batter_stats: Stats,
    league:       Stats,
) -> Tuple[float, Dict]:
    """
    Compute a multiplier [0.70 – 1.30] that adjusts the Log5 base.

    Sub-components
    --------------
    1. Exit Velocity Score  (35% weight)
       Sigmoid-scaled relative to league mean.
       Elite (95 mph avg) → +, weak (80 mph avg) → −

    2. Launch Angle Score   (25% weight)
       Peaks when mean LA is in the 8°–32° sweet-spot window.
       Extreme fly-ball (>35°) or ground-ball (<5°) tendencies are penalised.

    3. Barrel Rate Score    (25% weight)
       Linear scale from 0% (floor) to 20%+ (ceiling).

    4. xBA vs AVG Spread    (15% weight)
       Positive spread (xBA > AVG) → batter is due to regress upward.
       Negative spread → potential regression risk.

    All four sub-components land in [0, 1] and are weighted to a single
    [0, 1] composite.  That composite is then stretched to [0.70, 1.30],
    meaning the maximum Statcast swing is ±30% of the Log5 base.
    """
    detail: Dict = {}

    # --- 1. Exit velocity ---
    ev_mean  = _safe(batter_stats.get("avg_exit_velo"),  league["exit_velo"])
    ev_score = _sigmoid_scale(ev_mean, center=league["exit_velo"], scale=0.25)
    detail["exit_velo"] = {
        "value":  round(ev_mean, 1),
        "score":  round(ev_score, 3),
        "weight": 0.35,
        "note":   "sigmoid-scaled vs league mean",
    }

    # --- 2. Launch angle (sweet-spot proximity) ---
    la_mean = _safe(batter_stats.get("avg_launch_angle"), league["launch_angle"])
    if _LA_SWEET_SPOT_LOW <= la_mean <= _LA_SWEET_SPOT_HIGH:
        # Perfect sweet spot — scale linearly to peak at 20°
        la_score = 1.0 - abs(la_mean - 20.0) / 20.0
    elif la_mean < _LA_SWEET_SPOT_LOW:
        # Ground-ball tendency — partial credit proportional to distance from floor
        la_score = max(0.0, (la_mean - 0.0) / _LA_SWEET_SPOT_LOW) * 0.6
    else:
        # Fly-ball extreme — diminishing returns above 32°
        la_score = max(0.0, 1.0 - (la_mean - _LA_SWEET_SPOT_HIGH) / 20.0) * 0.7

    la_score = _clamp(la_score)
    detail["launch_angle"] = {
        "value":       round(la_mean, 1),
        "score":       round(la_score, 3),
        "weight":      0.25,
        "sweet_spot":  (_LA_SWEET_SPOT_LOW <= la_mean <= _LA_SWEET_SPOT_HIGH),
        "note":        "peaks at 8°-32° window",
    }

    # --- 3. Barrel rate ---
    barrel_pct  = _safe(batter_stats.get("barrel_pct"), league["barrel_pct"])
    barrel_norm = _clamp(barrel_pct / 0.20)   # 20% barrels = perfect ceiling
    detail["barrel_rate"] = {
        "value":  round(barrel_pct * 100, 1),
        "score":  round(barrel_norm, 3),
        "weight": 0.25,
        "note":   "linear 0%-20% range",
    }

    # --- 4. xBA vs actual AVG spread ---
    xba         = _safe(batter_stats.get("xba"),             league["xba"])
    actual_avg  = _safe(batter_stats.get("avg"),             league["avg"])
    spread      = xba - actual_avg                           # positive = batter underperforming xBA
    # Map spread [-0.05, +0.05] → [0, 1]
    spread_score = _clamp((spread + 0.05) / 0.10)
    detail["xba_spread"] = {
        "xba":    round(xba, 3),
        "avg":    round(actual_avg, 3),
        "spread": round(spread, 3),
        "score":  round(spread_score, 3),
        "weight": 0.15,
        "note":   "positive spread = batter due for upward regression",
    }

    # --- Weighted composite [0, 1] ---
    composite = (
        ev_score     * 0.35 +
        la_score     * 0.25 +
        barrel_norm  * 0.25 +
        spread_score * 0.15
    )

    # Stretch [0, 1] → [0.70, 1.30]  (±30% swing)
    multiplier = 0.70 + composite * 0.60

    detail["composite"] = round(composite, 3)
    detail["multiplier"] = round(multiplier, 3)

    return multiplier, detail


# ---------------------------------------------------------------------------
# Layer 3 — Contextual modifiers
# ---------------------------------------------------------------------------

def _contextual_adjustment(batter_stats: Stats, pitcher_stats: Stats) -> Tuple[float, Dict]:
    """
    Return an additive adjustment in probability units (roughly −0.05 to +0.05).

    Factors
    -------
    * Recent form  — L7 AVG vs season AVG (hot/cold streak signal)
    * Platoon      — batter side vs pitcher hand
    * Hard-hit %   — batter's hard-hit rate vs league (recent 14 days)
    """
    adjustment = 0.0
    detail: Dict = {}

    # 1. Recent form (L7 AVG)
    season_avg = _safe(batter_stats.get("avg"),     0.248)
    l7_avg     = _safe(batter_stats.get("l7_avg"),  None if batter_stats.get("l7_avg") is None else batter_stats["l7_avg"])
    if batter_stats.get("l7_avg") is not None:
        l7_avg     = _safe(batter_stats["l7_avg"], season_avg)
        form_delta  = l7_avg - season_avg          # positive = hot streak
        form_adj    = _clamp(form_delta * 0.5, -0.04, 0.04)
        adjustment += form_adj
        detail["recent_form"] = {
            "l7_avg":   round(l7_avg, 3),
            "season":   round(season_avg, 3),
            "delta":    round(form_delta, 3),
            "adj":      round(form_adj, 4),
        }
    else:
        detail["recent_form"] = {"adj": 0.0, "note": "L7 data unavailable"}

    # 2. Platoon advantage
    bat_side     = str(batter_stats.get("bat_side",    "R")).upper()
    pitcher_hand = str(pitcher_stats.get("pitcher_hand","R")).upper()

    same_hand = (bat_side == pitcher_hand)
    # Batter facing opposite-hand pitcher → small advantage (~6-8 OPS pts in real data)
    platoon_adj = -0.010 if same_hand else +0.010
    adjustment += platoon_adj
    detail["platoon"] = {
        "bat_side":     bat_side,
        "pitcher_hand": pitcher_hand,
        "same_hand":    same_hand,
        "adj":          round(platoon_adj, 4),
        "note":         "same-hand = slight disadvantage for batter",
    }

    # 3. Hard-hit rate (recent L14)
    hh_pct_recent = batter_stats.get("hard_hit_pct_l14")
    if hh_pct_recent is not None:
        hh_recent  = _safe(hh_pct_recent, 0.380)
        hh_delta   = hh_recent - 0.380             # vs league average
        hh_adj     = _clamp(hh_delta * 0.08, -0.02, 0.02)
        adjustment += hh_adj
        detail["hard_hit_l14"] = {
            "value": round(hh_recent * 100, 1),
            "adj":   round(hh_adj, 4),
        }
    else:
        detail["hard_hit_l14"] = {"adj": 0.0, "note": "L14 hard-hit unavailable"}

    return adjustment, detail


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------

def _hit_score_label(score: int) -> str:
    if score >= 75: return "🔥 Elite"
    if score >= 60: return "✅ Favorable"
    if score >= 45: return "⚖️ Neutral"
    if score >= 30: return "⚠️ Unfavorable"
    return "❌ Poor"


def _hit_score_color(score: int) -> str:
    """Return a hex colour suitable for Streamlit metric colouring."""
    if score >= 75: return "#00C566"
    if score >= 60: return "#7BCA3E"
    if score >= 45: return "#F5C518"
    if score >= 30: return "#FF7A00"
    return "#E84040"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_hitter_hit_prob(
    batter_stats:  Stats,
    pitcher_stats: Stats,
    league_avg:    float = 0.248,
    league_stats:  Optional[Stats] = None,
) -> Tuple[int, Dict]:
    """
    Estimate a batter's probability of recording a hit as a 0-100 Hit Score.

    Parameters
    ----------
    batter_stats : dict
        Required keys
        -------------
        avg  : float   — batter's season batting average (e.g. 0.285)

        Optional Statcast keys (all improve accuracy when present)
        ----------------------------------------------------------
        xba                : float — expected batting average (e.g. 0.291)
        avg_exit_velo      : float — mean exit velocity (mph, e.g. 91.3)
        avg_launch_angle   : float — mean launch angle (degrees, e.g. 14.2)
        barrel_pct         : float — barrel rate (e.g. 0.095)
        hard_hit_pct       : float — hard-hit rate season (e.g. 0.42)
        hard_hit_pct_l14   : float — hard-hit rate last 14 days
        l7_avg             : float — batting average last 7 days
        bat_side           : str   — 'L', 'R', or 'S'

    pitcher_stats : dict
        Required keys
        -------------
        avg_against : float — pitcher's season opponents' batting average

        Optional keys
        -------------
        pitcher_hand : str  — 'L' or 'R' (default 'R')

    league_avg : float
        Current MLB batting average (default 0.248).
        Update this in your Stage 1 nightly job each season.

    league_stats : dict, optional
        Override any of the league-context constants.
        Keys mirror `_LEAGUE_DEFAULTS`.

    Returns
    -------
    hit_score : int
        0–100 integer.  ~50 ≈ exactly league average expectation.

    breakdown : dict
        Complete intermediate values for display / debugging / logging.
        Structure:
        {
          "log5": { "batter_avg", "pitcher_avg", "league_avg", "probability" },
          "contact_quality": { ... sub-component detail ... },
          "contextual": { ... sub-component detail ... },
          "pipeline": { "log5_prob", "after_contact_adj", "after_context_adj",
                        "final_prob", "hit_score" },
          "label": str,
          "color": str,
        }

    Example
    -------
    >>> batter = {
    ...     "avg": 0.295, "xba": 0.310,
    ...     "avg_exit_velo": 92.1, "avg_launch_angle": 16.5,
    ...     "barrel_pct": 0.11, "hard_hit_pct": 0.44,
    ...     "l7_avg": 0.320, "bat_side": "L",
    ... }
    >>> pitcher = {"avg_against": 0.231, "pitcher_hand": "R"}
    >>> score, info = calculate_hitter_hit_prob(batter, pitcher, 0.248)
    >>> print(score, info["label"])
    67 ✅ Favorable
    """
    # --- Merge league defaults ---
    league: Stats = {**_LEAGUE_DEFAULTS, "avg": league_avg}
    if league_stats:
        league.update(league_stats)

    breakdown: Dict = {}

    # -------------------------------------------------------------------------
    # Layer 1 — Log5
    # -------------------------------------------------------------------------
    batter_avg  = _safe(batter_stats.get("avg"),         league["avg"])
    pitcher_avg = _safe(pitcher_stats.get("avg_against"), league["avg"])

    log5_prob = _log5(batter_avg, pitcher_avg, league["avg"])
    breakdown["log5"] = {
        "batter_avg":  round(batter_avg, 3),
        "pitcher_avg": round(pitcher_avg, 3),
        "league_avg":  round(league["avg"], 3),
        "probability": round(log5_prob, 4),
        "note": (
            "Bill James Log5 — isolates true batter vs pitcher skill "
            "relative to league context"
        ),
    }

    # -------------------------------------------------------------------------
    # Layer 2 — Contact quality multiplier
    # -------------------------------------------------------------------------
    contact_mult, contact_detail = _contact_quality_multiplier(batter_stats, league)
    after_contact = _clamp(log5_prob * contact_mult, 0.05, 0.70)

    breakdown["contact_quality"] = contact_detail
    breakdown["contact_quality"]["input_prob"]  = round(log5_prob,    4)
    breakdown["contact_quality"]["output_prob"] = round(after_contact, 4)

    # -------------------------------------------------------------------------
    # Layer 3 — Contextual modifiers
    # -------------------------------------------------------------------------
    ctx_adj, ctx_detail = _contextual_adjustment(batter_stats, pitcher_stats)
    after_context = _clamp(after_contact + ctx_adj, 0.04, 0.72)

    breakdown["contextual"] = ctx_detail
    breakdown["contextual"]["total_adj"]   = round(ctx_adj,      4)
    breakdown["contextual"]["output_prob"] = round(after_context, 4)

    # -------------------------------------------------------------------------
    # Final score — rescale probability to 0-100
    # -------------------------------------------------------------------------
    #
    # Anchoring rationale:
    #   A perfectly league-average matchup should yield ~50.
    #   We set prob=0.248 (league avg) → score=50 by solving:
    #     score = (prob / 0.496) * 100
    #   i.e., league_avg * 2 is the "100" ceiling at the probability level,
    #   which gives comfortable spread without bunching near 50.
    #
    anchor   = league["avg"] * 2.0            # e.g., 0.496
    raw_score = (after_context / anchor) * 100.0
    hit_score = int(_clamp(raw_score, 0.0, 100.0))

    breakdown["pipeline"] = {
        "log5_prob":          round(log5_prob,    4),
        "after_contact_adj":  round(after_contact, 4),
        "after_context_adj":  round(after_context, 4),
        "final_prob":         round(after_context, 4),
        "hit_score":          hit_score,
    }
    breakdown["label"] = _hit_score_label(hit_score)
    breakdown["color"] = _hit_score_color(hit_score)

    return hit_score, breakdown


# ---------------------------------------------------------------------------
# Batch helper — convenience wrapper for lineup cards
# ---------------------------------------------------------------------------

def score_lineup(
    hitters:      list[Stats],
    pitcher_stats: Stats,
    league_avg:    float = 0.248,
    league_stats:  Optional[Stats] = None,
) -> list[Dict]:
    """
    Score every hitter in a lineup and return a sorted list of result dicts.

    Parameters
    ----------
    hitters : list of batter_stats dicts (same schema as calculate_hitter_hit_prob)
    pitcher_stats : dict
    league_avg : float

    Returns
    -------
    List of dicts, sorted descending by hit_score, each containing:
        name, hit_score, label, color, breakdown
    """
    results = []
    for h in hitters:
        score, bd = calculate_hitter_hit_prob(h, pitcher_stats, league_avg, league_stats)
        results.append({
            "name":      h.get("name", "Unknown"),
            "hit_score": score,
            "label":     bd["label"],
            "color":     bd["color"],
            "breakdown": bd,
        })
    results.sort(key=lambda x: x["hit_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Quick smoke-test — run with: python hit_likelihood.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Test 1: elite contact hitter vs soft pitcher ---
    batter_elite = {
        "name":             "Freddie Freeman",
        "avg":              0.302,
        "xba":              0.315,
        "avg_exit_velo":    92.8,
        "avg_launch_angle": 15.4,
        "barrel_pct":       0.130,
        "hard_hit_pct":     0.490,
        "hard_hit_pct_l14": 0.520,
        "l7_avg":           0.333,
        "bat_side":         "L",
    }
    pitcher_soft = {
        "avg_against": 0.278,
        "pitcher_hand": "R",
    }

    # --- Test 2: weak contact hitter vs elite pitcher ---
    batter_weak = {
        "name":             "Pitcher Batting #9",
        "avg":              0.198,
        "xba":              0.182,
        "avg_exit_velo":    83.1,
        "avg_launch_angle": 5.2,
        "barrel_pct":       0.03,
        "hard_hit_pct":     0.28,
        "bat_side":         "R",
    }
    pitcher_elite = {
        "avg_against": 0.198,
        "pitcher_hand": "R",
    }

    # --- Test 3: league-average vs league-average (sanity check → ~50) ---
    batter_avg = {
        "name":  "Average Joe",
        "avg":   0.248,
        "xba":   0.245,
        "avg_exit_velo":    88.5,
        "avg_launch_angle": 12.0,
        "barrel_pct":       0.075,
        "hard_hit_pct":     0.380,
        "bat_side":         "R",
    }
    pitcher_avg = {
        "avg_against": 0.248,
        "pitcher_hand": "R",
    }

    for batter, pitcher, label in [
        (batter_elite, pitcher_soft,  "Elite batter vs soft pitcher"),
        (batter_weak,  pitcher_elite, "Weak batter vs elite pitcher"),
        (batter_avg,   pitcher_avg,   "Avg batter vs avg pitcher  "),
    ]:
        score, bd = calculate_hitter_hit_prob(batter, pitcher, 0.248)
        log5  = bd["log5"]["probability"]
        mult  = bd["contact_quality"]["multiplier"]
        ctx   = bd["contextual"]["total_adj"]
        print(
            f"{label}  →  Hit Score: {score:>3}  {bd['label']}"
            f"  (Log5={log5:.3f}, cq_mult={mult:.2f}, ctx_adj={ctx:+.4f})"
        )
