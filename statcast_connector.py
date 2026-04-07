"""
SALCI v5.0 - Statcast Data Connector & Scoring Engine
======================================================

Physics-based Stuff+ and Location+ calculations using real Statcast data.
Implements SALCI v3 formula optimized for STRIKEOUT PREDICTION.

SALCI v3 WEIGHTS (Optimized for Ks):
- Stuff: 40% (primary K driver - whiff/power potential)
- Matchup: 25% (split into Opp K% 15% + Opp Zone Contact% 10%)
- Workload: 20% (projected outs, leash factor, TTT penalty)
- Location: 15% (command - less important for Ks specifically)

KEY CHANGES FROM v2:
- Stuff increased from 30% to 40% (Ks are driven by whiffs)
- Location decreased from 25% to 15% (good location = pitching to contact)
- Matchup split into K-propensity (15%) and Zone Contact (10%)
- Workload includes "Leash Factor" for manager tendencies
- Lineup-level matchup using individual hitter K%

Installation:
    pip install pybaseball

Author: SALCI Development Team
Version: 3.0
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import warnings
from scipy.stats import poisson

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
# SALCI v3 WEIGHTS
# =============================================================================

SALCI_V3_WEIGHTS = {
    'stuff': 0.40,      # +10% from v2 - primary K driver
    'matchup': 0.25,    # Same total, but split differently
    'workload': 0.20,   # Same - includes leash factor
    'location': 0.15,   # -10% from v2 - less important for Ks
}

# Matchup sub-weights (within the 25%)
MATCHUP_SUBWEIGHTS = {
    'opp_k_pct': 0.60,        # 15% of total (0.60 * 0.25)
    'opp_zone_contact': 0.40,  # 10% of total (0.40 * 0.25)
}


# =============================================================================
# CONSTANTS & LEAGUE BASELINES (2024-2025 averages)
# =============================================================================

LEAGUE_BASELINES = {
    # Fastball metrics
    'ff_velo': 94.5,
    'ff_velo_std': 2.3,
    'ff_ivb': 14.5,
    'ff_ivb_std': 3.2,
    'ff_hb': 7.5,
    'ff_hb_std': 2.8,
    'ff_spin': 2250,
    'ff_spin_std': 180,
    
    # Breaking ball metrics
    'sl_velo': 85.5,
    'sl_hb': 5.5,
    'sl_hb_std': 3.5,
    'sl_vb': 2.0,
    'sl_spin': 2450,
    
    # Curveball metrics
    'cu_velo': 79.0,
    'cu_vb': -6.0,
    'cu_spin': 2700,
    
    # Changeup metrics
    'ch_velo_diff': 8.5,
    'ch_drop': 6.0,
    'ch_fade': 4.0,
    
    # Location metrics
    'zone_pct': 0.45,
    'edge_pct': 0.28,
    'heart_pct': 0.12,
    'chase_rate': 0.30,
    'csw_pct': 0.29,
    'first_pitch_strike': 0.60,
    
    # Outcome metrics
    'whiff_pct': 0.25,
    'k_pct': 0.22,
    'zone_contact_pct': 0.82,  # NEW: Contact rate on pitches in zone
    
    # Workload metrics
    'avg_pitch_count': 88,
    'avg_ip': 5.5,
    'ttt_k_drop': 0.03,  # K% typically drops 3% third time through
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
IN_ZONE = list(range(1, 10))


# =============================================================================
# STUFF+ CALCULATION (Physics-Based) - v3 Enhanced
# =============================================================================

def calculate_stuff_plus(df: pd.DataFrame) -> Dict:
    """
    Calculate physics-based Stuff+ from Statcast pitch data.
    
    v3 Enhancement: Also calculates CSW% contribution since CSW is the 
    best single predictor of K/9.
    
    Uses only physical traits:
    - Velocity, Movement (pfx_x, pfx_z), Spin rate, Extension
    - Velocity differentials for secondary pitches
    
    Returns:
        Dict with stuff_plus (100 = average) and per-pitch breakdown
    """
    if df is None or df.empty:
        return None
    
    results = {
        'stuff_plus': None,
        'by_pitch_type': {},
        'arsenal_summary': {},
        'raw_metrics': {},
        'csw_pct': None,  # v3: Track CSW for K prediction
    }
    
    # Calculate overall CSW% (Called Strikes + Whiffs)
    total_pitches = len(df)
    called_strikes = df[df['description'] == 'called_strike']
    whiffs = df[df['description'].isin(['swinging_strike', 'swinging_strike_blocked'])]
    csw_pct = (len(called_strikes) + len(whiffs)) / total_pitches if total_pitches > 0 else 0.29
    results['csw_pct'] = round(csw_pct * 100, 1)
    
    # Get primary fastball baseline
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
    results['raw_metrics']['csw_pct'] = results['csw_pct']
    
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
        extension = pitch_df['release_extension'].mean() if 'release_extension' in pitch_df.columns else 6.0
        
        velo_diff = fb_velo - velo
        ivb_diff = fb_ivb - ivb
        
        # Physics-based Stuff score by pitch type
        if pitch_type == 'FF':
            velo_z = (velo - LEAGUE_BASELINES['ff_velo']) / LEAGUE_BASELINES['ff_velo_std']
            ivb_z = (ivb - LEAGUE_BASELINES['ff_ivb']) / LEAGUE_BASELINES['ff_ivb_std']
            ext_bonus = (extension - 6.0) * 2 if extension > 6.0 else 0
            raw_stuff = (velo_z * 0.50) + (ivb_z * 0.35) + (ext_bonus * 0.05)
            
        elif pitch_type == 'SI':
            velo_z = (velo - (LEAGUE_BASELINES['ff_velo'] - 1.5)) / 2.0
            hb_z = (abs(hb) - 14) / 3.5
            drop_z = (fb_ivb - ivb - 4) / 2.5
            raw_stuff = (velo_z * 0.40) + (hb_z * 0.35) + (drop_z * 0.25)
            
        elif pitch_type == 'FC':
            velo_z = (velo - (LEAGUE_BASELINES['ff_velo'] - 3)) / 2.0
            cut_z = (abs(hb) - 3.5) / 2.0
            raw_stuff = (velo_z * 0.50) + (cut_z * 0.30)
            
        elif pitch_type in ['SL', 'ST', 'SV']:
            sweep_z = (abs(hb) - LEAGUE_BASELINES['sl_hb']) / LEAGUE_BASELINES['sl_hb_std']
            velo_diff_z = (velo_diff - 9) / 2.5
            drop_z = (ivb_diff - 10) / 4.0
            raw_stuff = (sweep_z * 0.40) + (drop_z * 0.30) + (velo_diff_z * 0.15)
            
        elif pitch_type in ['CU', 'KC']:
            drop_z = (-ivb - 6) / 3.0
            spin_z = (spin - LEAGUE_BASELINES['cu_spin']) / 300
            velo_diff_z = (velo_diff - 15) / 3.0
            raw_stuff = (drop_z * 0.45) + (spin_z * 0.25) + (velo_diff_z * 0.20)
            
        elif pitch_type == 'CH':
            velo_diff_z = (velo_diff - LEAGUE_BASELINES['ch_velo_diff']) / 2.0
            fade_z = (abs(hb) - fb_hb - LEAGUE_BASELINES['ch_fade']) / 2.5
            drop_z = (ivb_diff - LEAGUE_BASELINES['ch_drop']) / 2.5
            raw_stuff = (velo_diff_z * 0.35) + (fade_z * 0.30) + (drop_z * 0.35)
            
        elif pitch_type == 'FS':
            drop_z = (ivb_diff - 8) / 3.0
            velo_z = (velo_diff - 6) / 2.0
            raw_stuff = (drop_z * 0.50) + (velo_z * 0.30)
            
        else:
            raw_stuff = 0
        
        # Convert to 100-scale
        stuff_plus = 100 + (raw_stuff * 10)
        stuff_plus = max(60, min(140, stuff_plus))
        
        usage_pct = len(pitch_df) / len(df)
        
        # Calculate observed whiff rate
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
        
        pitch_stuff_scores.append((stuff_plus, usage_pct))
    
    # Calculate weighted overall Stuff+
    if pitch_stuff_scores:
        total_weight = sum(w for _, w in pitch_stuff_scores)
        weighted_stuff = sum(s * w for s, w in pitch_stuff_scores) / total_weight if total_weight > 0 else 100
        results['stuff_plus'] = round(weighted_stuff, 0)
    
    return results


# =============================================================================
# LOCATION+ CALCULATION - v3 (Reduced weight for K prediction)
# =============================================================================

def calculate_location_plus(df: pd.DataFrame) -> Dict:
    """
    Calculate Location+ from Statcast pitch data.
    
    Note: For K prediction, Location is less important (15% weight in v3).
    High Location+ often means "pitching to contact" which reduces Ks.
    
    Components:
    - Zone Rate, Edge Rate, Heart Rate (avoid middle)
    - Chase Rate induced, First Pitch Strike %, CSW%
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
    in_zone = zone_data.isin(IN_ZONE).sum()
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
    
    # CSW%
    called_strikes = df[df['description'] == 'called_strike']
    whiffs = df[df['description'].isin(['swinging_strike', 'swinging_strike_blocked'])]
    csw_pct = (len(called_strikes) + len(whiffs)) / total_pitches
    
    results['metrics'] = {
        'zone_pct': round(zone_pct * 100, 1),
        'edge_pct': round(edge_pct * 100, 1),
        'heart_pct': round(heart_pct * 100, 1),
        'chase_zone_pct': round(chase_zone_pct * 100, 1),
        'chase_rate': round(chase_rate * 100, 1),
        'fps_pct': round(fps_rate * 100, 1),
        'csw_pct': round(csw_pct * 100, 1),
    }
    
    # Location+ calculation
    zone_z = -abs(zone_pct - 0.47) / 0.05
    edge_z = (edge_pct - LEAGUE_BASELINES['edge_pct']) / 0.05
    heart_z = -(heart_pct - LEAGUE_BASELINES['heart_pct']) / 0.04
    chase_z = (chase_rate - LEAGUE_BASELINES['chase_rate']) / 0.05
    fps_z = (fps_rate - LEAGUE_BASELINES['first_pitch_strike']) / 0.06
    csw_z = (csw_pct - LEAGUE_BASELINES['csw_pct']) / 0.04
    
    raw_location = (
        zone_z * 0.10 +
        edge_z * 0.25 +
        heart_z * 0.20 +
        chase_z * 0.20 +
        fps_z * 0.10 +
        csw_z * 0.15
    )
    
    location_plus = 100 + (raw_location * 10)
    location_plus = max(70, min(130, location_plus))
    
    results['location_plus'] = round(location_plus, 0)
    
    # Zone-by-zone breakdown
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
# MATCHUP SCORE - v3 REFINED (Split into K% and Zone Contact%)
# =============================================================================

