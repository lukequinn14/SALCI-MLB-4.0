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
- 💾 UNIFIED REFLECTION SYSTEM: Standardized data storage with reflection.py

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
import plotly.express as px
import plotly.graph_objects as go

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
except ImportError as e:
    st.warning(f"⚠️ Statcast module not available: {e}")
    STATCAST_AVAILABLE = False
    SALCI_V3_AVAILABLE = False

try:
    from yesterday_tab import render_yesterday_tab
    YESTERDAY_TAB_AVAILABLE = True
except ImportError:
    YESTERDAY_TAB_AVAILABLE = False



# ---------------------------------------------------------------------------
# Hit Likelihood Integration
# ---------------------------------------------------------------------------
HIT_LIKELIHOOD_AVAILABLE = False
try:
    from hit_likelihood import calculate_hitter_hit_prob
    HIT_LIKELIHOOD_AVAILABLE = True
except ImportError:
    pass  # Graceful — Hit Score column simply won't appear

# ---------------------------------------------------------------------------
# Data Loader Integration (pre-computed JSON fast path)
# ---------------------------------------------------------------------------
DATA_LOADER_AVAILABLE = False
try:
    from data_loader import load_todays_data, get_pitchers, source_banner
    DATA_LOADER_AVAILABLE = True
except ImportError:
    pass  # Falls back to live compute

try:
    from pitching_dashboard_tab import render_pitching_dashboard
    PITCHING_DASH_AVAILABLE = True
except ImportError:
    PITCHING_DASH_AVAILABLE = False

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

# =============================================================================
# UNIFIED STORAGE & REFLECTION INTEGRATION
# =============================================================================

def save_predictions_with_reflection(date_str: str, all_pitcher_results: List[Dict], all_hitter_results: List[Dict]) -> bool:
    """
    Save predictions using the unified reflection module.
    
    This ensures predictions are stored in the standardized salci_data/ directory
    and are ready for tomorrow's reflection analysis.
    """
    if not REFLECTION_AVAILABLE:
        st.error("❌ Reflection module not available - cannot save predictions")
        return False
    
    data = {
        "date": date_str,
        "model_version": SALCI_VERSION,
        "pitchers": [
            {
                "pitcher_id": p.get("pitcher_id"),
                "pitcher_name": p.get("pitcher"),
                "team": p.get("team"),
                "opponent": p.get("opponent"),
                "salci": p.get("salci"),
                "salci_grade": p.get("salci_grade"),
                "expected": p.get("expected"),
                "k_lines": p.get("k_lines", {}),
                "stuff_score": p.get("stuff_score"),
                "location_score": p.get("location_score"),
                "matchup_score": p.get("matchup_score"),
                "workload_score": p.get("workload_score"),
                "is_statcast": p.get("is_statcast", False),
                "profile_type": p.get("profile_type"),
                "lineup_confirmed": p.get("lineup_confirmed", False)
            }
            for p in all_pitcher_results
        ],
        "hitters": [
            {
                "player_id": h.get("player_id"),
                "name": h.get("name"),
                "team": h.get("team"),
                "vs_pitcher": h.get("vs_pitcher"),
                "score": h.get("score"),
                "lineup_confirmed": h.get("lineup_confirmed", False)
            }
            for h in all_hitter_results
        ]
    }
    
    try:
        if refl.save_daily_predictions(date_str, data):
            st.success(f"✅ Predictions saved for {date_str}")
            return True
        else:
            st.error("Failed to save predictions")
            return False
    except Exception as e:
        st.error(f"Error saving predictions: {e}")
        return False

def load_predictions_from_reflection(date_str: str) -> Optional[Dict]:
    """Load predictions from the unified reflection module."""
    if not REFLECTION_AVAILABLE:
        return None
    try:
        return refl.load_daily_predictions(date_str)
    except Exception as e:
        st.warning(f"Could not load predictions: {e}")
        return None

def get_yesterday_date() -> str:
    """Get yesterday's date string."""
    return (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")

def get_current_season(date_obj: datetime) -> int:
    """
    Determine MLB season based on date.
    MLB season typically runs March-October, so:
    - March-October of year Y = season Y
    - November-February of year Y = season Y-1
    """
    if date_obj.month < 3:
        return date_obj.year - 1
    return date_obj.year

# ----------------------------
# Helper Functions
# ----------------------------
def normalize(val: float, min_val: float, max_val: float, higher_is_better: bool = True) -> float:
    """Normalize value to 0-1 range."""
    norm = np.clip((val - min_val) / (max_val - min_val), 0, 1)
    return norm if higher_is_better else (1 - norm)

def get_blend_weights(games_played: int) -> Tuple[float, float]:
    """
    Determine blend weights between recent and baseline stats.
    
    Early season: Weight recent less, baseline more (limited sample)
    Mid season: Equal weights
    Late season: Weight recent more (most current form)
    """
    if games_played < 3:
        return 0.2, 0.8  # 20% recent, 80% baseline
    elif games_played < 7:
        return 0.4, 0.6
    elif games_played < 15:
        return 0.6, 0.4
    return 0.8, 0.2  # 80% recent, 20% baseline

def get_rating(salci: float) -> Tuple[str, str, str]:
    """Convert SALCI score to rating (label, emoji, css_class)."""
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
    """Convert hitter score to rating."""
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
    """Get color for SALCI score."""
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
    """Get mapping of team names to their MLB IDs."""
    url = "https://statsapi.mlb.com/api/v1/teams?sportId=1"
    try:
        res = requests.get(url, timeout=10)
        return {team["name"]: team["id"] for team in res.json().get("teams", [])}
    except Exception as e:
        st.warning(f"Error fetching teams: {e}")
        return {}

@st.cache_data(ttl=60)
def get_games_by_date(date_str: str) -> List[Dict]:
    """Fetch all MLB games for a given date with probable pitchers."""
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
def get_game_lineups_api(game_pk: int) -> Optional[Dict]:
    """
    Fetch lineups from the dedicated MLB lineups endpoint.
    This works PRE-GAME, unlike the live feed battingOrder which only
    populates once the game starts.
    """
    url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/lineups"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        return data
    except Exception as e:
        return None

@st.cache_data(ttl=60)
def get_game_boxscore(game_pk: int) -> Optional[Dict]:
    """Fetch live game data including lineups (in-game/post-game fallback)."""
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    try:
        res = requests.get(url, timeout=15)
        return res.json()
    except Exception as e:
        return None

def get_confirmed_lineup(game_pk: int, team_side: str) -> Tuple[List[Dict], bool]:
    """
    Extract confirmed lineup using a two-source strategy:
    1. /game/{pk}/lineups  — works pre-game (primary)
    2. /feed/live boxscore — works in-game/post-game (fallback)
    
    Returns: (lineup_list, is_confirmed)
    """
    # ── SOURCE 1: Dedicated lineups endpoint (pre-game) ─────────────────────
    lineup_data = get_game_lineups_api(game_pk)
    if lineup_data:
        # The lineups endpoint returns {"homeBatters": [...], "awayBatters": [...]}
        key = "homeBatters" if team_side == "home" else "awayBatters"
        batters = lineup_data.get(key, [])
        
        if batters and len(batters) >= 9:
            lineup = []
            for i, player in enumerate(batters):
                lineup.append({
                    "id": player.get("id"),
                    "name": player.get("fullName", player.get("name", "Unknown")),
                    "position": player.get("primaryPosition", {}).get("abbreviation", ""),
                    "batting_order": i + 1,
                    "bat_side": player.get("batSide", {}).get("code", "R"),
                })
            return lineup, True

    # ── SOURCE 2: Live feed boxscore (in-game / post-game fallback) ──────────
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
        st.warning(f"Error parsing lineup: {e}")
        return [], False

# ----------------------------
# API Functions - Pitchers
# ----------------------------
@st.cache_data(ttl=300)
def get_player_season_stats(player_id: int, season: int) -> Optional[Dict]:
    """Fetch pitcher's full-season stats."""
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
    """
    Fetch pitcher's recent game-log stats (L7 by default).
    
    Calculates rolling: K9, K%, K/BB, P/IP from recent starts
    """
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
            "total_ip": totals["ip"],
            "avg_ip_per_start": totals["ip"] / totals["games"]  # NEW: Smart workload
        }
    except Exception as e:
        pass
    return None

def parse_season_stats(stats: Dict) -> Dict:
    """Parse pitcher season stats from MLB API response."""
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
    """Fetch hitter's recent game-log stats (L7 by default)."""
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
    except Exception as e:
        pass
    return None

@st.cache_data(ttl=3600)
def get_hitter_season_stats(player_id: int, season: int) -> Optional[Dict]:
    """Fetch hitter's full-season stats."""
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
    """Fetch team batting stats (for opponent K% calculation)."""
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
            try:
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
            except Exception as e:
                continue
        
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
    """Fetch team's full-season batting stats."""
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

