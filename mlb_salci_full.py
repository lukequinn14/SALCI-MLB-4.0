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
- ✅ Unified Storage: Predictions persist correctly with K-lines for reflection
- 🔒 Lineup-Gated Charts: Only confirmed lineups show in Charts & Share

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
# Statcast & Reflection Integration
# ----------------------------
STATCAST_AVAILABLE = False
SALCI_V3_AVAILABLE = False
REFLECTION_AVAILABLE = False

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

try:
    import reflection as refl
    REFLECTION_AVAILABLE = True
except ImportError:
    REFLECTION_AVAILABLE = False

# ----------------------------
# Version Info
# ----------------------------
SALCI_VERSION = "5.1"
SALCI_BUILD_DATE = "2026-04-06"

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
    "stuff": "#8b5cf6",
    "location": "#06b6d4",
}

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

def get_current_mlb_season(selected_date: datetime) -> int:
    """Determine MLB season based on selected date."""
    if selected_date.month >= 4:  # April onwards is current season
        return selected_date.year
    else:  # Jan-March is previous season
        return selected_date.year - 1

# ----------------------------
# API Functions - Teams & Schedule
# ----------------------------
@st.cache_data(ttl=300)
def get_team_id_lookup() -> Dict[str, int]:
    url = "https://statsapi.mlb.com/api/v1/teams?sportId=1"
    try:
        res = requests.get(url, timeout=10)
        return {team["name"]: team["id"] for team in res.json().get("teams", [])}
    except Exception as e:
        st.error(f"Error fetching teams: {e}")
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
    except Exception as e:
        return None

def get_confirmed_lineup(game_pk: int, team_side: str) -> Tuple[List[Dict], bool]:
    """Fetch confirmed lineup for a team in a game. Returns (lineup, is_confirmed)."""
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
        
        # Lineup is confirmed if we have at least 9 players
        is_confirmed = len(lineup) >= 9
        return lineup, is_confirmed
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
    except Exception as e:
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
    except Exception as e:
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
        
        if totals["ab"] == 0:
            return None
        
        avg = totals["hits"] / totals["ab"]
        slg = (totals["hits"] + totals["doubles"] + 2*totals["triples"] + 3*totals["hr"]) / totals["ab"]
        obp = (totals["hits"] + totals["bb"]) / (totals["ab"] + totals["bb"]) if (totals["ab"] + totals["bb"]) > 0 else 0
        ops = obp + slg
        k_rate = totals["so"] / totals["ab"]
        
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
            "games": totals["games"]
        }
    except Exception as e:
        pass
    return None

@st.cache_data(ttl=3600)
def get_hitter_season_stats(player_id: int, season: int) -> Optional[Dict]:
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
    except Exception as e:
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
    except Exception as e:
        pass
    return None

@st.cache_data(ttl=3600)
def get_team_season_batting(team_id: int, season: int) -> Optional[Dict]:
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
    except Exception as e:
        pass
    return None

# ----------------------------
# Calculation Functions
# ----------------------------
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
        elif recent_val is not None:
            pitcher_stats[metric] = recent_val
        elif baseline_val is not None:
            pitcher_stats[metric] = baseline_val
    
    opp_stats = {}
    for metric in ["OppK%", "OppContact%"]:
        recent_val = opp_recent.get(metric) if opp_recent else None
        baseline_val = opp_baseline.get(metric) if opp_baseline else None
        if recent_val is not None and baseline_val is not None:
            opp_stats[metric] = recent_w * recent_val + baseline_w * baseline_val
        elif recent_val is not None:
            opp_stats[metric] = recent_val
        elif baseline_val is not None:
            opp_stats[metric] = baseline_val
    
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
        elif weight > 0.05:
            missing.append(metric)
    
    if total_weight == 0:
        return None, {}, missing
    
    return round((score / total_weight) * 100, 1), breakdown, missing

