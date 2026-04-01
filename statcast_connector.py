"""
SALCI v5.0 - Statcast Data Connector
=====================================

Uses pybaseball to fetch real Statcast data from Baseball Savant.
Calculates true Stuff+ and Location+ scores from pitch-level data.

Installation:
    pip install pybaseball

Usage:
    from statcast_connector import get_pitcher_statcast_profile, get_hitter_zone_profile

Author: SALCI Development Team
Version: 1.0
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import warnings

# Suppress pybaseball warnings
warnings.filterwarnings('ignore')

try:
    from pybaseball import (
        statcast_pitcher, 
        statcast_batter,
        playerid_lookup,
        pitching_stats,
        batting_stats,
        cache
    )
    # Enable caching for faster repeated calls
    cache.enable()
    PYBASEBALL_AVAILABLE = True
except ImportError:
    PYBASEBALL_AVAILABLE = False
    print("Warning: pybaseball not installed. Run: pip install pybaseball")


# =============================================================================
# CONSTANTS
# =============================================================================

# Strike zone definitions (as seen from catcher's perspective)
# Zones 1-9 are in the strike zone, 11-14 are chase zones
ZONE_NAMES = {
    1: "High Inside", 2: "High Middle", 3: "High Outside",
    4: "Middle Inside", 5: "Heart", 6: "Middle Outside", 
    7: "Low Inside", 8: "Low Middle", 9: "Low Outside",
    11: "Chase Up-In", 12: "Chase Down-In",
    13: "Chase Up-Out", 14: "Chase Down-Out"
}

# Edge zones (corners of strike zone)
EDGE_ZONES = [1, 2, 3, 4, 6, 7, 8, 9]
HEART_ZONE = [5]
CHASE_ZONES = [11, 12, 13, 14]

# Pitch type mappings
PITCH_TYPES = {
    'FF': 'Four-Seam Fastball',
    'SI': 'Sinker',
    'FC': 'Cutter',
    'SL': 'Slider',
    'CU': 'Curveball',
    'KC': 'Knuckle Curve',
    'CH': 'Changeup',
    'FS': 'Splitter',
    'KN': 'Knuckleball',
    'ST': 'Sweeper',
    'SV': 'Slurve',
}

FASTBALLS = ['FF', 'SI', 'FC']
BREAKING = ['SL', 'CU', 'KC', 'ST', 'SV']
OFFSPEED = ['CH', 'FS']


# =============================================================================
# STUFF+ CALCULATION
# =============================================================================

def calculate_stuff_plus(df: pd.DataFrame) -> Dict:
    """
    Calculate Stuff+ score from Statcast pitch data.
    
    Based on FanGraphs methodology:
    - Velocity (raw + differential from fastball)
    - Movement (horizontal + vertical)
    - Spin rate
    - Release point consistency
    - Whiff rate induced
    
    Returns dict with overall stuff_plus and per-pitch-type breakdown.
    """
    if df is None or df.empty:
        return None
    
    results = {
        'overall_stuff_plus': None,
        'by_pitch_type': {},
        'arsenal': {},
        'metrics': {}
    }
    
    # Get fastball baseline (for differentials)
    fastballs = df[df['pitch_type'].isin(FASTBALLS)]
    if fastballs.empty:
        fb_velo = 93.0  # League average if no fastball
        fb_h_mov = 0
        fb_v_mov = 0
    else:
        fb_velo = fastballs['release_speed'].mean()
        fb_h_mov = fastballs['pfx_x'].mean() * 12  # Convert feet to inches
        fb_v_mov = fastballs['pfx_z'].mean() * 12
    
    results['metrics']['fb_velo'] = round(fb_velo, 1)
    
    # Calculate stuff for each pitch type
    pitch_stuff_scores = []
    
    for pitch_type in df['pitch_type'].unique():
        if pd.isna(pitch_type):
            continue
            
        pitch_df = df[df['pitch_type'] == pitch_type]
        
        if len(pitch_df) < 10:  # Need minimum sample
            continue
        
        # Raw metrics
        velo = pitch_df['release_speed'].mean()
        spin = pitch_df['release_spin_rate'].mean() if 'release_spin_rate' in pitch_df.columns else 2200
        h_mov = pitch_df['pfx_x'].mean() * 12 if 'pfx_x' in pitch_df.columns else 0
        v_mov = pitch_df['pfx_z'].mean() * 12 if 'pfx_z' in pitch_df.columns else 0
        
        # Velocity differential from fastball (for secondary pitches)
        velo_diff = fb_velo - velo if pitch_type not in FASTBALLS else 0
        
        # Movement differential
        h_mov_diff = abs(h_mov - fb_h_mov) if pitch_type not in FASTBALLS else abs(h_mov)
        
        # Whiff rate
        swings = pitch_df[pitch_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked', 
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        whiffs = pitch_df[pitch_df['description'].isin([
            'swinging_strike', 'swinging_strike_blocked'
        ])]
        whiff_rate = len(whiffs) / len(swings) if len(swings) > 0 else 0
        
        # Calculate stuff score based on pitch type
        if pitch_type in FASTBALLS:
            # Fastball stuff: velocity + ride + extension
            velo_score = normalize_metric(velo, 91, 97, higher_better=True) * 40
            v_mov_score = normalize_metric(v_mov, 10, 18, higher_better=True) * 25
            spin_score = normalize_metric(spin, 2100, 2500, higher_better=True) * 15
            whiff_score = normalize_metric(whiff_rate, 0.18, 0.32, higher_better=True) * 20
            
            stuff_score = velo_score + v_mov_score + spin_score + whiff_score
            
        elif pitch_type in BREAKING:
            # Breaking ball stuff: movement + spin + velo diff
            h_mov_score = normalize_metric(abs(h_mov), 4, 12, higher_better=True) * 25
            v_mov_score = normalize_metric(abs(v_mov - fb_v_mov), 4, 14, higher_better=True) * 25
            spin_score = normalize_metric(spin, 2400, 3000, higher_better=True) * 15
            whiff_score = normalize_metric(whiff_rate, 0.28, 0.42, higher_better=True) * 25
            velo_diff_score = normalize_metric(velo_diff, 6, 14, higher_better=True) * 10
            
            stuff_score = h_mov_score + v_mov_score + spin_score + whiff_score + velo_diff_score
            
        else:  # Offspeed
            # Changeup/splitter stuff: velo diff + fade + drop
            velo_diff_score = normalize_metric(velo_diff, 7, 13, higher_better=True) * 30
            h_mov_score = normalize_metric(h_mov_diff, 3, 10, higher_better=True) * 20
            drop_score = normalize_metric(fb_v_mov - v_mov, 3, 10, higher_better=True) * 20
            whiff_score = normalize_metric(whiff_rate, 0.28, 0.40, higher_better=True) * 30
            
            stuff_score = velo_diff_score + h_mov_score + drop_score + whiff_score
        
        # Convert to 100-scale (100 = average)
        stuff_plus = 80 + (stuff_score * 0.4)  # Scale so 100 is roughly average
        
        usage_pct = len(pitch_df) / len(df)
        
        results['by_pitch_type'][pitch_type] = {
            'stuff_plus': round(stuff_plus, 1),
            'usage_pct': round(usage_pct * 100, 1),
            'velocity': round(velo, 1),
            'spin_rate': round(spin, 0) if not pd.isna(spin) else None,
            'h_movement': round(h_mov, 1),
            'v_movement': round(v_mov, 1),
            'whiff_rate': round(whiff_rate * 100, 1),
            'pitch_count': len(pitch_df)
        }
        
        results['arsenal'][pitch_type] = {
            'name': PITCH_TYPES.get(pitch_type, pitch_type),
            'velo': round(velo, 1),
            'stuff': round(stuff_plus, 1)
        }
        
        # Weight by usage for overall
        pitch_stuff_scores.append((stuff_plus, usage_pct))
    
    # Calculate weighted overall stuff+
    if pitch_stuff_scores:
        total_weight = sum(w for _, w in pitch_stuff_scores)
        weighted_stuff = sum(s * w for s, w in pitch_stuff_scores) / total_weight if total_weight > 0 else 100
        results['overall_stuff_plus'] = round(weighted_stuff, 1)
    
    return results


# =============================================================================
# LOCATION+ CALCULATION
# =============================================================================

def calculate_location_plus(df: pd.DataFrame) -> Dict:
    """
    Calculate Location+ score from Statcast pitch data.
    
    Based on FanGraphs methodology:
    - Zone rate (pitches in strike zone)
    - Edge rate (pitches on corners)
    - Heart rate (pitches in middle - LOWER is better)
    - Chase rate induced
    - Count-appropriate locations
    
    Returns dict with overall location_plus and zone breakdown.
    """
    if df is None or df.empty or 'zone' not in df.columns:
        return None
    
    results = {
        'overall_location_plus': None,
        'zone_breakdown': {},
        'metrics': {}
    }
    
    total_pitches = len(df)
    zone_data = df['zone'].dropna()
    
    if len(zone_data) == 0:
        return None
    
    # Zone percentages
    in_zone = zone_data.isin(list(range(1, 10))).sum()
    on_edge = zone_data.isin(EDGE_ZONES).sum()
    in_heart = zone_data.isin(HEART_ZONE).sum()
    in_chase = zone_data.isin(CHASE_ZONES).sum()
    
    zone_pct = in_zone / len(zone_data)
    edge_pct = on_edge / len(zone_data)
    heart_pct = in_heart / len(zone_data)
    chase_zone_pct = in_chase / len(zone_data)
    
    results['metrics']['zone_pct'] = round(zone_pct * 100, 1)
    results['metrics']['edge_pct'] = round(edge_pct * 100, 1)
    results['metrics']['heart_pct'] = round(heart_pct * 100, 1)
    results['metrics']['chase_zone_pct'] = round(chase_zone_pct * 100, 1)
    
    # Chase rate (swings on pitches outside zone)
    chase_pitches = df[df['zone'].isin(CHASE_ZONES)]
    if len(chase_pitches) > 0:
        chase_swings = chase_pitches[chase_pitches['description'].isin([
            'swinging_strike', 'swinging_strike_blocked', 
            'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
        ])]
        chase_rate = len(chase_swings) / len(chase_pitches)
    else:
        chase_rate = 0.30  # League average
    
    results['metrics']['chase_rate'] = round(chase_rate * 100, 1)
    
    # First pitch strike rate
    first_pitches = df[(df['balls'] == 0) & (df['strikes'] == 0)]
    if len(first_pitches) > 0:
        fps_strikes = first_pitches[first_pitches['description'].isin([
            'called_strike', 'swinging_strike', 'swinging_strike_blocked',
            'foul', 'foul_tip', 'hit_into_play'
        ])]
        fps_rate = len(fps_strikes) / len(first_pitches)
    else:
        fps_rate = 0.60
    
    results['metrics']['first_pitch_strike_pct'] = round(fps_rate * 100, 1)
    
    # Calculate component scores
    # Zone rate: 42-52% is good (too high = hittable, too low = walks)
    zone_score = normalize_metric(zone_pct, 0.38, 0.52, higher_better=True) * 20
    
    # Edge rate: Higher is better (painting corners)
    edge_score = normalize_metric(edge_pct, 0.20, 0.38, higher_better=True) * 25
    
    # Heart rate: LOWER is better (avoiding middle)
    heart_score = normalize_metric(heart_pct, 0.15, 0.05, higher_better=False) * 20
    
    # Chase rate induced: Higher is better
    chase_score = normalize_metric(chase_rate, 0.26, 0.38, higher_better=True) * 20
    
    # First pitch strike: Higher is better
    fps_score = normalize_metric(fps_rate, 0.55, 0.70, higher_better=True) * 15
    
    # Combine into Location+ (100 = average)
    raw_score = zone_score + edge_score + heart_score + chase_score + fps_score
    location_plus = 80 + (raw_score * 0.4)
    
    results['overall_location_plus'] = round(location_plus, 1)
    
    # Zone-by-zone breakdown
    for zone in range(1, 15):
        zone_df = df[df['zone'] == zone]
        if len(zone_df) == 0:
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
            'whiff_pct': round(whiff_pct * 100, 1)
        }
    
    return results


# =============================================================================
# COMBINED PITCHER PROFILE
# =============================================================================

def get_pitcher_statcast_profile(
    player_id: int, 
    days: int = 30,
    season: int = None
) -> Optional[Dict]:
    """
    Get complete Statcast profile for a pitcher.
    
    Returns:
        - stuff_plus: Overall stuff score (100 = average)
        - location_plus: Overall location score (100 = average)
        - arsenal: Dict of pitch types with velocity and stuff scores
        - zone_breakdown: Performance by zone
        - profile_type: Classification (ELITE, STUFF-DOMINANT, etc.)
        - metrics: Raw underlying metrics
    """
    if not PYBASEBALL_AVAILABLE:
        return None
    
    # Calculate date range
    if season:
        start_date = f"{season}-03-01"
        end_date = f"{season}-11-01"
    else:
        end_date = datetime.today().strftime('%Y-%m-%d')
        start_date = (datetime.today() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    try:
        # Fetch Statcast data
        df = statcast_pitcher(start_date, end_date, player_id)
        
        if df is None or df.empty:
            return None
        
        # Calculate Stuff+ and Location+
        stuff_data = calculate_stuff_plus(df)
        location_data = calculate_location_plus(df)
        
        if stuff_data is None or location_data is None:
            return None
        
        stuff_plus = stuff_data['overall_stuff_plus']
        location_plus = location_data['overall_location_plus']
        
        # Classify profile
        profile_type, profile_desc = classify_pitcher_profile(stuff_plus, location_plus)
        
        return {
            'player_id': player_id,
            'period_days': days,
            'pitches_analyzed': len(df),
            'stuff_plus': stuff_plus,
            'location_plus': location_plus,
            'combined_plus': round((stuff_plus + location_plus) / 2, 1),
            'arsenal': stuff_data.get('arsenal', {}),
            'by_pitch_type': stuff_data.get('by_pitch_type', {}),
            'zone_breakdown': location_data.get('zone_breakdown', {}),
            'metrics': {
                **stuff_data.get('metrics', {}),
                **location_data.get('metrics', {})
            },
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
    
    Returns performance by zone to create damage heat map.
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
            
            # At-bats in this zone (pitches that ended PA)
            zone_abs = zone_df[zone_df['events'].notna()]
            zone_hits = zone_abs[zone_abs['events'].isin([
                'single', 'double', 'triple', 'home_run'
            ])]
            
            # Swing rate
            zone_swings = zone_df[zone_df['description'].isin([
                'swinging_strike', 'swinging_strike_blocked', 
                'foul', 'foul_tip', 'hit_into_play', 'foul_bunt'
            ])]
            zone_whiffs = zone_df[zone_df['description'].isin([
                'swinging_strike', 'swinging_strike_blocked'
            ])]
            
            swing_pct = len(zone_swings) / len(zone_df) if len(zone_df) > 0 else 0
            whiff_pct = len(zone_whiffs) / len(zone_swings) if len(zone_swings) > 0 else 0
            
            # Batting average in zone
            ba = len(zone_hits) / len(zone_abs) if len(zone_abs) > 0 else 0
            
            # xBA if available
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
# HEAT MAP DATA GENERATION
# =============================================================================

def get_pitcher_attack_map(player_id: int, days: int = 30) -> Optional[Dict]:
    """
    Generate heat map data showing where pitcher attacks.
    
    Returns 3x3 grid (plus chase zones) with:
    - Usage percentage
    - Effectiveness (whiff rate, BA against)
    - Color coding (green = good for pitcher, red = bad)
    """
    profile = get_pitcher_statcast_profile(player_id, days)
    
    if not profile or not profile.get('zone_breakdown'):
        return None
    
    zones = profile['zone_breakdown']
    
    # Create 3x3 grid representation
    grid = {}
    for zone in range(1, 10):
        zone_data = zones.get(zone, {})
        usage = zone_data.get('pitch_pct', 0)
        whiff = zone_data.get('whiff_pct', 20)
        
        # Color based on whiff rate
        if whiff >= 30:
            color = 'green'  # Dominant zone
        elif whiff >= 22:
            color = 'yellow'  # Average
        else:
            color = 'red'  # Gets hit here
        
        grid[zone] = {
            'usage': usage,
            'whiff_pct': whiff,
            'color': color
        }
    
    # Chase zones
    for zone in CHASE_ZONES:
        zone_data = zones.get(zone, {})
        grid[zone] = {
            'usage': zone_data.get('pitch_pct', 0),
            'whiff_pct': zone_data.get('whiff_pct', 0),
            'color': 'blue'  # Chase zones
        }
    
    return {
        'player_id': player_id,
        'grid': grid,
        'primary_zone': max(range(1, 10), key=lambda z: grid.get(z, {}).get('usage', 0)),
        'best_zone': max(range(1, 10), key=lambda z: grid.get(z, {}).get('whiff_pct', 0)),
    }


def get_hitter_damage_map(player_id: int, days: int = 30) -> Optional[Dict]:
    """
    Generate heat map data showing where hitter does damage.
    
    Returns grid with:
    - Batting average by zone
    - Damage zones (BA > .300)
    - Weakness zones (BA < .180)
    """
    profile = get_hitter_zone_profile(player_id, days)
    
    if not profile or not profile.get('zones'):
        return None
    
    zones = profile['zones']
    
    grid = {}
    for zone in range(1, 15):
        zone_data = zones.get(zone, {})
        ba = zone_data.get('ba', 0.250)
        
        # Color based on BA
        if ba >= 0.320:
            color = 'red'  # Crusher here
        elif ba >= 0.270:
            color = 'orange'
        elif ba >= 0.220:
            color = 'yellow'
        else:
            color = 'blue'  # Struggles here
        
        grid[zone] = {
            'ba': ba,
            'swing_pct': zone_data.get('swing_pct', 50),
            'color': color,
            'is_damage': zone_data.get('is_damage_zone', False),
            'is_weakness': zone_data.get('is_weakness', False)
        }
    
    # Find damage and weakness zones
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
    """
    Analyze zone overlap between pitcher and hitter.
    
    Returns:
    - Overlap zones (where pitcher attacks AND hitter does damage)
    - Advantage zones (pitcher attacks, hitter struggles)
    - Overall matchup edge
    """
    pitcher_map = get_pitcher_attack_map(pitcher_id, days)
    hitter_map = get_hitter_damage_map(hitter_id, days)
    
    if not pitcher_map or not hitter_map:
        return None
    
    danger_zones = []
    advantage_zones = []
    
    for zone in range(1, 10):
        pitcher_usage = pitcher_map['grid'].get(zone, {}).get('usage', 0)
        hitter_ba = hitter_map['grid'].get(zone, {}).get('ba', 0.250)
        
        if pitcher_usage >= 8:  # Pitcher uses this zone frequently
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
    
    # Calculate overall edge
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

def normalize_metric(value: float, min_val: float, max_val: float, higher_better: bool = True) -> float:
    """Normalize a metric to 0-100 scale."""
    if pd.isna(value):
        return 50
    
    normalized = (value - min_val) / (max_val - min_val)
    normalized = max(0, min(1, normalized))  # Clamp to 0-1
    
    if not higher_better:
        normalized = 1 - normalized
    
    return normalized * 100


def classify_pitcher_profile(stuff_plus: float, location_plus: float) -> Tuple[str, str]:
    """
    Classify pitcher profile based on Stuff+ and Location+.
    
    Returns (profile_type, description)
    """
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
    """
    Look up MLB player ID by name.
    
    Returns MLBAM ID for use with Statcast functions.
    """
    if not PYBASEBALL_AVAILABLE:
        return None
    
    try:
        result = playerid_lookup(last_name, first_name)
        if result is not None and not result.empty:
            # Return the MLBAM ID (key_mlbam column)
            return int(result.iloc[0]['key_mlbam'])
    except Exception as e:
        print(f"Player lookup error: {e}")
    
    return None


# =============================================================================
# FANGRAPHS LEADERBOARD DATA
# =============================================================================

def get_fangraphs_pitching_stats(season: int = 2025, qual: int = 20) -> Optional[pd.DataFrame]:
    """
    Get FanGraphs pitching leaderboard with Stuff+, Location+, Pitching+.
    
    Returns DataFrame with all FanGraphs advanced metrics.
    """
    if not PYBASEBALL_AVAILABLE:
        return None
    
    try:
        df = pitching_stats(season, qual=qual)
        return df
    except Exception as e:
        print(f"Error fetching FanGraphs data: {e}")
        return None


# =============================================================================
# TEST / DEMO
# =============================================================================

if __name__ == "__main__":
    print("SALCI Statcast Connector Test")
    print("=" * 50)
    
    if not PYBASEBALL_AVAILABLE:
        print("ERROR: pybaseball not installed")
        print("Run: pip install pybaseball")
    else:
        print("pybaseball is available!")
        print("\nExample usage:")
        print("  profile = get_pitcher_statcast_profile(669203, days=30)")
        print("  print(f'Stuff+: {profile[\"stuff_plus\"]}')")
        print("  print(f'Location+: {profile[\"location_plus\"]}')")