@st.cache_data(ttl=3600)
def get_yesterday_hitter_leaders(date_str: str, min_hits: int = 2) -> List[Dict]:
    """Fetch top hitter performances from completed games on a given date."""
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
            if game.get("status", {}).get("abstractGameState", "") != "Final":
                continue
            
            try:
                box_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
                box_data = requests.get(box_url, timeout=15).json()
                
                for side in ["home", "away"]:
                    team_data = box_data.get("teams", {}).get(side, {})
                    team_name = team_data.get("team", {}).get("name", "Unknown")
                    
                    for batter_id in team_data.get("batters", []):
                        player_key = f"ID{batter_id}"
                        player_data = team_data.get("players", {}).get(player_key, {})
                        stats = player_data.get("stats", {}).get("batting", {})
                        
                        if stats:
                            hits = int(stats.get("hits", 0))
                            if hits >= min_hits or int(stats.get("homeRuns", 0)) >= 1:
                                hitters.append({
                                    "player_name": player_data.get("person", {}).get("fullName", "Unknown"),
                                    "team": team_name,
                                    "hits": hits,
                                    "ab": int(stats.get("atBats", 0)),
                                    "hr": int(stats.get("homeRuns", 0)),
                                    "rbi": int(stats.get("rbi", 0)),
                                    "so": int(stats.get("strikeOuts", 0))
                                })
            except Exception as e:
                continue
        
        hitters.sort(key=lambda x: (x["hits"], x["hr"], x["rbi"]), reverse=True)
        return hitters
    
    except Exception as e:
        return []

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
    """
    Compute SALCI v1 (backward compatible calculation).
    
    Blends recent form with baseline, then applies weighted scoring.
    """
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
    """
    Compute hitter hotness score (0-100).
    
    Components: AVG (25%), OPS (25%), K% (15%), Hit Streak (15%), HR (10%), Hitless (10%)
    """
    if not recent:
        return 50
    
    score = 0
    weights_total = 0
    
    # AVG component
    if recent.get("avg"):
        avg_score = normalize(recent["avg"], 0.180, 0.380, True) * 100
        score += avg_score * 0.25
        weights_total += 0.25
    
    # OPS component
    if recent.get("ops"):
        ops_score = normalize(recent["ops"], 0.550, 1.100, True) * 100
        score += ops_score * 0.25
        weights_total += 0.25
    
    # K% component (lower is better for hitter)
    if recent.get("k_rate") is not None:
        k_score = normalize(recent["k_rate"], 0.35, 0.10, False) * 100
        score += k_score * 0.15
        weights_total += 0.15
    
    # Base score
    base_score = (score / weights_total * 100) if weights_total > 0 else 50
    
    # Bonuses/Penalties
    bonus = 0
    
    # Hit streak bonus (3+ game streak = 5% bonus, capped at 15%)
    if recent.get("hit_streak", 0) >= 3:
        bonus += min(recent["hit_streak"] * 3, 15)
    
    # Hitless streak penalty (2+ game slump = -5% penalty, capped at -20%)
    if recent.get("hitless_streak", 0) >= 2:
        bonus -= min(recent["hitless_streak"] * 5, 20)
    
    # HR bonus (1 HR = 5%, capped at 15%)
    if recent.get("hr", 0) >= 1:
        bonus += min(recent["hr"] * 5, 15)
    
    final_score = base_score + bonus
    return max(0, min(100, final_score * 1.1))

def project_lines(salci: float, base_k9: float = 9.0) -> Dict:
    """
    Project K-line probabilities from SALCI score.
    
    Returns: {"expected": float, "lines": {3: prob, 4: prob, ..., 8: prob}}
    """
    expected = (base_k9 * 5.5 / 9) * (0.7 + (salci / 100) * 0.6)
    
    lines = {}
    for k in range(3, 9):
        diff = k - expected
        if diff <= -2:
            prob = 92
        elif diff <= -1:
            prob = 80
        elif diff <= 0:
            prob = 65
        elif diff <= 1:
            prob = 45
        elif diff <= 2:
            prob = 28
        else:
            prob = 15
        
        prob = max(5, min(95, prob + (salci - 50) / 10))
        lines[k] = round(prob)
    
    return {"expected": round(expected, 1), "lines": lines}

def get_matchup_grade(hitter_k_rate: float, pitcher_k_pct: float, 
                      hitter_hand: str, pitcher_hand: str) -> Tuple[str, str]:
    """Grade the pitcher-hitter matchup (K perspective)."""
    # Platoon advantage
    platoon_adv = 10 if (hitter_hand != pitcher_hand) else -5
    
    # K matchup quality
    k_matchup = 0
    if hitter_k_rate < 0.18 and pitcher_k_pct > 0.28:
        k_matchup = 15  # Low-K hitter vs high-K pitcher = good
    elif hitter_k_rate > 0.28 and pitcher_k_pct > 0.28:
        k_matchup = -15  # High-K hitter vs high-K pitcher = bad
    elif hitter_k_rate < 0.20:
        k_matchup = 10  # Low-K hitter = good
    elif hitter_k_rate > 0.30:
        k_matchup = -10  # High-K hitter = bad
    
    total = 50 + platoon_adv + k_matchup
    
    if total >= 65:
        return "🟢 Favorable", "matchup-good"
    elif total >= 45:
        return "🟡 Neutral", "matchup-neutral"
    else:
        return "🔴 Tough", "matchup-bad"

# ----------------------------
# Chart Functions
# ----------------------------
def create_pitcher_comparison_chart(pitcher_results: List[Dict]) -> Optional[go.Figure]:
    """Create horizontal bar chart of top pitchers by SALCI."""
    if not pitcher_results:
        return None
    
    top_pitchers = sorted(pitcher_results, key=lambda x: x["salci"], reverse=True)[:10]
    top_pitchers = top_pitchers[::-1]
    
    names = [f"{p['pitcher'].split()[-1]} ({p.get('pitcher_hand', 'R')})" for p in top_pitchers]
    scores = [p["salci"] for p in top_pitchers]
    colors = [get_salci_color(s) for s in scores]
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=names,
        x=scores,
        orientation='h',
        marker_color=colors,
        text=[f"{s}" for s in scores],
        textposition='outside',
        textfont=dict(size=12, color='#333')
    ))
    
    fig.add_vline(x=75, line_dash="dash", line_color="#10b981", line_width=2,
                  annotation_text="Elite (75+)", annotation_position="top")
    fig.add_vline(x=60, line_dash="dot", line_color="#3b82f6", line_width=1,
                  annotation_text="Strong (60+)", annotation_position="bottom")
    
    fig.update_layout(
        title=dict(text="Today's Top SALCI Pitchers", font=dict(size=18)),
        xaxis_title="SALCI Score",
        yaxis_title="",
        xaxis=dict(range=[0, 100], tickvals=[0, 25, 50, 75, 100]),
        height=400,
        margin=dict(l=100, r=50, t=80, b=60),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
    )
    
    return fig

def create_hitter_hotness_chart(hitter_results: List[Dict]) -> Optional[go.Figure]:
    """Create grouped bar chart of hot hitters with AVG and OPS."""
    if not hitter_results:
        return None
    
    top_hitters = sorted(hitter_results, key=lambda x: x["score"], reverse=True)[:8]
    
    names = [f"{h['name'].split()[-1]} ({h.get('bat_side', 'R')})" for h in top_hitters]
    avgs = [h["recent"].get("avg", 0) for h in top_hitters]
    ops_vals = [h["recent"].get("ops", 0) for h in top_hitters]
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        name='AVG (L7)',
        x=names,
        y=avgs,
        marker_color=COLORS["hot"],
        text=[f".{int(a*1000):03d}" for a in avgs],
        textposition='outside'
    ))
    
    fig.add_trace(go.Bar(
        name='OPS (L7)',
        x=names,
        y=ops_vals,
        marker_color=COLORS["secondary"],
        text=[f"{o:.3f}" for o in ops_vals],
        textposition='outside'
    ))
    
    fig.update_layout(
        title=dict(text="Hottest Hitters (Last 7 Games)", font=dict(size=18)),
        yaxis_title="",
        barmode='group',
        height=350,
        margin=dict(l=50, r=50, t=80, b=80),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    
    return fig

def create_salci_breakdown_chart() -> go.Figure:
    """Create donut chart showing SALCI v3 metric weights."""
    labels = ['Stuff (40%)', 'Matchup (25%)', 'Workload (20%)', 'Location (15%)']
    values = [40, 25, 20, 15]
    colors_list = ['#8b5cf6', '#3b82f6', '#eab308', '#06b6d4']
    
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.6,
        marker_colors=colors_list,
        textinfo='label+percent',
        textposition='outside',
        textfont=dict(size=11)
    )])
    
    fig.update_layout(
        title=dict(text="SALCI v3 Weight Distribution (K-Optimized)", font=dict(size=16)),
        height=350,
        margin=dict(l=20, r=20, t=60, b=60),
        showlegend=False,
        annotations=[
            dict(
                text="SALCI<br>v3",
                x=0.5, y=0.5,
                font=dict(size=14, color="#333"),
                showarrow=False
            )
        ]
    )
    
    return fig

def create_expected_vs_salci_chart(pitchers: List[Dict]):
    """Expected Ks vs SALCI scatter (top 10 labeled)"""
    if len(pitchers) < 3:
        return None
    
    df = pd.DataFrame([
        {
            "Pitcher": p.get("pitcher", "Unknown"),
            "SALCI": p.get("salci", 0),
            "Expected Ks": p.get("expected", 0),
            "Floor": p.get("floor", 0),
            "Profile": p.get("profile_type", "Balanced")
        }
        for p in pitchers
    ])
    
    fig = px.scatter(
        df,
        x="SALCI",
        y="Expected Ks",
        hover_name="Pitcher",
        color="Profile",
        size="Floor",
        text="Pitcher",
        title="Expected Strikeouts vs SALCI Score",
        labels={"Expected Ks": "Projected Strikeouts", "SALCI": "SALCI Score"}
    )
    
    # Highlight and label top 10
    top10 = df.nlargest(10, "Expected Ks")
    for i, row in top10.iterrows():
        fig.add_annotation(
            x=row["SALCI"], y=row["Expected Ks"],
            text=row["Pitcher"].split()[0],  # first name only
            showarrow=True,
            arrowhead=2,
            ax=0, ay=-25,
            font=dict(size=12, color="#10b981")
        )
    
    fig.update_layout(
        height=420,
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)"
    )
    return fig


def create_top_10_expected_ks_chart(pitchers: List[Dict]):
    """Top 10 Expected Strikeouts horizontal bar"""
    if not pitchers:
        return None
    
    df = pd.DataFrame([
        {
            "Pitcher": p.get("pitcher", "Unknown"),
            "Expected Ks": p.get("expected", 0),
            "At Least": f"{p.get('floor', 0)}+ Ks",
            "Confidence": p.get("floor_confidence", 0)
        }
        for p in pitchers
    ])
    
    df = df.nlargest(10, "Expected Ks")
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        y=df["Pitcher"],
        x=df["Expected Ks"],
        text=df["At Least"] + " (" + df["Confidence"].astype(str) + "%)",
        textposition="inside",
        orientation="h",
        marker=dict(color="#10b981", opacity=0.85)
    ))
    
    fig.update_layout(
        title="Top 10 Projected Strikeouts (with At Least confidence)",
        xaxis_title="Expected Strikeouts",
        height=500,
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(autorange="reversed")
    )
    return fig


import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

def create_expected_vs_salci_chart(pitchers: List[Dict]):
    if len(pitchers) < 3:
        return None
    df = pd.DataFrame([{
        "Pitcher": p.get("pitcher", "Unknown"),
        "SALCI": p.get("salci", 0),
        "Expected Ks": p.get("expected", 0),
        "Floor": p.get("floor", 0),
        "Profile": p.get("profile_type", "Balanced")
    } for p in pitchers])
    
    fig = px.scatter(df, x="SALCI", y="Expected Ks",
                     hover_name="Pitcher", color="Profile",
                     size="Floor", text="Pitcher",
                     title="Expected Strikeouts vs SALCI Score")
    fig.update_layout(height=420, template="plotly_dark")
    return fig