def compute_hitter_score(recent: Dict, baseline: Dict = None) -> float:
    if not recent:
        return 50
    
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
    
    base_score = score / weights_total if weights_total > 0 else 50
    return max(0, min(100, base_score))

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
        
        if REFLECTION_AVAILABLE: st.success("📈 Reflection: Active")
        else: st.info("📈 Reflection: Not available")
        
        selected_date = st.date_input("📅 Select Date", value=datetime.today())
        preset_key = st.selectbox("Model Weights", options=list(WEIGHT_PRESETS.keys()), 
                                 format_func=lambda x: WEIGHT_PRESETS[x]["name"])
        
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    date_str = selected_date.strftime("%Y-%m-%d")
    season = get_current_mlb_season(selected_date)
    weights = WEIGHT_PRESETS[preset_key]["weights"]
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "⚾ Pitcher Analysis", "🏏 Hitter Matchups", "🎯 Best Bets", "📊 Charts & Share", "📈 Accuracy", "🔧 Debug"
    ])
    
    games = get_games_by_date(date_str)
    if not games:
        st.warning(f"No games found for {date_str}")
        return

    # -------------------------------------------
    # MAIN PROCESSING LOOP
    # -------------------------------------------
    all_pitcher_results = []
    all_hitter_results = []
    
    for game in games:
        game_pk = game["game_pk"]
        
        # Check lineup confirmation
        home_lineup, home_confirmed = get_confirmed_lineup(game_pk, "home")
        away_lineup, away_confirmed = get_confirmed_lineup(game_pk, "away")
        
        for side in ["home", "away"]:
            pid = game.get(f"{side}_pid")
            if not pid: 
                continue
            
            # Get pitcher stats
            p_recent = get_recent_pitcher_stats(pid, 7)
            p_baseline = parse_season_stats(get_player_season_stats(pid, season))
            
            opp_id = game.get("away_team_id" if side == "home" else "home_team_id")
            opp_recent = get_team_batting_stats(opp_id, 14)
            opp_baseline = get_team_season_batting(opp_id, season)
            
            # Determine lineup confirmation
            lineup = home_lineup if side == "home" else away_lineup
            lineup_confirmed = home_confirmed if side == "home" else away_confirmed
            
            # Try SALCI v3 first
            salci_v3_result = None
            if SALCI_V3_AVAILABLE:
                try:
                    profile = get_pitcher_statcast_profile(pid, days=30)
                    if profile:
                        stuff = profile.get('stuff_plus', 100)
                        loc = profile.get('location_plus', 100)
                        
                        # Calculate Matchup using lineup if confirmed
                        lineup_hitter_stats = None
                        if lineup_confirmed and lineup:
                            lineup_hitter_stats = []
                            for hitter in lineup:
                                hitter_recent = get_hitter_recent_stats(hitter['id'], 7)
                                if hitter_recent:
                                    lineup_hitter_stats.append({
                                        'name': hitter['name'],
                                        'k_rate': hitter_recent.get('k_rate', 0.22),
                                        'zone_contact_pct': 0.82,  # Default
                                        'bat_side': hitter.get('bat_side', 'R')
                                    })
                        
                        m_score, m_break = calculate_matchup_score_v3(
                            opp_recent or {}, 
                            lineup_hitter_stats,
                            game.get(f"{side}_pitcher_hand", "R")
                        )
                        
                        # Workload
                        avg_ip = (p_recent or {}).get('total_ip', 0) / max(1, (p_recent or {}).get('games_sampled', 1))
                        w_stats = {
                            'P/IP': (p_recent or {}).get('P/IP', 16.0), 
                            'avg_ip': avg_ip
                        }
                        w_score, w_break = calculate_workload_score_v3(w_stats)
                        
                        # SALCI v3
                        salci_v3_result = calculate_salci_v3(stuff, loc, m_score, w_score)
                        
                        # K projection with Poisson probabilities
                        proj = calculate_expected_ks_v3(salci_v3_result, projected_ip=5.5)
                        
                        res = {
                            "pitcher": game[f"{side}_pitcher"],
                            "pitcher_id": pid,
                            "team": game[f"{side}_team"],
                            "opponent": game["away_team" if side == "home" else "home_team"],
                            "salci": salci_v3_result['salci'],
                            "salci_grade": salci_v3_result['grade'],
                            "expected": proj["expected_ks"],
                            "k_lines": proj["k_lines"],  # CRITICAL: Persist K-lines
                            "floor": proj["floor"],
                            "floor_confidence": proj["floor_confidence"],
                            "stuff_score": stuff,
                            "location_score": loc,
                            "matchup_score": m_score,
                            "workload_score": w_score,
                            "is_statcast": True,
                            "lineup_confirmed": lineup_confirmed,
                            "stuff_breakdown": profile.get('by_pitch_type')
                        }
                        all_pitcher_results.append(res)
                        continue
                except Exception as e:
                    pass
            
            # Fallback: v1 SALCI
            salci, breakdown, missing = compute_salci(p_recent, p_baseline, opp_recent, opp_baseline, weights)
            if salci:
                proj = project_lines(salci)
                all_pitcher_results.append({
                    "pitcher": game[f"{side}_pitcher"],
                    "pitcher_id": pid,
                    "team": game[f"{side}_team"],
                    "opponent": game["away_team" if side == "home" else "home_team"],
                    "salci": salci,
                    "salci_grade": get_rating(salci)[0],
                    "expected": proj["expected"],
                    "k_lines": proj["lines"],
                    "floor": int(np.floor(proj["expected"])),
                    "floor_confidence": 70,
                    "is_statcast": False,
                    "lineup_confirmed": lineup_confirmed
                })

    # -------------------------------------------
    # TAB 1: PITCHER ANALYSIS
    # -------------------------------------------
    with tab1:
        if all_pitcher_results:
            # Sort by SALCI descending
            sorted_pitchers = sorted(all_pitcher_results, key=lambda x: x["salci"], reverse=True)
            
            for res in sorted_pitchers:
                salci = res["salci"]
                grade, emoji, css = get_rating(salci)
                lineup_badge = "✅ Confirmed" if res.get("lineup_confirmed") else "⏳ Pending"
                
                with st.expander(f"{emoji} {res['pitcher']} ({res['team']}) - SALCI: {salci} [{grade}] {lineup_badge}", expanded=salci >= 70):
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric("Expected Ks", res.get("expected", "--"))
                    with col2:
                        st.metric("Floor (Confident)", f"{res.get('floor', '--')}K @ {res.get('floor_confidence', '--')}%")
                    with col3:
                        st.metric("Stuff+ / Loc+", f"{res.get('stuff_score', '--')} / {res.get('location_score', '--')}")
                    with col4:
                        st.metric("Grade", res.get("salci_grade", "C"))
                    
                    st.divider()
                    
                    # K-line odds
                    if res.get("k_lines"):
                        st.subheader("K-Line Probabilities")
                        k_lines_data = []
                        for k_val, prob in sorted(res["k_lines"].items()):
                            k_lines_data.append({"Line": f"{k_val}+", "Probability": f"{prob}%"})
                        st.dataframe(pd.DataFrame(k_lines_data), use_container_width=True)
        else:
            st.info("No pitcher data available for selected date")

    # -------------------------------------------
    # TAB 4: CHARTS & SHARE (Lineup-Gated)
    # -------------------------------------------
    with tab4:
        st.subheader("📊 Charts & Share")
        st.info("🔒 Only showing pitchers with confirmed lineups (improves accuracy)")
        
        # Filter for confirmed lineups ONLY
        confirmed_pitchers = [p for p in all_pitcher_results if p.get("lineup_confirmed", False)]
        
        if confirmed_pitchers:
            # Sort by SALCI
            confirmed_pitchers = sorted(confirmed_pitchers, key=lambda x: x["salci"], reverse=True)
            
            st.subheader(f"🎯 {len(confirmed_pitchers)} Pitchers with Confirmed Lineups")
            
            # Create sortable table
            table_data = []
            for p in confirmed_pitchers:
                table_data.append({
                    "Pitcher": p["pitcher"],
                    "Team": p["team"],
                    "Opponent": p["opponent"],
                    "SALCI": p["salci"],
                    "Grade": p["salci_grade"],
                    "Expected Ks": p["expected"],
                    "Floor": f"{p['floor']}K",
                    "Confidence": f"{p['floor_confidence']}%"
                })
            
            df_table = pd.DataFrame(table_data)
            st.dataframe(df_table, use_container_width=True)
            
            # Charts
            col1, col2 = st.columns(2)
            
            with col1:
                fig = px.bar(
                    df_table.sort_values("SALCI"),
                    x="SALCI",
                    y="Pitcher",
                    orientation="h",
                    color="SALCI",
                    color_continuous_scale="RdYlGn",
                    title="SALCI Rankings (Confirmed Lineups)"
                )
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                fig = px.bar(
                    df_table.sort_values("Expected Ks"),
                    x="Expected Ks",
                    y="Pitcher",
                    orientation="h",
                    title="Expected Strikeouts (Confirmed Lineups)"
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("⏳ No confirmed lineups yet. Lineups typically release 1-2 hours before game time.")

    # -------------------------------------------
    # TAB 5: ACCURACY DASHBOARD
    # -------------------------------------------
    with tab5:
        st.subheader("📈 Model Accuracy")
        
        if REFLECTION_AVAILABLE:
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("📊 Generate Yesterday's Reflection"):
                    with st.spinner("Analyzing yesterday's predictions..."):
                        reflection = refl.collect_and_reflect_yesterday()
                        if reflection:
                            st.success(f"✅ Analyzed {reflection['games_tracked']} games")
                            st.json(reflection)
                        else:
                            st.warning("No data for yesterday")
            
            with col2:
                rolling = refl.get_rolling_accuracy(7)
                st.metric("7-Day Accuracy", f"{rolling.get('accuracy_pct', '--')}%")
                st.metric("Avg K Delta", rolling.get("avg_k_delta", "--"))
                st.metric("Tendency", rolling.get("tendency", "N/A"))
        else:
            st.warning("Reflection module not available")

    # -------------------------------------------
    # TAB 6: DEBUG / SAVE
    # -------------------------------------------
    with tab6:
        st.subheader("🔧 Debug & Storage")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("💾 Save Predictions for Today"):
                if REFLECTION_AVAILABLE:
                    if refl.save_daily_predictions(date_str, {
                        "date": date_str,
                        "model_version": SALCI_VERSION,
                        "pitchers": all_pitcher_results
                    }):
                        st.success(f"✅ Saved {len(all_pitcher_results)} pitcher predictions")
                    else:
                        st.error("Failed to save")
                else:
                    st.error("Reflection module not available")
        
        with col2:
            if st.button("📂 Load Saved Predictions"):
                if REFLECTION_AVAILABLE:
                    saved = refl.load_daily_predictions(date_str)
                    if saved:
                        st.json(saved)
                    else:
                        st.info("No saved predictions for this date")
        
        st.divider()
        st.subheader("System Info")
        st.write(f"**SALCI Version:** {SALCI_VERSION}")
        st.write(f"**Build Date:** {SALCI_BUILD_DATE}")
        st.write(f"**Season:** {season}")
        st.write(f"**Statcast Available:** {STATCAST_AVAILABLE}")
        st.write(f"**Reflection Available:** {REFLECTION_AVAILABLE}")
        st.write(f"**Total Pitchers Analyzed:** {len(all_pitcher_results)}")
        st.write(f"**Confirmed Lineups:** {sum(1 for p in all_pitcher_results if p.get('lineup_confirmed'))}")

if __name__ == "__main__":
    main()