def calculate_matchup_score_v3(
    opp_team_stats: Dict,
    lineup_hitter_stats: Optional[List[Dict]] = None,
    pitcher_hand: str = 'R'
) -> Tuple[float, Dict]:
    """
    Calculate Matchup score for SALCI v3.
    
    v3 CHANGES:
    - Split into Opp K% (60% of matchup) and Opp Zone Contact% (40% of matchup)
    - Uses individual hitter stats from confirmed lineup when available
    - Falls back to team-level stats when lineup not confirmed
    
    Args:
        opp_team_stats: Team-level batting stats (OppK%, OppContact%)
        lineup_hitter_stats: List of individual hitter stats from confirmed lineup
        pitcher_hand: 'R' or 'L'
    
    Returns:
        Tuple of (score 0-100, breakdown dict)
    """
    breakdown = {
        'source': 'team',  # or 'lineup'
        'opp_k_pct': {},
        'opp_zone_contact': {},
        'platoon': {},
        'individual_hitters': []
    }
    
    # ===========================================
    # Use lineup-level stats if available (more accurate)
    # ===========================================
    if lineup_hitter_stats and len(lineup_hitter_stats) >= 5:
        breakdown['source'] = 'lineup'
        
        # Calculate lineup averages
        total_weight = 0
        weighted_k_sum = 0
        weighted_contact_sum = 0
        same_hand_count = 0
        
        for i, hitter in enumerate(lineup_hitter_stats):
            # Weight by batting order (top of order matters more)
            order_weight = 1.0 + (0.1 * (9 - i)) if i < 9 else 0.5
            
            k_rate = hitter.get('k_rate', 0.22)
            zone_contact = hitter.get('zone_contact_pct', 0.82)
            bat_side = hitter.get('bat_side', 'R')
            
            weighted_k_sum += k_rate * order_weight
            weighted_contact_sum += zone_contact * order_weight
            total_weight += order_weight
            
            # Count same-hand matchups (pitcher advantage)
            if (pitcher_hand == 'R' and bat_side == 'R') or (pitcher_hand == 'L' and bat_side == 'L'):
                same_hand_count += 1
            
            breakdown['individual_hitters'].append({
                'name': hitter.get('name', f'Hitter {i+1}'),
                'order': i + 1,
                'k_rate': round(k_rate * 100, 1),
                'zone_contact': round(zone_contact * 100, 1),
                'bat_side': bat_side,
                'platoon': 'adv' if ((pitcher_hand == 'R' and bat_side == 'R') or 
                                     (pitcher_hand == 'L' and bat_side == 'L')) else 'dis'
            })
        
        opp_k_pct = weighted_k_sum / total_weight if total_weight > 0 else 0.22
        opp_zone_contact = weighted_contact_sum / total_weight if total_weight > 0 else 0.82
        same_side_pct = same_hand_count / len(lineup_hitter_stats)
        
    else:
        # ===========================================
        # Fall back to team-level stats
        # ===========================================
        breakdown['source'] = 'team'
        opp_k_pct = opp_team_stats.get('OppK%', 0.22)
        opp_zone_contact = opp_team_stats.get('OppZoneContact%', 
                                               1 - opp_team_stats.get('OppK%', 0.22) * 0.5)  # Estimate
        same_side_pct = 0.50  # Unknown without lineup
    
    # ===========================================
    # Calculate z-scores
    # ===========================================
    
    # Opp K%: Higher is better for pitcher (more Ks expected)
    k_z = (opp_k_pct - 0.22) / 0.03
    k_z = max(-2, min(2, k_z))
    breakdown['opp_k_pct'] = {
        'value': round(opp_k_pct * 100, 1),
        'z_score': round(k_z, 2),
        'interpretation': 'high_k' if k_z > 0.5 else 'low_k' if k_z < -0.5 else 'avg_k'
    }
    
    # Opp Zone Contact%: Lower is better for pitcher (more whiffs in zone)
    contact_z = -(opp_zone_contact - LEAGUE_BASELINES['zone_contact_pct']) / 0.04
    contact_z = max(-2, min(2, contact_z))
    breakdown['opp_zone_contact'] = {
        'value': round(opp_zone_contact * 100, 1),
        'z_score': round(contact_z, 2),
        'interpretation': 'easy_contact' if contact_z < -0.5 else 'tough_contact' if contact_z > 0.5 else 'avg_contact'
    }
    
    # Platoon advantage
    platoon_z = (same_side_pct - 0.50) / 0.15
    platoon_z = max(-1.5, min(1.5, platoon_z))
    breakdown['platoon'] = {
        'same_side_pct': round(same_side_pct * 100, 1),
        'z_score': round(platoon_z, 2)
    }
    
    # ===========================================
    # Weighted combination (v3 split)
    # ===========================================
    # Opp K% is 60% of matchup score, Zone Contact is 40%
    raw_matchup = (
        k_z * MATCHUP_SUBWEIGHTS['opp_k_pct'] +      # 60%
        contact_z * MATCHUP_SUBWEIGHTS['opp_zone_contact'] +  # 40%
        platoon_z * 0.10  # Small platoon bonus
    )
    
    # Normalize (reduce platoon contribution to keep within bounds)
    raw_matchup = raw_matchup / 1.10
    
    matchup_score = 50 + (raw_matchup * 15)
    matchup_score = max(20, min(80, matchup_score))
    
    return round(matchup_score, 1), breakdown