def create_top_10_expected_ks_chart(pitchers: List[Dict]):
    if not pitchers:
        return None
    df = pd.DataFrame([{
        "Pitcher": p.get("pitcher", "Unknown"),
        "Expected Ks": p.get("expected", 0),
        "At Least": f"{p.get('floor', 0)}+ Ks",
        "Confidence": p.get("floor_confidence", 0)
    } for p in pitchers])
    df = df.nlargest(10, "Expected Ks")
    
    fig = go.Figure(go.Bar(
        y=df["Pitcher"], x=df["Expected Ks"],
        text=df["At Least"] + " (" + df["Confidence"].astype(str) + "%)",
        textposition="inside", orientation="h",
        marker=dict(color="#10b981", opacity=0.85)
    ))
    fig.update_layout(
        title="Top 10 Projected Strikeouts",
        xaxis_title="Expected Strikeouts",
        height=500,
        template="plotly_dark",
        yaxis=dict(autorange="reversed")
    )
    return fig


def create_salci_vs_confidence_chart(pitchers: List[Dict]):
    """Bonus: Shows how reliable each SALCI projection is"""
    if len(pitchers) < 3:
        return None
    df = pd.DataFrame([{
        "Pitcher": p.get("pitcher", "Unknown")[:15],
        "SALCI": p.get("salci", 0),
        "Floor Confidence": p.get("floor_confidence", 0),
        "Expected Ks": p.get("expected", 0)
    } for p in pitchers])
    
    fig = px.scatter(df, x="SALCI", y="Floor Confidence",
                     hover_name="Pitcher", size="Expected Ks",
                     title="SALCI Score vs Floor Confidence (%)",
                     labels={"Floor Confidence": "Confidence in At Least X Ks"})
    fig.update_layout(height=420, template="plotly_dark")
    return fig



def create_matchup_scatter(hitter_results: List[Dict]) -> Optional[go.Figure]:
    """Create scatter plot of hitters: K% vs AVG."""
    if not hitter_results or len(hitter_results) < 3:
        return None
    
    k_rates = [h["recent"].get("k_rate", 0.22) * 100 for h in hitter_results]
    avgs = [h["recent"].get("avg", 0.250) for h in hitter_results]
    names = [f"{h['name']} ({h.get('bat_side', 'R')})" for h in hitter_results]
    short_names = [f"{h['name'].split()[-1]} ({h.get('bat_side', 'R')})" for h in hitter_results]
    scores = [h["score"] for h in hitter_results]
    
    colors = [get_salci_color(s) if s >= 50 else COLORS["cold"] for s in scores]
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=k_rates,
        y=avgs,
        mode='markers+text',
        marker=dict(size=12, color=colors, line=dict(width=1, color='white')),
        text=short_names,
        textposition='top center',
        textfont=dict(size=8),
        hovertemplate='<b>%{text}</b><br>K%: %{x:.1f}%<br>AVG: %{y:.3f}<extra></extra>'
    ))
    
    fig.add_hline(y=0.270, line_dash="dash", line_color="#ccc", line_width=1)
    fig.add_vline(x=22, line_dash="dash", line_color="#ccc", line_width=1)
    
    fig.add_annotation(x=15, y=0.35, text="🔥 Low K%, High AVG", showarrow=False, 
                       font=dict(size=10, color="#10b981"))
    fig.add_annotation(x=30, y=0.20, text="❄️ High K%, Low AVG", showarrow=False, 
                       font=dict(size=10, color="#ef4444"))
    
    fig.update_layout(
        title=dict(text="Hitter Profile: K% vs AVG (L7)", font=dict(size=16)),
        xaxis_title="K% (Lower is better)",
        yaxis_title="AVG (Higher is better)",
        height=400,
        margin=dict(l=60, r=40, t=80, b=80),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
    )
    
    return fig

def create_stuff_location_chart(pitcher_results: List[Dict]) -> Optional[go.Figure]:
    """Create scatter plot showing Stuff vs Location for pitchers."""
    if not pitcher_results:
        return None
    
    pitchers_with_scores = [p for p in pitcher_results 
                           if p.get("stuff_score") and p.get("location_score")]
    
    if len(pitchers_with_scores) < 3:
        return None
    
    stuff_scores = [p["stuff_score"] for p in pitchers_with_scores]
    location_scores = [p["location_score"] for p in pitchers_with_scores]
    names = [f"{p['pitcher'].split()[-1]} ({p.get('pitcher_hand', 'R')})" for p in pitchers_with_scores]
    salci_scores = [p["salci"] for p in pitchers_with_scores]
    
    colors = [get_salci_color(s) for s in salci_scores]
    sizes = [max(8, s / 5) for s in salci_scores]
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=stuff_scores,
        y=location_scores,
        mode='markers+text',
        marker=dict(size=sizes, color=colors, line=dict(width=1, color='white')),
        text=names,
        textposition='top center',
        textfont=dict(size=9),
        hovertemplate='<b>%{text}</b><br>Stuff: %{x}<br>Location: %{y}<extra></extra>'
    ))
    
    fig.add_hline(y=60, line_dash="dash", line_color="#ccc", line_width=1)
    fig.add_vline(x=60, line_dash="dash", line_color="#ccc", line_width=1)
    
    fig.add_annotation(x=80, y=80, text="⚡ ELITE", showarrow=False, 
                       font=dict(size=11, color="#10b981", weight="bold"))
    fig.add_annotation(x=80, y=40, text="🔥 Stuff Dominant", showarrow=False, 
                       font=dict(size=10, color="#8b5cf6"))
    fig.add_annotation(x=40, y=80, text="📍 Location Dominant", showarrow=False, 
                       font=dict(size=10, color="#3b82f6"))
    fig.add_annotation(x=40, y=40, text="⚠️ Limited", showarrow=False, 
                       font=dict(size=10, color="#ef4444"))
    
    fig.update_layout(
        title=dict(text="Pitcher Profiles: Stuff vs Location", font=dict(size=16)),
        xaxis_title="Stuff Score (Raw Arsenal Quality)",
        yaxis_title="Location Score (Command/Placement)",
        xaxis=dict(range=[20, 100]),
        yaxis=dict(range=[20, 100]),
        height=450,
        margin=dict(l=60, r=40, t=80, b=80),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
    )
    
    return fig

