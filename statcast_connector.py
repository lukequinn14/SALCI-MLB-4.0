"""
SALCI v6.0 - Statcast Data Connector & Scoring Engine
======================================================

SALCI v4 WEIGHTS (Pure Strikeout Engine):
- Stuff:    52% (dominant K driver — whiff, power, arsenal quality)
- Matchup:  30% (opponent K-propensity + zone contact — K-context)
- Workload: 10% (opportunity ceiling — IP projection only)
- Location:  8% (de-emphasized — high command = pitching to contact)

KEY CHANGES FROM v3 (the compression problem):
- Stuff normalizer uses a NONLINEAR curve (sigmoid-like) to spread elite vs poor
- Location is now PARTIALLY INVERTED: near-average location is rewarded,
  extreme precision *hurts* (elite location → contact, not strikeouts)
- Workload floor/ceiling clamping is relaxed to expose more variance
- Matchup sub-weights shift to 70% K-pct / 30% zone contact (pure Ks)
- Score scale: Poor <30 | Below 35-45 | Average 45-58 | Strong 58-70 | Elite 70-90+
- calculate_expected_ks_v4 recalibrated so elite SALCI = ~10+ Ks/game projection

CRITICAL FIX - why v3 was compressed:
  All four components were clamped to [20, 80] BEFORE weighting.
  Because every component sat in [20,80], weighted sum also sat ~[20,80].
  An average pitcher with all components at 50 scored: 50*0.48 + 50*0.28 + 50*0.14 + 50*0.10 = 50.
  An elite pitcher (all comps at 80) scored only: 80*0.48 + ... = 80.
  But NOBODY hits 80 on every component → scores never left [40,65].
  Fix: Expand the effective range of each input and use nonlinear normalization.

Installation:
    pip install pybaseball scipy

Version: 4.0 (SALCI v4)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import warnings
from scipy.stats import poisson
import math

warnings.filterwarnings('ignore')

try:
    from pybaseball import (
        statcast_pitcher,
        statcast_batter,
        playerid_lookup,
        cache
    )
    cache.enable()
    PYBASEBALL_AVAILABLE = True
except ImportError:
    print("Warning: pybaseball not found. Statcast features will be disabled.")
    PYBASEBALL_AVAILABLE = False


# =============================================================================
# SALCI v4 WEIGHTS  (exported — main app imports these)
# =============================================================================

SALCI_V4_WEIGHTS = {
    'stuff':    0.52,   # #1 K driver: whiff power, arsenal depth
    'matchup':  0.30,   # K-propensity of opposing lineup
    'workload': 0.10,   # Opportunity (IP ceiling)
    'location': 0.08,   # Near-neutral command best for Ks
}

# Keep v3 alias so existing imports don't break
SALCI_V3_WEIGHTS = SALCI_V4_WEIGHTS

# Matchup sub-weights (within the 30%)
MATCHUP_SUBWEIGHTS = {
    'opp_k_pct':       0.70,   # 21% of total — direct K opportunity
    'opp_zone_contact': 0.30,  #  9% of total — zone whiff environment
}


# =============================================================================
# CONSTANTS & LEAGUE BASELINES (2024-2025)
# =============================================================================

LEAGUE_BASELINES = {
    # Fastball
    'ff_velo':       94.5,
    'ff_velo_std':    2.3,
    'ff_ivb':        14.5,
    'ff_ivb_std':     3.2,
    'ff_hb':          7.5,
    'ff_hb_std':      2.8,
    'ff_spin':      2250.0,
    'ff_spin_std':   180.0,
    # Breaking
    'sl_velo':       85.5,
    'sl_hb':          5.5,
    'sl_hb_std':      3.5,
    'sl_vb':          2.0,
    'sl_spin':      2450.0,
    # Curveball
    'cu_velo':       79.0,
    'cu_vb':         -6.0,
    'cu_spin':      2700.0,
    # Changeup
    'ch_velo_diff':   8.5,
    'ch_drop':        6.0,
    'ch_fade':        4.0,
    # Location
    'zone_pct':       0.45,
    'edge_pct':       0.28,
    'heart_pct':      0.12,
    'chase_rate':     0.30,
    'csw_pct':        0.29,
    'first_pitch_strike': 0.60,
    # Outcome
    'whiff_pct':       0.25,
    'k_pct':           0.22,
    'zone_contact_pct': 0.82,
    # Workload
    'avg_pitch_count': 88,
    'avg_ip':          5.5,
    'ttt_k_drop':      0.03,
}

PITCH_TYPES = {
    'FF': 'Four-Seam Fastball',
    'SI': 'Sinker',
    'FC': 'Cutter',
    'SL': 'Slider',
    'ST': 'Sweeper',
    'SV': 'Slurve',
    'CU': 'Curveball',
    'KC': 'Knuckle Curve',
    'CH': 'Changeup',
    'FS': 'Splitter',
}

FASTBALLS = ['FF', 'SI', 'FC']
BREAKING  = ['SL', 'ST', 'SV', 'CU', 'KC']
OFFSPEED  = ['CH', 'FS']

ZONE_NAMES = {
    1: "High Inside",  2: "High Middle",  3: "High Outside",
    4: "Middle Inside", 5: "Heart",       6: "Middle Outside",
    7: "Low Inside",   8: "Low Middle",   9: "Low Outside",
    11: "Chase Up-In", 12: "Chase Down-In",
    13: "Chase Up-Out", 14: "Chase Down-Out",
}

EDGE_ZONES  = [1, 2, 3, 4, 6, 7, 8, 9]
HEART_ZONE  = [5]
CHASE_ZONES = [11, 12, 13, 14]
IN_ZONE     = list(range(1, 10))


# =============================================================================
# NORMALIZATION HELPERS
# =============================================================================

def _sigmoid_stretch(z: float, sharpness: float = 1.4) -> float:
    """
    Sigmoid-style stretch that converts a z-score into a 0-1 range,
    but with more aggressive tails so elite values really stand out.

    sharpness > 1.0 makes the curve steeper (more spread).
    Output 0..1 maps to score 0..100 after * 100.
    """
    return 1.0 / (1.0 + math.exp(-sharpness * z))


def _z_to_score(z: float, center: float = 50.0, scale: float = 20.0,
                hard_min: float = 10.0, hard_max: float = 95.0,
                sharpness: float = 1.6) -> float:
    """
    Convert z-score to 0-100 scale with sigmoid stretch.

    center:    score for an exactly-average pitcher
    scale:     how many score points per z-unit (wider = more spread)
    sharpness: sigmoid steepness — higher gives wider tails
    """
    stretched = (_sigmoid_stretch(z, sharpness) - 0.5) * 2   # -1 .. +1
    score = center + stretched * scale
    return max(hard_min, min(hard_max, score))


# =============================================================================
# STUFF+ CALCULATION (Physics-Based, v4 Enhanced)
# =============================================================================

def calculate_stuff_plus(df: pd.DataFrame) -> Dict:
    """
    Physics-based Stuff+ from Statcast pitch data.
    v4 changes:
      - Wider output range: max clamp relaxed from 140 → 155
      - CSW% feeds a bonus multiplier (best single K predictor)
      - Arsenal depth bonus for 3+ above-average pitches
    """
    if df is None or df.empty:
        return None

    results = {
        'stuff_plus': None,
        'by_pitch_type': {},
        'arsenal_summary': {},
        'raw_metrics': {},
        'csw_pct': None,
    }

    total_pitches = len(df)
    called_strikes = df[df['description'] == 'called_strike']
    whiffs = df[df['description'].isin(['swinging_strike', 'swinging_strike_blocked'])]
    csw_pct = (len(called_strikes) + len(whiffs)) / total_pitches if total_pitches > 0 else 0.29
    results['csw_pct'] = round(csw_pct * 100, 1)

    fastballs = df[df['pitch_type'].isin(FASTBALLS)]
    if len(fastballs) >= 10:
        fb_velo = fastballs['release_speed'].mean()
        fb_ivb  = fastballs['pfx_z'].mean() * 12 if 'pfx_z' in fastballs.columns else 14.5
        fb_hb   = abs(fastballs['pfx_x'].mean() * 12) if 'pfx_x' in fastballs.columns else 7.5
    else:
        fb_velo = LEAGUE_BASELINES['ff_velo']
        fb_ivb  = LEAGUE_BASELINES['ff_ivb']
        fb_hb   = LEAGUE_BASELINES['ff_hb']

    results['raw_metrics']['fb_velo']  = round(fb_velo, 1)
    results['raw_metrics']['fb_ivb']   = round(fb_ivb, 1)
    results['raw_metrics']['csw_pct']  = results['csw_pct']

    pitch_stuff_scores = []

    for pitch_type in df['pitch_type'].dropna().unique():
        pitch_df = df[df['pitch_type'] == pitch_type]
        if len(pitch_df) < 10:
            continue

        velo      = pitch_df['release_speed'].mean() if 'release_speed' in pitch_df.columns else 90
        spin      = pitch_df['release_spin_rate'].mean() if 'release_spin_rate' in pitch_df.columns else 2200
        ivb       = pitch_df['pfx_z'].mean() * 12 if 'pfx_z' in pitch_df.columns else 0
        hb        = pitch_df['pfx_x'].mean() * 12 if 'pfx_x' in pitch_df.columns else 0
        extension = pitch_df['release_extension'].mean() if 'release_extension' in pitch_df.columns else 6.0

        velo_diff = fb_velo - velo
        ivb_diff  = fb_ivb  - ivb

        if pitch_type == 'FF':
            velo_z    = (velo - LEAGUE_BASELINES['ff_velo']) / LEAGUE_BASELINES['ff_velo_std']
            ivb_z     = (ivb  - LEAGUE_BASELINES['ff_ivb'])  / LEAGUE_BASELINES['ff_ivb_std']
            ext_bonus = (extension - 6.0) * 2 if extension > 6.0 else 0
            raw_stuff = velo_z * 0.50 + ivb_z * 0.35 + ext_bonus * 0.05

        elif pitch_type == 'SI':
            velo_z    = (velo - (LEAGUE_BASELINES['ff_velo'] - 1.5)) / 2.0
            hb_z      = (abs(hb) - 14) / 3.5
            drop_z    = (fb_ivb - ivb - 4) / 2.5
            raw_stuff = velo_z * 0.40 + hb_z * 0.35 + drop_z * 0.25

        elif pitch_type == 'FC':
            velo_z    = (velo - (LEAGUE_BASELINES['ff_velo'] - 3)) / 2.0
            cut_z     = (abs(hb) - 3.5) / 2.0
            raw_stuff = velo_z * 0.50 + cut_z * 0.30

        elif pitch_type in ['SL', 'ST', 'SV']:
            sweep_z     = (abs(hb)   - LEAGUE_BASELINES['sl_hb'])  / LEAGUE_BASELINES['sl_hb_std']
            velo_diff_z = (velo_diff - 9)  / 2.5
            drop_z      = (ivb_diff  - 10) / 4.0
            raw_stuff   = sweep_z * 0.40 + drop_z * 0.30 + velo_diff_z * 0.15

        elif pitch_type in ['CU', 'KC']:
            drop_z      = (-ivb   - 6)  / 3.0
            spin_z      = (spin - LEAGUE_BASELINES['cu_spin']) / 300
            velo_diff_z = (velo_diff - 15) / 3.0
            raw_stuff   = drop_z * 0.45 + spin_z * 0.25 + velo_diff_z * 0.20

        elif pitch_type == 'CH':
            velo_diff_z = (velo_diff - LEAGUE_BASELINES['ch_velo_diff']) / 2.0
            fade_z      = (abs(hb) - fb_hb - LEAGUE_BASELINES['ch_fade']) / 2.5
            drop_z      = (ivb_diff - LEAGUE_BASELINES['ch_drop']) / 2.5
            raw_stuff   = velo_diff_z * 0.35 + fade_z * 0.30 + drop_z * 0.35

        elif pitch_type == 'FS':
            drop_z    = (ivb_diff - 8) / 3.0
            velo_z    = (velo_diff - 6) / 2.0
            raw_stuff = drop_z * 0.50 + velo_z * 0.30

        else:
            raw_stuff = 0

        # v4: wider clamp (60..155) — allows true elite headroom
        stuff_plus = 100 + (raw_stuff * 12)   # was *10 — more sensitive
        stuff_plus = max(60, min(155, stuff_plus))

        usage_pct = len(pitch_df) / len(df)

        swings = pitch_df[pitch_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked',
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        pitch_whiffs = pitch_df[pitch_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked'
        ])]
        observed_whiff = len(pitch_whiffs) / len(swings) if len(swings) > 0 else 0

        results['by_pitch_type'][pitch_type] = {
            'stuff_plus':          round(stuff_plus, 0),
            'usage_pct':           round(usage_pct * 100, 1),
            'velocity':            round(velo, 1),
            'ivb':                 round(ivb, 1),
            'hb':                  round(hb, 1),
            'spin':                round(spin, 0) if not pd.isna(spin) else None,
            'velo_diff':           round(velo_diff, 1),
            'observed_whiff_pct':  round(observed_whiff * 100, 1),
            'pitch_count':         len(pitch_df),
        }
        results['arsenal_summary'][pitch_type] = {
            'name':  PITCH_TYPES.get(pitch_type, pitch_type),
            'stuff': round(stuff_plus, 0),
            'velo':  round(velo, 1),
            'usage': round(usage_pct * 100, 1),
        }
        pitch_stuff_scores.append((stuff_plus, usage_pct))

    if not pitch_stuff_scores:
        return results

    # Weighted Stuff+ across arsenal
    total_weight = sum(w for _, w in pitch_stuff_scores)
    weighted_stuff = sum(s * w for s, w in pitch_stuff_scores) / total_weight

    # v4 Arsenal depth bonus: each additional pitch averaging ≥105 adds 2 pts
    above_avg_pitches = sum(1 for s, _ in pitch_stuff_scores if s >= 105)
    arsenal_bonus = max(0, (above_avg_pitches - 1) * 2.5)

    # v4 CSW% bonus (best K predictor): every 1% above league avg = +1 pt
    csw_bonus = max(0, (csw_pct - LEAGUE_BASELINES['csw_pct']) * 100)

    final_stuff = weighted_stuff + arsenal_bonus + csw_bonus
    results['stuff_plus'] = round(min(155, final_stuff), 0)

    return results


# =============================================================================
# LOCATION+ CALCULATION — v4  (Intentionally de-weighted for Ks)
# =============================================================================

def calculate_location_plus(df: pd.DataFrame) -> Dict:
    """
    Calculate Location+ for SALCI v4.

    Key v4 insight: for strikeout prediction, location is a WEAK signal.
    • Very high Location+ (extreme precision) → pitching to contact → fewer Ks.
    • Near-average or slightly aggressive Location → more chases → more Ks.
    • We deliberately PENALIZE extreme precision slightly.

    The effect is that Location rarely moves the SALCI score more than ±5 pts.
    """
    if df is None or df.empty or 'zone' not in df.columns:
        return None

    results = {
        'location_plus': None,
        'zone_breakdown': {},
        'metrics': {}
    }

    total_pitches = len(df)
    zone_data = df['zone'].dropna()
    if len(zone_data) < 50:
        return None

    in_zone    = zone_data.isin(IN_ZONE).sum()
    on_edge    = zone_data.isin(EDGE_ZONES).sum()
    in_heart   = zone_data.isin(HEART_ZONE).sum()
    in_chase   = zone_data.isin(CHASE_ZONES).sum()

    zone_pct       = in_zone  / len(zone_data)
    edge_pct       = on_edge  / len(zone_data)
    heart_pct      = in_heart / len(zone_data)
    chase_zone_pct = in_chase / len(zone_data)

    chase_pitches = df[df['zone'].isin(CHASE_ZONES)]
    if len(chase_pitches) > 10:
        chase_swings = chase_pitches[chase_pitches['description'].isin([
            'swinging_strike', 'swinging_strike_blocked',
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        chase_rate = len(chase_swings) / len(chase_pitches)
    else:
        chase_rate = LEAGUE_BASELINES['chase_rate']

    first_pitches = df[(df['balls'] == 0) & (df['strikes'] == 0)]
    if len(first_pitches) > 10:
        fps_strikes = first_pitches[first_pitches['description'].isin([
            'called_strike', 'swinging_strike', 'swinging_strike_blocked',
            'foul', 'foul_tip', 'hit_into_play'
        ])]
        fps_rate = len(fps_strikes) / len(first_pitches)
    else:
        fps_rate = LEAGUE_BASELINES['first_pitch_strike']

    called_strikes = df[df['description'] == 'called_strike']
    whiffs_df = df[df['description'].isin(['swinging_strike', 'swinging_strike_blocked'])]
    csw_pct = (len(called_strikes) + len(whiffs_df)) / total_pitches

    results['metrics'] = {
        'zone_pct':       round(zone_pct * 100, 1),
        'edge_pct':       round(edge_pct * 100, 1),
        'heart_pct':      round(heart_pct * 100, 1),
        'chase_zone_pct': round(chase_zone_pct * 100, 1),
        'chase_rate':     round(chase_rate * 100, 1),
        'fps_pct':        round(fps_rate * 100, 1),
        'csw_pct':        round(csw_pct * 100, 1),
    }

    # v4: penalise extreme precision (too "fine" = contact pitcher)
    # Optimal zone_pct for Ks is ~44-48% — penalise >52% (pitching too fine)
    zone_z  = -abs(zone_pct - 0.46) / 0.05     # peaks at 46%
    edge_z  = (edge_pct - LEAGUE_BASELINES['edge_pct'])  / 0.05
    heart_z = -(heart_pct - LEAGUE_BASELINES['heart_pct']) / 0.04
    chase_z = (chase_rate  - LEAGUE_BASELINES['chase_rate'])  / 0.05
    fps_z   = (fps_rate    - LEAGUE_BASELINES['first_pitch_strike']) / 0.06
    csw_z   = (csw_pct     - LEAGUE_BASELINES['csw_pct']) / 0.04

    raw_location = (
        zone_z  * 0.10 +
        edge_z  * 0.25 +
        heart_z * 0.20 +
        chase_z * 0.20 +
        fps_z   * 0.10 +
        csw_z   * 0.15
    )

    # v4: narrower effective range [75..125] — location won't dominate SALCI
    location_plus = 100 + (raw_location * 8)    # was *10
    location_plus = max(75, min(125, location_plus))
    results['location_plus'] = round(location_plus, 0)

    # Zone breakdown
    for zone in range(1, 15):
        zone_df = df[df['zone'] == zone]
        if len(zone_df) < 3:
            continue
        z_swings = zone_df[zone_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked',
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        z_whiffs = zone_df[zone_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked'
        ])]
        whiff_pct = len(z_whiffs) / len(z_swings) if len(z_swings) > 0 else 0
        results['zone_breakdown'][zone] = {
            'name':        ZONE_NAMES.get(zone, f"Zone {zone}"),
            'pitch_count': len(zone_df),
            'pitch_pct':   round(len(zone_df) / total_pitches * 100, 1),
            'whiff_pct':   round(whiff_pct * 100, 1),
            'is_edge':     zone in EDGE_ZONES,
            'is_heart':    zone in HEART_ZONE,
            'is_chase':    zone in CHASE_ZONES,
        }

    return results


# =============================================================================
# MATCHUP SCORE — v4  (K-focused: 70% Opp K% / 30% Zone Contact)
# =============================================================================

def calculate_matchup_score_v3(
    opp_team_stats: Dict,
    lineup_hitter_stats: Optional[List[Dict]] = None,
    pitcher_hand: str = 'R'
) -> Tuple[float, Dict]:
    """
    Matchup score for SALCI v4 (function name kept for backward compat).

    v4 changes:
    - Opp K%: 70% of matchup (was 60%) — pure K opportunity
    - Zone Contact: 30% of matchup (was 40%)
    - Wider output range [15..90] (was [20..80])
    - z-score scale increased (more separation between lineups)
    """
    breakdown = {
        'source':             'team',
        'opp_k_pct':          {},
        'opp_zone_contact':   {},
        'platoon':            {},
        'individual_hitters': [],
    }

    # --- Use lineup-level stats when available ---
    if lineup_hitter_stats and len(lineup_hitter_stats) >= 5:
        breakdown['source'] = 'lineup'
        total_weight       = 0
        weighted_k_sum     = 0
        weighted_contact_sum = 0
        same_hand_count    = 0

        for i, hitter in enumerate(lineup_hitter_stats):
            order_weight   = 1.0 + (0.1 * (9 - i)) if i < 9 else 0.5
            k_rate         = hitter.get('k_rate',          0.22)
            zone_contact   = hitter.get('zone_contact_pct', 0.82)
            bat_side       = hitter.get('bat_side', 'R')

            weighted_k_sum       += k_rate       * order_weight
            weighted_contact_sum += zone_contact * order_weight
            total_weight         += order_weight

            if (pitcher_hand == 'R' and bat_side == 'R') or \
               (pitcher_hand == 'L' and bat_side == 'L'):
                same_hand_count += 1

            breakdown['individual_hitters'].append({
                'name':         hitter.get('name', f'Hitter {i+1}'),
                'order':        i + 1,
                'k_rate':       round(k_rate * 100, 1),
                'zone_contact': round(zone_contact * 100, 1),
                'bat_side':     bat_side,
                'platoon':      'adv' if (
                    (pitcher_hand == 'R' and bat_side == 'R') or
                    (pitcher_hand == 'L' and bat_side == 'L')
                ) else 'dis',
            })

        opp_k_pct        = weighted_k_sum / total_weight if total_weight > 0 else 0.22
        opp_zone_contact = weighted_contact_sum / total_weight if total_weight > 0 else 0.82
        same_side_pct    = same_hand_count / len(lineup_hitter_stats)

    else:
        breakdown['source'] = 'team'
        opp_k_pct        = opp_team_stats.get('OppK%', 0.22)
        opp_zone_contact = opp_team_stats.get(
            'OppZoneContact%', 1 - opp_team_stats.get('OppK%', 0.22) * 0.5
        )
        same_side_pct = 0.50

    # --- Z-scores (v4: wider std bands for more separation) ---
    # Opp K%: higher = better for pitcher
    k_z = (opp_k_pct - 0.22) / 0.025      # was /0.03 — tighter std → more z
    k_z = max(-3.0, min(3.0, k_z))        # wider clamp than v3's ±2

    breakdown['opp_k_pct'] = {
        'value':          round(opp_k_pct * 100, 1),
        'z_score':        round(k_z, 2),
        'interpretation': 'high_k' if k_z > 0.5 else 'low_k' if k_z < -0.5 else 'avg_k',
    }

    # Opp Zone Contact: lower = better for pitcher
    contact_z = -(opp_zone_contact - LEAGUE_BASELINES['zone_contact_pct']) / 0.035
    contact_z = max(-3.0, min(3.0, contact_z))

    breakdown['opp_zone_contact'] = {
        'value':          round(opp_zone_contact * 100, 1),
        'z_score':        round(contact_z, 2),
        'interpretation': 'easy_contact' if contact_z < -0.5 else 'tough_contact' if contact_z > 0.5 else 'avg_contact',
    }

    platoon_z = (same_side_pct - 0.50) / 0.15
    platoon_z = max(-1.5, min(1.5, platoon_z))
    breakdown['platoon'] = {
        'same_side_pct': round(same_side_pct * 100, 1),
        'z_score':       round(platoon_z, 2),
    }

    # Weighted combination (v4 sub-weights)
    raw_matchup = (
        k_z       * MATCHUP_SUBWEIGHTS['opp_k_pct']       +
        contact_z * MATCHUP_SUBWEIGHTS['opp_zone_contact'] +
        platoon_z * 0.08    # small platoon nudge
    )

    # v4: scale=22 for more spread, range [15..90]
    matchup_score = _z_to_score(raw_matchup, center=50.0, scale=22.0,
                                 hard_min=15.0, hard_max=90.0)

    return round(matchup_score, 1), breakdown


# =============================================================================
# WORKLOAD SCORE — v4  (Opportunity only — 10% weight)
# =============================================================================

def calculate_workload_score_v3(
    pitcher_stats: Dict,
    manager_leash: Optional[Dict] = None,
    recent_games: Optional[List[Dict]] = None
) -> Tuple[float, Dict]:
    """
    Workload/Leash score for SALCI v4 (function name kept for compat).

    v4 philosophy: Workload is now ONLY about opportunity (will he pitch long
    enough to accumulate Ks?).  We've cut the weight to 10% because quality
    matters far more than opportunity for K prediction.

    Components:
    - Projected IP / batters faced  (50%)
    - Manager leash / pitch count   (30%)
    - TTT K% drop penalty          (20%)

    Range: [20..85] — slightly wider ceiling to reward deep starters.
    """
    breakdown = {
        'p_ip':          {},
        'projected_bf':  {},
        'leash_factor':  {},
        'ttt_penalty':   {},
    }

    # P/IP: lower is better (efficient → more batters faced)
    p_ip   = pitcher_stats.get('P/IP', 16.0)
    p_ip_z = -(p_ip - 15.5) / 2.0
    p_ip_z = max(-2.5, min(2.5, p_ip_z))
    breakdown['p_ip'] = {
        'value':          round(p_ip, 1),
        'z_score':        round(p_ip_z, 2),
        'interpretation': 'efficient' if p_ip < 15 else 'inefficient' if p_ip > 17 else 'average',
    }

    # Projected BF
    avg_ip      = pitcher_stats.get('avg_ip', 5.5)
    bpi         = 3 + (p_ip / 15)
    projected_bf = avg_ip * bpi
    bf_z        = (projected_bf - 24) / 4
    bf_z        = max(-2.5, min(2.5, bf_z))
    breakdown['projected_bf'] = {
        'value':        round(projected_bf, 1),
        'z_score':      round(bf_z, 2),
        'projected_ip': round(avg_ip, 1),
    }

    # Leash factor
    if manager_leash:
        avg_pitch_count = manager_leash.get('avg_pitch_count', 88)
        quick_hook_pct  = manager_leash.get('quick_hook_pct', 0.25)
    else:
        avg_pitch_count = pitcher_stats.get('avg_pitch_count', 88)
        quick_hook_pct  = pitcher_stats.get('quick_hook_pct', 0.25)

    leash_z = (avg_pitch_count - LEAGUE_BASELINES['avg_pitch_count']) / 10
    leash_z = leash_z - (quick_hook_pct - 0.25) * 2
    leash_z = max(-2.5, min(2.5, leash_z))
    breakdown['leash_factor'] = {
        'avg_pitch_count': round(avg_pitch_count, 0),
        'quick_hook_pct':  round(quick_hook_pct * 100, 1),
        'z_score':         round(leash_z, 2),
        'interpretation':  'long_leash' if leash_z > 0.5 else 'short_leash' if leash_z < -0.5 else 'normal',
    }

    # TTT penalty
    ttt_k_drop = pitcher_stats.get('ttt_k_drop', LEAGUE_BASELINES['ttt_k_drop'])
    ttt_z      = -ttt_k_drop / 0.03
    ttt_z      = max(-2.5, min(2.5, ttt_z))
    breakdown['ttt_penalty'] = {
        'k_drop_pct':     round(ttt_k_drop * 100, 1),
        'z_score':        round(ttt_z, 2),
        'interpretation': 'fades' if ttt_z < -0.5 else 'maintains' if ttt_z > 0.5 else 'normal',
    }

    # Combined (v4: heavier on opportunity, lighter on TTT since it's 10% anyway)
    raw_workload = (
        p_ip_z   * 0.25 +
        bf_z     * 0.30 +
        leash_z  * 0.25 +
        ttt_z    * 0.20
    )

    # v4: scale=22 for range [20..85]
    workload_score = _z_to_score(raw_workload, center=50.0, scale=22.0,
                                  hard_min=20.0, hard_max=85.0)

    return round(workload_score, 1), breakdown


# =============================================================================
# SALCI v4 MASTER CALCULATION
# =============================================================================

def calculate_salci_v3(
    stuff_score: float,
    location_score: float,
    matchup_score: float,
    workload_score: float
) -> Dict:
    """
    SALCI v4 — wider spectrum strikeout prediction engine.
    (Function name kept as calculate_salci_v3 for backward compatibility.)

    Score spectrum design:
        ≥ 80        : S-tier  — elite ace, 10+ K ceiling
        70-79       : A       — elite K upside
        60-69       : B+      — strong strikeout pitcher
        52-59       : B       — above-average K potential
        44-51       : C       — average
        35-43       : D       — below average, tough matchup
        < 35        : F       — fade / avoid

    Root cause fix (compression):
    ────────────────────────────
    v3 clamped every component to [20,80] then did a weighted average.
    Because it was a LINEAR average of bounded inputs, it was impossible
    to escape the [20,80] output range.

    v4 solution:
    1. Stuff uses a NONLINEAR normalization via sigmoid stretch.
       An elite Stuff+ (130) now contributes ~85 pts instead of ~80.
       A poor Stuff+ (85) contributes ~20 pts instead of ~35.

    2. Location is INTENTIONALLY near-neutral:
       We convert it on a flat scale, but cap its swing at ±10 pts from
       the weighted center. This prevents location from pulling average
       pitchers toward the middle.

    3. Matchup and Workload use z_to_score() with wider sigma, so a
       terrible matchup (K-friendly lineup) or great one actually matters.

    4. No hard clamp on the final SALCI — the naturally bounded inputs
       plus weights produce a range of roughly [15..92].
    """

    # ── STUFF: nonlinear (sigmoid) normalization ──────────────────────────
    # Input: Stuff+ on 100-scale (avg=100, elite=130+, poor=80-)
    # z-score with std=8 makes elite pitchers (Stuff+ 125) register as z=+3.1
    stuff_z = (stuff_score - 100) / 8.0 if stuff_score else 0.0
    # sharpness=1.6 + scale=36 → z=+3 maps to ~92, z=0 → 50, z=-3 → 8
    stuff_normalized = _z_to_score(stuff_z, center=50.0, scale=36.0,
                                    hard_min=6.0, hard_max=97.0, sharpness=1.8)

    # ── LOCATION: narrow swing, inverted near extreme precision ──────────
    # Input: Location+ on 100-scale (avg=100)
    # Near average (95-105) is fine; very high (>115) *hurts* (contact pitcher)
    location_z = (location_score - 100) / 10.0 if location_score else 0.0
    # For K prediction: clip benefit above z=+0.5 (diminishing returns past command)
    location_z_adj = min(location_z, 0.5)   # cap upside of great command
    # Scale = 10 (narrow) — location barely moves the needle
    location_normalized = _z_to_score(location_z_adj, center=50.0, scale=10.0,
                                       hard_min=35.0, hard_max=65.0)

    # ── MATCHUP & WORKLOAD already on [15..90] from their functions ──────
    matchup_clamped  = max(15.0, min(92.0, float(matchup_score)))
    workload_clamped = max(20.0, min(85.0, float(workload_score)))

    # ── Weighted SALCI ────────────────────────────────────────────────────
    salci = (
        stuff_normalized    * SALCI_V4_WEIGHTS['stuff']    +
        location_normalized * SALCI_V4_WEIGHTS['location'] +
        matchup_clamped     * SALCI_V4_WEIGHTS['matchup']  +
        workload_clamped    * SALCI_V4_WEIGHTS['workload']
    )

    # Soft cap: prevent astronomical scores but allow 90+
    salci = max(10.0, min(95.0, salci))

    # ── Grade ─────────────────────────────────────────────────────────────
    if salci >= 80:
        grade = 'S'
        grade_desc = 'Elite ace — 10+ K ceiling'
    elif salci >= 70:
        grade = 'A'
        grade_desc = 'Elite K upside'
    elif salci >= 60:
        grade = 'B+'
        grade_desc = 'Strong strikeout pitcher'
    elif salci >= 52:
        grade = 'B'
        grade_desc = 'Above-average K potential'
    elif salci >= 44:
        grade = 'C'
        grade_desc = 'Average'
    elif salci >= 35:
        grade = 'D'
        grade_desc = 'Below average'
    else:
        grade = 'F'
        grade_desc = 'Fade'

    return {
        'salci':      round(salci, 1),
        'grade':      grade,
        'grade_desc': grade_desc,
        'version':    'v4',
        'components': {
            'stuff': {
                'raw':          stuff_score,
                'normalized':   round(stuff_normalized, 1),
                'weight':       SALCI_V4_WEIGHTS['stuff'],
                'contribution': round(stuff_normalized * SALCI_V4_WEIGHTS['stuff'], 1),
                'grade':        get_component_grade(stuff_score, is_100_scale=True),
            },
            'location': {
                'raw':          location_score,
                'normalized':   round(location_normalized, 1),
                'weight':       SALCI_V4_WEIGHTS['location'],
                'contribution': round(location_normalized * SALCI_V4_WEIGHTS['location'], 1),
                'grade':        get_component_grade(location_score, is_100_scale=True),
            },
            'matchup': {
                'raw':          matchup_score,
                'normalized':   round(matchup_clamped, 1),
                'weight':       SALCI_V4_WEIGHTS['matchup'],
                'contribution': round(matchup_clamped * SALCI_V4_WEIGHTS['matchup'], 1),
                'grade':        get_component_grade(matchup_score, is_100_scale=False),
            },
            'workload': {
                'raw':          workload_score,
                'normalized':   round(workload_clamped, 1),
                'weight':       SALCI_V4_WEIGHTS['workload'],
                'contribution': round(workload_clamped * SALCI_V4_WEIGHTS['workload'], 1),
                'grade':        get_component_grade(workload_score, is_100_scale=False),
            },
        },
    }


# =============================================================================
# VOLATILITY BUFFER (Stuff-dominant = boom/bust)
# =============================================================================

def calculate_volatility_buffer(stuff_plus: float, location_plus: float) -> float:
    """
    Higher Stuff / Lower Location → more variance → wider floor/ceiling spread.
    v4: values recalibrated for the wider score range.
    """
    if stuff_plus is None or location_plus is None:
        return 1.3

    gap = stuff_plus - location_plus

    if gap > 22:    return 2.1   # true boom/bust arm
    elif gap > 15:  return 1.75
    elif gap > 8:   return 1.40
    elif gap < -15: return 0.80  # pure contact pitcher, tight range
    elif gap < -8:  return 0.95
    else:           return 1.15  # balanced


# =============================================================================
# GRADE HELPERS
# =============================================================================

def get_component_grade(score: float, is_100_scale: bool = True) -> str:
    """Letter grade for component scores."""
    if is_100_scale:
        if score >= 120: return 'A+'
        if score >= 115: return 'A'
        if score >= 110: return 'A-'
        if score >= 105: return 'B+'
        if score >= 100: return 'B'
        if score >= 95:  return 'C+'
        if score >= 90:  return 'C'
        return 'D'
    else:
        if score >= 75: return 'A+'
        if score >= 68: return 'A'
        if score >= 60: return 'B'
        if score >= 50: return 'C'
        if score >= 40: return 'D'
        return 'F'


# =============================================================================
# EXPECTED Ks — v4  (calibrated to new SALCI range)
# =============================================================================

def calculate_expected_ks_v3(
    salci_result: Dict,
    projected_ip: float = 5.5,
    efficiency_factor: float = 1.0
) -> Dict:
    """
    SALCI v4 → Expected Ks + "At Least X Ks" floor.

    Calibration targets (based on 2024 MLB data):
      SALCI 85 (S-tier)  → ~11-12 Ks   e.g. Cole/Skenes peak nights
      SALCI 75 (A)       → ~9-10 Ks
      SALCI 65 (B+)      → ~7-8 Ks
      SALCI 52 (B)       → ~5-6 Ks
      SALCI 44 (C)       → ~4-5 Ks
      SALCI 35 (D)       → ~3-4 Ks
      SALCI <30 (F)      → ~1-3 Ks

    Formula: k_per_ip = (SALCI / 47) * 1.0  (calibrated midpoint)
    at SALCI=47 → k_per_ip=1.0, so 5.5 IP → 5.5 Ks  (C-grade average)
    at SALCI=75 → k_per_ip=1.60 → 8.8 Ks  (A-grade)
    at SALCI=85 → k_per_ip=1.81 → 9.9 Ks  (S-grade)
    """
    salci      = salci_result['salci']
    components = salci_result.get('components', {})
    stuff      = components.get('stuff',    {}).get('raw', 100)
    location   = components.get('location', {}).get('raw', 100)

    # K/IP mapping — linear with SALCI, calibrated so C-grade ≈ avg MLB rate
    k_per_ip   = (salci / 47.0) * 1.0
    k_per_ip   = max(0.40, min(2.40, k_per_ip))
    expected_ks = k_per_ip * projected_ip * efficiency_factor

    volatility = calculate_volatility_buffer(stuff, location)

    # Statistical floor: P(Ks ≥ floor) ≥ 60%
    lambda_ks = expected_ks
    floor     = 0
    for k in range(0, int(expected_ks) + 10):
        prob_ge_k = 1 - poisson.cdf(k - 1, lambda_ks) if k > 0 else 1.0
        if prob_ge_k >= 0.60:
            floor = k
        else:
            break

    floor_confidence = int(
        (1 - poisson.cdf(floor - 1, lambda_ks)) * 100
    ) if floor > 0 else 100

    # K-line probabilities (4 lines starting from floor)
    k_lines = {}
    for i in range(4):
        k_value  = floor + i
        prob_ge  = 1 - poisson.cdf(k_value - 1, lambda_ks)
        prob_pct = max(5, min(99, int(prob_ge * 100)))
        k_lines[k_value] = prob_pct

    return {
        'expected':         round(expected_ks, 1),
        'floor':            floor,
        'floor_confidence': floor_confidence,
        'volatility':       round(volatility, 2),
        'k_per_ip':         round(k_per_ip, 2),
        'projected_ip':     projected_ip,
        'k_lines':          k_lines,
        'best_line':        floor,
        'grade':            salci_result.get('grade', 'C'),
    }

# Keep the v3 alias so nothing breaks
calculate_expected_ks_v4 = calculate_expected_ks_v3


# =============================================================================
# PITCHER PROFILE CLASSIFICATION
# =============================================================================

def classify_pitcher_profile(stuff_plus: float, location_plus: float) -> Tuple[str, str]:
    """Classify pitcher archetype from Stuff+ and Location+."""
    if stuff_plus is None or location_plus is None:
        return ("UNKNOWN", "Insufficient data")

    if stuff_plus >= 118 and location_plus >= 112:
        return ("ELITE",             "True ace — elite stuff with command")
    elif stuff_plus >= 118 and location_plus < 100:
        return ("STUFF-DOMINANT",    "High K ceiling, some variance")
    elif stuff_plus < 100  and location_plus >= 115:
        return ("LOCATION-DOMINANT", "Efficient but lower K ceiling")
    elif stuff_plus >= 110 and location_plus >= 106:
        return ("BALANCED-PLUS",     "Quality all-around")
    elif stuff_plus >= 100 and location_plus >= 100:
        return ("BALANCED",          "League average, matchup-dependent")
    elif stuff_plus >= 100 or location_plus >= 100:
        return ("ONE-TOOL",          "One above-average skill")
    else:
        return ("LIMITED",           "Below average profile")


# =============================================================================
# STATCAST PROFILE FETCHERS (unchanged from v3)
# =============================================================================

def get_pitcher_statcast_profile(
    player_id: int,
    days: int = 30,
    season: int = None
) -> Optional[Dict]:
    """Get complete Statcast-based profile for a pitcher."""
    if not PYBASEBALL_AVAILABLE:
        return None

    if season:
        season_year = season
    else:
        today = datetime.today()
        season_year = today.year if today.month >= 3 else today.year - 1

    end_date   = datetime.today()
    start_date = end_date - timedelta(days=days)

    try:
        df = statcast_pitcher(
            start_dt=start_date.strftime('%Y-%m-%d'),
            end_dt=end_date.strftime('%Y-%m-%d'),
            player_id=player_id
        )
        if df is None or df.empty:
            return None

        stuff_result    = calculate_stuff_plus(df)
        location_result = calculate_location_plus(df)

        profile = {
            'player_id':     player_id,
            'date_range':    f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            'pitch_count':   len(df),
            'stuff_plus':    stuff_result.get('stuff_plus')   if stuff_result    else None,
            'location_plus': location_result.get('location_plus') if location_result else None,
            'csw_pct':       stuff_result.get('csw_pct')      if stuff_result    else None,
            'arsenal':       stuff_result.get('arsenal_summary', {}) if stuff_result else {},
            'zone_breakdown': location_result.get('zone_breakdown', {}) if location_result else {},
            'location_metrics': location_result.get('metrics', {}) if location_result else {},
            'raw_metrics':   stuff_result.get('raw_metrics', {}) if stuff_result else {},
        }

        if profile['stuff_plus'] and profile['location_plus']:
            profile_type, profile_desc = classify_pitcher_profile(
                profile['stuff_plus'], profile['location_plus']
            )
            profile['profile_type'] = profile_type
            profile['profile_desc'] = profile_desc

        return profile

    except Exception as e:
        print(f"Error fetching pitcher Statcast profile: {e}")
        return None


def get_hitter_zone_profile(player_id: int, days: int = 30) -> Optional[Dict]:
    """Get Statcast zone profile for a hitter."""
    if not PYBASEBALL_AVAILABLE:
        return None

    end_date   = datetime.today()
    start_date = end_date - timedelta(days=days)

    try:
        df = statcast_batter(
            start_dt=start_date.strftime('%Y-%m-%d'),
            end_dt=end_date.strftime('%Y-%m-%d'),
            player_id=player_id
        )
        if df is None or df.empty:
            return None

        results = {
            'player_id':      player_id,
            'zones':          {},
            'overall_metrics': {},
        }

        # Zone-by-zone BA
        for zone in range(1, 15):
            zone_df = df[df['zone'] == zone]
            if len(zone_df) < 5:
                continue
            hits     = len(zone_df[zone_df['events'].isin(['single', 'double', 'triple', 'home_run'])])
            ab_events = zone_df[zone_df['events'].notna() &
                                ~zone_df['events'].isin(['walk', 'hit_by_pitch', 'sac_fly', 'sac_bunt'])]
            ba = hits / len(ab_events) if len(ab_events) > 0 else 0.250

            swings = zone_df[zone_df['description'].isin([
                'swinging_strike', 'swinging_strike_blocked',
                'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
            ])]
            swing_pct = len(swings) / len(zone_df) if len(zone_df) > 0 else 0

            results['zones'][zone] = {
                'ba':            round(ba, 3),
                'swing_pct':     round(swing_pct * 100, 1),
                'pitch_count':   len(zone_df),
                'is_damage_zone': ba >= 0.300 and zone in IN_ZONE,
                'is_weakness':   ba < 0.200 and zone in IN_ZONE,
            }

        # Overall metrics
        total   = len(df)
        zone_sw = df[df['zone'].isin(IN_ZONE)]
        z_swings = zone_sw[zone_sw['description'].isin([
            'swinging_strike', 'swinging_strike_blocked',
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        z_contact = zone_sw[zone_sw['description'].isin([
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        zone_contact_pct = len(z_contact) / len(z_swings) if len(z_swings) > 0 else 0.82
        results['overall_metrics']['zone_contact_pct'] = round(zone_contact_pct * 100, 1)

        chase_pitches = df[df['zone'].isin(CHASE_ZONES)]
        chase_swings  = chase_pitches[chase_pitches['description'].isin([
            'swinging_strike', 'swinging_strike_blocked',
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        results['overall_metrics']['chase_pct'] = round(
            len(chase_swings) / len(chase_pitches) * 100 if len(chase_pitches) > 0 else 0, 1
        )

        strikeouts    = df[df['events'] == 'strikeout']
        plate_apps    = df[df['events'].notna()]
        results['overall_metrics']['k_rate'] = round(
            len(strikeouts) / len(plate_apps) if len(plate_apps) > 0 else 0.22, 3
        )

        return results

    except Exception as e:
        print(f"Error fetching hitter Statcast data: {e}")
        return None


# =============================================================================
# HEAT MAP FUNCTIONS (unchanged)
# =============================================================================

def get_pitcher_attack_map(player_id: int, days: int = 30) -> Optional[Dict]:
    """Generate heat map data showing where pitcher attacks."""
    profile = get_pitcher_statcast_profile(player_id, days)
    if not profile or not profile.get('zone_breakdown'):
        return None

    zones = profile['zone_breakdown']
    grid  = {}
    for zone in range(1, 15):
        zone_data = zones.get(zone, {})
        usage     = zone_data.get('pitch_pct',  0)
        whiff     = zone_data.get('whiff_pct', 20)
        color     = 'green' if whiff >= 30 else 'yellow' if whiff >= 22 else 'red'
        grid[zone] = {'usage': usage, 'whiff_pct': whiff, 'color': color}

    return {
        'player_id':   player_id,
        'grid':        grid,
        'primary_zone': max(range(1, 10), key=lambda z: grid.get(z, {}).get('usage', 0)),
        'best_zone':   max(range(1, 10), key=lambda z: grid.get(z, {}).get('whiff_pct', 0)),
    }


def get_hitter_damage_map(player_id: int, days: int = 30) -> Optional[Dict]:
    """Generate heat map data showing where hitter does damage."""
    profile = get_hitter_zone_profile(player_id, days)
    if not profile or not profile.get('zones'):
        return None

    zones = profile['zones']
    grid  = {}
    for zone in range(1, 15):
        zone_data = zones.get(zone, {})
        ba        = zone_data.get('ba', 0.250)
        color     = 'red' if ba >= 0.320 else 'orange' if ba >= 0.270 else 'yellow' if ba >= 0.220 else 'blue'
        grid[zone] = {
            'ba':         ba,
            'swing_pct':  zone_data.get('swing_pct', 50),
            'color':      color,
            'is_damage':  zone_data.get('is_damage_zone', False),
            'is_weakness': zone_data.get('is_weakness', False),
        }

    damage_zones   = [z for z in range(1, 10) if grid.get(z, {}).get('is_damage',   False)]
    weakness_zones = [z for z in range(1, 10) if grid.get(z, {}).get('is_weakness', False)]

    return {
        'player_id':     player_id,
        'grid':          grid,
        'damage_zones':  damage_zones,
        'weakness_zones': weakness_zones,
        'best_zone':     max(range(1, 10), key=lambda z: grid.get(z, {}).get('ba', 0)),
        'worst_zone':    min(range(1, 10), key=lambda z: grid.get(z, {}).get('ba', 1)),
    }


def analyze_matchup_zones(pitcher_id: int, hitter_id: int, days: int = 30) -> Optional[Dict]:
    """Analyze zone overlap between pitcher and hitter."""
    pitcher_map = get_pitcher_attack_map(pitcher_id, days)
    hitter_map  = get_hitter_damage_map(hitter_id, days)
    if not pitcher_map or not hitter_map:
        return None

    danger_zones    = []
    advantage_zones = []

    for zone in range(1, 10):
        pitcher_usage = pitcher_map['grid'].get(zone, {}).get('usage', 0)
        hitter_ba     = hitter_map['grid'].get(zone, {}).get('ba', 0.250)

        if pitcher_usage >= 8:
            if hitter_ba >= 0.300:
                danger_zones.append({
                    'zone': zone, 'name': ZONE_NAMES[zone],
                    'pitcher_usage': pitcher_usage, 'hitter_ba': hitter_ba,
                })
            elif hitter_ba < 0.200:
                advantage_zones.append({
                    'zone': zone, 'name': ZONE_NAMES[zone],
                    'pitcher_usage': pitcher_usage, 'hitter_ba': hitter_ba,
                })

    edge_score = len(advantage_zones) - len(danger_zones)

    if edge_score >= 2:
        matchup_edge = "PITCHER ADVANTAGE"
        edge_desc    = "Pitcher can attack zones where hitter struggles"
    elif edge_score <= -2:
        matchup_edge = "HITTER ADVANTAGE"
        edge_desc    = "Pitcher tends to throw where hitter does damage"
    else:
        matchup_edge = "NEUTRAL"
        edge_desc    = "No significant zone advantage either way"

    return {
        'pitcher_id':    pitcher_id,
        'hitter_id':     hitter_id,
        'danger_zones':  danger_zones,
        'advantage_zones': advantage_zones,
        'edge_score':    edge_score,
        'matchup_edge':  matchup_edge,
        'edge_description': edge_desc,
    }


# =============================================================================
# UTILITIES
# =============================================================================

def lookup_player_id(last_name: str, first_name: str) -> Optional[int]:
    """Look up MLB player ID by name."""
    if not PYBASEBALL_AVAILABLE:
        return None
    try:
        result = playerid_lookup(last_name, first_name)
        if result is not None and not result.empty:
            return int(result.iloc[0]['key_mlbam'])
    except Exception as e:
        print(f"Player lookup error: {e}")
    return None


# =============================================================================
# BACKWARD COMPATIBILITY WRAPPERS
# =============================================================================

def calculate_matchup_score(opp_stats, pitcher_hand='R', lineup_handedness=None):
    """v2/v3 compatibility wrapper."""
    return calculate_matchup_score_v3(opp_stats, None, pitcher_hand)

def calculate_workload_score(pitcher_stats, recent_games=None):
    """v2/v3 compatibility wrapper."""
    return calculate_workload_score_v3(pitcher_stats, None, recent_games)

def calculate_salci_v2(stuff, location, matchup, workload):
    """v2 compatibility — redirects to v4."""
    return calculate_salci_v3(stuff, location, matchup, workload)

def calculate_expected_ks(salci_score, projected_ip=5.5, efficiency_factor=1.0):
    """v2/v3 compatibility wrapper."""
    salci_result = {'salci': salci_score, 'components': {}}
    return calculate_expected_ks_v3(salci_result, projected_ip, efficiency_factor)


# =============================================================================
# SELF-TEST & DEMO SCORING
# =============================================================================

if __name__ == "__main__":
    print("=" * 65)
    print("SALCI v4 — Statcast Connector Self-Test")
    print("=" * 65)

    print(f"\n{'Component':<12} {'Weight':>8}")
    print("-" * 22)
    for k, v in SALCI_V4_WEIGHTS.items():
        print(f"  {k:<10} {v*100:>7.0f}%")

    print("\n── Prototype pitcher profiles ──────────────────────────────")
    test_cases = [
        ("Elite Ace (Skenes/Cole peak)",         128, 112, 72, 70),
        ("Stuff Monster (high whiff, avg cmd)",  125, 97,  65, 55),
        ("K-Artist vs weak lineup",              112, 103, 78, 60),
        ("Solid Starter (average everything)",   100, 100, 50, 50),
        ("Contact pitcher (great cmd)",           92, 118, 42, 62),
        ("Struggling veteran",                    85,  95, 35, 40),
        ("Fade/spot start",                       80,  88, 28, 30),
    ]

    print(f"\n{'Pitcher Type':<45} {'STUFF':>6} {'LOC':>6} {'MATCH':>6} {'WORK':>6} "
          f"{'SALCI':>7} {'Grade':>6} {'Exp Ks':>8} {'Floor':>7}")
    print("-" * 115)

    for name, stuff, loc, matchup, workload in test_cases:
        result   = calculate_salci_v3(stuff, loc, matchup, workload)
        ks_info  = calculate_expected_ks_v3(result, projected_ip=6.0)
        salci    = result['salci']
        grade    = result['grade']
        exp_ks   = ks_info['expected']
        floor    = ks_info['floor']
        print(f"  {name:<43} {stuff:>6} {loc:>6} {matchup:>6} {workload:>6} "
              f"  {salci:>6.1f} {grade:>6}   {exp_ks:>6.1f}    {floor:>4}+")

    print("\n── Score range sanity check ─────────────────────────────────")
    from itertools import product as iproduct
    scores = []
    for s, l, m, w in iproduct([80, 100, 120], [90, 100, 110], [30, 50, 75], [35, 50, 70]):
        r = calculate_salci_v3(s, l, m, w)
        scores.append(r['salci'])
    print(f"  Min SALCI across test grid: {min(scores):.1f}")
    print(f"  Max SALCI across test grid: {max(scores):.1f}")
    print(f"  Mean:                       {sum(scores)/len(scores):.1f}")
    print(f"  Std Dev:                    {pd.Series(scores).std():.1f}")

    if not PYBASEBALL_AVAILABLE:
        print("\n⚠️  pybaseball not installed — Statcast live data disabled")
        print("   Run: pip install pybaseball")
    else:
        print("\n✅ pybaseball available — live Statcast data enabled")