# =============================================================================
# WORKLOAD / LEASH SCORE - v3 ENHANCED
# =============================================================================

def calculate_workload_score_v3(
    pitcher_stats: Dict,
    manager_leash: Optional[Dict] = None,
    recent_games: Optional[List[Dict]] = None
) -> Tuple[float, Dict]:
    """
    Calculate Workload/Leash score for SALCI v3.
    
    v3 ENHANCEMENTS:
    - "Leash Factor": Manager's tendency to pull starters early
    - K% by time through order (TTT penalty)
    - Projected batters faced (not just IP)
    
    Components:
    - P/IP efficiency (25%)
    - Projected batters faced (30%)
    - Leash factor (25%)
    - TTT K% drop (20%)
    """
    breakdown = {
        'p_ip': {},
        'projected_bf': {},
        'leash_factor': {},
        'ttt_penalty': {},
    }
    
    # P/IP: Lower is better (more efficient = more batters faced)
    p_ip = pitcher_stats.get('P/IP', 16.0)
    p_ip_z = -(p_ip - 15.5) / 2.0
    p_ip_z = max(-2, min(2, p_ip_z))
    breakdown['p_ip'] = {
        'value': round(p_ip, 1),
        'z_score': round(p_ip_z, 2),
        'interpretation': 'efficient' if p_ip < 15 else 'inefficient' if p_ip > 17 else 'average'
    }
    
    # Projected batters faced (based on avg IP and efficiency)
    avg_ip = pitcher_stats.get('avg_ip', 5.5)
    # Batters per inning estimate: ~4.3 is average
    bpi = 3 + (p_ip / 15)  # More pitches = more baserunners = more batters
    projected_bf = avg_ip * bpi
    bf_z = (projected_bf - 24) / 4  # 24 BF is ~5.5 IP average
    bf_z = max(-2, min(2, bf_z))
    breakdown['projected_bf'] = {
        'value': round(projected_bf, 1),
        'z_score': round(bf_z, 2),
        'projected_ip': round(avg_ip, 1)
    }
    
    # Leash factor: Manager's tendency to pull early
    if manager_leash:
        avg_pitch_count = manager_leash.get('avg_pitch_count', 88)
        quick_hook_pct = manager_leash.get('quick_hook_pct', 0.25)  # % of starts < 5 IP
    else:
        avg_pitch_count = pitcher_stats.get('avg_pitch_count', 88)
        quick_hook_pct = pitcher_stats.get('quick_hook_pct', 0.25)
    
    # Lower avg pitch count = tighter leash = fewer K opportunities
    leash_z = (avg_pitch_count - LEAGUE_BASELINES['avg_pitch_count']) / 10
    leash_z = leash_z - (quick_hook_pct - 0.25) * 2  # Penalty for quick hooks
    leash_z = max(-2, min(2, leash_z))
    breakdown['leash_factor'] = {
        'avg_pitch_count': round(avg_pitch_count, 0),
        'quick_hook_pct': round(quick_hook_pct * 100, 1),
        'z_score': round(leash_z, 2),
        'interpretation': 'long_leash' if leash_z > 0.5 else 'short_leash' if leash_z < -0.5 else 'normal'
    }
    
    # TTT (Third Time Through) K% penalty
    # Most pitchers see K% drop 2-4% third time through
    ttt_k_drop = pitcher_stats.get('ttt_k_drop', LEAGUE_BASELINES['ttt_k_drop'])
    ttt_z = -ttt_k_drop / 0.03  # Negative because drop is bad
    ttt_z = max(-2, min(2, ttt_z))
    breakdown['ttt_penalty'] = {
        'k_drop_pct': round(ttt_k_drop * 100, 1),
        'z_score': round(ttt_z, 2),
        'interpretation': 'fades' if ttt_z < -0.5 else 'maintains' if ttt_z > 0.5 else 'normal'
    }
    
    # Weighted combination (v3)
    raw_workload = (
        p_ip_z * 0.25 +
        bf_z * 0.30 +
        leash_z * 0.25 +
        ttt_z * 0.20
    )
    
    workload_score = 50 + (raw_workload * 15)
    workload_score = max(20, min(80, workload_score))
    
    return round(workload_score, 1), breakdown


