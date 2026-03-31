"""
Baseball Savant / Statcast API Connector
SALCI v4.0

Fetches pitch-level data, zone metrics, and advanced stats from Baseball Savant.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import io
import time

# Cache for API responses (in-memory for Streamlit)
_savant_cache = {}
CACHE_TTL = 300  # 5 minutes


def _get_cache_key(endpoint: str, params: dict) -> str:
    """Generate cache key from endpoint and params."""
    param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{endpoint}?{param_str}"


def _is_cache_valid(key: str) -> bool:
    """Check if cached data is still valid."""
    if key not in _savant_cache:
        return False
    cached_time = _savant_cache[key].get("_cached_at", 0)
    return (time.time() - cached_time) < CACHE_TTL


# =============================================================================
# STATCAST SEARCH - Core pitch-level data
# =============================================================================

def get_statcast_pitcher_data(
    player_id: int,
    start_date: str = None,
    end_date: str = None,
    season: int = None
) -> Optional[pd.DataFrame]:
    """
    Fetch pitch-level Statcast data for a pitcher.
    
    Returns DataFrame with columns:
    - pitch_type, release_speed, release_spin_rate
    - pfx_x, pfx_z (movement)
    - plate_x, plate_z (location)
    - zone (1-14)
    - description (called_strike, swinging_strike, ball, etc.)
    - launch_speed, launch_angle (when hit)
    - estimated_ba_using_speedangle (xBA)
    """
    if season and not start_date:
        start_date = f"{season}-03-01"
        end_date = f"{season}-11-01"
    elif not start_date:
        end_date = datetime.today().strftime("%Y-%m-%d")
        start_date = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    params = {
        "all": "true",
        "player_type": "pitcher",
        "hfPT": "",  # All pitch types
        "hfAB": "",  # All at-bat results
        "hfGT": "R|",  # Regular season
        "hfPR": "",  # All pitch results
        "hfZ": "",   # All zones
        "stadium": "",
        "hfBBL": "",
        "hfNewZones": "",
        "hfPull": "",
        "hfC": "",
        "hfSea": f"{season}|" if season else "",
        "hfSit": "",
        "player_id": player_id,
        "hfOuts": "",
        "hfOpponent": "",
        "pitcher_throws": "",
        "batter_stands": "",
        "hfSA": "",
        "game_date_gt": start_date,
        "game_date_lt": end_date,
        "hfInfield": "",
        "team": "",
        "position": "",
        "hfOutfield": "",
        "hfRO": "",
        "home_road": "",
        "hfFlag": "",
        "hfBBT": "",
        "metric_1": "",
        "hfInn": "",
        "min_pitches": "0",
        "min_results": "0",
        "group_by": "name",
        "sort_col": "pitches",
        "player_event_sort": "api_p_release_speed",
        "sort_order": "desc",
        "min_pas": "0",
        "type": "details",
    }
    
    cache_key = _get_cache_key("statcast_pitcher", {"player_id": player_id, "start": start_date, "end": end_date})
    if _is_cache_valid(cache_key):
        return _savant_cache[cache_key]["data"]
    
    url = "https://baseballsavant.mlb.com/statcast_search/csv"
    
    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200 and len(response.content) > 100:
            df = pd.read_csv(io.StringIO(response.text), low_memory=False)
            _savant_cache[cache_key] = {"data": df, "_cached_at": time.time()}
            return df
    except Exception as e:
        print(f"Error fetching Savant data: {e}")
    
    return None


def get_statcast_batter_data(
    player_id: int,
    start_date: str = None,
    end_date: str = None,
    season: int = None
) -> Optional[pd.DataFrame]:
    """
    Fetch pitch-level Statcast data for a batter.
    
    Returns DataFrame with zone-based performance data.
    """
    if season and not start_date:
        start_date = f"{season}-03-01"
        end_date = f"{season}-11-01"
    elif not start_date:
        end_date = datetime.today().strftime("%Y-%m-%d")
        start_date = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    params = {
        "all": "true",
        "player_type": "batter",
        "hfPT": "",
        "hfAB": "",
        "hfGT": "R|",
        "hfPR": "",
        "hfZ": "",
        "stadium": "",
        "hfBBL": "",
        "hfNewZones": "",
        "hfPull": "",
        "hfC": "",
        "hfSea": f"{season}|" if season else "",
        "hfSit": "",
        "player_id": player_id,
        "hfOuts": "",
        "hfOpponent": "",
        "pitcher_throws": "",
        "batter_stands": "",
        "hfSA": "",
        "game_date_gt": start_date,
        "game_date_lt": end_date,
        "hfInfield": "",
        "team": "",
        "position": "",
        "hfOutfield": "",
        "hfRO": "",
        "home_road": "",
        "hfFlag": "",
        "hfBBT": "",
        "metric_1": "",
        "hfInn": "",
        "min_pitches": "0",
        "min_results": "0",
        "group_by": "name",
        "sort_col": "pitches",
        "player_event_sort": "api_p_release_speed",
        "sort_order": "desc",
        "min_pas": "0",
        "type": "details",
    }
    
    cache_key = _get_cache_key("statcast_batter", {"player_id": player_id, "start": start_date, "end": end_date})
    if _is_cache_valid(cache_key):
        return _savant_cache[cache_key]["data"]
    
    url = "https://baseballsavant.mlb.com/statcast_search/csv"
    
    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200 and len(response.content) > 100:
            df = pd.read_csv(io.StringIO(response.text), low_memory=False)
            _savant_cache[cache_key] = {"data": df, "_cached_at": time.time()}
            return df
    except Exception as e:
        print(f"Error fetching Savant batter data: {e}")
    
    return None


# =============================================================================
# STUFF METRICS - Pitch quality calculations
# =============================================================================

def calculate_stuff_metrics(df: pd.DataFrame) -> Dict:
    """
    Calculate Stuff metrics from pitch-level data.
    
    Returns:
        stuff_score: 0-100 composite
        fastball_velo: Average 4-seam velocity
        spin_rate: Average spin on primary pitches
        whiff_pct: Swinging strike rate
        movement: Average induced movement
        pitch_mix: Dict of pitch type usage
    """
    if df is None or df.empty:
        return None
    
    metrics = {}
    
    # Fastball velocity (4-seam, sinker)
    fastballs = df[df["pitch_type"].isin(["FF", "SI", "FC"])]
    if not fastballs.empty:
        metrics["fastball_velo"] = fastballs["release_speed"].mean()
    else:
        metrics["fastball_velo"] = df["release_speed"].mean()
    
    # Spin rate
    if "release_spin_rate" in df.columns:
        metrics["spin_rate"] = df["release_spin_rate"].mean()
    else:
        metrics["spin_rate"] = None
    
    # Whiff percentage (swinging strikes / swings)
    swings = df[df["description"].isin([
        "swinging_strike", "swinging_strike_blocked", 
        "foul", "foul_tip", "hit_into_play"
    ])]
    whiffs = df[df["description"].isin([
        "swinging_strike", "swinging_strike_blocked"
    ])]
    
    if len(swings) > 0:
        metrics["whiff_pct"] = len(whiffs) / len(swings)
    else:
        metrics["whiff_pct"] = 0
    
    # Movement (average absolute movement)
    if "pfx_x" in df.columns and "pfx_z" in df.columns:
        df_movement = df.dropna(subset=["pfx_x", "pfx_z"])
        if not df_movement.empty:
            # Convert to inches, calculate total movement
            metrics["h_movement"] = abs(df_movement["pfx_x"].mean() * 12)
            metrics["v_movement"] = abs(df_movement["pfx_z"].mean() * 12)
            metrics["total_movement"] = (metrics["h_movement"]**2 + metrics["v_movement"]**2)**0.5
    
    # Pitch mix
    pitch_counts = df["pitch_type"].value_counts(normalize=True)
    metrics["pitch_mix"] = pitch_counts.to_dict()
    
    # Calculate composite Stuff Score (0-100)
    stuff_score = 0
    components = 0
    
    # Velocity component (90-98 range, higher better)
    if metrics.get("fastball_velo"):
        velo_norm = min(max((metrics["fastball_velo"] - 90) / 8, 0), 1)
        stuff_score += velo_norm * 25
        components += 25
    
    # Spin component (2000-2600 range)
    if metrics.get("spin_rate"):
        spin_norm = min(max((metrics["spin_rate"] - 2000) / 600, 0), 1)
        stuff_score += spin_norm * 20
        components += 20
    
    # Whiff component (0.20-0.35 range)
    if metrics.get("whiff_pct"):
        whiff_norm = min(max((metrics["whiff_pct"] - 0.20) / 0.15, 0), 1)
        stuff_score += whiff_norm * 35
        components += 35
    
    # Movement component (10-18 inch range)
    if metrics.get("total_movement"):
        move_norm = min(max((metrics["total_movement"] - 10) / 8, 0), 1)
        stuff_score += move_norm * 20
        components += 20
    
    if components > 0:
        metrics["stuff_score"] = round((stuff_score / components) * 100, 1)
    else:
        metrics["stuff_score"] = None
    
    return metrics


# =============================================================================
# LOCATION METRICS - Command/placement calculations
# =============================================================================

def calculate_location_metrics(df: pd.DataFrame) -> Dict:
    """
    Calculate Location metrics from pitch-level data.
    
    Returns:
        location_score: 0-100 composite
        zone_pct: Pitches in strike zone
        edge_pct: Pitches on zone edges
        chase_pct: Chases induced (swings outside zone)
        heart_pct: Pitches in heart of zone (bad)
        first_pitch_strike_pct: First pitch strikes
    """
    if df is None or df.empty:
        return None
    
    metrics = {}
    total_pitches = len(df)
    
    # Zone definitions (1-9 = strike zone, 11-14 = chase zones)
    if "zone" in df.columns:
        zone_data = df["zone"].dropna()
        
        # Zone percentage (zones 1-9)
        in_zone = zone_data.isin([1, 2, 3, 4, 5, 6, 7, 8, 9]).sum()
        metrics["zone_pct"] = in_zone / len(zone_data) if len(zone_data) > 0 else 0
        
        # Heart percentage (zone 5 = center)
        heart = zone_data.isin([5]).sum()
        metrics["heart_pct"] = heart / len(zone_data) if len(zone_data) > 0 else 0
        
        # Edge percentage (zones 1,2,3,4,6,7,8,9 but not 5)
        edge = zone_data.isin([1, 2, 3, 4, 6, 7, 8, 9]).sum()
        metrics["edge_pct"] = edge / len(zone_data) if len(zone_data) > 0 else 0
        
        # Chase zones (11-14)
        chase_zones = zone_data.isin([11, 12, 13, 14])
        chase_pitches = df[df["zone"].isin([11, 12, 13, 14])]
        chase_swings = chase_pitches[chase_pitches["description"].isin([
            "swinging_strike", "swinging_strike_blocked", 
            "foul", "foul_tip", "hit_into_play"
        ])]
        
        if len(chase_pitches) > 0:
            metrics["chase_pct"] = len(chase_swings) / len(chase_pitches)
        else:
            metrics["chase_pct"] = 0
    
    # First pitch strike rate
    if "balls" in df.columns and "strikes" in df.columns:
        first_pitches = df[(df["balls"] == 0) & (df["strikes"] == 0)]
        if len(first_pitches) > 0:
            # Strikes include called, swinging, foul
            fps_strikes = first_pitches[first_pitches["description"].isin([
                "called_strike", "swinging_strike", "swinging_strike_blocked",
                "foul", "foul_tip", "hit_into_play"
            ])]
            metrics["first_pitch_strike_pct"] = len(fps_strikes) / len(first_pitches)
        else:
            metrics["first_pitch_strike_pct"] = 0
    
    # Calculate composite Location Score (0-100)
    location_score = 0
    components = 0
    
    # Zone% component (0.40-0.55 range, optimal around 0.48)
    if metrics.get("zone_pct") is not None:
        # Sweet spot is around 0.45-0.50
        zone_norm = min(max((metrics["zone_pct"] - 0.35) / 0.20, 0), 1)
        location_score += zone_norm * 20
        components += 20
    
    # Edge% component (0.15-0.30 range, higher better)
    if metrics.get("edge_pct") is not None:
        edge_norm = min(max((metrics["edge_pct"] - 0.15) / 0.15, 0), 1)
        location_score += edge_norm * 25
        components += 25
    
    # Chase% component (0.25-0.40 range, higher better)
    if metrics.get("chase_pct") is not None:
        chase_norm = min(max((metrics["chase_pct"] - 0.25) / 0.15, 0), 1)
        location_score += chase_norm * 25
        components += 25
    
    # Heart% component (0.20-0.10 range, LOWER better)
    if metrics.get("heart_pct") is not None:
        heart_norm = 1 - min(max((metrics["heart_pct"] - 0.10) / 0.10, 0), 1)
        location_score += heart_norm * 15
        components += 15
    
    # FPS component (0.55-0.70 range, higher better)
    if metrics.get("first_pitch_strike_pct") is not None:
        fps_norm = min(max((metrics["first_pitch_strike_pct"] - 0.55) / 0.15, 0), 1)
        location_score += fps_norm * 15
        components += 15
    
    if components > 0:
        metrics["location_score"] = round((location_score / components) * 100, 1)
    else:
        metrics["location_score"] = None
    
    return metrics


# =============================================================================
# ZONE HEAT MAP DATA
# =============================================================================

def get_zone_performance(df: pd.DataFrame, is_pitcher: bool = True) -> Dict:
    """
    Calculate performance by zone for heat map visualization.
    
    Returns dict with zone numbers (1-14) as keys and performance metrics as values.
    """
    if df is None or df.empty or "zone" not in df.columns:
        return None
    
    zones = {}
    
    for zone in range(1, 15):
        zone_df = df[df["zone"] == zone]
        
        if len(zone_df) == 0:
            zones[zone] = None
            continue
        
        zone_data = {
            "pitch_count": len(zone_df),
            "pitch_pct": len(zone_df) / len(df),
        }
        
        # Swings and whiffs
        swings = zone_df[zone_df["description"].isin([
            "swinging_strike", "swinging_strike_blocked", 
            "foul", "foul_tip", "hit_into_play"
        ])]
        whiffs = zone_df[zone_df["description"].isin([
            "swinging_strike", "swinging_strike_blocked"
        ])]
        
        if len(swings) > 0:
            zone_data["whiff_pct"] = len(whiffs) / len(swings)
        else:
            zone_data["whiff_pct"] = 0
        
        # Batting average against (for pitchers) or for (batters)
        hits = zone_df[zone_df["events"].isin([
            "single", "double", "triple", "home_run"
        ])] if "events" in zone_df.columns else pd.DataFrame()
        
        abs_in_zone = zone_df[zone_df["events"].notna()] if "events" in zone_df.columns else pd.DataFrame()
        
        if len(abs_in_zone) > 0:
            zone_data["ba"] = len(hits) / len(abs_in_zone)
        else:
            zone_data["ba"] = None
        
        # xBA if available
        if "estimated_ba_using_speedangle" in zone_df.columns:
            xba = zone_df["estimated_ba_using_speedangle"].dropna()
            if len(xba) > 0:
                zone_data["xba"] = xba.mean()
        
        zones[zone] = zone_data
    
    return zones


# =============================================================================
# PROFILE CLASSIFICATION
# =============================================================================

def classify_pitcher_profile(stuff_score: float, location_score: float) -> Tuple[str, str]:
    """
    Classify pitcher profile based on Stuff and Location scores.
    
    Returns:
        (profile_type, description)
    """
    if stuff_score is None or location_score is None:
        return ("UNKNOWN", "Insufficient data")
    
    if stuff_score >= 75 and location_score >= 75:
        return ("ELITE", "True ace - elite arsenal with pinpoint command")
    elif stuff_score >= 75 and location_score < 65:
        return ("STUFF-DOMINANT", "High ceiling, high variance - lives on swing-and-miss")
    elif stuff_score < 65 and location_score >= 75:
        return ("LOCATION-DOMINANT", "Lower ceiling, low variance - lives on weak contact")
    elif stuff_score >= 60 and location_score >= 60:
        return ("BALANCED", "Solid but not spectacular - matchup-dependent")
    elif stuff_score >= 55 or location_score >= 55:
        return ("AVERAGE", "League average arm - context matters")
    else:
        return ("LIMITED", "Below average - fade in most matchups")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_pitcher_stuff_location(player_id: int, days: int = 30) -> Optional[Dict]:
    """
    One-call function to get complete Stuff/Location profile for a pitcher.
    """
    end_date = datetime.today().strftime("%Y-%m-%d")
    start_date = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    df = get_statcast_pitcher_data(player_id, start_date, end_date)
    
    if df is None or df.empty:
        return None
    
    stuff = calculate_stuff_metrics(df)
    location = calculate_location_metrics(df)
    zones = get_zone_performance(df, is_pitcher=True)
    
    if stuff is None or location is None:
        return None
    
    profile_type, profile_desc = classify_pitcher_profile(
        stuff.get("stuff_score"), 
        location.get("location_score")
    )
    
    return {
        "player_id": player_id,
        "days_sampled": days,
        "pitches_analyzed": len(df),
        "stuff": stuff,
        "location": location,
        "zones": zones,
        "profile_type": profile_type,
        "profile_description": profile_desc,
        "combined_score": round(
            (stuff.get("stuff_score", 50) * 0.5 + location.get("location_score", 50) * 0.5), 1
        ) if stuff.get("stuff_score") and location.get("location_score") else None
    }


def get_batter_zone_profile(player_id: int, days: int = 30) -> Optional[Dict]:
    """
    One-call function to get zone-based performance profile for a batter.
    """
    end_date = datetime.today().strftime("%Y-%m-%d")
    start_date = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    df = get_statcast_batter_data(player_id, start_date, end_date)
    
    if df is None or df.empty:
        return None
    
    zones = get_zone_performance(df, is_pitcher=False)
    
    # Calculate overall metrics
    swings = df[df["description"].isin([
        "swinging_strike", "swinging_strike_blocked", 
        "foul", "foul_tip", "hit_into_play"
    ])]
    whiffs = df[df["description"].isin([
        "swinging_strike", "swinging_strike_blocked"
    ])]
    
    chase_pitches = df[df["zone"].isin([11, 12, 13, 14])] if "zone" in df.columns else pd.DataFrame()
    chase_swings = chase_pitches[chase_pitches["description"].isin([
        "swinging_strike", "swinging_strike_blocked", 
        "foul", "foul_tip", "hit_into_play"
    ])] if not chase_pitches.empty else pd.DataFrame()
    
    return {
        "player_id": player_id,
        "days_sampled": days,
        "pitches_seen": len(df),
        "zones": zones,
        "overall_whiff_pct": len(whiffs) / len(swings) if len(swings) > 0 else 0,
        "chase_pct": len(chase_swings) / len(chase_pitches) if len(chase_pitches) > 0 else 0,
    }