def create_k_projection_chart(pitcher_results: List[Dict]) -> Optional[go.Figure]:
    """Create bar chart showing K line projections for top pitchers."""
    if not pitcher_results:
        return None
    
    top_pitchers = sorted(pitcher_results, key=lambda x: x["salci"], reverse=True)[:5]
    
    names = [f"{p['pitcher'].split()[-1]} ({p.get('pitcher_hand', 'R')})" for p in top_pitchers]
    expected_ks = [p["expected"] for p in top_pitchers]
    
    # Extract K-lines safely (handling both empty and populated cases)
    k_lines_data = []
    for p in top_pitchers:
        k_dict = p.get("k_lines", {}) or p.get("lines", {})
        if k_dict:
            k_vals = sorted(k_dict.keys())
            k_lines_data.append([k_dict.get(k, 50) for k in k_vals[:4]])
        else:
            k_lines_data.append([50, 40, 30, 20])
    
    fig = go.Figure()
    
    if k_lines_data and top_pitchers:
        first_klines = sorted((top_pitchers[0].get("k_lines", {}) or {}).keys())
        if not first_klines:
            first_klines = [5, 6, 7, 8]
        line_labels = [f"{k}+" for k in first_klines[:4]]
        
        for line_idx, line_label in enumerate(line_labels):
            probs = [kld[line_idx] if line_idx < len(kld) else 0 for kld in k_lines_data]
            fig.add_trace(go.Bar(
                name=line_label,
                x=names,
                y=probs,
                text=[f"{p}%" for p in probs],
                textposition='outside'
            ))
    
    fig.update_layout(
        title=dict(text="K Line Probabilities (Top Pitchers)", font=dict(size=16)),
        yaxis_title="Probability %",
        yaxis=dict(range=[0, 100]),
        barmode='group',
        height=350,
        margin=dict(l=50, r=50, t=80, b=80),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    
    return fig

# ----------------------------
# UI Rendering Functions
# ----------------------------
def render_pitcher_card(result: Dict, show_stuff_location: bool = True):
    """Render pitcher card with SALCI v3 component breakdown + new At Least Ks floor."""
    salci = result["salci"]
    rating_label, emoji, css_class = get_rating(salci)
    
    with st.container():
        col1, col2, col3 = st.columns([2, 1, 2])
        
        with col1:
            p_hand = result.get("pitcher_hand", "R")
            st.markdown(f"### {result['pitcher']} ({p_hand}HP)")
            st.markdown(f"**{result['team']}** vs {result['opponent']}")
            
            if result.get("profile_type") and result.get("profile_type") != "BALANCED":
                profile_emoji = {
                    "ELITE": "⚡", "STUFF-DOMINANT": "🔥", "LOCATION-DOMINANT": "🎯",
                    "BALANCED-PLUS": "💪", "BALANCED": "⚖️", "ONE-TOOL": "📊", "LIMITED": "⚠️"
                }.get(result["profile_type"], "❓")
                st.markdown(f"<span style='font-size: 0.85rem;'>{profile_emoji} {result['profile_type']}</span>", 
                           unsafe_allow_html=True)
            
            badges = []
            if result.get("is_statcast"):
                badges.append("<span style='font-size: 0.7rem; background: #10b981; color: white; padding: 2px 6px; border-radius: 4px;'>🎯 Statcast</span>")
            else:
                badges.append("<span style='font-size: 0.7rem; background: #6b7280; color: white; padding: 2px 6px; border-radius: 4px;'>📊 Stats API</span>")
            
            if badges:
                st.markdown(" ".join(badges), unsafe_allow_html=True)
        
        with col2:
            grade = result.get("salci_grade", "C")
            st.markdown(f"<div style='text-align: center;'>"
                       f"<span style='font-size: 2.5rem; font-weight: bold;'>{result['salci']}</span><br>"
                       f"<span class='{css_class}'>{emoji} Grade {grade}</span></div>",
                       unsafe_allow_html=True)

        with col3:
            # NEW: Pull from the updated calculate_expected_ks_v3 output
            expected_ks = result.get("expected", "--")
            floor_ks = result.get("floor")
            floor_conf = result.get("floor_confidence")
            
            st.markdown(f"**Expected Ks:** {expected_ks}")
            
            if floor_ks is not None and floor_conf is not None:
                st.markdown(f"**At Least:** <span style='color:#10b981; font-weight:bold;'>{floor_ks} Ks</span> "
                           f"({floor_conf}% confidence)", unsafe_allow_html=True)
            else:
                st.markdown("**At Least:** --")
            
            # K-lines (now correctly populated with "At Least" Poisson probabilities)
            k_lines = result.get("k_lines", {}) or result.get("lines", {})
            if k_lines:
                cols = st.columns(4)
                for i, (k_value, prob) in enumerate(sorted(k_lines.items())[:4]):
                    with cols[i]:
                        color = "#22c55e" if prob >= 70 else "#eab308" if prob >= 50 else "#ef4444"
                        st.markdown(f"<div style='text-align:center;'><small>{k_value}+</small><br>"
                                   f"<span style='color:{color}; font-weight:bold;'>{prob}%</span></div>",
                                    unsafe_allow_html=True)


        # v5.1: SALCI v3 4-Component Breakdown
        if show_stuff_location:
            stuff = result.get("stuff_score")
            location = result.get("location_score")
            matchup = result.get("matchup_score")
            workload = result.get("workload_score")
            
            if stuff or location or matchup or workload:
                st.markdown("<div style='margin-top: 0.5rem;'>", unsafe_allow_html=True)
                
                col_s, col_m, col_w, col_l = st.columns(4)
                
                def get_component_color(score, is_100_scale=True):
                    """Get color for component score."""
                    if score is None:
                        return "#d1d5db"  # Gray
                    if is_100_scale:
                        if score >= 115: return "#10b981"
                        if score >= 105: return "#22c55e"
                        if score >= 95: return "#eab308"
                        return "#ef4444"
                    else:
                        if score >= 65: return "#10b981"
                        if score >= 50: return "#22c55e"
                        if score >= 35: return "#eab308"
                        return "#ef4444"
                
                # Stuff (40%)
                with col_s:
                    if stuff:
                        stuff_color = get_component_color(stuff, is_100_scale=True)
                        stuff_pct = min(100, max(0, (stuff - 70) * 2))
                        st.markdown(f"""
                        <div style='text-align: center;'>
                            <div style='font-size: 0.7rem; color: #666;'>⚡ STUFF (40%)</div>
                            <div style='font-size: 1.2rem; font-weight: bold; color: {stuff_color};'>{int(stuff)}</div>
                            <div style='background: #e5e7eb; border-radius: 4px; height: 6px; margin-top: 2px;'>
                                <div style='width: {stuff_pct}%; background: {stuff_color}; border-radius: 4px; height: 100%;'></div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='text-align: center; color: #aaa; font-size: 0.8rem;'>STUFF<br>--</div>", 
                                   unsafe_allow_html=True)
                
                # Matchup (25%)
                with col_m:
                    if matchup:
                        match_color = get_component_color(matchup, is_100_scale=False)
                        st.markdown(f"""
                        <div style='text-align: center;'>
                            <div style='font-size: 0.7rem; color: #666;'>🎯 MATCHUP (25%)</div>
                            <div style='font-size: 1.2rem; font-weight: bold; color: {match_color};'>{int(matchup)}</div>
                            <div style='background: #e5e7eb; border-radius: 4px; height: 6px; margin-top: 2px;'>
                                <div style='width: {matchup}%; background: {match_color}; border-radius: 4px; height: 100%;'></div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='text-align: center; color: #aaa; font-size: 0.8rem;'>MATCHUP<br>--</div>", 
                                   unsafe_allow_html=True)
                
                # Workload (20%)
                with col_w:
                    if workload:
                        work_color = get_component_color(workload, is_100_scale=False)
                        st.markdown(f"""
                        <div style='text-align: center;'>
                            <div style='font-size: 0.7rem; color: #666;'>📊 WORKLOAD (20%)</div>
                            <div style='font-size: 1.2rem; font-weight: bold; color: {work_color};'>{int(workload)}</div>
                            <div style='background: #e5e7eb; border-radius: 4px; height: 6px; margin-top: 2px;'>
                                <div style='width: {workload}%; background: {work_color}; border-radius: 4px; height: 100%;'></div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='text-align: center; color: #aaa; font-size: 0.8rem;'>WORKLOAD<br>--</div>", 
                                   unsafe_allow_html=True)
                
                # Location (15%)
                with col_l:
                    if location:
                        loc_color = get_component_color(location, is_100_scale=True)
                        loc_pct = min(100, max(0, (location - 70) * 2))
                        st.markdown(f"""
                        <div style='text-align: center;'>
                            <div style='font-size: 0.7rem; color: #666;'>📍 LOCATION (15%)</div>
                            <div style='font-size: 1.2rem; font-weight: bold; color: {loc_color};'>{int(location)}</div>
                            <div style='background: #e5e7eb; border-radius: 4px; height: 6px; margin-top: 2px;'>
                                <div style='width: {loc_pct}%; background: {loc_color}; border-radius: 4px; height: 100%;'></div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='text-align: center; color: #aaa; font-size: 0.8rem;'>LOCATION<br>--</div>", 
                                   unsafe_allow_html=True)
                
                st.markdown("</div>", unsafe_allow_html=True)
                
                # Arsenal display (already fixed in previous step)
                stuff_breakdown = result.get("stuff_breakdown", {})
                if stuff_breakdown and result.get("is_statcast"):
                    render_arsenal_display(stuff_breakdown)
        
        st.progress(min(result["salci"] / 100, 1.0))
        st.markdown("---")

def render_compact_summary(pitcher_results: List[Dict]):
    """
    Renders a clean, copy-paste-ready summary block of ALL pitchers
    sorted by SALCI descending (highest first).
    
    Exact format you asked for:
    Player Name
    #SALCI: XX.X
    Expected: X.X
    Ks 6+ @ 66% | 7+ @ 51% | 8+ @ 36%
    """
    if not pitcher_results:
        st.info("No pitchers to summarize yet.")
        return
    
    # Sort by SALCI descending
    sorted_pitchers = sorted(
        pitcher_results,
        key=lambda x: x.get("salci", 0),
        reverse=True
    )
    
    st.markdown("---")
    st.markdown("### 📋 Quick Copy SALCI Summary (Highest → Lowest)")
    
    summary_lines = []
    
    for result in sorted_pitchers:
        name = result.get("pitcher", "Unknown")
        salci = result.get("salci", 0)
        expected = result.get("expected", "--")
        
        # Get the k_lines (already sorted from floor upward)
        k_lines = result.get("k_lines", {})
        
        # Take the first 3 "At Least" lines
        lines = []
        for k_value, prob in list(k_lines.items())[:3]:
            lines.append(f"{k_value}+ @ {prob}%")
        
        line_str = " | ".join(lines) if lines else "No K-lines"
        
        summary_block = f"""
**{name}**
#SALCI: {salci}
Expected: {expected}
Ks {line_str}
"""
        summary_lines.append(summary_block.strip())
    
    # Join everything with blank lines for perfect copy-paste
    full_summary = "\n\n".join(summary_lines)
    
    # Display in a clean box that's easy to triple-click and copy
    st.markdown(
        f"""
<div style="background: rgba(255,255,255,0.05); 
            padding: 16px; 
            border-radius: 8px; 
            font-family: monospace; 
            white-space: pre-wrap;">
{full_summary}
</div>
        """,
        unsafe_allow_html=True
    )
    
    # Optional: also show a plain-text version in st.code for one-click copy
    st.caption("👇 Triple-click below to copy the entire list")
    st.code(full_summary, language=None)



def render_arsenal_display(stuff_breakdown: Dict):
    """Render pitch arsenal with per-pitch Stuff+ scores using native columns (more reliable)."""
    if not stuff_breakdown:
        return
    
    pitches = []
    for pitch_type, data in stuff_breakdown.items():
        if isinstance(data, dict) and data.get('usage_pct', 0) >= 5:
            pitches.append({
                'type': pitch_type,
                'stuff': data.get('stuff_plus', 100),
                'velo': data.get('velocity', 0),
                'usage': data.get('usage_pct', 0),
                'whiff': data.get('observed_whiff_pct', 0)
            })
    
    if not pitches:
        return
    
    pitches.sort(key=lambda x: x['usage'], reverse=True)
    
    pitch_names = {
        'FF': ('4-Seam', '#ef4444'),
        'SI': ('Sinker', '#f97316'),
        'FC': ('Cutter', '#eab308'),
        'SL': ('Slider', '#22c55e'),
        'ST': ('Sweeper', '#14b8a6'),
        'CU': ('Curve', '#3b82f6'),
        'KC': ('Knuckle-C', '#6366f1'),
        'CH': ('Change', '#a855f7'),
        'FS': ('Splitter', '#ec4899'),
        'SV': ('Slurve', '#06b6d4'),
    }
    
    # Outer container
    st.markdown("<div style='margin-top: 0.5rem; padding: 8px; background: rgba(0,0,0,0.03); border-radius: 8px;'>", 
                unsafe_allow_html=True)
    st.markdown("<div style='font-size: 0.7rem; color: #666; margin-bottom: 4px;'>🎪 ARSENAL</div>", 
                unsafe_allow_html=True)
    
    # One column per pitch (max 5)
    num_pitches = min(len(pitches), 5)
    if num_pitches > 0:
        cols = st.columns(num_pitches)
        for i, pitch in enumerate(pitches[:5]):
            with cols[i]:
                p_type = pitch['type']
                name, color = pitch_names.get(p_type, (p_type, '#6b7280'))
                stuff = pitch['stuff']
                velo = pitch['velo']
                usage = pitch['usage']
                whiff = pitch['whiff']
                
                if stuff >= 115:
                    stuff_color = "#10b981"
                    stuff_bg = "rgba(16, 185, 129, 0.1)"
                elif stuff >= 105:
                    stuff_color = "#22c55e"
                    stuff_bg = "rgba(34, 197, 94, 0.1)"
                elif stuff >= 95:
                    stuff_color = "#6b7280"
                    stuff_bg = "rgba(107, 114, 128, 0.1)"
                else:
                    stuff_color = "#ef4444"
                    stuff_bg = "rgba(239, 68, 68, 0.1)"
                
                st.markdown(f"""
                <div style='background: {stuff_bg}; border: 1px solid {color}; border-radius: 6px; padding: 6px 10px; min-width: 80px;'>
                    <div style='font-size: 0.75rem; font-weight: bold; color: {color};'>{name}</div>
                    <div style='font-size: 0.65rem; color: #666;'>{velo:.0f} mph • {usage:.0f}%</div>
                    <div style='font-size: 0.85rem; font-weight: bold; color: {stuff_color};'>Stuff+ {int(stuff)}</div>
                    <div style='font-size: 0.6rem; color: #888;'>Whiff {whiff:.0f}%</div>
                </div>
                """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)

def render_hitter_card(hitter: Dict, show_batting_order: bool = True):
    """Render hitter card with stats and matchup grade."""
    score = hitter.get("score", 50)
    rating, css = get_hitter_rating(score)
    recent = hitter.get("recent", {})
    season = hitter.get("season", {})
    
    matchup_grade, matchup_css = get_matchup_grade(
        recent.get("k_rate", 0.22),
        hitter.get("pitcher_k_pct", 0.22),
        hitter.get("bat_side", "R"),
        hitter.get("pitcher_hand", "R")
    )
    
    season_ab = season.get("ab", 0)
    bat_hand = hitter.get("bat_side", "R")
    
    col1, col2, col3, col4, col5 = st.columns([2.5, 1.2, 1.2, 1.2, 1])
    
    with col1:
        order_badge = ""
        if show_batting_order and hitter.get("batting_order"):
            order_badge = f"<span class='batting-order'>#{hitter['batting_order']}</span> "
        
        st.markdown(f"{order_badge}**{hitter['name']}** ({hitter.get('position', '')})", 
                   unsafe_allow_html=True)
        st.markdown(f"<span style='font-size: 0.8rem; color: #555;'>{bat_hand}HB • {season_ab} AB (2025)</span>", 
                   unsafe_allow_html=True)
        
        if recent.get("hit_streak", 0) >= 3:
            st.markdown(f"<span class='hot-streak'>🔥 {recent['hit_streak']}-game hit streak</span>", 
                       unsafe_allow_html=True)
        elif recent.get("hitless_streak", 0) >= 3:
            st.markdown(f"<span class='cold-streak'>❄️ {recent['hitless_streak']}-game hitless</span>",
                       unsafe_allow_html=True)
    
    with col2:
        season_avg = season.get("avg", 0)
        recent_avg = recent.get("avg", 0)
        st.markdown(f"""
        <div style='text-align: center;'>
            <div style='font-size: 0.7rem; color: #666;'>AVG</div>
            <div style='font-size: 1rem; font-weight: bold;'>{recent_avg:.3f}</div>
            <div style='font-size: 0.7rem; color: #888;'>L7</div>
            <div style='font-size: 0.85rem; color: #666;'>{season_avg:.3f}</div>
            <div style='font-size: 0.65rem; color: #aaa;'>Season</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        season_ops = season.get("ops", 0)
        recent_ops = recent.get("ops", 0)
        st.markdown(f"""
        <div style='text-align: center;'>
            <div style='font-size: 0.7rem; color: #666;'>OPS</div>
            <div style='font-size: 1rem; font-weight: bold;'>{recent_ops:.3f}</div>
            <div style='font-size: 0.7rem; color: #888;'>L7</div>
            <div style='font-size: 0.85rem; color: #666;'>{season_ops:.3f}</div>
            <div style='font-size: 0.65rem; color: #aaa;'>Season</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        recent_krate = recent.get("k_rate", 0) * 100
        krate_color = "#10b981" if recent_krate < 20 else "#eab308" if recent_krate < 28 else "#ef4444"
        st.markdown(f"""
        <div style='text-align: center;'>
            <div style='font-size: 0.7rem; color: #666;'>K% (L7)</div>
            <div style='font-size: 1rem; font-weight: bold; color: {krate_color};'>{recent_krate:.1f}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col5:
        st.markdown(f"<div class='{matchup_css}' style='padding: 0.5rem; border-radius: 5px; text-align: center; font-size: 0.8rem;'>"
                   f"{matchup_grade}</div>", unsafe_allow_html=True)

# ----------------------------
# Main App
# ----------------------------
def main():
    """Main SALCI application."""
    st.markdown(f"<h1 class='main-header'>⚾ SALCI v{SALCI_VERSION}</h1>", unsafe_allow_html=True)
    st.markdown("<p class='sub-header'>Advanced MLB Prediction System • Stuff + Location + Reflection</p>", 
               unsafe_allow_html=True)
    
    # Sidebar Configuration
    with st.sidebar:
        st.header("⚙️ Settings")
        
        if STATCAST_AVAILABLE:
            st.success("🎯 Statcast: Connected")
        else:
            st.info("📊 Statcast: Using proxy metrics")
        
        if REFLECTION_AVAILABLE:
            st.success("💾 Reflection: Connected")
        else:
            st.info("⚠️ Reflection: Not available")
        
        st.markdown("---")
        
        selected_date = st.date_input(
            "📅 Select Date",
            value=datetime.today(),
            min_value=datetime.today() - timedelta(days=7),
            max_value=datetime.today() + timedelta(days=7)
        )
        
        st.markdown("---")
        
        preset_key = st.selectbox(
            "Pitcher Model Weights",
            options=list(WEIGHT_PRESETS.keys()),
            format_func=lambda x: WEIGHT_PRESETS[x]["name"]
        )
        st.caption(WEIGHT_PRESETS[preset_key]["desc"])
        
        st.markdown("---")
        
        st.subheader("Filters")
        min_salci = st.slider("Min Pitcher SALCI", 0, 80, 0, 5)
        show_hitters = st.checkbox("Show Hitter Analysis", value=True)
        confirmed_only = st.checkbox("Confirmed Lineups Only", value=True)
        hot_hitters_only = st.checkbox("Hot Hitters Only (Score ≥ 60)", value=False)
        
        st.markdown("---")
        
        if st.button("🔄 Refresh Lineups", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.caption("💡 Lineups are usually posted 1-2 hours before game time. Click refresh to get latest!")
        
        st.markdown("---")
        
        with st.expander("📊 About SALCI v5.1"):
            st.markdown("""
            **SALCI v5.1** = Strikeout Adjusted Lineup Confidence Index
            
            *K-Optimized Model with Unified Reflection System*
            
            **SALCI v3 Component Weights:**
            
            | Component | Weight | What It Measures |
            |-----------|--------|------------------|
            | **Stuff** | 40% | Raw pitch quality (velocity, movement, spin) |
            | **Matchup** | 25% | Opponent K% (lineup-aware when confirmed) |
            | **Workload** | 20% | Leash factor, projected innings, per-start IP |
            | **Location** | 15% | Command and placement precision |
            
            **v5.1 Improvements:**
            - ✅ Unified storage system for predictions & reflections
            - ✅ Early-season blending (v1 + v3 for < 5 games)
            - ✅ Smart workload (actual avg IP per start vs league average)
            - ✅ Confirmed-lineup-only charts in Charts & Share tab
            - ✅ Full accuracy dashboard with rolling metrics
            
            **Data Sources:**
            - 🎯 Statcast: Real physics-based metrics from Baseball Savant
            - 📊 Proxy: Estimated metrics from MLB Stats API
            """)
    
    # Main Content
    date_str = selected_date.strftime("%Y-%m-%d")
    weights = WEIGHT_PRESETS[preset_key]["weights"]
    current_season = get_current_season(selected_date)
    
    # Tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "⚾ Pitcher Analysis", "🏏 Hitter Matchups", "🎯 Best Bets",
        "🔥 Heat Maps", "📊 Charts & Share", "📈 Yesterday",
        "🎯 Model Accuracy", "📡 Team Pitching"   # ← new
    ])
    
    # Fetch games
    with st.spinner("🔍 Fetching games and lineups..."):
        games = get_games_by_date(date_str)
    
    if not games:
        st.warning(f"No games found for {date_str}")
        return
    
    st.success(f"Found **{len(games)} games** for {selected_date.strftime('%A, %B %d, %Y')}")
    
    # Check lineup confirmation
    lineup_status = {}
    for game in games:
        game_pk = game["game_pk"]
        home_lineup, home_confirmed = get_confirmed_lineup(game_pk, "home")
        away_lineup, away_confirmed = get_confirmed_lineup(game_pk, "away")
        lineup_status[game_pk] = {
            "home": {"lineup": home_lineup, "confirmed": home_confirmed},
            "away": {"lineup": away_lineup, "confirmed": away_confirmed}
        }
    
    confirmed_count = sum(1 for g in games 
                         if lineup_status[g["game_pk"]]["home"]["confirmed"] 
                         or lineup_status[g["game_pk"]]["away"]["confirmed"])
    
    if confirmed_count == 0:
        st.warning("⏳ **No lineups confirmed yet.** Lineups are typically released 1-2 hours before game time.")
    else:
        st.info(f"✅ **{confirmed_count} games** have confirmed lineups")
    
    # Process all data — try pre-computed JSON first, fall back to live compute
    all_pitcher_results = []
    all_hitter_results = []

    _precomputed_loaded = False
    if DATA_LOADER_AVAILABLE:
        _precomp, _source = load_todays_data(date_str)
        if _precomp is not None:
            all_pitcher_results = get_pitchers(_precomp)
            _msg, _level = source_banner(_precomp, _source)
            if _level == "success":
                st.success(_msg)
            elif _level == "info":
                st.info(_msg)
            else:
                st.warning(_msg)
            _precomputed_loaded = True

    if not _precomputed_loaded:
        if DATA_LOADER_AVAILABLE:
            st.warning("⚠️ No pre-computed data found for today — running live calculations.")

    if not _precomputed_loaded:
        progress = st.progress(0)

    if not _precomputed_loaded:
      for i, game in enumerate(games):
        progress.progress((i + 1) / len(games))
        game_pk = game["game_pk"]
        game_lineups = lineup_status[game_pk]
        
        for side in ["home", "away"]:
            pitcher = game.get(f"{side}_pitcher", "TBD")
            pid = game.get(f"{side}_pid")
            pitcher_hand = game.get(f"{side}_pitcher_hand", "R")
            team = game.get(f"{side}_team")
            opp = game.get("away_team" if side == "home" else "home_team")
            opp_id = game.get("away_team_id" if side == "home" else "home_team_id")
            opp_side = "away" if side == "home" else "home"
            
            if not pid or pitcher == "TBD":
                continue
            
            # Pitcher stats
            p_recent = get_recent_pitcher_stats(pid, 7)
            p_baseline = parse_season_stats(get_player_season_stats(pid, current_season))
            opp_recent = get_team_batting_stats(opp_id, 14)
            opp_baseline = get_team_season_batting(opp_id, current_season)
            
            games_played = p_recent.get("games_sampled", 0) if p_recent else 0
            
            # Initialize component scores
            stuff_score = None
            location_score = None
            matchup_score = None
            workload_score = None
            stuff_breakdown = {}
            profile_type = "BALANCED"
            profile_desc = ""
            salci_grade = "C"
            is_statcast = False
            
            # Combine stats for blending
            combined_stats = {}
            if p_recent:
                combined_stats.update(p_recent)
            if p_baseline:
                for key in ["K9", "K_percent", "K/BB", "P/IP"]:
                    if key in p_baseline and key in combined_stats:
                        combined_stats[key] = combined_stats[key] * 0.6 + p_baseline[key] * 0.4
                    elif key in p_baseline:
                        combined_stats[key] = p_baseline[key]
            
            opp_stats = {}
            if opp_recent:
                opp_stats.update(opp_recent)
            if opp_baseline:
                for key in ["OppK%", "OppContact%"]:
                    if key in opp_baseline and key in opp_stats:
                        opp_stats[key] = opp_stats[key] * 0.6 + opp_baseline[key] * 0.4
                    elif key in opp_baseline:
                        opp_stats[key] = opp_baseline[key]
            
            # Try SALCI v3 first
            salci_v3_result = None
            if SALCI_V3_AVAILABLE and STATCAST_AVAILABLE:
                try:
                    profile = get_pitcher_statcast_profile(pid, days=30)
                    if profile:
                        stuff_score = profile.get('stuff_plus', 100)
                        location_score = profile.get('location_plus', 100)
                        stuff_breakdown = profile.get('by_pitch_type', {})
                        profile_type = profile.get('profile_type', 'BALANCED')
                        profile_desc = profile.get('profile_description', '')
                        
                        # Workload
                        avg_ip = (p_recent or {}).get('avg_ip_per_start', 5.5)
                        w_stats = {'P/IP': combined_stats.get('P/IP', 16.0), 'avg_ip': avg_ip}
                        workload_score, w_break = calculate_workload_score_v3(w_stats)
                        
                        # Matchup - lineup-aware
                        opp_lineup_info = game_lineups[opp_side]
                        lineup_hitter_stats = None
                        
                        if opp_lineup_info.get('confirmed') and opp_lineup_info.get('lineup'):
                            lineup_hitter_stats = []
                            for player in opp_lineup_info['lineup']:
                                h_recent = get_hitter_recent_stats(player['id'], 7)
                                if h_recent:
                                    lineup_hitter_stats.append({
                                        'name': player['name'],
                                        'k_rate': h_recent.get('k_rate', 0.22),
                                        'zone_contact_pct': 1 - h_recent.get('k_rate', 0.22) * 0.8,
                                        'bat_side': player.get('bat_side', 'R')
                                    })
                        
                        matchup_score, m_break = calculate_matchup_score_v3(
                            opp_stats, lineup_hitter_stats, pitcher_hand
                        )
                        
                        # Calculate SALCI v3
                        salci_v3_result = calculate_salci_v3(
                            stuff_score, location_score, matchup_score, workload_score
                        )
                        salci_grade = salci_v3_result.get('grade', 'C')
                        is_statcast = True
                except Exception as e:
                    st.warning(f"SALCI v3 error for {pitcher}: {e}")
                    pass
            
            # Fallback to SALCI v1
            if salci_v3_result:
                salci = salci_v3_result['salci']
                proj = calculate_expected_ks_v3(salci_v3_result, 
                                               (p_recent or {}).get('avg_ip_per_start', 5.5))
                
                result = {
                    "pitcher": pitcher,
                    "pitcher_id": pid,
                    "pitcher_hand": pitcher_hand,
                    "pitcher_k_pct": (p_baseline or p_recent or {}).get("K_percent", 0.22),
                    "team": team,
                    "opponent": opp,
                    "opponent_id": opp_id,
                    "game_pk": game_pk,
                    "salci": salci,
                    "salci_grade": salci_grade,
                    "expected": proj.get("expected", 5),
                    "k_lines": proj.get("k_lines", {}),
                    "lines": proj.get("k_lines", {}),
                    "best_line": proj.get("best_line", 5),
                    "breakdown": {},
                    "lineup_confirmed": game_lineups[opp_side]["confirmed"],
                    "floor": proj.get("floor", 5),
                    "floor_confidence": proj.get("floor_confidence", 70),
                    "volatility": proj.get("volatility", 1.2),
                    "stuff_score": stuff_score,
                    "location_score": location_score,
                    "matchup_score": matchup_score,
                    "workload_score": workload_score,
                    "stuff_breakdown": stuff_breakdown,
                    "profile_type": profile_type,
                    "profile_desc": profile_desc,
                    "is_statcast": is_statcast,
                    "k_per_ip": proj.get("k_per_ip"),
                    "projected_ip": proj.get("projected_ip"),
                }
                all_pitcher_results.append(result)
            else:
                # V1 fallback
                salci, breakdown, missing = compute_salci(
                    p_recent, p_baseline, opp_recent, opp_baseline, weights, games_played
                )
                
                if salci is not None:
                    base_k9 = (p_baseline or p_recent or {}).get("K9", 9.0)
                    proj = project_lines(salci, base_k9)
                    
                    all_pitcher_results.append({
                        "pitcher": pitcher,
                        "pitcher_id": pid,
                        "pitcher_hand": pitcher_hand,
                        "pitcher_k_pct": (p_baseline or p_recent or {}).get("K_percent", 0.22),
                        "team": team,
                        "opponent": opp,
                        "opponent_id": opp_id,
                        "game_pk": game_pk,
                        "salci": salci,
                        "salci_grade": ("A" if salci >= 75 else
                                        "B" if salci >= 60 else
                                        "C" if salci >= 45 else
                                        "D" if salci >= 30 else "F"),
                        "expected": proj["expected"],
                        "k_lines": proj["lines"],
                        "lines": proj["lines"],
                        "best_line": (max((k for k, v in proj["lines"].items() if v >= 50), default=None)
                                      or (max(proj["lines"].keys()) if proj["lines"] else 5)),
                        "breakdown": breakdown,
                        "lineup_confirmed": game_lineups[opp_side]["confirmed"],
                        "is_statcast": False,
                        "stuff_score": None,
                        "location_score": None,
                        "profile_type": "N/A",
                    })
            
            # Hitter processing
            if show_hitters:
                opp_lineup_info = game_lineups[opp_side]
                
                if opp_lineup_info["confirmed"] or not confirmed_only:
                    lineup = opp_lineup_info["lineup"]
                    
                    for player in lineup:
                        h_recent = get_hitter_recent_stats(player["id"], 7)
                        h_season = get_hitter_season_stats(player["id"], current_season)
                        if h_recent:
                            h_score = compute_hitter_score(h_recent)
                            if not hot_hitters_only or h_score >= 60:
                                # Compute Log5 Hit Score if hit_likelihood is available
                                hit_prob_score = None
                                hit_prob_breakdown = {}
                                if HIT_LIKELIHOOD_AVAILABLE:
                                    try:
                                        batter_stats = {
                                            "avg": (h_season or {}).get("avg") or h_recent.get("avg", 0.248),
                                            "l7_avg": h_recent.get("avg"),
                                            "bat_side": player.get("bat_side", "R"),
                                        }
                                        pitcher_stats_for_log5 = {
                                            "avg_against": (p_baseline or p_recent or {}).get("avg_against", 0.248),
                                            "pitcher_hand": pitcher_hand,
                                        }
                                        hit_prob_score, hit_prob_breakdown = calculate_hitter_hit_prob(
                                            batter_stats, pitcher_stats_for_log5, league_avg=0.248
                                        )
                                    except Exception:
                                        pass
                                all_hitter_results.append({
                                    "name": player["name"],
                                    "player_id": player["id"],
                                    "position": player["position"],
                                    "batting_order": player["batting_order"],
                                    "bat_side": player["bat_side"],
                                    "team": opp,
                                    "vs_pitcher": pitcher,
                                    "pitcher_hand": pitcher_hand,
                                    "pitcher_k_pct": (p_baseline or p_recent or {}).get("K_percent", 0.22),
                                    "game_pk": game_pk,
                                    "recent": h_recent,
                                    "season": h_season or {},
                                    "score": h_score,
                                    "lineup_confirmed": opp_lineup_info["confirmed"],
                                    "hit_prob_score": hit_prob_score,
                                    "hit_prob_breakdown": hit_prob_breakdown,
                                })
    
      progress.empty()

    # Sort results
    all_pitcher_results.sort(key=lambda x: x["salci"], reverse=True)
    all_hitter_results.sort(key=lambda x: x["score"], reverse=True)

    

    
    # ======================
    # TAB 1: Pitcher Analysis
    # ======================
    with tab1:
        st.markdown("### 🎯 Pitcher Strikeout Predictions (SALCI v3)")
        
        filtered_pitchers = [p for p in all_pitcher_results if p["salci"] >= min_salci]
        
        if not filtered_pitchers:
            st.info("No pitchers match your filters.")
        else:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Pitchers", len(filtered_pitchers))
            with col2:
                elite = len([p for p in filtered_pitchers if p["salci"] >= 75])
                st.metric("🔥 Elite (A)", elite)
            with col3:
                strong = len([p for p in filtered_pitchers if 60 <= p["salci"] < 75])
                st.metric("✅ Strong (B)", strong)
            with col4:
                confirmed = len([p for p in filtered_pitchers if p.get("lineup_confirmed")])
                st.metric("📋 Lineups Confirmed", confirmed)
            
            st.markdown("---")
            
            view_mode = st.radio(
                "View Mode",
                ["📊 Component Table", "🎴 Pitcher Cards"],
                horizontal=True,
                index=0
            )
            
            st.markdown("")
            
            if view_mode == "📊 Component Table":
                st.markdown("#### All Pitchers - SALCI v3 Components")
                st.caption("Stuff (40%), Matchup (25%), Workload (20%), Location (15%)")
                
                def get_grade_emoji(score, is_100_scale=True):
                    if is_100_scale:
                        if score >= 115: return "A+"
                        if score >= 110: return "A"
                        if score >= 105: return "B+"
                        if score >= 100: return "B"
                        if score >= 95: return "C+"
                        if score >= 90: return "C"
                        return "D"
                    else:
                        if score >= 70: return "A"
                        if score >= 60: return "B"
                        if score >= 50: return "C"
                        if score >= 40: return "D"
                        return "F"
                
                df_pitchers = pd.DataFrame([{
                    "Pitcher": f"{p['pitcher']} ({p.get('pitcher_hand', 'R')})",
                    "Team": p["team"],
                    "vs": p["opponent"],
                    "SALCI": p["salci"],
                    "Grade": p.get("salci_grade", "C"),
                    "Stuff": f"{int(p.get('stuff_score', 100))} ({get_grade_emoji(p.get('stuff_score', 100), True)})" if p.get('stuff_score') else "-",
                    "Match": f"{int(p.get('matchup_score', 50))} ({get_grade_emoji(p.get('matchup_score', 50), False)})" if p.get('matchup_score') else "-",
                    "Work": f"{int(p.get('workload_score', 50))} ({get_grade_emoji(p.get('workload_score', 50), False)})" if p.get('workload_score') else "-",
                    "Loc": f"{int(p.get('location_score', 100))} ({get_grade_emoji(p.get('location_score', 100), True)})" if p.get('location_score') else "-",
                    "Exp K": p["expected"],
                    "5+": f"{p['lines'].get(5, '-')}%",
                    "6+": f"{p['lines'].get(6, '-')}%",
                    "7+": f"{p['lines'].get(7, '-')}%",
                    "Profile": p.get("profile_type", "-"),
                    "Source": "🎯" if p.get("is_statcast") else "📊",
                    "✓": "✅" if p.get("lineup_confirmed") else "⏳",
                } for p in filtered_pitchers])
                
                st.dataframe(
                    df_pitchers,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "SALCI": st.column_config.NumberColumn(format="%.1f"),
                        "Exp K": st.column_config.NumberColumn(format="%.1f"),
                    }
                )
                
                st.markdown("---")
                st.caption("**SALCI v3 Weights:** Stuff (40%) • Matchup (25%) • Workload (20%) • Location (15%)")
                st.caption("**Source:** 🎯 = Real Statcast physics data | 📊 = Proxy metrics from MLB Stats API")
            
            else:
                # Card view
                for result in filtered_pitchers:
                    if result.get("lineup_confirmed"):
                        st.markdown(f"<span class='lineup-confirmed'>✓ Opponent Lineup Confirmed</span>", 
                                   unsafe_allow_html=True)
                    else:
                        st.markdown(f"<span class='lineup-pending'>⏳ Lineup Pending</span>", 
                                   unsafe_allow_html=True)
                    render_pitcher_card(result)
            render_compact_summary(all_pitcher_results)
    
    
    # ======================
    # TAB 2: Hitter Matchups
    # ======================
    with tab2:
        st.markdown("### 🏏 Hitter Analysis & Matchups")
        
        if confirmed_only:
            st.info("📋 Showing **CONFIRMED STARTERS ONLY** - These players are in today's starting lineup!")
        
        if not all_hitter_results:
            if confirmed_only:
                st.warning("⏳ No confirmed lineups available yet. Lineups are typically released 1-2 hours before game time.")
            else:
                st.info("Enable 'Show Hitter Analysis' in sidebar to see hitter data.")
        else:
            hot_hitters = [h for h in all_hitter_results if h["score"] >= 70]
            cold_hitters = [h for h in all_hitter_results if h["score"] <= 30]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 🔥 Hottest Hitters (Starting Today)")
                if hot_hitters:
                    for h in hot_hitters[:8]:
                        render_hitter_card(h, show_batting_order=True)
                        st.markdown("")
                else:
                    st.info("No hot hitters in confirmed lineups yet.")
            
            with col2:
                st.markdown("#### ❄️ Coldest Hitters (Fade Candidates)")
                if cold_hitters:
                    for h in cold_hitters[:8]:
                        render_hitter_card(h, show_batting_order=True)
                        st.markdown("")
                else:
                    st.info("No cold hitters in confirmed lineups yet.")
            
            st.markdown("---")
            st.markdown("#### 📊 All Confirmed Starters")
            
            if all_hitter_results:
                def _hs_label(score):
                    if score is None: return "—"
                    if score >= 75: return f"{score} 🔥"
                    if score >= 60: return f"{score} ✅"
                    if score >= 45: return f"{score} ➖"
                    if score >= 30: return f"{score} ⚠️"
                    return f"{score} ❌"

                df_hitters = pd.DataFrame([{
                    "Order": f"#{h['batting_order']}" if h.get('batting_order') else "-",
                    "Player": h["name"],
                    "Bats": h.get("bat_side", "R"),
                    "AB": h.get("season", {}).get("ab", 0),
                    "Team": h["team"],
                    "Pos": h["position"],
                    "vs Pitcher": h["vs_pitcher"],
                    "P Hand": h.get("pitcher_hand", "R"),
                    "AVG (L7)": f"{h['recent'].get('avg', 0):.3f}",
                    "OPS (L7)": f"{h['recent'].get('ops', 0):.3f}",
                    "K% (L7)": f"{h['recent'].get('k_rate', 0)*100:.1f}%",
                    "Hit Score": _hs_label(h.get("hit_prob_score")),
                    "Confirmed": "✅" if h.get("lineup_confirmed") else "⏳"
                } for h in all_hitter_results])
                
                st.dataframe(df_hitters, use_container_width=True, hide_index=True)
                
                if HIT_LIKELIHOOD_AVAILABLE:
                    st.caption("🎯 **Hit Score** — 0-100 Log5 probability (50 = league average matchup). "
                               "🔥 ≥75 · ✅ ≥60 · ➖ ≥45 · ⚠️ ≥30 · ❌ <30")
    
    # ======================
    # TAB 3: Best Bets
    # ======================
    with tab3:
        st.markdown("### 🎯 Today's Best Bets")
        
        confirmed_hitters = [h for h in all_hitter_results if h.get("lineup_confirmed")]
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### ⚾ Top Pitcher K Props")
            top_pitchers = [p for p in all_pitcher_results if p["salci"] >= 60][:5]
            
            if not top_pitchers:
                st.info("No elite pitcher picks available.")
            else:
                for i, p in enumerate(top_pitchers, 1):
                    rating_label, emoji, _ = get_rating(p["salci"])
                    lineup_badge = "✅" if p.get("lineup_confirmed") else "⏳"
                    p_hand = p.get("pitcher_hand", "R")
                    st.markdown(f"""
                    <div style='background: #e0f2fe; padding: 1rem; border-radius: 10px; 
                                margin-bottom: 0.5rem; border-left: 4px solid #3b82f6;'>
                        <span style='color: #1e3a5f;'><strong>#{i} {p['pitcher']} ({p_hand}HP)</strong> ({p['team']} vs {p['opponent']}) {lineup_badge}</span><br>
                        <span style='font-size: 1.2rem; color: #1e3a5f;'>{emoji} SALCI: {p['salci']}</span><br>
                        <span style='color: #1e3a5f;'>Expected: <strong>{p['expected']} Ks</strong></span><br>
                        <span style='color: #1e3a5f;'>5+ @ {p['lines'].get(5, '?')}% | 6+ @ {p['lines'].get(6, '?')}% | 7+ @ {p['lines'].get(7, '?')}%</span>
                    </div>
                    """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("#### 🏏 Hot Hitter Props (Confirmed Starters)")
            top_hitters = [h for h in confirmed_hitters if h["score"] >= 65][:5]
            
            if not top_hitters:
                st.info("⏳ Waiting for lineup confirmations. Check back closer to game time!")
            else:
                for i, h in enumerate(top_hitters, 1):
                    r = h["recent"]
                    h_hand = h.get("bat_side", "R")
                    p_hand = h.get("pitcher_hand", "R")
                    matchup, _ = get_matchup_grade(r.get("k_rate", 0.22), h["pitcher_k_pct"],
                                                   h_hand, p_hand)
                    st.markdown(f"""
                    <div style='background: #fef3c7; padding: 1rem; border-radius: 10px;
                                margin-bottom: 0.5rem; border-left: 4px solid #f59e0b;'>
                        <span style='color: #78350f;'><strong>#{i} {h['name']} ({h_hand}HB)</strong> ({h['team']}) - Batting #{h.get('batting_order', '?')}</span><br>
                        <span style='color: #78350f;'>vs {h['vs_pitcher']} ({p_hand}HP) | {matchup}</span><br>
                        <span style='color: #78350f;'>L7: <strong>{r.get('avg', 0):.3f} AVG</strong> / {r.get('ops', 0):.3f} OPS</span><br>
                        <span style='color: #78350f;'>{f"🔥 {r.get('hit_streak', 0)}-game hit streak" if r.get('hit_streak', 0) >= 3 else ""}</span>
                    </div>
                    """, unsafe_allow_html=True)
    
    # ======================
    # TAB 4: Heat Maps
    # ======================
    with tab4:
        st.markdown("### 🔥 Zone Heat Maps")
        
        if not STATCAST_AVAILABLE:
            st.warning("""
            ⚠️ **Heat Maps require Statcast data**
            
            To enable this feature:
            1. Install pybaseball: `pip install pybaseball`
            2. Add `statcast_connector.py` to your app folder
            3. Restart the app
            
            Heat Maps show:
            - **Pitcher Attack Zones** - Where pitchers throw most frequently
            - **Hitter Damage Zones** - Where hitters do the most damage
            - **Matchup Analysis** - Overlap for predictions
            """)
        else:
            st.markdown("*Select a pitcher or hitter to see their zone performance*")
            
            col_p, col_h = st.columns(2)
            
            with col_p:
                st.markdown("#### 🎯 Pitcher Attack Map")
                if all_pitcher_results:
                    pitcher_options = {f"{p['pitcher']} ({p['team']})": p for p in all_pitcher_results}
                    selected_pitcher_name = st.selectbox(
                        "Select Pitcher",
                        options=list(pitcher_options.keys()),
                        key="heatmap_pitcher"
                    )
                    if selected_pitcher_name:
                        selected_p = pitcher_options[selected_pitcher_name]
                        pid = selected_p.get("pitcher_id")
                        if pid:
                            with st.spinner("Loading Statcast data..."):
                                attack_map = get_pitcher_attack_map(pid, days=30)
                            if attack_map and attack_map.get('grid'):
                                st.markdown("##### Strike Zone Usage & Effectiveness")
                                zone_grid = attack_map['grid']
                                z_data, text_data = [], []
                                for row in [3, 2, 1]:
                                    row_vals, row_text = [], []
                                    for col in [1, 2, 3]:
                                        zone = (row - 1) * 3 + col
                                        zone_info = zone_grid.get(zone, {})
                                        usage = zone_info.get('usage', 0)
                                        whiff = zone_info.get('whiff_pct', 20)
                                        row_vals.append(whiff)
                                        row_text.append(f"Zone {zone}<br>Usage: {usage:.0f}%<br>Whiff: {whiff:.0f}%")
                                    z_data.append(row_vals)
                                    text_data.append(row_text)
                                
                                fig = go.Figure(data=go.Heatmap(
                                    z=z_data,
                                    text=text_data,
                                    texttemplate="%{text}",
                                    textfont={"size": 10},
                                    colorscale=[[0, '#ef4444'], [0.5, '#fbbf24'], [1, '#22c55e']],
                                    showscale=True,
                                    colorbar=dict(title="Whiff%"),
                                ))
                                fig.update_layout(
                                    title=f"{selected_p['pitcher']} - Attack Zones (L30D)",
                                    xaxis=dict(showticklabels=False),
                                    yaxis=dict(showticklabels=False),
                                    height=350,
                                )
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("Unable to load heat map data for this pitcher")
            
            with col_h:
                st.markdown("#### 💥 Hitter Damage Map")
                if all_hitter_results:
                    hitter_options = {f"{h['name']} ({h['team']})": h for h in all_hitter_results[:20]}
                    selected_hitter_name = st.selectbox(
                        "Select Hitter",
                        options=list(hitter_options.keys()),
                        key="heatmap_hitter"
                    )
                    if selected_hitter_name:
                        selected_h = hitter_options[selected_hitter_name]
                        hid = selected_h.get("player_id")
                        if hid:
                            with st.spinner("Loading Statcast data..."):
                                damage_map = get_hitter_damage_map(hid, days=30)
                            if damage_map and damage_map.get('grid'):
                                st.markdown("##### Batting Average by Zone")
                                zone_grid = damage_map['grid']
                                z_data, text_data = [], []
                                for row in [3, 2, 1]:
                                    row_vals, row_text = [], []
                                    for col in [1, 2, 3]:
                                        zone = (row - 1) * 3 + col
                                        zone_info = zone_grid.get(zone, {})
                                        ba = zone_info.get('ba', 0.250)
                                        swing = zone_info.get('swing_pct', 50)
                                        row_vals.append(ba)
                                        row_text.append(f"Zone {zone}<br>BA: {ba:.3f}<br>Swing: {swing:.0f}%")
                                    z_data.append(row_vals)
                                    text_data.append(row_text)
                                
                                fig = go.Figure(data=go.Heatmap(
                                    z=z_data,
                                    text=text_data,
                                    texttemplate="%{text}",
                                    textfont={"size": 10},
                                    colorscale=[[0, '#3b82f6'], [0.4, '#fbbf24'], [1, '#ef4444']],
                                    showscale=True,
                                    colorbar=dict(title="BA"),
                                ))
                                fig.update_layout(
                                    title=f"{selected_h['name']} - Damage Zones (L30D)",
                                    xaxis=dict(showticklabels=False),
                                    yaxis=dict(showticklabels=False),
                                    height=350,
                                )
                                st.plotly_chart(fig, use_container_width=True)
    
    # ======================
    # TAB 5: Charts & Share
    # ======================
    with tab5:
        st.markdown("### 📊 Shareable Charts & Insights")
        st.markdown("*Only showing confirmed lineups. Charts update as lineups are released.*")
        
        st.markdown("---")
        
        confirmed_pitchers = [p for p in all_pitcher_results if p.get("lineup_confirmed", False)]
        confirmed_hitters = [h for h in all_hitter_results if h.get("lineup_confirmed", False)]
        
        if not confirmed_pitchers:
            st.warning("⚠️ No confirmed lineups yet. Charts will appear once lineups are released.")
            st.info("💡 Tip: Click 'Refresh Lineups' in the sidebar to check for updates.")
        else:
            st.success(f"✅ Using {len(confirmed_pitchers)} pitchers with confirmed opponent lineups")
            
            # === NEW TOP SECTION: Expected Ks Focus ===
            col_new1, col_new2, col_new3 = st.columns(3)
            
            with col_new1:
                st.markdown("#### 📈 Expected Ks vs SALCI")
                fig_expected_salci = create_expected_vs_salci_chart(confirmed_pitchers)
                if fig_expected_salci:
                    st.plotly_chart(fig_expected_salci, use_container_width=True)
                else:
                    st.info("Not enough data")
            
            with col_new2:
                st.markdown("#### 🔥 Top 10 Expected Strikeouts")
                fig_top10_ks = create_top_10_expected_ks_chart(confirmed_pitchers)
                if fig_top10_ks:
                    st.plotly_chart(fig_top10_ks, use_container_width=True)
                else:
                    st.info("No pitcher data")
            
            with col_new3:
                st.markdown("#### ⚡ SALCI vs Floor Confidence")
                fig_confidence = create_salci_vs_confidence_chart(confirmed_pitchers)
                if fig_confidence:
                    st.plotly_chart(fig_confidence, use_container_width=True)
                else:
                    st.info("Not enough data")
            
            st.markdown("---")
            
            # === YOUR ORIGINAL CHARTS (unchanged) ===
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### 📈 Pitcher SALCI Rankings")
                fig_pitchers = create_pitcher_comparison_chart(confirmed_pitchers)
                if fig_pitchers:
                    st.plotly_chart(fig_pitchers, use_container_width=True)
            
            with col2:
                st.markdown("#### 🔥 Hot Hitters (L7)")
                fig_hitters = create_hitter_hotness_chart(confirmed_hitters)
                if fig_hitters:
                    st.plotly_chart(fig_hitters, use_container_width=True)
            
            st.markdown("---")
            
            col3, col4 = st.columns(2)
            with col3:
                st.markdown("#### 🎯 K Line Projections")
                fig_k_lines = create_k_projection_chart(confirmed_pitchers)
                if fig_k_lines:
                    st.plotly_chart(fig_k_lines, use_container_width=True)
            
            with col4:
                st.markdown("#### 🧮 SALCI v3 Weight Distribution")
                fig_breakdown = create_salci_breakdown_chart()
                st.plotly_chart(fig_breakdown, use_container_width=True)
            
            st.markdown("---")
            
            st.markdown("#### 📊 Hitter Profile: K% vs AVG")
            fig_scatter = create_matchup_scatter(confirmed_hitters)
            if fig_scatter:
                st.plotly_chart(fig_scatter, use_container_width=True)
            
            st.markdown("---")
            
            st.markdown("#### ⚡ Pitcher Profiles: Stuff vs Location")
            st.markdown("*Shows where pitchers fall on the Stuff vs Location spectrum*")
            fig_stuff_loc = create_stuff_location_chart(confirmed_pitchers)
            if fig_stuff_loc:
                st.plotly_chart(fig_stuff_loc, use_container_width=True)
            
            st.markdown("---")
            
            with st.expander("📱 Tips for Sharing on Twitter/X"):
                st.markdown("""
                **How to share these charts:**
                1. Screenshot the chart
                2. Crop to focus on the visual
                3. Post with #SALCI
                
                **Sample tweet:**
                > 🚨 Top SALCI pitcher today: [Name] at 82 🔥  
                > Expected: 7.2 Ks | 6+ @ 78%  
                > #SALCI #MLB
                """)
    
    # ======================
    # TAB 6: Yesterday's Reflection
    # ======================
    with tab6:
        if YESTERDAY_TAB_AVAILABLE:
            render_yesterday_tab()
        else:
            st.warning("⚠️ `yesterday_tab.py` not found. Make sure it is in the same folder as this file.")
    
    # ======================
    # TAB 7: Model Accuracy
    # ======================
    with tab7:
        st.markdown("### 🎯 SALCI Model Accuracy Dashboard")
        st.markdown("*Track how well SALCI predictions match actual results over time.*")
        st.markdown("---")

        if not YESTERDAY_TAB_AVAILABLE:
            st.warning("⚠️ `yesterday_tab.py` not found. Cannot display accuracy dashboard.")
        else:
            from yesterday_tab import load_rolling_accuracy

            window = st.radio("Lookback window", ["7 days", "14 days", "30 days"],
                              horizontal=True, key="accuracy_window")
            days_map = {"7 days": 7, "14 days": 14, "30 days": 30}
            n_days = days_map[window]

            ra = load_rolling_accuracy(n_days)

            if ra.get("days_analyzed", 0) == 0:
                st.info(
                    f"No accuracy data for the past {n_days} days yet.\n\n"
                    "GitHub Actions will build this automatically — one day of data appears each morning."
                )
            else:
                st.markdown(f"#### Last {n_days} days — {ra.get('games_analyzed', 0)} pitcher-games")

                tendency = ra.get("tendency", "CALIBRATED")
                tendency_color = {"OVER": "#3b82f6", "UNDER": "#f97316", "CALIBRATED": "#10b981"}.get(tendency, "#6b7280")
                tendency_label = {
                    "OVER":       "📈 Running LOW — model under-projects Ks",
                    "UNDER":      "📉 Running HIGH — model over-projects Ks",
                    "CALIBRATED": "⚖️ Well calibrated",
                }.get(tendency, "")
                st.markdown(
                    f"<div style='background:{tendency_color}22;border:1px solid {tendency_color};"
                    f"border-radius:8px;padding:0.6rem 1rem;margin-bottom:1rem;'>"
                    f"<strong style='color:{tendency_color};'>{tendency_label}</strong></div>",
                    unsafe_allow_html=True
                )

                c1, c2, c3 = st.columns(3)
                c1.metric("✅ Hit Rate",    f"{ra.get('accuracy_pct', 0):.1f}%", help="% within ±1.5 Ks of actual")
                c2.metric("📊 Games Analyzed", ra.get("games_analyzed", 0))
                c3.metric("⚖️ Avg K Delta",  f"{ra.get('avg_k_delta', 0):+.2f} Ks", delta_color="inverse")

    with tab8:
        if PITCHING_DASH_AVAILABLE:
            render_pitching_dashboard()

if __name__ == "__main__":
    main()