# =============================================================================
# SALCI v3 MASTER CALCULATION
# =============================================================================

def calculate_salci_v3(
    stuff_score: float,
    location_score: float,
    matchup_score: float,
    workload_score: float
) -> Dict:
    """
    Calculate SALCI v3 using K-optimized weights.
    
    SALCI v3 = (0.40 × Stuff) + (0.15 × Location) + (0.25 × Matchup) + (0.20 × Workload)
    
    Args:
        stuff_score: Stuff+ (100 = average)
        location_score: Location+ (100 = average)
        matchup_score: Matchup score (0-100, 50 = average)
        workload_score: Workload score (0-100, 50 = average)
    
    Returns:
        Dict with SALCI score, grade, and component breakdown
    """
    # Normalize Stuff+ and Location+ from 100-centered to 0-100 scale
    # 100 → 50, 120 → 70, 80 → 30
    stuff_normalized = 50 + (stuff_score - 100) if stuff_score else 50
    location_normalized = 50 + (location_score - 100) if location_score else 50
    
    # Clamp all to valid range
    stuff_normalized = max(20, min(80, stuff_normalized))
    location_normalized = max(20, min(80, location_normalized))
    matchup_clamped = max(20, min(80, matchup_score))
    workload_clamped = max(20, min(80, workload_score))
    
    # Apply SALCI v3 weights
    salci = (
        stuff_normalized * SALCI_V3_WEIGHTS['stuff'] +
        location_normalized * SALCI_V3_WEIGHTS['location'] +
        matchup_clamped * SALCI_V3_WEIGHTS['matchup'] +
        workload_clamped * SALCI_V3_WEIGHTS['workload']
    )
    
    # Determine grade
    if salci >= 70:
        grade = 'A'
        grade_desc = 'Elite K upside'
    elif salci >= 60:
        grade = 'B'
        grade_desc = 'Strong K potential'
    elif salci >= 50:
        grade = 'C'
        grade_desc = 'Average'
    elif salci >= 40:
        grade = 'D'
        grade_desc = 'Below average'
    else:
        grade = 'F'
        grade_desc = 'Fade'
    
    return {
        'salci': round(salci, 1),
        'grade': grade,
        'grade_desc': grade_desc,
        'version': 'v3',
        'components': {
            'stuff': {
                'raw': stuff_score,
                'normalized': round(stuff_normalized, 1),
                'weight': SALCI_V3_WEIGHTS['stuff'],
                'contribution': round(stuff_normalized * SALCI_V3_WEIGHTS['stuff'], 1),
                'grade': get_component_grade(stuff_score, is_100_scale=True)
            },
            'location': {
                'raw': location_score,
                'normalized': round(location_normalized, 1),
                'weight': SALCI_V3_WEIGHTS['location'],
                'contribution': round(location_normalized * SALCI_V3_WEIGHTS['location'], 1),
                'grade': get_component_grade(location_score, is_100_scale=True)
            },
            'matchup': {
                'raw': matchup_score,
                'normalized': round(matchup_clamped, 1),
                'weight': SALCI_V3_WEIGHTS['matchup'],
                'contribution': round(matchup_clamped * SALCI_V3_WEIGHTS['matchup'], 1),
                'grade': get_component_grade(matchup_score, is_100_scale=False)
            },
            'workload': {
                'raw': workload_score,
                'normalized': round(workload_clamped, 1),
                'weight': SALCI_V3_WEIGHTS['workload'],
                'contribution': round(workload_clamped * SALCI_V3_WEIGHTS['workload'], 1),
                'grade': get_component_grade(workload_score, is_100_scale=False)
            },
        }
    }


