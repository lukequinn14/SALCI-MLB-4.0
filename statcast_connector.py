"""
SALCI v5.0 - Statcast Data Connector & Scoring Engine
======================================================

Physics-based Stuff+ and Location+ calculations using real Statcast data.
Implements SALCI v2 formula with proper component weighting.

STUFF+ METHODOLOGY:
- Uses raw physical traits (velocity, movement, spin, release point)
- Compares to historical pitch outcomes via expected run values
- Normalized to 100 = league average, 10 points = 1 standard deviation

SALCI v2 WEIGHTS:
- Stuff: 30% (raw pitch quality)
- Location: 25% (command and placement)
- Matchup: 25% (opponent tendencies)
- Workload: 20% (efficiency, TTT risk, projected IP)

Installation:
    pip install pybaseball

Author: SALCI Development Team
Version: 2.0
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import warnings

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
    PYBASEBALL_AVAILABLE = False
    print("Warning: pybaseball not installed. Run: pip install pybaseball")


# =============================================================================
# CONSTANTS & LEAGUE BASELINES (2024-2025 averages)
# =============================================================================

# League average baselines for normalization (updated for 2024-2025)
LEAGUE_BASELINES = {
    # Fastball metrics
    'ff_velo': 94.5,           # 4-seam average velocity
    'ff_velo_std': 2.3,        # Standard deviation
    'ff_ivb': 14.5,            # Induced vertical break (inches)
    'ff_ivb_std': 3.2,
    'ff_hb': 7.5,              # Horizontal break (inches, abs value)
    'ff_hb_std': 2.8,
    'ff_spin': 2250,           # Spin rate
    'ff_spin_std': 180,
    
    # Breaking ball metrics (slider/sweeper)
    'sl_velo': 85.5,
    'sl_hb': 5.5,              # Horizontal sweep
    'sl_hb_std': 3.5,
    'sl_vb': 2.0,              # Vertical drop below FF
    'sl_spin': 2450,
    
    # Curveball metrics
    'cu_velo': 79.0,
    'cu_vb': -6.0,             # Vertical drop (negative = drops more)
    'cu_spin': 2700,
    
    # Changeup metrics
    'ch_velo_diff': 8.5,       # Velocity below fastball
    'ch_drop': 6.0,            # Drop below fastball plane
    'ch_fade': 4.0,            # Arm-side fade
    
    # Location metrics
    'zone_pct': 0.45,          # % pitches in strike zone
    'edge_pct': 0.28,          # % pitches on edges (not heart, not ball)
    'heart_pct': 0.12,         # % pitches in heart of zone
    'chase_rate': 0.30,        # % swings on pitches outside zone
    'csw_pct': 0.29,           # Called strike + whiff %
    'first_pitch_strike': 0.60,
    
    # Outcome metrics (for validation, not Stuff calculation)
    'whiff_pct': 0.25,         # Swinging strikes / swings
    'k_pct': 0.22,
}

# Pitch type mappings
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
BREAKING = ['SL', 'ST', 'SV', 'CU', 'KC']
OFFSPEED = ['CH', 'FS']

# Zone definitions
ZONE_NAMES = {
    1: "High Inside", 2: "High Middle", 3: "High Outside",
    4: "Middle Inside", 5: "Heart", 6: "Middle Outside", 
    7: "Low Inside", 8: "Low Middle", 9: "Low Outside",
    11: "Chase Up-In", 12: "Chase Down-In",
    13: "Chase Up-Out", 14: "Chase Down-Out"
}

EDGE_ZONES = [1, 2, 3, 4, 6, 7, 8, 9]
HEART_ZONE = [5]
CHASE_ZONES = [11, 12, 13, 14]


# =============================================================================
# STUFF+ CALCULATION (Physics-Based)
# =============================================================================

def calculate_stuff_plus(df: pd.DataFrame) -> Dict:
    """
    Calculate physics-based Stuff+ from Statcast pitch data.
    
    This does NOT use outcomes (K%, whiff rate) as inputs.
    It uses only the physical characteristics of the pitch:
    - Velocity
    - Movement (induced vertical break, horizontal break)
    - Spin rate
    - Release point
    - Velocity differentials (for secondary pitches)
    
    The philosophy: "Given these physical traits, what SHOULD happen historically?"
    
    Returns:
        Dict with overall stuff_plus (100 = average) and per-pitch breakdown
    """
    if df is None or df.empty:
        return None
    
    results = {
        'stuff_plus': None,
        'by_pitch_type': {},
        'arsenal_summary': {},
        'raw_metrics': {}
    }
    
    # Get primary fastball baseline (for differentials)
    fastballs = df[df['pitch_type'].isin(FASTBALLS)]
    if len(fastballs) >= 10:
        fb_velo = fastballs['release_speed'].mean()
        fb_ivb = fastballs['pfx_z'].mean() * 12 if 'pfx_z' in fastballs.columns else 14.5
        fb_hb = abs(fastballs['pfx_x'].mean() * 12) if 'pfx_x' in fastballs.columns else 7.5
    else:
        fb_velo = LEAGUE_BASELINES['ff_velo']
        fb_ivb = LEAGUE_BASELINES['ff_ivb']
        fb_hb = LEAGUE_BASELINES['ff_hb']
    
    results['raw_metrics']['fb_velo'] = round(fb_velo, 1)
    results['raw_metrics']['fb_ivb'] = round(fb_ivb, 1)
    
    pitch_stuff_scores = []
    
    for pitch_type in df['pitch_type'].dropna().unique():
        pitch_df = df[df['pitch_type'] == pitch_type]
        
        if len(pitch_df) < 10:
            continue
        
        # Extract physical metrics
        velo = pitch_df['release_speed'].mean() if 'release_speed' in pitch_df.columns else 90
        spin = pitch_df['release_spin_rate'].mean() if 'release_spin_rate' in pitch_df.columns else 2200
        ivb = pitch_df['pfx_z'].mean() * 12 if 'pfx_z' in pitch_df.columns else 0
        hb = pitch_df['pfx_x'].mean() * 12 if 'pfx_x' in pitch_df.columns else 0
        
        # Calculate extension if available
        extension = pitch_df['release_extension'].mean() if 'release_extension' in pitch_df.columns else 6.0
        
        # Velocity differential from fastball
        velo_diff = fb_velo - velo
        
        # Movement differential
        ivb_diff = fb_ivb - ivb
        hb_diff = abs(hb) - fb_hb
        
        # =====================================================
        # PHYSICS-BASED STUFF SCORE BY PITCH TYPE
        # Each component is normalized to standard deviations
        # above/below league average, then weighted
        # =====================================================
        
        if pitch_type == 'FF':
            # Four-Seam Fastball: Velocity + Ride + Extension
            velo_z = (velo - LEAGUE_BASELINES['ff_velo']) / LEAGUE_BASELINES['ff_velo_std']
            ivb_z = (ivb - LEAGUE_BASELINES['ff_ivb']) / LEAGUE_BASELINES['ff_ivb_std']
            
            # Extension bonus (perceived velocity)
            ext_bonus = (extension - 6.0) * 2 if extension > 6.0 else 0
            
            # Weighted combination (velo most important for FF)
            raw_stuff = (velo_z * 0.50) + (ivb_z * 0.35) + (ext_bonus * 0.05)
            
        elif pitch_type == 'SI':
            # Sinker: Velocity + Arm-Side Run + Drop
            velo_z = (velo - (LEAGUE_BASELINES['ff_velo'] - 1.5)) / 2.0
            hb_z = (abs(hb) - 14) / 3.5  # Sinkers should have more run
            drop_z = (fb_ivb - ivb - 4) / 2.5  # Drop relative to FF
            
            raw_stuff = (velo_z * 0.40) + (hb_z * 0.35) + (drop_z * 0.25)
            
        elif pitch_type == 'FC':
            # Cutter: Velocity + Glove-Side Movement
            velo_z = (velo - (LEAGUE_BASELINES['ff_velo'] - 3)) / 2.0
            cut_z = (abs(hb) - 3.5) / 2.0  # Cutters have less arm-side run
            
            raw_stuff = (velo_z * 0.50) + (cut_z * 0.30) + (0.20 * 0)  # Spin less important
            
        elif pitch_type in ['SL', 'ST', 'SV']:
            # Slider/Sweeper: Horizontal Break + Velocity Diff + Depth
            sweep_z = (abs(hb) - LEAGUE_BASELINES['sl_hb']) / LEAGUE_BASELINES['sl_hb_std']
            velo_diff_z = (velo_diff - 9) / 2.5  # Good sliders are 8-12 mph off FB
            drop_z = (ivb_diff - 10) / 4.0  # Drop below fastball plane
            
            raw_stuff = (sweep_z * 0.40) + (drop_z * 0.30) + (velo_diff_z * 0.15) + (0.15 * 0)
            
        elif pitch_type in ['CU', 'KC']:
            # Curveball: Depth (vertical drop) + Spin + Velo Diff
            drop_z = (-ivb - 6) / 3.0  # More negative = more drop
            spin_z = (spin - LEAGUE_BASELINES['cu_spin']) / 300
            velo_diff_z = (velo_diff - 15) / 3.0  # Good curves are 14-18 mph off FB
            
            raw_stuff = (drop_z * 0.45) + (spin_z * 0.25) + (velo_diff_z * 0.20)
            
        elif pitch_type == 'CH':
            # Changeup: Velo Diff + Fade + Drop + Arm Speed Deception
            velo_diff_z = (velo_diff - LEAGUE_BASELINES['ch_velo_diff']) / 2.0
            fade_z = (abs(hb) - fb_hb - LEAGUE_BASELINES['ch_fade']) / 2.5
            drop_z = (ivb_diff - LEAGUE_BASELINES['ch_drop']) / 2.5
            
            raw_stuff = (velo_diff_z * 0.35) + (fade_z * 0.30) + (drop_z * 0.35)
            
        elif pitch_type == 'FS':
            # Splitter: Drop + Velo (close to FB) + Late Break
            drop_z = (ivb_diff - 8) / 3.0  # Splitters drop hard
            velo_z = (velo_diff - 6) / 2.0  # Should be close to FB velo
            
            raw_stuff = (drop_z * 0.50) + (velo_z * 0.30) + (0.20 * 0)
            
        else:
            # Unknown pitch type - use generic formula
            raw_stuff = 0
        
        # Convert to 100-scale (100 = average, 10 pts = 1 std dev)
        # raw_stuff is in standard deviations, so multiply by 10 and add 100
        stuff_plus = 100 + (raw_stuff * 10)
        stuff_plus = max(60, min(140, stuff_plus))  # Clamp to realistic range
        
        usage_pct = len(pitch_df) / len(df)
        
        # Calculate observed whiff rate for comparison (not used in Stuff calculation)
        swings = pitch_df[pitch_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked', 
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        whiffs = pitch_df[pitch_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked'
        ])]
        observed_whiff = len(whiffs) / len(swings) if len(swings) > 0 else 0
        
        results['by_pitch_type'][pitch_type] = {
            'stuff_plus': round(stuff_plus, 0),
            'usage_pct': round(usage_pct * 100, 1),
            'velocity': round(velo, 1),
            'ivb': round(ivb, 1),
            'hb': round(hb, 1),
            'spin': round(spin, 0) if not pd.isna(spin) else None,
            'velo_diff': round(velo_diff, 1),
            'observed_whiff_pct': round(observed_whiff * 100, 1),
            'pitch_count': len(pitch_df)
        }
        
        results['arsenal_summary'][pitch_type] = {
            'name': PITCH_TYPES.get(pitch_type, pitch_type),
            'stuff': round(stuff_plus, 0),
            'velo': round(velo, 1),
            'usage': round(usage_pct * 100, 1)
        }
        
        # Weight by usage for overall calculation
        pitch_stuff_scores.append((stuff_plus, usage_pct))
    
    # Calculate weighted overall Stuff+
    if pitch_stuff_scores:
        total_weight = sum(w for _, w in pitch_stuff_scores)
        weighted_stuff = sum(s * w for s, w in pitch_stuff_scores) / total_weight if total_weight > 0 else 100
        results['stuff_plus'] = round(weighted_stuff, 0)
    
    return results


# =============================================================================
# LOCATION+ CALCULATION
# =============================================================================

def calculate_location_plus(df: pd.DataFrame) -> Dict:
    """
    Calculate Location+ from Statcast pitch data.
    
    Components:
    - Zone Rate: % pitches in strike zone (not too high - that's hittable)
    - Edge Rate: % pitches on corners (optimal location)
    - Heart Rate: % pitches in middle of zone (bad - lower is better)
    - Chase Rate: % swings induced on pitches outside zone
    - First Pitch Strike %: Command indicator
    - CSW%: Called strikes + whiffs (execution quality)
    
    Returns:
        Dict with overall location_plus (100 = average) and breakdown
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
    
    # Calculate zone percentages
    in_zone = zone_data.isin(list(range(1, 10))).sum()
    on_edge = zone_data.isin(EDGE_ZONES).sum()
    in_heart = zone_data.isin(HEART_ZONE).sum()
    in_chase = zone_data.isin(CHASE_ZONES).sum()
    
    zone_pct = in_zone / len(zone_data)
    edge_pct = on_edge / len(zone_data)
    heart_pct = in_heart / len(zone_data)
    chase_zone_pct = in_chase / len(zone_data)
    
    # Chase rate (swings on pitches outside zone)
    chase_pitches = df[df['zone'].isin(CHASE_ZONES)]
    if len(chase_pitches) > 10:
        chase_swings = chase_pitches[chase_pitches['description'].isin([
            'swinging_strike', 'swinging_strike_blocked', 
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        chase_rate = len(chase_swings) / len(chase_pitches)
    else:
        chase_rate = LEAGUE_BASELINES['chase_rate']
    
    # First pitch strike rate
    first_pitches = df[(df['balls'] == 0) & (df['strikes'] == 0)]
    if len(first_pitches) > 10:
        fps_strikes = first_pitches[first_pitches['description'].isin([
            'called_strike', 'swinging_strike', 'swinging_strike_blocked',
            'foul', 'foul_tip', 'hit_into_play'
        ])]
        fps_rate = len(fps_strikes) / len(first_pitches)
    else:
        fps_rate = LEAGUE_BASELINES['first_pitch_strike']
    
    # CSW% (called strike + whiff)
    called_strikes = df[df['description'] == 'called_strike']
    whiffs = df[df['description'].isin(['swinging_strike', 'swinging_strike_blocked'])]
    csw_pct = (len(called_strikes) + len(whiffs)) / total_pitches
    
    # Store raw metrics
    results['metrics'] = {
        'zone_pct': round(zone_pct * 100, 1),
        'edge_pct': round(edge_pct * 100, 1),
        'heart_pct': round(heart_pct * 100, 1),
        'chase_zone_pct': round(chase_zone_pct * 100, 1),
        'chase_rate': round(chase_rate * 100, 1),
        'fps_pct': round(fps_rate * 100, 1),
        'csw_pct': round(csw_pct * 100, 1),
    }
    
    # =====================================================
    # LOCATION+ CALCULATION
    # Each component normalized to z-score, then weighted
    # =====================================================
    
    # Zone rate: Optimal is ~45-50% (too high = hittable, too low = walks)
    zone_z = -abs(zone_pct - 0.47) / 0.05  # Penalize deviation from optimal
    
    # Edge rate: Higher is better (painting corners)
    edge_z = (edge_pct - LEAGUE_BASELINES['edge_pct']) / 0.05
    
    # Heart rate: Lower is better (avoiding middle)
    heart_z = -(heart_pct - LEAGUE_BASELINES['heart_pct']) / 0.04  # Negative because lower is better
    
    # Chase rate: Higher is better (getting swings outside zone)
    chase_z = (chase_rate - LEAGUE_BASELINES['chase_rate']) / 0.05
    
    # First pitch strike: Higher is better
    fps_z = (fps_rate - LEAGUE_BASELINES['first_pitch_strike']) / 0.06
    
    # CSW: Higher is better
    csw_z = (csw_pct - LEAGUE_BASELINES['csw_pct']) / 0.04
    
    # Weighted combination
    raw_location = (
        zone_z * 0.10 +
        edge_z * 0.25 +
        heart_z * 0.20 +
        chase_z * 0.20 +
        fps_z * 0.10 +
        csw_z * 0.15
    )
    
    # Convert to 100-scale
    location_plus = 100 + (raw_location * 10)
    location_plus = max(70, min(130, location_plus))
    
    results['location_plus'] = round(location_plus, 0)
    
    # Zone-by-zone breakdown for heat maps
    for zone in range(1, 15):
        zone_df = df[df['zone'] == zone]
        if len(zone_df) < 3:
            continue
        
        zone_swings = zone_df[zone_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked', 
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        zone_whiffs = zone_df[zone_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked'
        ])]
        
        whiff_pct = len(zone_whiffs) / len(zone_swings) if len(zone_swings) > 0 else 0
        
        results['zone_breakdown'][zone] = {
            'name': ZONE_NAMES.get(zone, f"Zone {zone}"),
            'pitch_count': len(zone_df),
            'pitch_pct': round(len(zone_df) / total_pitches * 100, 1),
            'whiff_pct': round(whiff_pct * 100, 1),
            'is_edge': zone in EDGE_ZONES,
            'is_heart': zone in HEART_ZONE,
            'is_chase': zone in CHASE_ZONES
        }
    
    return results


# =============================================================================
# WORKLOAD / EFFICIENCY SCORE (NEW IN v2)
# =============================================================================

def calculate_workload_score(
    pitcher_stats: Dict,
    recent_games: Optional[List[Dict]] = None
) -> Tuple[float, Dict]:
    """
    Calculate Workload/Efficiency score for SALCI v2.
    
    Components:
    - Projected IP (based on recent starts)
    - P/IP (pitches per inning - efficiency)
    - TTT Risk (third-time-through-the-order performance)
    - Pitch count management tendency
    
    Returns:
        Tuple of (score 0-100, breakdown dict)
    """
    breakdown = {}
    
    # P/IP: Lower is better (more efficient)
    p_ip = pitcher_stats.get('P/IP', 16.0)
    p_ip_z = -(p_ip - 15.5) / 2.0  # 15.5 is good, lower is better
    p_ip_z = max(-2, min(2, p_ip_z))
    breakdown['p_ip'] = {'value': round(p_ip, 1), 'z_score': round(p_ip_z, 2)}
    
    # Average IP (projected workload)
    avg_ip = pitcher_stats.get('avg_ip', 5.5)
    ip_z = (avg_ip - 5.5) / 1.0  # 5.5 IP is average
    ip_z = max(-2, min(2, ip_z))
    breakdown['avg_ip'] = {'value': round(avg_ip, 1), 'z_score': round(ip_z, 2)}
    
    # Deep game rate (6+ IP)
    deep_game_pct = pitcher_stats.get('deep_game_pct', 0.40)
    deep_z = (deep_game_pct - 0.40) / 0.15
    deep_z = max(-2, min(2, deep_z))
    breakdown['deep_game_pct'] = {'value': round(deep_game_pct * 100, 1), 'z_score': round(deep_z, 2)}
    
    # TTT Risk: How does pitcher perform 3rd time through?
    # If not available, use neutral
    ttt_risk = pitcher_stats.get('ttt_woba_diff', 0)  # wOBA increase 3rd time through
    ttt_z = -ttt_risk / 0.030  # Negative because increase is bad
    ttt_z = max(-2, min(2, ttt_z))
    breakdown['ttt_risk'] = {'value': round(ttt_risk * 1000, 0), 'z_score': round(ttt_z, 2)}
    
    # Weighted combination
    raw_workload = (
        p_ip_z * 0.30 +
        ip_z * 0.35 +
        deep_z * 0.20 +
        ttt_z * 0.15
    )
    
    # Convert to 0-100 scale (50 = average)
    workload_score = 50 + (raw_workload * 15)
    workload_score = max(20, min(80, workload_score))
    
    return round(workload_score, 1), breakdown


# =============================================================================
# MATCHUP SCORE
# =============================================================================

def calculate_matchup_score(
    opp_stats: Dict,
    pitcher_hand: str = 'R',
    lineup_handedness: Optional[Dict] = None
) -> Tuple[float, Dict]:
    """
    Calculate Matchup score based on opponent tendencies.
    
    Components:
    - Opponent K% (team strikeout rate)
    - Opponent Contact% (team contact rate)
    - Handedness splits (if available)
    - Lineup composition
    
    Returns:
        Tuple of (score 0-100, breakdown dict)
    """
    breakdown = {}
    
    # Opponent K%: Higher is better for pitcher
    opp_k_pct = opp_stats.get('OppK%', 0.22)
    k_z = (opp_k_pct - 0.22) / 0.03
    k_z = max(-2, min(2, k_z))
    breakdown['opp_k_pct'] = {'value': round(opp_k_pct * 100, 1), 'z_score': round(k_z, 2)}
    
    # Opponent Contact%: Lower is better for pitcher
    opp_contact = opp_stats.get('OppContact%', 0.78)
    contact_z = -(opp_contact - 0.78) / 0.03  # Negative because lower is better
    contact_z = max(-2, min(2, contact_z))
    breakdown['opp_contact'] = {'value': round(opp_contact * 100, 1), 'z_score': round(contact_z, 2)}
    
    # Platoon advantage
    if lineup_handedness:
        same_side = lineup_handedness.get('same_side_pct', 0.50)
        # Same-side matchups favor pitcher
        platoon_z = (same_side - 0.50) / 0.15
    else:
        platoon_z = 0
    platoon_z = max(-1.5, min(1.5, platoon_z))
    breakdown['platoon'] = {'value': round(platoon_z, 2), 'z_score': round(platoon_z, 2)}
    
    # Weighted combination
    raw_matchup = (
        k_z * 0.45 +
        contact_z * 0.35 +
        platoon_z * 0.20
    )
    
    # Convert to 0-100 scale
    matchup_score = 50 + (raw_matchup * 15)
    matchup_score = max(20, min(80, matchup_score))
    
    return round(matchup_score, 1), breakdown


# =============================================================================
# SALCI v2 MASTER CALCULATION
# =============================================================================

def calculate_salci_v2(
    stuff_score: float,
    location_score: float,
    matchup_score: float,
    workload_score: float
) -> Dict:
    """
    Calculate SALCI v2 using the new component weights.
    
    SALCI v2 = (0.30 × Stuff) + (0.25 × Location) + (0.25 × Matchup) + (0.20 × Workload)
    
    All inputs should be on 0-100 scale (or 100-centered for Stuff+/Location+).
    
    Returns:
        Dict with SALCI score and breakdown
    """
    # Normalize Stuff+ and Location+ from 100-centered to 0-100 scale
    # 100 = 50, 120 = 70, 80 = 30
    stuff_normalized = (stuff_score - 50) / 2 if stuff_score else 50
    location_normalized = (location_score - 50) / 2 if location_score else 50
    
    # Ensure all scores are on 0-100 scale
    stuff_normalized = max(20, min(80, stuff_normalized))
    location_normalized = max(20, min(80, location_normalized))
    matchup_score = max(20, min(80, matchup_score))
    workload_score = max(20, min(80, workload_score))
    
    # Apply SALCI v2 weights
    salci = (
        stuff_normalized * 0.30 +
        location_normalized * 0.25 +
        matchup_score * 0.25 +
        workload_score * 0.20
    )
    
    return {
        'salci': round(salci, 1),
        'components': {
            'stuff': {'score': stuff_score, 'normalized': round(stuff_normalized, 1), 'weight': 0.30},
            'location': {'score': location_score, 'normalized': round(location_normalized, 1), 'weight': 0.25},
            'matchup': {'score': matchup_score, 'normalized': round(matchup_score, 1), 'weight': 0.25},
            'workload': {'score': workload_score, 'normalized': round(workload_score, 1), 'weight': 0.20},
        },
        'weighted_contributions': {
            'stuff': round(stuff_normalized * 0.30, 1),
            'location': round(location_normalized * 0.25, 1),
            'matchup': round(matchup_score * 0.25, 1),
            'workload': round(workload_score * 0.20, 1),
        }
    }


def calculate_expected_ks(
    salci_score: float,
    projected_ip: float = 5.5,
    efficiency_factor: float = 1.0
) -> Dict:
    """
    Calculate expected strikeouts from SALCI v2 score.
    
    Formula: Expected_Ks = (SALCI / 10) × Projected_IP × Efficiency_Factor
    
    Args:
        salci_score: SALCI v2 score (0-100)
        projected_ip: Expected innings pitched
        efficiency_factor: Adjustment for pitch count tendencies (0.8-1.2)
    
    Returns:
        Dict with expected K projection and K-line probabilities
    """
    # Base K rate from SALCI
    # SALCI 50 = 1.0 K/IP, SALCI 70 = 1.4 K/IP, SALCI 30 = 0.6 K/IP
    k_per_ip = (salci_score / 50) * 1.0
    k_per_ip = max(0.4, min(2.0, k_per_ip))
    
    # Expected Ks
    expected_ks = k_per_ip * projected_ip * efficiency_factor
    
    # K-line probabilities (using Poisson-ish distribution)
    lines = {}
    for k in range(4, 11):
        # Simplified probability calculation
        # Higher expected = higher probability of reaching each line
        prob = max(0, min(95, 100 - (k - expected_ks) * 18))
        lines[k] = round(prob, 0)
    
    return {
        'expected_ks': round(expected_ks, 1),
        'k_per_ip': round(k_per_ip, 2),
        'projected_ip': projected_ip,
        'efficiency_factor': efficiency_factor,
        'lines': lines
    }


# =============================================================================
# COMPLETE PITCHER PROFILE
# =============================================================================

def get_pitcher_statcast_profile(
    player_id: int, 
    days: int = 30,
    season: int = None
) -> Optional[Dict]:
    """
    Get complete Statcast-based profile for a pitcher.
    
    Returns physics-based Stuff+ and Location+ along with all raw metrics.
    """
    if not PYBASEBALL_AVAILABLE:
        return None
    
    if season:
        start_date = f"{season}-03-01"
        end_date = f"{season}-11-01"
    else:
        end_date = datetime.today().strftime('%Y-%m-%d')
        start_date = (datetime.today() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    try:
        df = statcast_pitcher(start_date, end_date, player_id)
        
        if df is None or df.empty:
            return None
        
        # Calculate physics-based Stuff+
        stuff_data = calculate_stuff_plus(df)
        
        # Calculate Location+
        location_data = calculate_location_plus(df)
        
        if stuff_data is None or location_data is None:
            return None
        
        stuff_plus = stuff_data['stuff_plus']
        location_plus = location_data['location_plus']
        
        # Determine profile type
        profile_type, profile_desc = classify_pitcher_profile(stuff_plus, location_plus)
        
        return {
            'player_id': player_id,
            'period_days': days,
            'pitches_analyzed': len(df),
            'stuff_plus': stuff_plus,
            'location_plus': location_plus,
            'combined_plus': round((stuff_plus + location_plus) / 2, 0),
            'arsenal': stuff_data.get('arsenal_summary', {}),
            'by_pitch_type': stuff_data.get('by_pitch_type', {}),
            'raw_metrics': stuff_data.get('raw_metrics', {}),
            'zone_breakdown': location_data.get('zone_breakdown', {}),
            'location_metrics': location_data.get('metrics', {}),
            'profile_type': profile_type,
            'profile_description': profile_desc
        }
        
    except Exception as e:
        print(f"Error fetching Statcast data: {e}")
        return None


# =============================================================================
# HITTER ZONE PROFILE
# =============================================================================

def get_hitter_zone_profile(
    player_id: int,
    days: int = 30,
    season: int = None
) -> Optional[Dict]:
    """
    Get zone-based performance profile for a hitter.
    """
    if not PYBASEBALL_AVAILABLE:
        return None
    
    if season:
        start_date = f"{season}-03-01"
        end_date = f"{season}-11-01"
    else:
        end_date = datetime.today().strftime('%Y-%m-%d')
        start_date = (datetime.today() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    try:
        df = statcast_batter(start_date, end_date, player_id)
        
        if df is None or df.empty:
            return None
        
        results = {
            'player_id': player_id,
            'period_days': days,
            'pitches_seen': len(df),
            'zones': {},
            'overall_metrics': {}
        }
        
        # Overall whiff and chase rates
        swings = df[df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked', 
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        whiffs = df[df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked'
        ])]
        
        results['overall_metrics']['whiff_pct'] = round(
            len(whiffs) / len(swings) * 100 if len(swings) > 0 else 0, 1
        )
        
        # Chase rate
        chase_pitches = df[df['zone'].isin(CHASE_ZONES)]
        chase_swings = chase_pitches[chase_pitches['description'].isin([
            'swinging_strike', 'swinging_strike_blocked', 
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        results['overall_metrics']['chase_pct'] = round(
            len(chase_swings) / len(chase_pitches) * 100 if len(chase_pitches) > 0 else 0, 1
        )
        
        # Zone-by-zone performance
        for zone in range(1, 15):
            zone_df = df[df['zone'] == zone]
            
            if len(zone_df) < 5:
                continue
            
            zone_abs = zone_df[zone_df['events'].notna()]
            zone_hits = zone_abs[zone_abs['events'].isin([
                'single', 'double', 'triple', 'home_run'
            ])]
            
            zone_swings = zone_df[zone_df['description'].isin([
                'swinging_strike', 'swinging_strike_blocked', 
                'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
            ])]
            zone_whiffs = zone_df[zone_df['description'].isin([
                'swinging_strike', 'swinging_strike_blocked'
            ])]
            
            swing_pct = len(zone_swings) / len(zone_df) if len(zone_df) > 0 else 0
            whiff_pct = len(zone_whiffs) / len(zone_swings) if len(zone_swings) > 0 else 0
            ba = len(zone_hits) / len(zone_abs) if len(zone_abs) > 0 else 0
            
            xba = zone_abs['estimated_ba_using_speedangle'].mean() if 'estimated_ba_using_speedangle' in zone_abs.columns else None
            
            results['zones'][zone] = {
                'name': ZONE_NAMES.get(zone, f"Zone {zone}"),
                'pitches_seen': len(zone_df),
                'swing_pct': round(swing_pct * 100, 1),
                'whiff_pct': round(whiff_pct * 100, 1),
                'ba': round(ba, 3),
                'xba': round(xba, 3) if xba and not pd.isna(xba) else None,
                'is_damage_zone': ba > 0.300,
                'is_weakness': ba < 0.180 and swing_pct > 0.50
            }
        
        return results
        
    except Exception as e:
        print(f"Error fetching hitter Statcast data: {e}")
        return None


# =============================================================================
# HEAT MAP FUNCTIONS
# =============================================================================

def get_pitcher_attack_map(player_id: int, days: int = 30) -> Optional[Dict]:
    """Generate heat map data showing where pitcher attacks."""
    profile = get_pitcher_statcast_profile(player_id, days)
    
    if not profile or not profile.get('zone_breakdown'):
        return None
    
    zones = profile['zone_breakdown']
    
    grid = {}
    for zone in range(1, 15):
        zone_data = zones.get(zone, {})
        usage = zone_data.get('pitch_pct', 0)
        whiff = zone_data.get('whiff_pct', 20)
        
        if whiff >= 30:
            color = 'green'
        elif whiff >= 22:
            color = 'yellow'
        else:
            color = 'red'
        
        grid[zone] = {
            'usage': usage,
            'whiff_pct': whiff,
            'color': color
        }
    
    return {
        'player_id': player_id,
        'grid': grid,
        'primary_zone': max(range(1, 10), key=lambda z: grid.get(z, {}).get('usage', 0)),
        'best_zone': max(range(1, 10), key=lambda z: grid.get(z, {}).get('whiff_pct', 0)),
    }


def get_hitter_damage_map(player_id: int, days: int = 30) -> Optional[Dict]:
    """Generate heat map data showing where hitter does damage."""
    profile = get_hitter_zone_profile(player_id, days)
    
    if not profile or not profile.get('zones'):
        return None
    
    zones = profile['zones']
    
    grid = {}
    for zone in range(1, 15):
        zone_data = zones.get(zone, {})
        ba = zone_data.get('ba', 0.250)
        
        if ba >= 0.320:
            color = 'red'
        elif ba >= 0.270:
            color = 'orange'
        elif ba >= 0.220:
            color = 'yellow'
        else:
            color = 'blue'
        
        grid[zone] = {
            'ba': ba,
            'swing_pct': zone_data.get('swing_pct', 50),
            'color': color,
            'is_damage': zone_data.get('is_damage_zone', False),
            'is_weakness': zone_data.get('is_weakness', False)
        }
    
    damage_zones = [z for z in range(1, 10) if grid.get(z, {}).get('is_damage', False)]
    weakness_zones = [z for z in range(1, 10) if grid.get(z, {}).get('is_weakness', False)]
    
    return {
        'player_id': player_id,
        'grid': grid,
        'damage_zones': damage_zones,
        'weakness_zones': weakness_zones,
        'best_zone': max(range(1, 10), key=lambda z: grid.get(z, {}).get('ba', 0)),
        'worst_zone': min(range(1, 10), key=lambda z: grid.get(z, {}).get('ba', 1)),
    }


def analyze_matchup_zones(pitcher_id: int, hitter_id: int, days: int = 30) -> Optional[Dict]:
    """Analyze zone overlap between pitcher and hitter."""
    pitcher_map = get_pitcher_attack_map(pitcher_id, days)
    hitter_map = get_hitter_damage_map(hitter_id, days)
    
    if not pitcher_map or not hitter_map:
        return None
    
    danger_zones = []
    advantage_zones = []
    
    for zone in range(1, 10):
        pitcher_usage = pitcher_map['grid'].get(zone, {}).get('usage', 0)
        hitter_ba = hitter_map['grid'].get(zone, {}).get('ba', 0.250)
        
        if pitcher_usage >= 8:
            if hitter_ba >= 0.300:
                danger_zones.append({
                    'zone': zone,
                    'name': ZONE_NAMES[zone],
                    'pitcher_usage': pitcher_usage,
                    'hitter_ba': hitter_ba
                })
            elif hitter_ba < 0.200:
                advantage_zones.append({
                    'zone': zone,
                    'name': ZONE_NAMES[zone],
                    'pitcher_usage': pitcher_usage,
                    'hitter_ba': hitter_ba
                })
    
    edge_score = len(advantage_zones) - len(danger_zones)
    
    if edge_score >= 2:
        matchup_edge = "PITCHER ADVANTAGE"
        edge_desc = "Pitcher can attack zones where hitter struggles"
    elif edge_score <= -2:
        matchup_edge = "HITTER ADVANTAGE"  
        edge_desc = "Pitcher tends to throw where hitter does damage"
    else:
        matchup_edge = "NEUTRAL"
        edge_desc = "No significant zone advantage either way"
    
    return {
        'pitcher_id': pitcher_id,
        'hitter_id': hitter_id,
        'danger_zones': danger_zones,
        'advantage_zones': advantage_zones,
        'edge_score': edge_score,
        'matchup_edge': matchup_edge,
        'edge_description': edge_desc
    }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def classify_pitcher_profile(stuff_plus: float, location_plus: float) -> Tuple[str, str]:
    """Classify pitcher profile based on Stuff+ and Location+."""
    if stuff_plus is None or location_plus is None:
        return ("UNKNOWN", "Insufficient data")
    
    if stuff_plus >= 115 and location_plus >= 110:
        return ("ELITE", "True ace - elite arsenal with pinpoint command")
    elif stuff_plus >= 115 and location_plus < 100:
        return ("STUFF-DOMINANT", "High ceiling, high variance - lives on swing-and-miss")
    elif stuff_plus < 100 and location_plus >= 115:
        return ("LOCATION-DOMINANT", "Lower ceiling, consistent - lives on weak contact")
    elif stuff_plus >= 105 and location_plus >= 105:
        return ("BALANCED-PLUS", "Quality stuff and command - reliable performer")
    elif stuff_plus >= 95 and location_plus >= 95:
        return ("BALANCED", "Average stuff and command - matchup-dependent")
    elif stuff_plus >= 95 or location_plus >= 95:
        return ("ONE-TOOL", "Has one above-average skill - streaky")
    else:
        return ("LIMITED", "Below average stuff and command - fade candidate")


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
# TEST
# =============================================================================

if __name__ == "__main__":
    print("SALCI v2 Statcast Connector Test")
    print("=" * 50)
    
    if not PYBASEBALL_AVAILABLE:
        print("ERROR: pybaseball not installed")
        print("Run: pip install pybaseball")
    else:
        print("pybaseball is available!")
        print("\nSALCI v2 Weights:")
        print("  Stuff: 30%")
        print("  Location: 25%")
        print("  Matchup: 25%")
        print("  Workload: 20%")
        print("\nExample usage:")
        print("  profile = get_pitcher_statcast_profile(669203, days=30)")
        print("  print(f'Physics-based Stuff+: {profile[\"stuff_plus\"]}')")
