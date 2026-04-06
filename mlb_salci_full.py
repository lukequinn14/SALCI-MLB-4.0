#!/usr/bin/env python3
"""
SALCI v5.1 - Advanced MLB Prediction System
Strikeout Adjusted Lineup Confidence Index

NEW IN v5.1:
- 🎯 SALCI v3 K-Optimized Weights: Stuff 40%, Matchup 25%, Workload 20%, Location 15%
- 📋 Lineup-Level Matchup: Uses individual hitter K% when lineup confirmed
- 🎪 Arsenal Display: Per-pitch Stuff+ scores on pitcher cards
- 📊 Sortable Table View: Quick-scan all pitchers with grades and K-lines
- 📈 Model Accuracy Dashboard: 7-day and 30-day rolling performance tracking
- ⚡ Leash Factor: Manager tendencies in workload calculation

INCLUDED FROM v5.0:
- 🎯 Real Statcast Data Integration (pybaseball)
- 📊 True Stuff+ / Location+ calculations from pitch-level data
- 🔥 Heat Maps - Pitcher attack zones vs hitter damage zones
- 💡 Progressive Disclosure UI (expandable advanced sections)

Run with:
    streamlit run mlb_salci_full.py

NOTE: Install pybaseball for real Statcast data: pip install pybaseball
Lineups are typically released 1-2 hours before game time.
"""

import streamlit as st
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os

# ----------------------------
# Statcast Integration (pybaseball) & SALCI v3
# ----------------------------
STATCAST_AVAILABLE = False
SALCI_V3_AVAILABLE = False
try:
    from statcast_connector import (
        # Statcast profile functions
        get_pitcher_statcast_profile,
        get_hitter_zone_profile,
        get_pitcher_attack_map,
        get_hitter_damage_map,
        analyze_matchup_zones,
        # SALCI v3 scoring functions
        calculate_stuff_plus,
        calculate_location_plus,
        calculate_workload_score_v3,
        calculate_matchup_score_v3,
        calculate_salci_v3,
        calculate_expected_ks_v3,
        classify_pitcher_profile,
        get_component_grade,
        # v3 weights
        SALCI_V3_WEIGHTS,
        MATCHUP_SUBWEIGHTS,
        # Backward compat
        calculate_workload_score,
        calculate_matchup_score,
        PYBASEBALL_AVAILABLE
    )
    STATCAST_AVAILABLE = PYBASEBALL_AVAILABLE
    SALCI_V3_AVAILABLE = True
except ImportError:
    STATCAST_AVAILABLE = False
    SALCI_V3_AVAILABLE = False

# ----------------------------
# Reflection Module Integration
# ----------------------------
REFLECTION_AVAILABLE = False
try:
    import reflection as refl
    REFLECTION_AVAILABLE = True
except ImportError:
    REFLECTION_AVAILABLE = False

# ----------------------------
# Version Info
# ----------------------------
SALCI_VERSION = "5.1"
SALCI_BUILD_DATE = "2026-04-03"