def calculate_volatility_buffer(stuff_plus: float, location_plus: float) -> float:
    """Higher volatility = wider spread → more conservative floor."""
    if stuff_plus is None or location_plus is None:
        return 1.2
    
    gap = stuff_plus - location_plus
    
    # Stuff-dominant pitchers are boom/bust
    if gap > 18:      # e.g. 122 Stuff + 98 Loc
        return 1.85
    elif gap > 12:
        return 1.55
    elif gap > 5:
        return 1.30
    # Location-dominant = very predictable
    elif gap < -12:
        return 0.85
    else:
        return 1.10  # balanced = normal MLB variance




def get_component_grade(score: float, is_100_scale: bool = True) -> str:
    """Convert score to letter grade."""
    if is_100_scale:
        # For Stuff+/Location+ (100 = average)
        if score >= 115: return 'A+'
        if score >= 110: return 'A'
        if score >= 105: return 'B+'
        if score >= 100: return 'B'
        if score >= 95: return 'C+'
        if score >= 90: return 'C'
        return 'D'
    else:
        # For 0-100 scale (50 = average)
        if score >= 70: return 'A'
        if score >= 60: return 'B'
        if score >= 50: return 'C'
        if score >= 40: return 'D'
        return 'F'


def calculate_expected_ks_v3(
    salci_result: Dict,
    projected_ip: float = 5.5,
    efficiency_factor: float = 1.0
) -> Dict:
    """
    FINAL VERSION - SALCI v3 → Expected Ks + "At Least X Ks" Floor
    Uses Poisson distribution + profile-aware volatility.
    """
    salci = salci_result['salci']
    components = salci_result.get('components', {})
    stuff = components.get('stuff', {}).get('raw', 100)
    location = components.get('location', {}).get('raw', 100)

    # 1. Mean Expected Ks
    k_per_ip = (salci / 50) * 1.0
    k_per_ip = max(0.5, min(2.0, k_per_ip))
    expected_ks = k_per_ip * projected_ip * efficiency_factor

    # 2. Volatility (Stuff-dominant = higher variance)
    volatility = calculate_volatility_buffer(stuff, location)

    # 3. Statistical Floor: highest K with P(X ≥ K) ≥ 60%
    floor = 0
    lambda_ks = expected_ks
    for k in range(0, int(expected_ks) + 8):
        prob_ge_k = 1 - poisson.cdf(k - 1, lambda_ks) if k > 0 else 1.0
        if prob_ge_k >= 0.60:
            floor = k
        else:
            break

    floor_confidence = int((1 - poisson.cdf(floor - 1, lambda_ks)) * 100) if floor > 0 else 100

    # 4. K-lines (At Least probabilities)
    k_lines = {}
    for i in range(4):
        k_value = floor + i
        prob_ge = 1 - poisson.cdf(k_value - 1, lambda_ks)
        prob_pct = max(5, min(100, int(prob_ge * 100)))
        k_lines[k_value] = prob_pct

    return {
        'expected': round(expected_ks, 1),           # ← UI key
        'floor': floor,
        'floor_confidence': floor_confidence,
        'volatility': round(volatility, 2),
        'k_per_ip': round(k_per_ip, 2),
        'projected_ip': projected_ip,
        'k_lines': k_lines,
        'best_line': floor,
        'grade': salci_result.get('grade', 'C')
    }


# =============================================================================
# PITCHER PROFILE & CLASSIFICATION
# =============================================================================

def classify_pitcher_profile(stuff_plus: float, location_plus: float) -> Tuple[str, str]:
    """Classify pitcher profile based on Stuff+ and Location+."""
    if stuff_plus is None or location_plus is None:
        return ("UNKNOWN", "Insufficient data")
    
    if stuff_plus >= 115 and location_plus >= 110:
        return ("ELITE", "True ace - elite stuff with command")
    elif stuff_plus >= 115 and location_plus < 100:
        return ("STUFF-DOMINANT", "High K ceiling, some variance")
    elif stuff_plus < 100 and location_plus >= 115:
        return ("LOCATION-DOMINANT", "Efficient but lower K ceiling")
    elif stuff_plus >= 108 and location_plus >= 105:
        return ("BALANCED-PLUS", "Quality all-around")
    elif stuff_plus >= 100 and location_plus >= 100:
        return ("BALANCED", "League average, matchup-dependent")
    elif stuff_plus >= 100 or location_plus >= 100:
        return ("ONE-TOOL", "One above-average skill")
    else:
        return ("LIMITED", "Below average profile")


def get_pitcher_statcast_profile(
    player_id: int, 
    days: int = 30,
    season: int = None
) -> Optional[Dict]:
    """Get complete Statcast-based profile for a pitcher."""
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
        
        stuff_data = calculate_stuff_plus(df)
        location_data = calculate_location_plus(df)
        
        if stuff_data is None or location_data is None:
            return None
        
        stuff_plus = stuff_data['stuff_plus']
        location_plus = location_data['location_plus']
        profile_type, profile_desc = classify_pitcher_profile(stuff_plus, location_plus)
        
        return {
            'player_id': player_id,
            'period_days': days,
            'pitches_analyzed': len(df),
            'stuff_plus': stuff_plus,
            'location_plus': location_plus,
            'csw_pct': stuff_data.get('csw_pct'),
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
        import traceback
        print(f"Error fetching Statcast data for pitcher {player_id}: {e}")
        traceback.print_exc()
        return None


def calculate_strikeout_floor_v3(
    salci_result: Dict,
    stuff_plus: float,
    location_plus: float,
    projected_ip: float = 5.5,
    efficiency_factor: float = 1.0
) -> Dict:
    """
    Calculate the "At Least X Ks" floor for SALCI predictions.
    
    The Floor = the conservative Ks estimate we're CONFIDENT will happen
    The Ceiling = the upside scenario
    The Probability = how often pitcher hits the Floor
    
    Key Insight:
    - High Stuff + Low Location = High volatility (wider floor/ceiling gap)
    - High Stuff + High Location = Low volatility (tighter range, more reliable)
    
    Returns:
        Dict with floor, mean, ceiling, and confidence
    """
    salci = salci_result.get('salci', 50)
    
    # 1. Calculate Mean Expected Ks
    # (This is what we already do)
    k_per_ip = (salci / 50) * 1.0  # SALCI 50 = 1.0 K/IP
    k_per_ip = max(0.5, min(2.0, k_per_ip))
    mean_ks = k_per_ip * projected_ip * efficiency_factor
    
    # 2. Calculate Volatility (Standard Deviation)
    # Based on Stuff vs Location gap (the "profile mismatch")
    gap = None
    if stuff_plus and location_plus:
        # Gap measures variance
        # High Stuff + Low Location = Volatile pitcher
        # Balanced pitcher = Consistent
        gap = stuff_plus - location_plus
        
        # Base volatility (StdDev in K count)
        if gap > 20:  # Stuff-dominant (e.g., 120 Stuff, 95 Loc)
            volatility = 1.8  # High variance (±1.8 Ks)
        elif gap > 10:  # Stuff-first (e.g., 115 Stuff, 100 Loc)
            volatility = 1.4
        elif gap > -10:  # Balanced (e.g., 105 Stuff, 105 Loc)
            volatility = 1.0  # Standard variance
        elif gap < -10:  # Location-dominant (e.g., 95 Stuff, 115 Loc)
            volatility = 0.8  # More predictable
        else:
            volatility = 1.2
    else:
        volatility = 1.2  # Default when no Statcast data
    
    # 3. Calculate Floor, Mean, Ceiling
    # Using normal distribution approximation
    # Floor = Mean - 1 SD (68% confidence, ~1 std dev below)
    # Ceiling = Mean + 1 SD
    floor = max(0, mean_ks - volatility)
    ceiling = mean_ks + volatility
    
    # 4. Calculate Confidence Score (0-100)
    # How confident are we the pitcher hits the Floor?
    # Higher Location+ = Higher confidence
    # Higher volatility = Lower confidence
    base_confidence = 70  # Baseline
    
    # Location bonus: Good command = predictable results
    location_bonus = (location_plus - 100) * 0.8 if location_plus else 0
    location_bonus = max(-15, min(15, location_bonus))
    
    # Volatility penalty: High variance = less predictable
    volatility_penalty = (volatility - 1.0) * 15
    volatility_penalty = max(0, volatility_penalty)
    
    confidence = base_confidence + location_bonus - volatility_penalty
    confidence = max(35, min(98, confidence))
    
    # 5. Determine the "Best Floor" (highest floor with >60% confidence)
    # This is the "At Least" number we're selling
    best_floor = int(np.floor(floor))
    
    return {
        # Main outputs
        'floor': best_floor,  # Conservative "At Least X"
        'mean': round(mean_ks, 1),  # Expected value
        'ceiling': round(ceiling, 1),  # Upside
        'confidence': int(confidence),  # 0-100 confidence in Floor
        
        # Details for analysis
        'volatility': round(volatility, 2),  # StdDev
        'stuff_location_gap': round(gap, 1) if gap is not None else None,
        'profile': 'Volatile' if volatility > 1.5 else 'Consistent' if volatility < 1.0 else 'Normal',
        
        # Hit probability by line (Poisson-style)
        'hit_probabilities': {
            best_floor: int(confidence),  # Confidence in hitting Floor
            best_floor + 1: int(confidence * 0.75),  # Hitting Floor+1
            best_floor + 2: int(confidence * 0.50),  # Hitting Floor+2
        },
        
        # Validation info
        'recommendation': _get_floor_recommendation(salci, confidence, best_floor)
    }


def _get_floor_recommendation(salci: float, confidence: int, floor: int) -> str:
    """Generate a recommendation based on SALCI and confidence."""
    if confidence < 50:
        return "⚠️ PASS - Too much variance, unclear edge"
    elif salci < 50:
        return "❌ FADE - Below average SALCI + low confidence"
    elif salci >= 70 and confidence >= 75:
        return "🟢 STRONG PLAY - Elite SALCI + high confidence"
    elif salci >= 60 and confidence >= 65:
        return "🟡 MODERATE PLAY - Good SALCI, decent confidence"
    elif confidence >= 60:
        return "🟡 CONDITIONAL - Confidence is there, SALCI is middle"
    else:
        return "⚠️ WEAK PLAY - Below confidence threshold"

# =============================================================================
# HITTER FUNCTIONS
# =============================================================================

def get_hitter_zone_profile(
    player_id: int,
    days: int = 30,
    season: int = None
) -> Optional[Dict]:
    """Get zone-based performance profile for a hitter."""
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
        
        # Zone contact rate (important for v3 matchup)
        zone_pitches = df[df['zone'].isin(IN_ZONE)]
        zone_swings = zone_pitches[zone_pitches['description'].isin([
            'swinging_strike', 'swinging_strike_blocked', 
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        zone_contact = zone_pitches[zone_pitches['description'].isin([
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        
        zone_contact_pct = len(zone_contact) / len(zone_swings) if len(zone_swings) > 0 else 0.82
        results['overall_metrics']['zone_contact_pct'] = round(zone_contact_pct * 100, 1)
        
        # Chase rate
        chase_pitches = df[df['zone'].isin(CHASE_ZONES)]
        chase_swings = chase_pitches[chase_pitches['description'].isin([
            'swinging_strike', 'swinging_strike_blocked', 
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        results['overall_metrics']['chase_pct'] = round(
            len(chase_swings) / len(chase_pitches) * 100 if len(chase_pitches) > 0 else 0, 1
        )
        
        # K rate estimate
        strikeouts = df[df['events'] == 'strikeout']
        plate_appearances = df[df['events'].notna()]
        results['overall_metrics']['k_rate'] = round(
            len(strikeouts) / len(plate_appearances) if len(plate_appearances) > 0 else 0.22, 3
        )
        
        return results
        
    except Exception as e:
        print(f"Error fetching hitter Statcast data: {e}")
        return None


# =============================================================================
# HEAT MAP FUNCTIONS (unchanged from v2)
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
# BACKWARD COMPATIBILITY (v2 functions that map to v3)
# =============================================================================

def calculate_matchup_score(opp_stats, pitcher_hand='R', lineup_handedness=None):
    """v2 compatibility wrapper for calculate_matchup_score_v3."""
    return calculate_matchup_score_v3(opp_stats, None, pitcher_hand)

def calculate_workload_score(pitcher_stats, recent_games=None):
    """v2 compatibility wrapper for calculate_workload_score_v3."""
    return calculate_workload_score_v3(pitcher_stats, None, recent_games)

def calculate_salci_v2(stuff, location, matchup, workload):
    """v2 compatibility - redirects to v3."""
    return calculate_salci_v3(stuff, location, matchup, workload)

def calculate_expected_ks(salci_score, projected_ip=5.5, efficiency_factor=1.0):
    """v2 compatibility wrapper."""
    salci_result = {'salci': salci_score}
    return calculate_expected_ks_v3(salci_result, projected_ip, efficiency_factor)

expected_data = calculate_expected_ks_v3(
    salci_result=salci_result,
    projected_ip=5.5,          # ← change if you have a better IP projection
    efficiency_factor=1.0      # ← 1.0 is normal; use 0.85–0.95 on short leash
)

result = {
    "salci": salci_result['salci'],
    "salci_grade": salci_result.get('grade', 'C'),
    # ... all your existing fields (stuff_score, location_score, etc.) ...
    "stuff_breakdown": stuff_breakdown,
    
    # ← NEW KEYS FROM THE FLOOR CALCULATION
    "expected": expected_data["expected"],
    "floor": expected_data["floor"],
    "floor_confidence": expected_data["floor_confidence"],
    "k_lines": expected_data["k_lines"],
}



# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("SALCI v3 Statcast Connector Test")
    print("=" * 50)
    print("\nSALCI v3 Weights (K-Optimized):")
    print(f"  Stuff:    {SALCI_V3_WEIGHTS['stuff']*100:.0f}%")
    print(f"  Matchup:  {SALCI_V3_WEIGHTS['matchup']*100:.0f}%")
    print(f"  Workload: {SALCI_V3_WEIGHTS['workload']*100:.0f}%")
    print(f"  Location: {SALCI_V3_WEIGHTS['location']*100:.0f}%")
    print("\nMatchup Sub-weights:")
    print(f"  Opp K%:         {MATCHUP_SUBWEIGHTS['opp_k_pct']*100:.0f}% of matchup")
    print(f"  Zone Contact%:  {MATCHUP_SUBWEIGHTS['opp_zone_contact']*100:.0f}% of matchup")
    
    if not PYBASEBALL_AVAILABLE:
        print("\nWARNING: pybaseball not installed")
        print("Run: pip install pybaseball")
    else:
        print("\n✅ pybaseball is available!")