# ----------------------------
# Page Configuration
# ----------------------------
st.set_page_config(
    page_title=f"SALCI v{SALCI_VERSION} - MLB Predictions",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------------------
# Custom CSS
# ----------------------------
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
        background: linear-gradient(90deg, #1e3a5f, #2e5a8f);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .sub-header {
        text-align: center;
        color: #666;
        margin-top: 0;
        margin-bottom: 1.5rem;
    }
    .lineup-confirmed {
        background: linear-gradient(135deg, #10b981, #34d399);
        color: white;
        padding: 0.2rem 0.5rem;
        border-radius: 10px;
        font-size: 0.75rem;
        font-weight: bold;
    }
    .lineup-pending {
        background: linear-gradient(135deg, #f59e0b, #fbbf24);
        color: white;
        padding: 0.2rem 0.5rem;
        border-radius: 10px;
        font-size: 0.75rem;
        font-weight: bold;
    }
    .hot-streak {
        background: linear-gradient(135deg, #ff6b6b, #ffa500);
        color: white;
        padding: 0.3rem 0.6rem;
        border-radius: 15px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .cold-streak {
        background: linear-gradient(135deg, #4a90d9, #67b8de);
        color: white;
        padding: 0.3rem 0.6rem;
        border-radius: 15px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .elite { color: #10b981; font-weight: bold; }
    .strong { color: #22c55e; font-weight: bold; }
    .average { color: #eab308; font-weight: bold; }
    .below { color: #f97316; font-weight: bold; }
    .poor { color: #ef4444; font-weight: bold; }
    
    .batting-order {
        background: #f0f9ff;
        border-left: 3px solid #3b82f6;
        padding: 0.2rem 0.5rem;
        font-weight: bold;
        border-radius: 3px;
    }
    
    .stat-card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #e9ecef;
    }
    .matchup-good { background-color: #d4edda; color: #155724; font-weight: bold; }
    .matchup-neutral { background-color: #fff3cd; color: #856404; font-weight: bold; }
    .matchup-bad { background-color: #f8d7da; color: #721c24; font-weight: bold; }
    
    .chart-container {
        background: white;
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 1rem;
    }
    
    .salci-watermark {
        font-size: 0.7rem;
        color: #999;
        text-align: right;
        margin-top: 0.5rem;
    }
    
    div[data-testid="stHorizontalBlock"] > div {
        padding: 0.25rem;
    }
</style>
""", unsafe_allow_html=True)

# ----------------------------
# Configuration
# ----------------------------
WEIGHT_PRESETS = {
    "balanced": {
        "name": "⚖️ Balanced",
        "desc": "Equal weight to pitcher and matchup",
        "weights": {
            "K9": 0.18, "K_percent": 0.18, "K/BB": 0.14, "P/IP": 0.10,
            "OppK%": 0.22, "OppContact%": 0.18
        }
    },
    "pitcher": {
        "name": "💪 Pitcher Heavy",
        "desc": "Focus on pitcher's K ability",
        "weights": {
            "K9": 0.28, "K_percent": 0.25, "K/BB": 0.20, "P/IP": 0.12,
            "OppK%": 0.08, "OppContact%": 0.07
        }
    },
    "matchup": {
        "name": "🎯 Matchup Heavy",
        "desc": "Focus on opponent K tendencies",
        "weights": {
            "K9": 0.12, "K_percent": 0.10, "K/BB": 0.08, "P/IP": 0.08,
            "OppK%": 0.32, "OppContact%": 0.30
        }
    }
}

BOUNDS = {
    "K9": (6.0, 13.0, True),
    "K_percent": (0.15, 0.38, True),
    "K/BB": (1.5, 7.0, True),
    "P/IP": (13, 18, False),
    "OppK%": (0.18, 0.28, True),
    "OppContact%": (0.70, 0.85, False)
}

HITTER_BOUNDS = {
    "avg": (0.200, 0.350),
    "ops": (0.600, 1.000),
    "slg": (0.350, 0.600),
    "k_rate": (0.30, 0.15),
    "hr": (0, 3),
}

# v4.0: Stuff & Location Bounds
STUFF_BOUNDS = {
    "whiff_rate": (0.20, 0.40, True),      # Higher is better
    "velocity": (90.0, 98.0, True),         # Higher is better
    "movement": (-2.0, 4.0, True),          # More break is better
    "chase_rate": (0.25, 0.40, True),       # Higher chase induced is better
}

LOCATION_BOUNDS = {
    "edge_rate": (0.20, 0.35, True),        # Higher edge % is better
    "zone_rate": (0.40, 0.55, True),        # Moderate zone % is good
    "heart_rate": (0.08, 0.20, False),      # Lower heart % is better (avoid middle)
    "csw_rate": (0.25, 0.35, True),         # Higher CSW is better
}

# Chart color scheme
COLORS = {
    "elite": "#10b981",
    "strong": "#3b82f6",
    "average": "#eab308",
    "below": "#f97316",
    "poor": "#ef4444",
    "hot": "#D85A30",
    "cold": "#4a90d9",
    "primary": "#1e3a5f",
    "secondary": "#7F77DD",
    "accent": "#1D9E75",
    "stuff": "#8b5cf6",      # Purple for Stuff
    "location": "#06b6d4",   # Cyan for Location
}

# v4.0: Data Storage Paths (Standardized)
DATA_DIR = "salci_data"
PREDICTIONS_DIR = os.path.join(DATA_DIR, "predictions")

# ----------------------------
# Helper Functions
# ----------------------------
def normalize(val: float, min_val: float, max_val: float, higher_is_better: bool = True) -> float:
    norm = np.clip((val - min_val) / (max_val - min_val), 0, 1)
    return norm if higher_is_better else (1 - norm)

def get_blend_weights(games_played: int) -> Tuple[float, float]:
    if games_played < 3:
        return 0.2, 0.8
    elif games_played < 7:
        return 0.4, 0.6
    elif games_played < 15:
        return 0.6, 0.4
    return 0.8, 0.2

def get_rating(salci: float) -> Tuple[str, str, str]:
    if salci >= 75:
        return "Elite", "🔥", "elite"
    elif salci >= 60:
        return "Strong", "✅", "strong"
    elif salci >= 45:
        return "Average", "➖", "average"
    elif salci >= 30:
        return "Below Avg", "⚠️", "below"
    return "Poor", "❌", "poor"

def get_hitter_rating(score: float) -> Tuple[str, str]:
    if score >= 80:
        return "🔥 On Fire", "hot-streak"
    elif score >= 60:
        return "✅ Hot", "strong"
    elif score >= 40:
        return "➖ Normal", "average"
    elif score >= 20:
        return "❄️ Cold", "cold-streak"
    return "🥶 Ice Cold", "poor"

def get_salci_color(salci: float) -> str:
    if salci >= 75:
        return COLORS["elite"]
    elif salci >= 60:
        return COLORS["strong"]
    elif salci >= 45:
        return COLORS["average"]
    elif salci >= 30:
        return COLORS["below"]
    return COLORS["poor"]

# ----------------------------
# API Functions - Teams & Schedule
# ----------------------------
@st.cache_data(ttl=300)
def get_team_id_lookup() -> Dict[str, int]:
    url = "https://statsapi.mlb.com/api/v1/teams?sportId=1"
    try:
        res = requests.get(url, timeout=10)
        return {team["name"]: team["id"] for team in res.json().get("teams", [])}
    except:
        return {}

@st.cache_data(ttl=60)
def get_games_by_date(date_str: str) -> List[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher,lineups,team"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        if not data.get("dates"):
            return []
        
        games = []
        for g in data["dates"][0]["games"]:
            game_info = {
                "game_pk": g.get("gamePk"),
                "game_time": g.get("gameDate"),
                "status": g.get("status", {}).get("abstractGameState", ""),
                "detailed_status": g.get("status", {}).get("detailedState", ""),
                "home_team": g["teams"]["home"]["team"]["name"],
                "away_team": g["teams"]["away"]["team"]["name"],
                "home_team_id": g["teams"]["home"]["team"]["id"],
                "away_team_id": g["teams"]["away"]["team"]["id"],
                "lineups_available": False
            }
            
            for side in ["home", "away"]:
                pp = g["teams"][side].get("probablePitcher")
                if pp:
                    game_info[f"{side}_pitcher"] = pp.get("fullName", "TBD")
                    game_info[f"{side}_pid"] = pp.get("id")
                    game_info[f"{side}_pitcher_hand"] = pp.get("pitchHand", {}).get("code", "R")
                else:
                    game_info[f"{side}_pitcher"] = "TBD"
                    game_info[f"{side}_pid"] = None
                    game_info[f"{side}_pitcher_hand"] = "R"
            
            games.append(game_info)
        return games
    except Exception as e:
        st.error(f"Error fetching games: {e}")
        return []

@st.cache_data(ttl=60)
def get_game_boxscore(game_pk: int) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    try:
        res = requests.get(url, timeout=15)
        return res.json()
    except:
        return None

def get_confirmed_lineup(game_pk: int, team_side: str) -> Tuple[List[Dict], bool]:
    data = get_game_boxscore(game_pk)
    if not data:
        return [], False
    
    try:
        game_data = data.get("gameData", {})
        live_data = data.get("liveData", {})
        boxscore = live_data.get("boxscore", {})
        
        teams = boxscore.get("teams", {})
        team_data = teams.get(team_side, {})
        
        batting_order = team_data.get("battingOrder", [])
        
        if not batting_order:
            return [], False
        
        players = team_data.get("players", {})
        lineup = []
        
        for i, player_id in enumerate(batting_order):
            player_key = f"ID{player_id}"
            player_info = players.get(player_key, {})
            person = player_info.get("person", {})
            position = player_info.get("position", {})
            
            all_players = game_data.get("players", {})
            full_player = all_players.get(player_key, {})
            bat_side = full_player.get("batSide", {}).get("code", "R")
            
            lineup.append({
                "id": player_id,
                "name": person.get("fullName", "Unknown"),
                "position": position.get("abbreviation", ""),
                "batting_order": i + 1,
                "bat_side": bat_side
            })
        
        return lineup, len(lineup) >= 9
        
    except Exception as e:
        return [], False

# ----------------------------
# API Functions - Pitchers
# ----------------------------
@st.cache_data(ttl=300)
def get_player_season_stats(player_id: int, season: int) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&season={season}&group=pitching"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        if data.get("stats") and data["stats"][0].get("splits"):
            return data["stats"][0]["splits"][0]["stat"]
    except:
        pass
    return None

@st.cache_data(ttl=300)
def get_recent_pitcher_stats(player_id: int, num_games: int = 7) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=pitching"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        if not data.get("stats") or not data["stats"][0].get("splits"):
            return None
        
        games = sorted(data["stats"][0]["splits"], 
                      key=lambda x: x.get("date", ""), reverse=True)[:num_games]
        if not games:
            return None
        
        totals = {"ip": 0, "so": 0, "bb": 0, "tbf": 0, "np": 0, "games": len(games)}
        
        for g in games:
            s = g.get("stat", {})
            ip_raw = str(s.get("inningsPitched", "0.0"))
            if "." in ip_raw:
                parts = ip_raw.split(".")
                ip = int(parts[0]) + int(parts[1]) / 3
            else:
                ip = float(ip_raw)
            
            totals["ip"] += ip
            totals["so"] += int(s.get("strikeOuts", 0))
            totals["bb"] += int(s.get("baseOnBalls", 0))
            totals["tbf"] += int(s.get("battersFaced", 0))
            totals["np"] += int(s.get("numberOfPitches", 0))
        
        if totals["ip"] == 0 or totals["tbf"] == 0:
            return None
        
        return {
            "K9": totals["so"] / totals["ip"] * 9,
            "K_percent": totals["so"] / totals["tbf"],
            "K/BB": totals["so"] / totals["bb"] if totals["bb"] > 0 else totals["so"] * 2,
            "P/IP": totals["np"] / totals["ip"],
            "games_sampled": totals["games"],
            "total_so": totals["so"],
            "total_ip": totals["ip"]
        }
    except:
        pass
    return None

def parse_season_stats(stats: Dict) -> Dict:
    if not stats:
        return {}
    
    ip_raw = str(stats.get("inningsPitched", "0.0"))
    if "." in ip_raw:
        parts = ip_raw.split(".")
        ip = int(parts[0]) + int(parts[1]) / 3
    else:
        ip = float(ip_raw)
    
    if ip == 0:
        return {}
    
    so = int(stats.get("strikeOuts", 0))
    bb = int(stats.get("baseOnBalls", 0))
    tbf = int(stats.get("battersFaced", 1))
    np_total = int(stats.get("numberOfPitches", 0))
    
    return {
        "K9": so / ip * 9,
        "K_percent": so / tbf,
        "K/BB": so / bb if bb > 0 else so * 2,
        "P/IP": np_total / ip if np_total > 0 else 15.0,
        "ERA": float(stats.get("era", 0)),
        "WHIP": float(stats.get("whip", 0))
    }

# ----------------------------
# API Functions - Hitters
# ----------------------------
@st.cache_data(ttl=300)
def get_hitter_recent_stats(player_id: int, num_games: int = 7) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=hitting"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        if not data.get("stats") or not data["stats"][0].get("splits"):
            return None
        
        games = sorted(data["stats"][0]["splits"],
                      key=lambda x: x.get("date", ""), reverse=True)[:num_games]
        if not games:
            return None
        
        totals = {
            "ab": 0, "hits": 0, "doubles": 0, "triples": 0, "hr": 0,
            "rbi": 0, "bb": 0, "so": 0, "sb": 0, "games": len(games)
        }
        
        game_results = []
        
        for g in games:
            s = g.get("stat", {})
            ab = int(s.get("atBats", 0))
            hits = int(s.get("hits", 0))
            
            totals["ab"] += ab
            totals["hits"] += hits
            totals["doubles"] += int(s.get("doubles", 0))
            totals["triples"] += int(s.get("triples", 0))
            totals["hr"] += int(s.get("homeRuns", 0))
            totals["rbi"] += int(s.get("rbi", 0))
            totals["bb"] += int(s.get("baseOnBalls", 0))
            totals["so"] += int(s.get("strikeOuts", 0))
            totals["sb"] += int(s.get("stolenBases", 0))
            
            if ab > 0:
                game_results.append({"date": g.get("date"), "hits": hits, "ab": ab})
        
        if totals["ab"] == 0:
            return None
        
        avg = totals["hits"] / totals["ab"]
        slg = (totals["hits"] + totals["doubles"] + 2*totals["triples"] + 3*totals["hr"]) / totals["ab"]
        obp = (totals["hits"] + totals["bb"]) / (totals["ab"] + totals["bb"]) if (totals["ab"] + totals["bb"]) > 0 else 0
        ops = obp + slg
        k_rate = totals["so"] / totals["ab"]
        
        hit_streak = 0
        for gr in game_results:
            if gr["hits"] > 0:
                hit_streak += 1
            else:
                break
        
        hitless_streak = 0
        for gr in game_results:
            if gr["hits"] == 0:
                hitless_streak += 1
            else:
                break
        
        return {
            "avg": avg,
            "obp": obp,
            "slg": slg,
            "ops": ops,
            "k_rate": k_rate,
            "hr": totals["hr"],
            "rbi": totals["rbi"],
            "sb": totals["sb"],
            "hits": totals["hits"],
            "ab": totals["ab"],
            "so": totals["so"],
            "games": totals["games"],
            "hit_streak": hit_streak,
            "hitless_streak": hitless_streak
        }
    except:
        pass
    return None

@st.cache_data(ttl=3600)
def get_hitter_season_stats(player_id: int, season: int = 2025) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&season={season}&group=hitting"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        if data.get("stats") and data["stats"][0].get("splits"):
            s = data["stats"][0]["splits"][0]["stat"]
            ab = int(s.get("atBats", 1))
            return {
                "avg": float(s.get("avg", 0)),
                "obp": float(s.get("obp", 0)),
                "slg": float(s.get("slg", 0)),
                "ops": float(s.get("ops", 0)),
                "hr": int(s.get("homeRuns", 0)),
                "rbi": int(s.get("rbi", 0)),
                "k_rate": int(s.get("strikeOuts", 0)) / ab if ab > 0 else 0,
                "ab": ab
            }
    except:
        pass
    return None

@st.cache_data(ttl=300)
def get_team_batting_stats(team_id: int, days: int = 14) -> Optional[Dict]:
    end_date = datetime.today()
    start_date = end_date - timedelta(days=days)
    
    url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}"
           f"&startDate={start_date.strftime('%Y-%m-%d')}&endDate={end_date.strftime('%Y-%m-%d')}")
    
    try:
        res = requests.get(url, timeout=10)
        dates = res.json().get("dates", [])
        games = [g["gamePk"] for d in dates for g in d.get("games", [])]
        
        totals = {"pa": 0, "so": 0, "hits": 0, "ab": 0}
        games_counted = 0
        
        for gid in games[:7]:
            b_url = f"https://statsapi.mlb.com/api/v1/game/{gid}/boxscore"
            b_res = requests.get(b_url, timeout=10)
            box = b_res.json().get("teams", {})
            
            for side in ["home", "away"]:
                if box.get(side, {}).get("team", {}).get("id") == team_id:
                    stats = box[side].get("teamStats", {}).get("batting", {})
                    totals["so"] += int(stats.get("strikeOuts", 0))
                    totals["pa"] += int(stats.get("plateAppearances", 0))
                    totals["hits"] += int(stats.get("hits", 0))
                    totals["ab"] += int(stats.get("atBats", 0))
                    games_counted += 1
                    break
        
        if totals["pa"] == 0:
            return None
        
        return {
            "OppK%": totals["so"] / totals["pa"],
            "OppContact%": totals["hits"] / totals["ab"] if totals["ab"] > 0 else 0.25,
            "games_sampled": games_counted
        }
    except:
        pass
    return None

@st.cache_data(ttl=3600)
def get_team_season_batting(team_id: int, season: int = 2025) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=season&season={season}&group=hitting"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        if data.get("stats") and data["stats"][0].get("splits"):
            stats = data["stats"][0]["splits"][0]["stat"]
            pa = int(stats.get("plateAppearances", 1))
            so = int(stats.get("strikeOuts", 0))
            ab = int(stats.get("atBats", 1))
            hits = int(stats.get("hits", 0))
            return {"OppK%": so / pa, "OppContact%": hits / ab}
    except:
        pass
    return None

# ----------------------------
# Yesterday's Box Scores & Leaders
# ----------------------------
@st.cache_data(ttl=300)
def get_yesterday_box_scores(date_str: str) -> List[Dict]:
    schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    try:
        res = requests.get(schedule_url, timeout=15)
        data = res.json()
        if not data.get("dates"):
            return []
        
        results = []
        games = data["dates"][0].get("games", [])
        
        for game in games:
            game_pk = game.get("gamePk")
            status = game.get("status", {}).get("abstractGameState", "")
            
            if status != "Final":
                continue
            
            box_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
            try:
                box_res = requests.get(box_url, timeout=15)
                box_data = box_res.json()
                
                teams = box_data.get("teams", {})
                
                for side in ["home", "away"]:
                    team_data = teams.get(side, {})
                    team_info = team_data.get("team", {})
                    team_name = team_info.get("name", "Unknown")
                    
                    pitchers = team_data.get("pitchers", [])
                    if not pitchers:
                        continue
                    
                    starter_id = pitchers[0]
                    players = team_data.get("players", {})
                    starter_key = f"ID{starter_id}"
                    starter_data = players.get(starter_key, {})
                    
                    stats = starter_data.get("stats", {}).get("pitching", {})
                    person = starter_data.get("person", {})
                    
                    if stats:
                        ip_str = stats.get("inningsPitched", "0.0")
                        if "." in str(ip_str):
                            parts = str(ip_str).split(".")
                            ip = int(parts[0]) + int(parts[1]) / 3
                        else:
                            ip = float(ip_str)
                        
                        results.append({
                            "game_pk": game_pk,
                            "date": date_str,
                            "team": team_name,
                            "pitcher_id": starter_id,
                            "pitcher_name": person.get("fullName", "Unknown"),
                            "actual_ip": round(ip, 1),
                            "actual_k": int(stats.get("strikeOuts", 0)),
                            "actual_bb": int(stats.get("baseOnBalls", 0)),
                            "actual_h": int(stats.get("hits", 0)),
                            "actual_er": int(stats.get("earnedRuns", 0)),
                            "pitches": int(stats.get("numberOfPitches", 0)),
                        })
            except:
                continue
        
        return results
    except Exception as e:
        return []

@st.cache_data(ttl=300)
def get_yesterday_hitter_leaders(date_str: str, min_hits: int = 2) -> List[Dict]:
    schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    try:
        res = requests.get(schedule_url, timeout=15)
        data = res.json()
        if not data.get("dates"):
            return []
        
        hitters = []
        games = data["dates"][0].get("games", [])
        
        for game in games:
            game_pk = game.get("gamePk")
            status = game.get("status", {}).get("abstractGameState", "")
            
            if status != "Final":
                continue
            
            box_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
            try:
                box_res = requests.get(box_url, timeout=15)
                box_data = box_res.json()
                
                teams = box_data.get("teams", {})
                
                for side in ["home", "away"]:
                    team_data = teams.get(side, {})
                    team_info = team_data.get("team", {})
                    team_name = team_info.get("name", "Unknown")
                    
                    batters = team_data.get("batters", [])
                    players = team_data.get("players", {})
                    
                    for batter_id in batters:
                        player_key = f"ID{batter_id}"
                        player_data = players.get(player_key, {})
                        
                        stats = player_data.get("stats", {}).get("batting", {})
                        person = player_data.get("person", {})
                        position = player_data.get("position", {})
                        
                        if stats:
                            hits = int(stats.get("hits", 0))
                            ab = int(stats.get("atBats", 0))
                            hr = int(stats.get("homeRuns", 0))
                            rbi = int(stats.get("rbi", 0))
                            bb = int(stats.get("baseOnBalls", 0))
                            so = int(stats.get("strikeOuts", 0))
                            
                            if hits >= min_hits or hr >= 1:
                                hitters.append({
                                    "game_pk": game_pk,
                                    "date": date_str,
                                    "team": team_name,
                                    "player_id": batter_id,
                                    "player_name": person.get("fullName", "Unknown"),
                                    "position": position.get("abbreviation", ""),
                                    "hits": hits,
                                    "ab": ab,
                                    "hr": hr,
                                    "rbi": rbi,
                                    "bb": bb,
                                    "so": so,
                                    "avg_game": round(hits / ab, 3) if ab > 0 else 0,
                                })
            except:
                continue
        
        hitters.sort(key=lambda x: (x["hits"], x["hr"], x["rbi"]), reverse=True)
        return hitters
    except:
        return []

# ----------------------------
# v5.0: Stuff vs Location Functions (with Statcast Integration)
# ----------------------------
_statcast_cache = {}

def get_cached_statcast_profile(player_id: int, days: int = 30) -> Optional[Dict]:
    if not STATCAST_AVAILABLE:
        return None
    
    cache_key = f"{player_id}_{days}"
    if cache_key not in _statcast_cache:
        try:
            profile = get_pitcher_statcast_profile(player_id, days=days)
            _statcast_cache[cache_key] = profile
        except:
            _statcast_cache[cache_key] = None
    
    return _statcast_cache.get(cache_key)

def calculate_stuff_score(pitcher_stats: Dict, player_id: int = None) -> Tuple[float, Dict]:
    breakdown = {}
    if player_id and STATCAST_AVAILABLE:
        statcast_profile = get_cached_statcast_profile(player_id, days=30)
        if statcast_profile:
            stuff_plus = statcast_profile.get('stuff_plus', 100)
            breakdown = {
                'source': 'statcast',
                'velocity': {'value': statcast_profile.get('avg_velocity', 93), 'norm': min(100, (statcast_profile.get('avg_velocity', 93)-90)*10)},
                'movement': {'value': statcast_profile.get('avg_break', 8), 'norm': min(100, statcast_profile.get('avg_break', 8)*10)},
                'whiff_rate': {'value': statcast_profile.get('avg_whiff', 25), 'norm': statcast_profile.get('avg_whiff', 25)*3},
                'spin_rate': {'value': statcast_profile.get('avg_spin', 2200), 'norm': min(100, (statcast_profile.get('avg_spin', 2200)-1800)/10)},
                'by_pitch_type': statcast_profile.get('by_pitch_type', {}),
            }
            scaled_score = 35 + (stuff_plus - 80) * 0.75
            scaled_score = max(20, min(95, scaled_score))
            return round(scaled_score, 1), breakdown
    
    breakdown['source'] = 'proxy'
    k9 = pitcher_stats.get("K9", 9.0)
    k_pct = pitcher_stats.get("K_percent", 0.22)
    k9_norm = normalize(k9, 6.0, 13.0, True)
    k_pct_norm = normalize(k_pct, 0.15, 0.38, True)
    breakdown["k9"] = {"value": round(k9, 1), "norm": round(k9_norm * 100)}
    breakdown["k_pct"] = {"value": round(k_pct * 100, 1), "norm": round(k_pct_norm * 100)}
    stuff_score = (k9_norm * 0.5 + k_pct_norm * 0.5) * 100
    return round(stuff_score, 1), breakdown

def calculate_location_score(pitcher_stats: Dict, player_id: int = None) -> Tuple[float, Dict]:
    breakdown = {}
    if player_id and STATCAST_AVAILABLE:
        statcast_profile = get_cached_statcast_profile(player_id, days=30)
        if statcast_profile:
            location_plus = statcast_profile.get('location_plus', 100)
            metrics = statcast_profile.get('location_metrics', {})
            breakdown = {
                'source': 'statcast',
                'zone_pct': {'value': metrics.get('zone_pct', 45), 'norm': metrics.get('zone_pct', 45)},
                'edge_pct': {'value': metrics.get('edge_pct', 28), 'norm': min(100, metrics.get('edge_pct', 28) * 3)},
                'heart_pct': {'value': metrics.get('heart_pct', 12), 'norm': max(0, 100 - metrics.get('heart_pct', 12) * 5)},
                'chase_rate': {'value': metrics.get('chase_rate', 30), 'norm': min(100, metrics.get('chase_rate', 30) * 2.5)},
                'fps_pct': {'value': metrics.get('first_pitch_strike_pct', 60), 'norm': metrics.get('first_pitch_strike_pct', 60)},
                'zone_breakdown': statcast_profile.get('zone_breakdown', {}),
            }
            scaled_score = 35 + (location_plus - 80) * 0.75
            scaled_score = max(20, min(95, scaled_score))
            return round(scaled_score, 1), breakdown
    
    breakdown['source'] = 'proxy'
    k_bb = pitcher_stats.get("K/BB", 2.5)
    p_ip = pitcher_stats.get("P/IP", 16.0)
    k_bb_norm = normalize(k_bb, 1.5, 7.0, True)
    p_ip_norm = normalize(p_ip, 18, 13, False)
    breakdown["k_bb"] = {"value": round(k_bb, 1), "norm": round(k_bb_norm * 100)}
    breakdown["p_ip"] = {"value": round(p_ip, 1), "norm": round(p_ip_norm * 100)}
    location_score = (k_bb_norm * 0.6 + p_ip_norm * 0.4) * 100
    return round(location_score, 1), breakdown

def get_edge_type(stuff_score: float, location_score: float) -> Tuple[str, str]:
    diff = stuff_score - location_score
    avg = (stuff_score + location_score) / 2
    if avg >= 75:
        if diff > 10: return "🔥 Stuff Dominant", "Elite stuff carries performance"
        elif diff < -10: return "🎯 Location Master", "Elite command and placement"
        else: return "⚡ Complete Pitcher", "Elite stuff AND location"
    elif avg >= 60:
        if diff > 8: return "💪 Stuff-First", "Relies on pitch quality over placement"
        elif diff < -8: return "📍 Command-First", "Relies on placement over raw stuff"
        else: return "⚖️ Balanced", "Good mix of stuff and location"
    elif avg >= 45:
        if diff > 5: return "⚠️ Stuff Only", "Needs better location to succeed"
        elif diff < -5: return "⚠️ Location Only", "Needs better stuff to dominate"
        else: return "➖ Average", "Middle-of-the-road profile"
    else: return "❌ Struggling", "Below average in both areas"

def compute_salci(
    pitcher_recent: Optional[Dict],
    pitcher_baseline: Optional[Dict],
    opp_recent: Optional[Dict],
    opp_baseline: Optional[Dict],
    weights: Dict,
    games_played: int = 5
) -> Tuple[Optional[float], Dict, List[str]]:
    recent_w, baseline_w = get_blend_weights(games_played)
    pitcher_stats = {}
    for metric in ["K9", "K_percent", "K/BB", "P/IP"]:
        recent_val = pitcher_recent.get(metric) if pitcher_recent else None
        baseline_val = pitcher_baseline.get(metric) if pitcher_baseline else None
        if recent_val is not None and baseline_val is not None:
            pitcher_stats[metric] = recent_w * recent_val + baseline_w * baseline_val
        elif recent_val is not None: pitcher_stats[metric] = recent_val
        elif baseline_val is not None: pitcher_stats[metric] = baseline_val
    
    opp_stats = {}
    for metric in ["OppK%", "OppContact%"]:
        recent_val = opp_recent.get(metric) if opp_recent else None
        baseline_val = opp_baseline.get(metric) if opp_baseline else None
        if recent_val is not None and baseline_val is not None:
            opp_stats[metric] = recent_w * recent_val + baseline_w * baseline_val
        elif recent_val is not None: opp_stats[metric] = recent_val
        elif baseline_val is not None: opp_stats[metric] = baseline_val
    
    score = 0.0
    total_weight = 0.0
    breakdown = {}
    missing = []
    all_stats = {**pitcher_stats, **opp_stats}
    for metric, weight in weights.items():
        if metric in all_stats:
            val = all_stats[metric]
            bounds = BOUNDS.get(metric)
            if bounds:
                min_v, max_v, higher_better = bounds
                norm_val = normalize(val, min_v, max_v, higher_better)
                score += weight * norm_val
                total_weight += weight
                breakdown[metric] = {"raw": val, "norm": norm_val, "weight": weight}
        elif weight > 0.05: missing.append(metric)
    
    if total_weight == 0: return None, {}, missing
    return round((score / total_weight) * 100, 1), breakdown, missing

def compute_hitter_score(recent: Dict, baseline: Dict = None) -> float:
    if not recent: return 50
    score = 0
    weights_total = 0
    if recent.get("avg"):
        avg_score = normalize(recent["avg"], 0.180, 0.380, True) * 100
        score += avg_score * 0.25
        weights_total += 0.25
    if recent.get("ops"):
        ops_score = normalize(recent["ops"], 0.550, 1.100, True) * 100
        score += ops_score * 0.25
        weights_total += 0.25
    if recent.get("k_rate"):
        k_score = normalize(recent["k_rate"], 0.35, 0.10, False) * 100
        score += k_score * 0.15
        weights_total += 0.15
    
    # Bonuses/Penalties
    bonus = 0
    if recent.get("hit_streak", 0) >= 3:
        bonus += min(recent["hit_streak"] * 3, 15)
    if recent.get("hitless_streak", 0) >= 2:
        bonus -= min(recent["hitless_streak"] * 5, 20)
    if recent.get("hr", 0) >= 1:
        bonus += min(recent["hr"] * 5, 15)
    
    if weights_total == 0: return 50
    final_score = (score / weights_total) + bonus
    return max(0, min(100, final_score * 1.1))

def project_lines(salci: float, base_k9: float = 9.0) -> Dict:
    expected = (base_k9 * 5.5 / 9) * (0.7 + (salci / 100) * 0.6)
    lines = {}
    for k in range(3, 9):
        diff = k - expected
        if diff <= -2: prob = 92
        elif diff <= -1: prob = 80
        elif diff <= 0: prob = 65
        elif diff <= 1: prob = 45
        elif diff <= 2: prob = 28
        else: prob = 15
        prob = max(5, min(95, prob + (salci - 50) / 10))
        lines[k] = round(prob)
    return {"expected": round(expected, 1), "lines": lines}

def get_matchup_grade(hitter_k_rate: float, pitcher_k_pct: float, 
                      hitter_hand: str, pitcher_hand: str) -> Tuple[str, str]:
    platoon_adv = 10 if (hitter_hand == "L" and pitcher_hand == "R") or (hitter_hand == "R" and pitcher_hand == "L") else -5
    k_matchup = 0
    if hitter_k_rate < 0.18 and pitcher_k_pct > 0.28: k_matchup = 15
    elif hitter_k_rate > 0.28 and pitcher_k_pct > 0.28: k_matchup = -15
    elif hitter_k_rate < 0.20: k_matchup = 10
    elif hitter_k_rate > 0.30: k_matchup = -10
    total = 50 + platoon_adv + k_matchup
    if total >= 65: return "🟢 Favorable", "matchup-good"
    elif total >= 45: return "🟡 Neutral", "matchup-neutral"
    else: return "🔴 Tough", "matchup-bad"

# ----------------------------
# Chart Functions
# ----------------------------
def create_pitcher_comparison_chart(pitcher_results: List[Dict]) -> go.Figure:
    if not pitcher_results: return None
    top_pitchers = sorted(pitcher_results, key=lambda x: x["salci"], reverse=True)[:10][::-1]
    names = [f"{p['pitcher'].split()[-1]} ({p.get('pitcher_hand', 'R')})" for p in top_pitchers]
    scores = [p["salci"] for p in top_pitchers]
    colors = [get_salci_color(s) for s in scores]
    fig = go.Figure(go.Bar(y=names, x=scores, orientation='h', marker_color=colors, text=[f"{s}" for s in scores], textposition='outside'))
    fig.add_vline(x=75, line_dash="dash", line_color="#10b981", line_width=2, annotation_text="Elite (75+)")
    fig.update_layout(title="Today's Top SALCI Pitchers", xaxis=dict(range=[0, 100]), height=400, margin=dict(l=100, r=50, t=80, b=60))
    return fig

def create_hitter_hotness_chart(hitter_results: List[Dict]) -> go.Figure:
    if not hitter_results: return None
    top_hitters = sorted(hitter_results, key=lambda x: x["score"], reverse=True)[:8]
    names = [f"{h['name'].split()[-1]} ({h.get('bat_side', 'R')})" for h in top_hitters]
    avgs = [h["recent"].get("avg", 0) for h in top_hitters]
    ops_vals = [h["recent"].get("ops", 0) for h in top_hitters]
    fig = go.Figure()
    fig.add_trace(go.Bar(name='AVG (L7)', x=names, y=avgs, marker_color=COLORS["hot"]))
    fig.add_trace(go.Bar(name='OPS (L7)', x=names, y=ops_vals, marker_color=COLORS["secondary"]))
    fig.update_layout(title="Hottest Hitters (Last 7 Games)", barmode='group', height=350)
    return fig

def create_salci_breakdown_chart() -> go.Figure:
    labels = ['K/9', 'K%', 'Opp K%', 'Opp Contact%', 'K/BB', 'P/IP']
    values = [18, 18, 22, 18, 14, 10]
    fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.6, marker_colors=['#3266ad', '#7F77DD', '#1D9E75', '#D85A30', '#eab308', '#888780'])])
    fig.update_layout(title="SALCI Score Breakdown", height=350, showlegend=False)
    return fig

def create_matchup_scatter(hitter_results: List[Dict]) -> go.Figure:
    if not hitter_results or len(hitter_results) < 3: return None
    k_rates = [h["recent"].get("k_rate", 0.22) * 100 for h in hitter_results]
    avgs = [h["recent"].get("avg", 0.250) for h in hitter_results]
    short_names = [f"{h['name'].split()[-1]} ({h.get('bat_side', 'R')})" for h in hitter_results]
    colors = [get_salci_color(h["score"]) if h["score"] >= 50 else COLORS["cold"] for h in hitter_results]
    fig = go.Figure(go.Scatter(x=k_rates, y=avgs, mode='markers+text', marker=dict(size=12, color=colors), text=short_names, textposition='top center'))
    fig.update_layout(title="Hitter Profile: K% vs AVG (L7)", xaxis_title="K% (Lower is better)", yaxis_title="AVG", height=400)
    return fig

def create_stuff_location_chart(pitcher_results: List[Dict]) -> go.Figure:
    p_with_scores = [p for p in pitcher_results if p.get("stuff_score") and p.get("location_score")]
    if len(p_with_scores) < 3: return None
    stuff = [p["stuff_score"] for p in p_with_scores]
    loc = [p["location_score"] for p in p_with_scores]
    names = [f"{p['pitcher'].split()[-1]} ({p.get('pitcher_hand', 'R')})" for p in p_with_scores]
    colors = [get_salci_color(p["salci"]) for p in p_with_scores]
    fig = go.Figure(go.Scatter(x=stuff, y=loc, mode='markers+text', marker=dict(size=12, color=colors), text=names, textposition='top center'))
    fig.update_layout(title="Pitcher Profiles: Stuff vs Location", xaxis_title="Stuff", yaxis_title="Location", xaxis=dict(range=[20, 100]), yaxis=dict(range=[20, 100]), height=450)
    return fig

def create_k_projection_chart(pitcher_results: List[Dict]) -> go.Figure:
    if not pitcher_results: return None
    top_p = sorted(pitcher_results, key=lambda x: x["salci"], reverse=True)[:5]
    names = [f"{p['pitcher'].split()[-1]}" for p in top_p]
    expected = [p["expected"] for p in top_p]
    fig = go.Figure(go.Bar(x=names, y=expected, marker_color=COLORS["primary"], text=expected, textposition='outside'))
    fig.update_layout(title="Expected Strikeouts (Top Pitchers)", height=350)
    return fig

def render_pitcher_card(result: Dict, show_stuff_location: bool = True):
    rating_label, emoji, css_class = get_rating(result["salci"])
    with st.container():
        col1, col2, col3 = st.columns([2, 1, 2])
        with col1:
            p_hand = result.get("pitcher_hand", "R")
            st.markdown(f"### {result['pitcher']} ({p_hand}HP)")
            st.markdown(f"**{result['team']}** vs {result['opponent']}")
            if result.get("profile_type") and result.get("profile_type") != "BALANCED":
                profile_emoji = {"ELITE": "⚡", "STUFF-DOMINANT": "🔥", "LOCATION-DOMINANT": "🎯", "BALANCED-PLUS": "💪", "BALANCED": "⚖️", "ONE-TOOL": "📊", "LIMITED": "⚠️"}.get(result["profile_type"], "📊")
                st.markdown(f"<span style='font-size: 0.85rem;'>{profile_emoji} {result['profile_type']}</span>", unsafe_allow_html=True)
            badges = []
            badges.append("<span style='font-size: 0.7rem; background: #10b981; color: white; padding: 2px 6px; border-radius: 4px;'>🎯 Statcast</span>" if result.get("is_statcast") else "<span style='font-size: 0.7rem; background: #6b7280; color: white; padding: 2px 6px; border-radius: 4px;'>📊 Stats API</span>")
            if result.get("matchup_source") == "lineup": badges.append("<span style='font-size: 0.7rem; background: #3b82f6; color: white; padding: 2px 6px; border-radius: 4px;'>📋 Lineup Match</span>")
            st.markdown(" ".join(badges), unsafe_allow_html=True)
        with col2:
            st.markdown(f"""
            <div style='text-align: center; background: #f0f4f8; border-radius: 10px; padding: 0.5rem; border: 1px solid #e2e8f0;'>
                <div style='font-size: 0.8rem; color: #666;'>SALCI</div>
                <div style='font-size: 1.8rem; font-weight: bold; color: {get_salci_color(result['salci'])};'>{result['salci']}</div>
                <div style='font-size: 0.7rem; font-weight: bold;'>{rating_label} {emoji}</div>
            </div>
            """, unsafe_allow_html=True)
        with col3:
            st.markdown(f"**Expected Ks: {result['expected']}**")
            lines_dict = result.get("lines", {}) or result.get("k_lines", {})
            k5 = lines_dict.get(5, "?")
            k6 = lines_dict.get(6, "?")
            k7 = lines_dict.get(7, "?")
            st.markdown(f"<span style='font-size: 0.9rem;'>5+ Ks: **{k5}%** | 6+ Ks: **{k6}%** | 7+ Ks: **{k7}%**</span>", unsafe_allow_html=True)
            if result.get("floor"): st.markdown(f"<span style='font-size: 0.8rem; color: #666;'>Floor: {result['floor']} Ks ({result.get('floor_confidence', 70)}% conf)</span>", unsafe_allow_html=True)
        
        if show_stuff_location and (result.get("stuff_score") or result.get("location_score")):
            st.markdown("---")
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("Stuff Score", result.get("stuff_score", "-"))
            with c2: st.metric("Location Score", result.get("location_score", "-"))
            with c3: st.metric("Matchup Score", result.get("matchup_score", "-"))
            with c4: st.metric("Workload Score", result.get("workload_score", "-"))
            if result.get("stuff_breakdown") and result["stuff_breakdown"].get("by_pitch_type"):
                with st.expander("🎪 Arsenal & Per-Pitch Stuff+"):
                    render_arsenal_display(result["stuff_breakdown"]["by_pitch_type"])

def render_arsenal_display(arsenal: Dict):
    arsenal_html = "<div style='overflow-x: auto;'><div style='display: flex; gap: 10px; padding: 5px 0;'>"
    for name, data in arsenal.items():
        usage = data.get('usage', 0)
        if usage < 5: continue
        stuff = data.get('stuff_plus', 100)
        velo = data.get('velocity', 0)
        whiff = data.get('whiff_pct', 0)
        color = "#8b5cf6" if stuff >= 105 else "#6b7280" if stuff >= 95 else "#ef4444"
        bg = "rgba(139, 92, 246, 0.1)" if stuff >= 105 else "rgba(107, 114, 128, 0.1)" if stuff >= 95 else "rgba(239, 68, 68, 0.1)"
        arsenal_html += f"""
        <div style='background: {bg}; border: 1px solid {color}; border-radius: 6px; padding: 6px 10px; min-width: 80px;'>
            <div style='font-size: 0.75rem; font-weight: bold; color: {color};'>{name}</div>
            <div style='font-size: 0.65rem; color: #666;'>{velo:.0f} mph • {usage:.0f}%</div>
            <div style='font-size: 0.85rem; font-weight: bold; color: {color};'>Stuff+ {int(stuff)}</div>
            <div style='font-size: 0.6rem; color: #888;'>Whiff {whiff:.0f}%</div>
        </div>
        """
    arsenal_html += "</div></div>"
    st.markdown(arsenal_html, unsafe_allow_html=True)

def render_hitter_card(hitter: Dict, show_batting_order: bool = True):
    score = hitter.get("score", 50)
    rating, css = get_hitter_rating(score)
    recent = hitter.get("recent", {})
    season = hitter.get("season", {})
    matchup_grade, matchup_css = get_matchup_grade(recent.get("k_rate", 0.22), hitter.get("pitcher_k_pct", 0.22), hitter.get("bat_side", "R"), hitter.get("pitcher_hand", "R"))
    col1, col2, col3, col4, col5 = st.columns([2.5, 1.2, 1.2, 1.2, 1])
    with col1:
        order = f"<span class='batting-order'>#{hitter['batting_order']}</span> " if show_batting_order and hitter.get("batting_order") else ""
        st.markdown(f"{order}**{hitter['name']}** ({hitter.get('position', '')})", unsafe_allow_html=True)
        st.markdown(f"<span style='font-size: 0.8rem; color: #555;'>{hitter.get('bat_side', 'R')}HB • {season.get('ab', 0)} AB (2025)</span>", unsafe_allow_html=True)
        if recent.get("hit_streak", 0) >= 3: st.markdown(f"<span class='hot-streak'>🔥 {recent['hit_streak']}-game hit streak</span>", unsafe_allow_html=True)
        elif recent.get("hitless_streak", 0) >= 3: st.markdown(f"<span class='cold-streak'>❄️ {recent['hitless_streak']}-game hitless</span>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div style='text-align: center;'><div style='font-size: 0.7rem; color: #666;'>AVG</div><div style='font-size: 1rem; font-weight: bold;'>{recent.get('avg', 0):.3f}</div><div style='font-size: 0.65rem; color: #aaa;'>L7</div></div>", unsafe_allow_html=True)
    with col3:
        st.markdown(f"<div style='text-align: center;'><div style='font-size: 0.7rem; color: #666;'>OPS</div><div style='font-size: 1rem; font-weight: bold;'>{recent.get('ops', 0):.3f}</div><div style='font-size: 0.65rem; color: #aaa;'>L7</div></div>", unsafe_allow_html=True)
    with col4:
        krate = recent.get("k_rate", 0) * 100
        color = "#10b981" if krate < 20 else "#eab308" if krate < 28 else "#ef4444"
        st.markdown(f"<div style='text-align: center;'><div style='font-size: 0.7rem; color: #666;'>K% (L7)</div><div style='font-size: 1rem; font-weight: bold; color: {color};'>{krate:.1f}%</div></div>", unsafe_allow_html=True)
    with col5:
        st.markdown(f"<div class='{matchup_css}' style='padding: 0.5rem; border-radius: 5px; text-align: center; font-size: 0.8rem;'>{matchup_grade}</div>", unsafe_allow_html=True)

# ----------------------------
# Main App
# ----------------------------
def main():
    st.markdown(f"<h1 class='main-header'>⚾ SALCI v{SALCI_VERSION}</h1>", unsafe_allow_html=True)
    st.markdown("<p class='sub-header'>Advanced MLB Prediction System • Stuff + Location + Reflection</p>", unsafe_allow_html=True)
    
    with st.sidebar:
        st.header("⚙️ Settings")
        if STATCAST_AVAILABLE: st.success("🎯 Statcast: Connected")
        else: st.info("📊 Statcast: Using proxy metrics")
        
        selected_date = st.date_input("📅 Select Date", value=datetime.today())
        current_year = selected_date.year
        
        preset_key = st.selectbox("Pitcher Model Weights", options=list(WEIGHT_PRESETS.keys()), format_func=lambda x: WEIGHT_PRESETS[x]["name"])
        st.caption(WEIGHT_PRESETS[preset_key]["desc"])
        
        st.subheader("Filters")
        min_salci = st.slider("Min Pitcher SALCI", 0, 80, 0, 5)
        show_hitters = st.checkbox("Show Hitter Analysis", value=True)
        confirmed_only = st.checkbox("Confirmed Lineups Only", value=True)
        hot_hitters_only = st.checkbox("Hot Hitters Only (Score ≥ 60)", value=False)
        
        if st.button("🔄 Refresh Lineups", use_container_width=True):
            st.cache_data.clear()
            _statcast_cache.clear()
            st.rerun()
    
    date_str = selected_date.strftime("%Y-%m-%d")
    weights = WEIGHT_PRESETS[preset_key]["weights"]
    
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["⚾ Pitcher Analysis", "🏏 Hitter Matchups", "🎯 Best Bets", "🔥 Heat Maps", "📊 Charts & Share", "📈 Yesterday", "🎯 Model Accuracy"])
    
    with st.spinner("🔍 Fetching games and lineups..."):
        games = get_games_by_date(date_str)
    
    if not games:
        st.warning(f"No games found for {date_str}")
        return
    
    lineup_status = {}
    for game in games:
        game_pk = game["game_pk"]
        h_l, h_c = get_confirmed_lineup(game_pk, "home")
        a_l, a_c = get_confirmed_lineup(game_pk, "away")
        lineup_status[game_pk] = {"home": {"lineup": h_l, "confirmed": h_c}, "away": {"lineup": a_l, "confirmed": a_c}}
    
    all_pitcher_results = []
    all_hitter_results = []
    
    progress = st.progress(0)
    for i, game in enumerate(games):
        progress.progress((i + 1) / len(games))
        game_pk = game["game_pk"]
        game_lineups = lineup_status[game_pk]
        
        for side in ["home", "away"]:
            pitcher = game.get(f"{side}_pitcher", "TBD")
            pid = game.get(f"{side}_pid")
            if not pid or pitcher == "TBD": continue
            
            p_hand = game.get(f"{side}_pitcher_hand", "R")
            team = game.get(f"{side}_team")
            opp = game.get("away_team" if side == "home" else "home_team")
            opp_id = game.get("away_team_id" if side == "home" else "home_team_id")
            opp_side = "away" if side == "home" else "home"
            
            p_recent = get_recent_pitcher_stats(pid, 7)
            p_baseline = parse_season_stats(get_player_season_stats(pid, current_year))
            opp_recent = get_team_batting_stats(opp_id, 14)
            opp_baseline = get_team_season_batting(opp_id, current_year)
            
            # SALCI v3 Logic
            salci_v3_result = None
            if STATCAST_AVAILABLE:
                try:
                    profile = get_cached_statcast_profile(pid, days=30)
                    if profile:
                        stuff = profile.get('stuff_plus', 100)
                        loc = profile.get('location_plus', 100)
                        
                        # Blending
                        games_played = p_recent.get("games_sampled", 0) if p_recent else 0
                        opp_lineup_info = game_lineups[opp_side]
                        lineup_hitter_stats = []
                        if opp_lineup_info.get('confirmed') and opp_lineup_info.get('lineup'):
                            for player in opp_lineup_info['lineup']:
                                h_recent = get_hitter_recent_stats(player['id'], 7)
                                if h_recent:
                                    lineup_hitter_stats.append({'name': player['name'], 'k_rate': h_recent.get('k_rate', 0.22), 'bat_side': player.get('bat_side', 'R')})
                        
                        m_score, m_break = calculate_matchup_score_v3(opp_recent or {}, lineup_hitter_stats, p_hand)
                        avg_ip = p_recent.get('total_ip', 0) / max(p_recent.get('games_sampled', 1), 1) if p_recent else 5.5
                        w_stats = {'P/IP': p_recent.get('P/IP', 16.0) if p_recent else 16.0, 'avg_ip': avg_ip}
                        w_score, w_break = calculate_workload_score_v3(w_stats)
                        
                        salci_v3_result = calculate_salci_v3(stuff, loc, m_score, w_score)
                        if games_played < 5:
                            v1_score, _, _ = compute_salci(p_recent, p_baseline, opp_recent, opp_baseline, weights, games_played)
                            if v1_score:
                                w3, w1 = get_blend_weights(games_played)
                                salci_v3_result['salci'] = (salci_v3_result['salci'] * w3) + (v1_score * w1)
                except: pass

            if salci_v3_result:
                salci = salci_v3_result['salci']
                proj = calculate_expected_ks_v3(salci_v3_result)
                breakdown = salci_v3_result['components']
            else:
                salci, breakdown, _ = compute_salci(p_recent, p_baseline, opp_recent, opp_baseline, weights, p_recent.get("games_sampled", 0) if p_recent else 0)
                proj = project_lines(salci, p_baseline.get("K9", 9.0) if p_baseline else 9.0)
            
            if salci is not None:
                stuff_s, stuff_b = calculate_stuff_score(p_recent or {}, pid)
                loc_s, loc_b = calculate_location_score(p_recent or {}, pid)
                all_pitcher_results.append({
                    "pitcher": pitcher, "pitcher_id": pid, "pitcher_hand": p_hand, "team": team, "opponent": opp, "opponent_id": opp_id, "game_pk": game_pk,
                    "salci": salci, "salci_grade": get_component_grade(salci) if 'get_component_grade' in globals() else "C",
                    "expected": proj["expected"], "lines": proj.get("lines", {}), "k_lines": proj.get("k_lines", {}),
                    "stuff_score": stuff_s, "location_score": loc_s, "matchup_score": breakdown.get("Matchup", 50), "workload_score": breakdown.get("Workload", 50),
                    "stuff_breakdown": stuff_b, "is_statcast": salci_v3_result is not None, "lineup_confirmed": game_lineups[opp_side]["confirmed"]
                })
            
            if show_hitters:
                opp_lineup = game_lineups[opp_side]
                if opp_lineup["confirmed"] or not confirmed_only:
                    for player in opp_lineup["lineup"]:
                        h_recent = get_hitter_recent_stats(player["id"], 7)
                        h_season = get_hitter_season_stats(player["id"], current_year)
                        if h_recent:
                            h_score = compute_hitter_score(h_recent)
                            if not hot_hitters_only or h_score >= 60:
                                all_hitter_results.append({
                                    "name": player["name"], "player_id": player["id"], "position": player["position"], "batting_order": player["batting_order"],
                                    "bat_side": player["bat_side"], "team": opp, "vs_pitcher": pitcher, "pitcher_hand": p_hand, "pitcher_k_pct": p_recent.get("K_percent", 0.22) if p_recent else 0.22,
                                    "game_pk": game_pk, "recent": h_recent, "season": h_season or {}, "score": h_score, "lineup_confirmed": opp_lineup["confirmed"]
                                })
    progress.empty()

    with tab1:
        st.markdown("### ⚾ Pitcher Analysis")
        if not all_pitcher_results: st.info("No pitcher data available for this date.")
        else:
            top_p = sorted(all_pitcher_results, key=lambda x: x["salci"], reverse=True)
            for p in top_p:
                if p["salci"] >= min_salci:
                    render_pitcher_card(p)
                    st.markdown("---")

    with tab2:
        st.markdown("### 🏏 Hitter Matchups")
        if not all_hitter_results: st.info("No hitter data available.")
        else:
            col1, col2 = st.columns(2)
            hot = [h for h in all_hitter_results if h["score"] >= 70]
            cold = [h for h in all_hitter_results if h["score"] <= 30]
            with col1:
                st.markdown("#### 🔥 Hottest Hitters")
                for h in hot[:8]: render_hitter_card(h)
            with col2:
                st.markdown("#### ❄️ Coldest Hitters")
                for h in cold[:8]: render_hitter_card(h)
            st.markdown("---")
            st.markdown("#### 📊 All Confirmed Starters")
            df_hitters = pd.DataFrame([{
                "Order": f"#{h['batting_order']}", "Player": h["name"], "Bats": h.get("bat_side", "R"), "Team": h["team"], "Pos": h["position"],
                "vs Pitcher": h["vs_pitcher"], "AVG (L7)": f"{h['recent'].get('avg', 0):.3f}", "OPS (L7)": f"{h['recent'].get('ops', 0):.3f}",
                "K% (L7)": f"{h['recent'].get('k_rate', 0)*100:.1f}%", "Streak": h["recent"].get("hit_streak", 0) if h["recent"].get("hit_streak", 0) > 0 else -h["recent"].get("hitless_streak", 0),
                "Confirmed": "✅" if h.get("lineup_confirmed") else "⏳"
            } for h in all_hitter_results])
            st.dataframe(df_hitters, use_container_width=True, hide_index=True)

    with tab3:
        st.markdown("### 🎯 Best Bets")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### ⚾ Top Pitcher K Props")
            top_p = [p for p in all_pitcher_results if p["salci"] >= 60][:5]
            for i, p in enumerate(top_p, 1):
                label, emoji, _ = get_rating(p["salci"])
                lines = p.get("lines", {}) or p.get("k_lines", {})
                st.markdown(f"""
                <div style='background: #e0f2fe; padding: 1rem; border-radius: 10px; margin-bottom: 0.5rem; border-left: 4px solid #3b82f6;'>
                    <strong>#{i} {p['pitcher']} ({p['pitcher_hand']}HP)</strong> ({p['team']} vs {p['opponent']})<br>
                    {emoji} SALCI: {p['salci']} | Expected: <strong>{p['expected']} Ks</strong><br>
                    5+ @ {lines.get(5, "?")}% | 6+ @ {lines.get(6, "?")}% | 7+ @ {lines.get(7, "?")}%
                </div>
                """, unsafe_allow_html=True)
        with c2:
            st.markdown("#### 🏏 Hot Hitter Props")
            top_h = [h for h in all_hitter_results if h["score"] >= 65 and h.get("lineup_confirmed")][:5]
            for i, h in enumerate(top_h, 1):
                st.markdown(f"""
                <div style='background: #fef3c7; padding: 1rem; border-radius: 10px; margin-bottom: 0.5rem; border-left: 4px solid #f59e0b;'>
                    <strong>#{i} {h['name']} ({h['bat_side']}HB)</strong> ({h['team']})<br>
                    vs {h['vs_pitcher']} | L7: <strong>{h['recent'].get('avg', 0):.3f} AVG</strong> / {h['recent'].get('ops', 0):.3f} OPS<br>
                    {f"🔥 {h['recent'].get('hit_streak', 0)}-game hit streak" if h['recent'].get('hit_streak', 0) >= 3 else ""}
                </div>
                """, unsafe_allow_html=True)

    with tab4:
        st.markdown("### 🔥 Zone Heat Maps")
        if not STATCAST_AVAILABLE: st.warning("Heat Maps require Statcast data (pybaseball).")
        else:
            col_p, col_h = st.columns(2)
            with col_p:
                st.markdown("#### 🎯 Pitcher Attack Map")
                p_opts = {f"{p['pitcher']} ({p['team']})": p for p in all_pitcher_results}
                sel_p_name = st.selectbox("Select Pitcher", options=list(p_opts.keys()), key="heatmap_pitcher")
                if sel_p_name:
                    sel_p = p_opts[sel_p_name]
                    attack = get_pitcher_attack_map(sel_p["pitcher_id"], days=30)
                    if attack and attack.get('grid'):
                        grid = attack['grid']
                        z_data = [[grid.get((r-1)*3+c, {}).get('whiff_pct', 20) for c in [1,2,3]] for r in [3,2,1]]
                        fig = go.Figure(data=go.Heatmap(z=z_data, colorscale='RdYlGn', showscale=True))
                        fig.update_layout(title=f"{sel_p['pitcher']} Attack Zones", height=350)
                        st.plotly_chart(fig, use_container_width=True)
            with col_h:
                st.markdown("#### 💥 Hitter Damage Map")
                h_opts = {f"{h['name']} ({h['team']})": h for h in all_hitter_results[:20]}
                sel_h_name = st.selectbox("Select Hitter", options=list(h_opts.keys()), key="heatmap_hitter")
                if sel_h_name:
                    sel_h = h_opts[sel_h_name]
                    damage = get_hitter_damage_map(sel_h["player_id"], days=30)
                    if damage and damage.get('grid'):
                        grid = damage['grid']
                        z_data = [[grid.get((r-1)*3+c, {}).get('ba', 0.250) for c in [1,2,3]] for r in [3,2,1]]
                        fig = go.Figure(data=go.Heatmap(z=z_data, colorscale='Blues', showscale=True))
                        fig.update_layout(title=f"{sel_h['name']} Damage Zones", height=350)
                        st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("---")
            st.markdown("#### ⚔️ Matchup Collision Analysis")
            if all_pitcher_results and all_hitter_results:
                cp1, cp2 = st.columns(2)
                with cp1: m_p = st.selectbox("Pitcher", options=[f"{p['pitcher']} ({p['team']})" for p in all_pitcher_results], key="m_p")
                with cp2: m_h = st.selectbox("Hitter", options=[f"{h['name']} ({h['team']})" for h in all_hitter_results[:20]], key="m_h")
                if st.button("🔍 Analyze Matchup", use_container_width=True):
                    p_obj = next(p for p in all_pitcher_results if f"{p['pitcher']} ({p['team']})" == m_p)
                    h_obj = next(h for h in all_hitter_results if f"{h['name']} ({h['team']})" == m_h)
                    res = analyze_matchup_zones(p_obj["pitcher_id"], h_obj["player_id"], days=30)
                    if res:
                        st.success(f"Matchup Edge: {res.get('matchup_edge', 'NEUTRAL')}")
                        st.write(res.get('edge_description', ''))

    with tab5:
        st.markdown("### 📊 Charts & Share")
        c1, c2 = st.columns(2)
        with c1:
            fig1 = create_pitcher_comparison_chart(all_pitcher_results)
            if fig1: st.plotly_chart(fig1, use_container_width=True)
        with c2:
            fig2 = create_hitter_hotness_chart(all_hitter_results)
            if fig2: st.plotly_chart(fig2, use_container_width=True)
        c3, c4 = st.columns(2)
        with c3:
            fig3 = create_stuff_location_chart(all_pitcher_results)
            if fig3: st.plotly_chart(fig3, use_container_width=True)
        with c4:
            fig4 = create_k_projection_chart(all_pitcher_results)
            if fig4: st.plotly_chart(fig4, use_container_width=True)

    with tab6:
        st.markdown("### 📈 Yesterday's Reflection")
        yesterday_str = (selected_date - timedelta(days=1)).strftime("%Y-%m-%d")
        if REFLECTION_AVAILABLE:
            if st.button("📥 Collect Yesterday's Results & Reflect", use_container_width=True):
                with st.spinner("Analyzing yesterday's performance..."):
                    refl_data = refl.collect_and_reflect_yesterday()
                    if refl_data: st.success("Reflection generated successfully!")
                    else: st.warning("No predictions found for yesterday.")
            
            yesterday_refl = refl.load_reflection(yesterday_str)
            if yesterday_refl:
                st.markdown(f"#### Reflection for {yesterday_str}")
                st.metric("Projection Accuracy", f"{yesterday_refl['projection_accuracy']*100:.1f}%")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Overperformers**")
                    for p in yesterday_refl['overperformers']: st.write(f"- {p['name']}: {p['actual']} Ks (Proj: {p['projected']})")
                with col2:
                    st.markdown("**Underperformers**")
                    for p in yesterday_refl['underperformers']: st.write(f"- {p['name']}: {p['actual']} Ks (Proj: {p['projected']})")
            else: st.info(f"No reflection data for {yesterday_str}. Use the button above to generate.")
        
        st.markdown("---")
        st.markdown("#### 💾 Save Today's Predictions")
        if st.button("📥 Save Predictions for Tomorrow", use_container_width=True):
            if REFLECTION_AVAILABLE:
                preds = {"date": date_str, "pitchers": all_pitcher_results}
                if refl.save_daily_predictions(date_str, preds): st.success(f"Saved {len(all_pitcher_results)} predictions for {date_str}")
                else: st.error("Failed to save predictions.")
            else: st.error("Reflection module not found.")

    with tab7:
        st.markdown("### 🎯 Model Accuracy Dashboard")
        if REFLECTION_AVAILABLE:
            rolling = refl.get_rolling_accuracy(days=7)
            if rolling.get("games_analyzed", 0) > 0:
                st.metric("7-Day Accuracy (±1.5 K)", f"{rolling['accuracy_pct']}%")
                st.write(f"Games Analyzed: {rolling['games_analyzed']}")
                st.write(f"Average K Delta: {rolling['avg_k_delta']}")
                st.write(f"Model Tendency: {rolling['tendency']}")
            else: st.info("No historical accuracy data available yet.")
        else: st.error("Reflection module not found.")

if __name__ == "__main__":
    main()
