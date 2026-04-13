#!/usr/bin/env python3
"""
SALCI v5.2 - Advanced MLB Prediction System
Strikeout Adjusted Lineup Confidence Index

NEW IN v5.2:
- ⚔️ Head-to-Head Matchup Card: Visual side-by-side game matchup graphic
  rendered directly under Pitcher Cards for each game.

INCLUDED FROM v5.1:
- 🎯 SALCI v3 K-Optimized Weights: Stuff 40%, Matchup 25%, Workload 20%, Location 15%
- 📋 Lineup-Level Matchup: Uses individual hitter K% when lineup confirmed
- 🎪 Arsenal Display: Per-pitch Stuff+ scores on pitcher cards
- 📊 Sortable Table View: Quick-scan all pitchers with grades and K-lines
- 📈 Model Accuracy Dashboard: 7-day and 30-day rolling performance tracking
- ⚡ Leash Factor: Manager tendencies in workload calculation
- 💾 UNIFIED REFLECTION SYSTEM: Standardized data storage with reflection.py

Run with:
    streamlit run mlb_salci_full.py
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
        get_pitcher_statcast_profile,
        get_hitter_zone_profile,
        get_pitcher_attack_map,
        get_hitter_damage_map,
        analyze_matchup_zones,
        calculate_stuff_plus,
        calculate_location_plus,
        calculate_workload_score_v3,
        calculate_matchup_score_v3,
        calculate_salci_v3,
        calculate_expected_ks_v3,
        classify_pitcher_profile,
        get_component_grade,
        SALCI_V3_WEIGHTS,
        MATCHUP_SUBWEIGHTS,
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
    import reflection as refl
    REFLECTION_AVAILABLE = True
except ImportError as e:
    st.warning(f"⚠️ Reflection module not available: {e}")
    REFLECTION_AVAILABLE = False

# ----------------------------
# Version Info
# ----------------------------
SALCI_VERSION = "5.2"
SALCI_BUILD_DATE = "2026-04-14"

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

    /* ── Matchup Card Styles ── */
    .matchup-card-wrapper {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 16px;
        padding: 20px 24px 16px;
        margin: 8px 0 20px 0;
        position: relative;
        overflow: hidden;
    }
    .matchup-card-wrapper::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: linear-gradient(90deg, #3b82f6, #8b5cf6, #ec4899);
    }
    .matchup-header {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        color: #64748b;
        text-transform: uppercase;
        text-align: center;
        margin-bottom: 14px;
    }
    .pitcher-name-away {
        font-size: 1.15rem;
        font-weight: 800;
        color: #e2e8f0;
        text-align: left;
    }
    .pitcher-name-home {
        font-size: 1.15rem;
        font-weight: 800;
        color: #e2e8f0;
        text-align: right;
    }
    .team-label {
        font-size: 0.72rem;
        color: #64748b;
        font-weight: 600;
        letter-spacing: 0.05em;
    }
    .salci-big {
        font-size: 2.6rem;
        font-weight: 900;
        line-height: 1;
    }
    .grade-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        margin-top: 4px;
    }
    .edge-center {
        text-align: center;
        padding: 4px 0;
    }
    .edge-label {
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #94a3b8;
    }
    .edge-vs {
        font-size: 1.6rem;
        font-weight: 900;
        line-height: 1.1;
    }
    .edge-delta {
        font-size: 0.75rem;
        color: #94a3b8;
        margin-top: 2px;
    }
    .stat-row-label {
        font-size: 0.65rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .stat-row-value {
        font-size: 0.95rem;
        font-weight: 700;
        color: #e2e8f0;
    }
    .conf-bar-bg {
        background: #1e293b;
        border-radius: 6px;
        height: 8px;
        margin: 6px 0 2px 0;
        overflow: hidden;
    }
    .conf-bar-fill {
        height: 100%;
        border-radius: 6px;
        transition: width 0.4s ease;
    }
    .conf-label {
        font-size: 0.65rem;
        color: #64748b;
        text-align: center;
    }
    .key-insight {
        background: rgba(255,255,255,0.04);
        border-left: 3px solid #3b82f6;
        border-radius: 0 8px 8px 0;
        padding: 8px 12px;
        margin-top: 12px;
        font-size: 0.78rem;
        color: #94a3b8;
        line-height: 1.5;
    }
    .matchup-pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.65rem;
        font-weight: 600;
        margin: 2px 2px 0 0;
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
    if not REFLECTION_AVAILABLE:
        return False
    try:
        predictions = {
            "date": date_str,
            "generated_at": datetime.now().isoformat(),
            "salci_version": SALCI_VERSION,
            "pitchers": [
                {
                    "pitcher_id": p.get("pitcher_id"),
                    "pitcher_name": p.get("pitcher"),
                    "team": p.get("team"),
                    "opponent": p.get("opponent"),
                    "salci": p.get("salci"),
                    "expected_ks": p.get("expected"),
                    "k_lines": p.get("k_lines", {}),
                    "floor": p.get("floor"),
                    "floor_confidence": p.get("floor_confidence"),
                    "lineup_confirmed": p.get("lineup_confirmed", False),
                }
                for p in all_pitcher_results
            ],
            "hitters": [
                {
                    "player_id": h.get("player_id"),
                    "name": h.get("name"),
                    "team": h.get("team"),
                    "score": h.get("score"),
                    "lineup_confirmed": h.get("lineup_confirmed", False),
                }
                for h in all_hitter_results
            ]
        }
        return refl.save_daily_predictions(date_str, predictions)
    except Exception as e:
        st.warning(f"Could not save predictions: {e}")
        return False

def load_predictions_for_reflection(date_str: str):
    if not REFLECTION_AVAILABLE:
        return None
    try:
        return refl.load_daily_predictions(date_str)
    except Exception as e:
        st.warning(f"Could not load predictions: {e}")
        return None

def get_yesterday_date() -> str:
    return (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")

def get_current_season(date_obj: datetime) -> int:
    if date_obj.month < 3:
        return date_obj.year - 1
    return date_obj.year

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
    except Exception as e:
        st.warning(f"Error fetching teams: {e}")
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
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&season=2025&group=pitching&limit={num_games}"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None

        totals = {
            "ip": 0, "so": 0, "bb": 0, "hits": 0, "runs": 0,
            "pitches": 0, "strikes": 0, "games": 0
        }
        for g in splits[:num_games]:
            s = g.get("stat", {})
            ip_str = s.get("inningsPitched", "0.0")
            try:
                parts = ip_str.split(".")
                ip = int(parts[0]) + int(parts[1]) / 3 if len(parts) > 1 else float(ip_str)
            except:
                ip = 0
            totals["ip"] += ip
            totals["so"] += int(s.get("strikeOuts", 0))
            totals["bb"] += int(s.get("baseOnBalls", 0))
            totals["hits"] += int(s.get("hits", 0))
            totals["runs"] += int(s.get("runs", 0))
            totals["pitches"] += int(s.get("numberOfPitches", 0))
            totals["strikes"] += int(s.get("strikes", 0))
            totals["games"] += 1

        if totals["ip"] == 0:
            return None

        k9 = (totals["so"] / totals["ip"]) * 9
        k_pct = totals["so"] / max(totals["so"] + totals["bb"] + totals["hits"], 1)
        k_bb = totals["so"] / max(totals["bb"], 1)
        p_ip = totals["pitches"] / max(totals["ip"], 1)
        avg_ip = totals["ip"] / max(totals["games"], 1)

        return {
            "K9": round(k9, 2),
            "K_percent": round(k_pct, 3),
            "K/BB": round(k_bb, 2),
            "P/IP": round(p_ip, 1),
            "SO": totals["so"],
            "IP": round(totals["ip"], 1),
            "games_sampled": totals["games"],
            "avg_ip_per_start": round(avg_ip, 2),
        }
    except Exception as e:
        return None

def parse_season_stats(raw: Optional[Dict]) -> Optional[Dict]:
    if not raw:
        return None
    try:
        ip_str = raw.get("inningsPitched", "0.0")
        parts = ip_str.split(".")
        ip = int(parts[0]) + int(parts[1]) / 3 if len(parts) > 1 else float(ip_str)
        if ip == 0:
            return None
        so = int(raw.get("strikeOuts", 0))
        bb = int(raw.get("baseOnBalls", 0))
        hits = int(raw.get("hits", 0))
        pitches = int(raw.get("numberOfPitches", 0))
        return {
            "K9": round((so / ip) * 9, 2),
            "K_percent": round(so / max(so + bb + hits, 1), 3),
            "K/BB": round(so / max(bb, 1), 2),
            "P/IP": round(pitches / max(ip, 1), 1),
            "IP": round(ip, 1),
        }
    except:
        return None

@st.cache_data(ttl=300)
def get_team_batting_stats(team_id: int, num_games: int = 14) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=gameLog&season=2025&group=hitting&limit={num_games}"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        totals = {"ab": 0, "so": 0, "h": 0, "bb": 0}
        for g in splits[:num_games]:
            s = g.get("stat", {})
            totals["ab"] += int(s.get("atBats", 0))
            totals["so"] += int(s.get("strikeOuts", 0))
            totals["h"] += int(s.get("hits", 0))
            totals["bb"] += int(s.get("baseOnBalls", 0))
        pa = totals["ab"] + totals["bb"]
        return {
            "OppK%": round(totals["so"] / max(pa, 1), 3),
            "OppContact%": round(1 - totals["so"] / max(totals["ab"], 1), 3),
        }
    except:
        return None

@st.cache_data(ttl=3600)
def get_team_season_batting(team_id: int, season: int) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=season&season={season}&group=hitting"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        s = splits[0]["stat"]
        ab = int(s.get("atBats", 1))
        so = int(s.get("strikeOuts", 0))
        bb = int(s.get("baseOnBalls", 0))
        pa = ab + bb
        return {
            "OppK%": round(so / max(pa, 1), 3),
            "OppContact%": round(1 - so / max(ab, 1), 3),
        }
    except:
        return None

# ----------------------------
# API Functions - Hitters
# ----------------------------
@st.cache_data(ttl=300)
def get_hitter_recent_stats(player_id: int, num_games: int = 7) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&season=2025&group=hitting&limit={num_games}"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        totals = {"ab": 0, "h": 0, "bb": 0, "so": 0, "hr": 0, "2b": 0, "3b": 0, "rbi": 0}
        hit_streak = 0
        hitless_streak = 0
        tracking_streak = True
        for g in splits[:num_games]:
            s = g.get("stat", {})
            h = int(s.get("hits", 0))
            ab = int(s.get("atBats", 0))
            if tracking_streak:
                if h > 0:
                    if hitless_streak == 0:
                        hit_streak += 1
                    else:
                        tracking_streak = False
                else:
                    if hit_streak == 0:
                        hitless_streak += 1
                    else:
                        tracking_streak = False
            totals["ab"] += ab
            totals["h"] += h
            totals["bb"] += int(s.get("baseOnBalls", 0))
            totals["so"] += int(s.get("strikeOuts", 0))
            totals["hr"] += int(s.get("homeRuns", 0))
            totals["2b"] += int(s.get("doubles", 0))
            totals["3b"] += int(s.get("triples", 0))
            totals["rbi"] += int(s.get("rbi", 0))

        if totals["ab"] == 0:
            return None

        avg = totals["h"] / totals["ab"]
        slg = (totals["h"] + totals["2b"] + 2 * totals["3b"] + 3 * totals["hr"]) / max(totals["ab"], 1)
        obp = (totals["h"] + totals["bb"]) / max(totals["ab"] + totals["bb"], 1)
        ops = obp + slg
        k_rate = totals["so"] / max(totals["ab"] + totals["bb"], 1)

        return {
            "avg": round(avg, 3),
            "ops": round(ops, 3),
            "obp": round(obp, 3),
            "slg": round(slg, 3),
            "k_rate": round(k_rate, 3),
            "hr": totals["hr"],
            "rbi": totals["rbi"],
            "ab": totals["ab"],
            "hit_streak": hit_streak,
            "hitless_streak": hitless_streak,
        }
    except:
        return None

@st.cache_data(ttl=3600)
def get_hitter_season_stats(player_id: int, season: int) -> Optional[Dict]:
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&season={season}&group=hitting"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0]["stat"]
            return {
                "avg": float(s.get("avg", 0.250)),
                "ops": float(s.get("ops", 0.700)),
                "ab": int(s.get("atBats", 0)),
                "hr": int(s.get("homeRuns", 0)),
            }
    except:
        pass
    return None

@st.cache_data(ttl=300)
def get_box_score_hitters(date_str: str, min_hits: int = 2) -> List[Dict]:
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
            except:
                continue
        hitters.sort(key=lambda x: (x["hits"], x["hr"], x["rbi"]), reverse=True)
        return hitters
    except:
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
    recent_w, base_w = get_blend_weights(games_played)
    blended = {}
    missing = []

    def blend(key: str, r_dict, b_dict) -> Optional[float]:
        r = r_dict.get(key) if r_dict else None
        b = b_dict.get(key) if b_dict else None
        if r is not None and b is not None:
            return r * recent_w + b * base_w
        return r or b

    stat_sources = {
        "K9": (pitcher_recent, pitcher_baseline),
        "K_percent": (pitcher_recent, pitcher_baseline),
        "K/BB": (pitcher_recent, pitcher_baseline),
        "P/IP": (pitcher_recent, pitcher_baseline),
        "OppK%": (opp_recent, opp_baseline),
        "OppContact%": (opp_recent, opp_baseline),
    }

    breakdown = {}
    total_weight = 0
    weighted_score = 0

    for stat, (r_src, b_src) in stat_sources.items():
        val = blend(stat, r_src, b_src)
        w = weights.get(stat, 0)
        if val is None:
            missing.append(stat)
            continue
        min_v, max_v, higher = BOUNDS[stat]
        norm = normalize(val, min_v, max_v, higher)
        contribution = norm * w * 100
        blended[stat] = val
        breakdown[stat] = {"value": val, "normalized": norm, "contribution": contribution}
        weighted_score += contribution
        total_weight += w

    if total_weight == 0:
        return None, {}, missing

    salci = weighted_score / total_weight
    return round(salci, 1), breakdown, missing

def compute_hitter_score(recent: Dict) -> float:
    if not recent:
        return 50
    score = 0
    weights_total = 0
    if recent.get("avg"):
        score += normalize(recent["avg"], 0.180, 0.380, True) * 100 * 0.25
        weights_total += 0.25
    if recent.get("ops"):
        score += normalize(recent["ops"], 0.550, 1.100, True) * 100 * 0.25
        weights_total += 0.25
    if recent.get("k_rate") is not None:
        score += normalize(recent["k_rate"], 0.35, 0.10, False) * 100 * 0.15
        weights_total += 0.15
    base_score = (score / weights_total * 100) if weights_total > 0 else 50
    bonus = 0
    if recent.get("hit_streak", 0) >= 3:
        bonus += min(recent["hit_streak"] * 3, 15)
    if recent.get("hitless_streak", 0) >= 2:
        bonus -= min(recent["hitless_streak"] * 5, 20)
    if recent.get("hr", 0) >= 1:
        bonus += min(recent["hr"] * 5, 15)
    final_score = base_score + bonus
    return max(0, min(100, final_score * 1.1))

def project_lines(salci: float, base_k9: float = 9.0) -> Dict:
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
    combined = (hitter_k_rate * 0.5 + pitcher_k_pct * 0.5)
    platoon = (hitter_hand == pitcher_hand)
    if combined >= 0.28 and not platoon:
        return "🔴 K-Prone Matchup", "matchup-bad"
    elif combined >= 0.25:
        return "🟡 Neutral Matchup", "matchup-neutral"
    elif not platoon:
        return "🟢 Favorable Matchup", "matchup-good"
    return "🟡 Platoon Disadvantage", "matchup-neutral"

# ----------------------------
# Charting Functions
# ----------------------------
def create_pitcher_comparison_chart(pitcher_results: List[Dict]):
    if not pitcher_results:
        return None
    top = sorted(pitcher_results, key=lambda x: x["salci"], reverse=True)[:8]
    names = [f"{p['pitcher'].split()[-1]}" for p in top]
    salci_vals = [p["salci"] for p in top]
    colors = [get_salci_color(s) for s in salci_vals]
    fig = go.Figure(go.Bar(
        x=names, y=salci_vals, marker_color=colors,
        text=[f"{s:.1f}" for s in salci_vals], textposition='outside'
    ))
    fig.update_layout(
        title=dict(text="SALCI Rankings", font=dict(size=14)),
        yaxis=dict(range=[0, 100], title="SALCI"),
        height=300, margin=dict(l=20, r=20, t=50, b=60),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig

def create_hitter_hotness_chart(hitter_results: List[Dict]):
    if not hitter_results:
        return None
    top = sorted(hitter_results, key=lambda x: x["score"], reverse=True)[:8]
    names = [h["name"].split()[-1] for h in top]
    scores = [h["score"] for h in top]
    fig = go.Figure(go.Bar(
        x=names, y=scores,
        marker_color=["#D85A30" if s >= 70 else "#4a90d9" if s <= 30 else "#eab308" for s in scores],
        text=[f"{s:.0f}" for s in scores], textposition='outside'
    ))
    fig.update_layout(
        title=dict(text="Hitter Heat Index (L7)", font=dict(size=14)),
        yaxis=dict(range=[0, 100], title="Score"),
        height=300, margin=dict(l=20, r=20, t=50, b=60),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig

def create_expected_vs_salci_chart(pitcher_results: List[Dict]):
    if not pitcher_results:
        return None
    names = [p["pitcher"].split()[-1] for p in pitcher_results]
    salci_v = [p["salci"] for p in pitcher_results]
    exp_k = [p["expected"] for p in pitcher_results]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=salci_v, y=exp_k, mode='markers+text',
        text=names, textposition='top center',
        marker=dict(size=10, color=salci_v, colorscale='RdYlGn', showscale=True)
    ))
    fig.update_layout(
        title="Expected Ks vs SALCI", xaxis_title="SALCI", yaxis_title="Expected Ks",
        height=300, margin=dict(l=40, r=20, t=50, b=40),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig

def create_top_10_expected_ks_chart(pitcher_results: List[Dict]):
    if not pitcher_results:
        return None
    top = sorted(pitcher_results, key=lambda x: x["expected"], reverse=True)[:10]
    names = [p["pitcher"].split()[-1] for p in top]
    exp = [p["expected"] for p in top]
    fig = go.Figure(go.Bar(
        x=names, y=exp, marker_color="#3b82f6",
        text=[f"{e:.1f}" for e in exp], textposition='outside'
    ))
    fig.update_layout(
        title="Top 10 Expected Ks", yaxis_title="Exp K",
        height=300, margin=dict(l=20, r=20, t=50, b=60),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig

def create_salci_vs_confidence_chart(pitcher_results: List[Dict]):
    if not pitcher_results:
        return None
    top = sorted(pitcher_results, key=lambda x: x["salci"], reverse=True)[:8]
    names = [p["pitcher"].split()[-1] for p in top]
    floors = [p.get("floor", 5) for p in top]
    confs = [p.get("floor_confidence", 70) for p in top]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Floor Ks", x=names, y=floors, marker_color="#10b981"))
    fig.add_trace(go.Scatter(
        name="Confidence %", x=names, y=confs,
        mode='lines+markers', yaxis='y2',
        marker=dict(color="#f59e0b", size=8), line=dict(color="#f59e0b")
    ))
    fig.update_layout(
        title="Floor Ks + Confidence", height=300,
        margin=dict(l=40, r=60, t=50, b=60),
        yaxis=dict(title="Floor Ks"),
        yaxis2=dict(title="Confidence %", overlaying='y', side='right', range=[0, 100]),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation="h", y=1.15)
    )
    return fig

def create_k_projection_chart(pitcher_results: List[Dict]):
    if not pitcher_results:
        return None
    top = sorted(pitcher_results, key=lambda x: x["salci"], reverse=True)[:5]
    names = [f"{p['pitcher'].split()[-1]} ({p.get('pitcher_hand', 'R')})" for p in top]
    k_lines_data = []
    for p in top:
        k_dict = p.get("k_lines", {}) or p.get("lines", {})
        if k_dict:
            k_vals = sorted(k_dict.keys())
            k_lines_data.append([k_dict.get(k, 50) for k in k_vals[:4]])
        else:
            k_lines_data.append([50, 40, 30, 20])
    fig = go.Figure()
    if k_lines_data and top:
        first_klines = sorted((top[0].get("k_lines", {}) or {}).keys())
        if not first_klines:
            first_klines = [5, 6, 7, 8]
        line_labels = [f"{k}+" for k in first_klines[:4]]
        for line_idx, line_label in enumerate(line_labels):
            probs = [kld[line_idx] if line_idx < len(kld) else 0 for kld in k_lines_data]
            fig.add_trace(go.Bar(
                name=line_label, x=names, y=probs,
                text=[f"{p}%" for p in probs], textposition='outside'
            ))
    fig.update_layout(
        title=dict(text="K Line Probabilities (Top Pitchers)", font=dict(size=16)),
        yaxis_title="Probability %", yaxis=dict(range=[0, 100]),
        barmode='group', height=350, margin=dict(l=50, r=50, t=80, b=80),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig

# =============================================================================
# ⚔️  NEW: HEAD-TO-HEAD MATCHUP CARD
# =============================================================================

def render_matchup_card(
    away_result: Dict,
    home_result: Dict,
    lineup_status: Dict,
    game_pk: int
) -> None:
    """
    Render a cinematic head-to-head matchup card between two pitchers.

    Displays:
    - Side-by-side SALCI scores with grade badges
    - K-line comparison (best line for each pitcher)
    - Lineup threat level (hot hitters faced)
    - Component breakdown mini-bars (Stuff / Matchup / Workload / Location)
    - Confidence bar + edge label
    - Key insight note
    """

    # ── Pull data ──────────────────────────────────────────────────────────
    away_salci    = away_result.get("salci", 0)
    home_salci    = home_result.get("salci", 0)
    away_name     = away_result.get("pitcher", "TBD")
    home_name     = home_result.get("pitcher", "TBD")
    away_team     = away_result.get("team", "")
    home_team     = home_result.get("team", "")
    away_hand     = away_result.get("pitcher_hand", "R")
    home_hand     = home_result.get("pitcher_hand", "R")
    away_grade    = away_result.get("salci_grade", "C")
    home_grade    = home_result.get("salci_grade", "C")
    away_exp      = away_result.get("expected", "--")
    home_exp      = home_result.get("expected", "--")

    # K-lines — pick the best "at-least" line with probability ≥ 50%
    def best_k_line(result: Dict) -> str:
        k_dict = result.get("k_lines", {}) or result.get("lines", {})
        if not k_dict:
            return "--"
        eligible = {k: v for k, v in k_dict.items() if v >= 50}
        if not eligible:
            best_k = max(k_dict, key=k_dict.get)
            return f"{best_k}+ @ {k_dict[best_k]}%"
        best_k = max(eligible)
        return f"{best_k}+ @ {eligible[best_k]}%"

    away_kline = best_k_line(away_result)
    home_kline = best_k_line(home_result)

    # Lineup threat (hot hitters = score proxy not directly stored, use lineup size)
    game_lineups = lineup_status.get(game_pk, {})
    home_lineup  = game_lineups.get("home", {}).get("lineup", [])
    away_lineup  = game_lineups.get("away", {}).get("lineup", [])
    home_confirmed = game_lineups.get("home", {}).get("confirmed", False)
    away_confirmed = game_lineups.get("away", {}).get("confirmed", False)

    # Away pitcher faces the HOME lineup, home pitcher faces AWAY lineup
    away_threat = len(home_lineup)   # how many hitters away pitcher faces
    home_threat = len(away_lineup)

    # ── Edge computation ───────────────────────────────────────────────────
    delta = home_salci - away_salci   # positive = home has edge
    abs_delta = abs(delta)

    if abs_delta < 3:
        edge_label   = "DEAD EVEN"
        edge_symbol  = "⚖️"
        edge_hex     = "#eab308"
        edge_bg      = "rgba(234,179,8,0.15)"
        edge_border  = "#854d0e"
    elif delta > 0:
        edge_label   = "HOME EDGE"
        edge_symbol  = "🏠"
        edge_hex     = "#22c55e"
        edge_bg      = "rgba(34,197,94,0.12)"
        edge_border  = "#166534"
    else:
        edge_label   = "AWAY EDGE"
        edge_symbol  = "✈️"
        edge_hex     = "#3b82f6"
        edge_bg      = "rgba(59,130,246,0.12)"
        edge_border  = "#1e3a8a"

    # Confidence: scales 0–100 from delta 0–15+
    confidence = min(int(abs_delta * 6.5), 100)

    # ── Grade colour helper ────────────────────────────────────────────────
    def grade_color(salci: float) -> Tuple[str, str]:
        """Returns (hex_color, bg_color) for inline badge."""
        if salci >= 75:
            return "#10b981", "rgba(16,185,129,0.2)"
        elif salci >= 60:
            return "#3b82f6", "rgba(59,130,246,0.2)"
        elif salci >= 45:
            return "#eab308", "rgba(234,179,8,0.2)"
        elif salci >= 30:
            return "#f97316", "rgba(249,115,22,0.2)"
        return "#ef4444", "rgba(239,68,68,0.2)"

    away_color, away_bg  = grade_color(away_salci)
    home_color, home_bg  = grade_color(home_salci)

    # ── Component mini-bar helper ──────────────────────────────────────────
    def comp_bar(label: str, value, is_100_scale: bool = False) -> str:
        """Return HTML for a labelled mini progress bar."""
        if value is None:
            return f"""
            <div style='margin-bottom:6px;'>
              <div style='display:flex;justify-content:space-between;font-size:0.6rem;color:#64748b;margin-bottom:2px;'>
                <span>{label}</span><span>--</span>
              </div>
              <div style='background:#1e293b;border-radius:4px;height:5px;'>
                <div style='width:0%;background:#475569;border-radius:4px;height:100%;'></div>
              </div>
            </div>"""
        if is_100_scale:
            pct = min(100, max(0, (value - 70) * 2))
            color = "#10b981" if value >= 110 else "#22c55e" if value >= 100 else "#eab308" if value >= 90 else "#ef4444"
            display = str(int(value))
        else:
            pct = min(100, max(0, value))
            color = "#10b981" if value >= 65 else "#22c55e" if value >= 50 else "#eab308" if value >= 35 else "#ef4444"
            display = str(int(value))
        return f"""
        <div style='margin-bottom:6px;'>
          <div style='display:flex;justify-content:space-between;font-size:0.6rem;color:#94a3b8;margin-bottom:2px;'>
            <span>{label}</span><span style='color:{color};font-weight:700;'>{display}</span>
          </div>
          <div style='background:#1e293b;border-radius:4px;height:5px;'>
            <div style='width:{pct}%;background:{color};border-radius:4px;height:100%;'></div>
          </div>
        </div>"""

    # ── Key insight text ───────────────────────────────────────────────────
    def build_insight() -> str:
        notes = []
        # SALCI gap
        if abs_delta >= 10:
            leader = home_name.split()[-1] if delta > 0 else away_name.split()[-1]
            notes.append(f"<strong>{leader}</strong> holds a dominant SALCI edge (+{abs_delta:.1f})")
        elif abs_delta >= 5:
            leader = home_name.split()[-1] if delta > 0 else away_name.split()[-1]
            notes.append(f"<strong>{leader}</strong> has a meaningful SALCI advantage (+{abs_delta:.1f})")
        else:
            notes.append("Both pitchers are evenly matched — monitor lineup releases for tiebreaker")

        # Profile types
        away_profile = away_result.get("profile_type", "")
        home_profile = home_result.get("profile_type", "")
        if away_profile and away_profile not in ("BALANCED", "N/A", ""):
            notes.append(f"{away_name.split()[-1]} profiles as <strong>{away_profile}</strong>")
        if home_profile and home_profile not in ("BALANCED", "N/A", ""):
            notes.append(f"{home_name.split()[-1]} profiles as <strong>{home_profile}</strong>")

        # Lineup confirmation
        if away_confirmed and home_confirmed:
            notes.append("✅ Both lineups confirmed — projections are fully lineup-aware")
        elif away_confirmed or home_confirmed:
            confirmed_side = "Away" if away_confirmed else "Home"
            notes.append(f"⏳ {confirmed_side} lineup confirmed; opponent lineup still pending")
        else:
            notes.append("⏳ No lineups confirmed yet — check back closer to game time")

        # Hot K-line callout
        for p_name, p_result in [(away_name, away_result), (home_name, home_result)]:
            k_dict = p_result.get("k_lines", {}) or p_result.get("lines", {})
            if k_dict:
                high_conf = {k: v for k, v in k_dict.items() if v >= 75}
                if high_conf:
                    best = max(high_conf, key=high_conf.get)
                    notes.append(
                        f"🎯 <strong>{p_name.split()[-1]}</strong> has a strong {best}+ K line at {high_conf[best]}%"
                    )

        return " &nbsp;·&nbsp; ".join(notes[:3])  # cap at 3 notes

    insight_html = build_insight()

    # ── Lineup status pill ─────────────────────────────────────────────────
    def lineup_pill(confirmed: bool, size: int) -> str:
        if confirmed:
            return f"<span class='matchup-pill' style='background:rgba(16,185,129,0.2);color:#10b981;border:1px solid #065f46;'>✓ {size} Confirmed</span>"
        return f"<span class='matchup-pill' style='background:rgba(234,179,8,0.15);color:#eab308;border:1px solid #854d0e;'>⏳ Pending</span>"

    # ── Render the card ────────────────────────────────────────────────────
    st.markdown(f"""
    <div class='matchup-card-wrapper'>
      <div class='matchup-header'>⚔️ &nbsp; HEAD-TO-HEAD MATCHUP &nbsp; ⚔️</div>

      <!-- TOP ROW: names + SALCI scores -->
      <div style='display:grid;grid-template-columns:1fr 100px 1fr;gap:8px;align-items:center;'>

        <!-- AWAY PITCHER -->
        <div style='text-align:left;'>
          <div style='font-size:0.65rem;color:#64748b;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;'>
            ✈️ AWAY &nbsp;·&nbsp; {away_team}
          </div>
          <div style='font-size:1.1rem;font-weight:800;color:#e2e8f0;line-height:1.2;margin:3px 0;'>{away_name}</div>
          <div style='font-size:0.72rem;color:#64748b;'>({away_hand}HP)</div>

          <!-- SALCI score -->
          <div style='margin-top:8px;display:inline-block;background:{away_bg};
                      border:1px solid {away_color}40;border-radius:12px;padding:6px 14px;'>
            <span style='font-size:2.2rem;font-weight:900;color:{away_color};line-height:1;'>{away_salci:.1f}</span>
            <span style='font-size:0.7rem;font-weight:700;color:{away_color};margin-left:4px;
                         display:inline-block;vertical-align:bottom;margin-bottom:4px;'>
              Gr {away_grade}
            </span>
          </div>
        </div>

        <!-- CENTER EDGE -->
        <div style='text-align:center;'>
          <div style='font-size:1.8rem;line-height:1;'>{edge_symbol}</div>
          <div style='font-size:0.55rem;font-weight:700;letter-spacing:0.12em;
                      color:{edge_hex};text-transform:uppercase;margin-top:3px;'>{edge_label}</div>
          <div style='font-size:0.85rem;font-weight:800;color:{edge_hex};margin-top:1px;'>
            Δ {abs_delta:.1f}
          </div>
        </div>

        <!-- HOME PITCHER -->
        <div style='text-align:right;'>
          <div style='font-size:0.65rem;color:#64748b;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;'>
            🏠 HOME &nbsp;·&nbsp; {home_team}
          </div>
          <div style='font-size:1.1rem;font-weight:800;color:#e2e8f0;line-height:1.2;margin:3px 0;'>{home_name}</div>
          <div style='font-size:0.72rem;color:#64748b;'>({home_hand}HP)</div>

          <!-- SALCI score -->
          <div style='margin-top:8px;display:inline-block;background:{home_bg};
                      border:1px solid {home_color}40;border-radius:12px;padding:6px 14px;'>
            <span style='font-size:2.2rem;font-weight:900;color:{home_color};line-height:1;'>{home_salci:.1f}</span>
            <span style='font-size:0.7rem;font-weight:700;color:{home_color};margin-left:4px;
                         display:inline-block;vertical-align:bottom;margin-bottom:4px;'>
              Gr {home_grade}
            </span>
          </div>
        </div>
      </div>

      <!-- DIVIDER -->
      <div style='border-top:1px solid #1e293b;margin:14px 0 12px;'></div>

      <!-- MIDDLE ROW: stats + component bars -->
      <div style='display:grid;grid-template-columns:1fr 100px 1fr;gap:8px;'>

        <!-- AWAY stats -->
        <div>
          <div style='font-size:0.65rem;color:#64748b;text-transform:uppercase;
                      letter-spacing:0.08em;margin-bottom:4px;'>Projection</div>
          <div style='font-size:0.85rem;font-weight:700;color:#e2e8f0;'>
            Exp Ks: <span style='color:{away_color};'>{away_exp}</span>
          </div>
          <div style='font-size:0.78rem;color:#94a3b8;margin-top:2px;'>
            Best line: {away_kline}
          </div>
          <div style='margin-top:6px;'>
            {lineup_pill(home_confirmed, len(home_lineup))}
            <span style='font-size:0.62rem;color:#64748b;'>&nbsp;opp lineup</span>
          </div>
          <div style='margin-top:10px;'>
            {comp_bar("⚡ Stuff", away_result.get("stuff_score"), is_100_scale=True)}
            {comp_bar("🎯 Matchup", away_result.get("matchup_score"), is_100_scale=False)}
            {comp_bar("⚖️ Workload", away_result.get("workload_score"), is_100_scale=False)}
            {comp_bar("📍 Location", away_result.get("location_score"), is_100_scale=True)}
          </div>
        </div>

        <!-- CENTER: confidence bar -->
        <div style='display:flex;flex-direction:column;justify-content:center;align-items:center;'>
          <div style='font-size:0.6rem;color:#64748b;text-transform:uppercase;
                      letter-spacing:0.08em;margin-bottom:8px;text-align:center;'>Confidence</div>
          <!-- vertical bar -->
          <div style='width:28px;height:90px;background:#1e293b;border-radius:6px;
                      overflow:hidden;display:flex;align-items:flex-end;'>
            <div style='width:100%;height:{confidence}%;background:linear-gradient(180deg,{edge_hex},{edge_hex}88);
                        border-radius:6px;transition:height 0.4s;'></div>
          </div>
          <div style='font-size:0.9rem;font-weight:800;color:{edge_hex};margin-top:6px;'>{confidence}%</div>
          <div style='font-size:0.55rem;color:#475569;text-align:center;margin-top:2px;'>CONF</div>
        </div>

        <!-- HOME stats -->
        <div style='text-align:right;'>
          <div style='font-size:0.65rem;color:#64748b;text-transform:uppercase;
                      letter-spacing:0.08em;margin-bottom:4px;'>Projection</div>
          <div style='font-size:0.85rem;font-weight:700;color:#e2e8f0;'>
            Exp Ks: <span style='color:{home_color};'>{home_exp}</span>
          </div>
          <div style='font-size:0.78rem;color:#94a3b8;margin-top:2px;'>
            Best line: {home_kline}
          </div>
          <div style='margin-top:6px;text-align:right;'>
            <span style='font-size:0.62rem;color:#64748b;'>opp lineup&nbsp;</span>
            {lineup_pill(away_confirmed, len(away_lineup))}
          </div>
          <div style='margin-top:10px;'>
            {comp_bar("⚡ Stuff", home_result.get("stuff_score"), is_100_scale=True)}
            {comp_bar("🎯 Matchup", home_result.get("matchup_score"), is_100_scale=False)}
            {comp_bar("⚖️ Workload", home_result.get("workload_score"), is_100_scale=False)}
            {comp_bar("📍 Location", home_result.get("location_score"), is_100_scale=True)}
          </div>
        </div>
      </div>

      <!-- KEY INSIGHT -->
      <div class='key-insight'>
        💡 {insight_html}
      </div>

      <!-- WATERMARK -->
      <div style='text-align:right;font-size:0.58rem;color:#334155;margin-top:8px;'>
        SALCI v{SALCI_VERSION} Matchup Engine
      </div>
    </div>
    """, unsafe_allow_html=True)


# =============================================================================
# UI Rendering Functions
# =============================================================================

def render_arsenal_display(stuff_breakdown: Dict):
    """Render pitch arsenal with per-pitch Stuff+ scores."""
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
        'FF': ('4-Seam', '#ef4444'), 'SI': ('Sinker', '#f97316'), 'FC': ('Cutter', '#eab308'),
        'SL': ('Slider', '#22c55e'), 'ST': ('Sweeper', '#14b8a6'), 'CU': ('Curve', '#3b82f6'),
        'KC': ('Knuckle-C', '#6366f1'), 'CH': ('Change', '#a855f7'), 'FS': ('Splitter', '#ec4899'),
        'SV': ('Slurve', '#06b6d4'),
    }
    st.markdown("<div style='margin-top: 0.5rem; padding: 8px; background: rgba(0,0,0,0.03); border-radius: 8px;'>",
                unsafe_allow_html=True)
    st.markdown("<div style='font-size: 0.7rem; color: #666; margin-bottom: 4px;'>🎪 ARSENAL</div>",
                unsafe_allow_html=True)
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
                    stuff_color = "#10b981"; stuff_bg = "rgba(16, 185, 129, 0.1)"
                elif stuff >= 105:
                    stuff_color = "#22c55e"; stuff_bg = "rgba(34, 197, 94, 0.1)"
                elif stuff >= 95:
                    stuff_color = "#eab308"; stuff_bg = "rgba(234, 179, 8, 0.1)"
                elif stuff >= 85:
                    stuff_color = "#6b7280"; stuff_bg = "rgba(107, 114, 128, 0.1)"
                else:
                    stuff_color = "#ef4444"; stuff_bg = "rgba(239, 68, 68, 0.1)"
                st.markdown(f"""
                <div style='background: {stuff_bg}; border: 1px solid {color}; border-radius: 6px; padding: 6px 10px; min-width: 80px;'>
                    <div style='font-size: 0.75rem; font-weight: bold; color: {color};'>{name}</div>
                    <div style='font-size: 0.65rem; color: #666;'>{velo:.0f} mph • {usage:.0f}%</div>
                    <div style='font-size: 0.85rem; font-weight: bold; color: {stuff_color};'>Stuff+ {int(stuff)}</div>
                    <div style='font-size: 0.6rem; color: #888;'>Whiff {whiff:.0f}%</div>
                </div>
                """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_pitcher_card(result: Dict, show_stuff_location: bool = True):
    """Render pitcher card with SALCI v3 component breakdown + At Least Ks floor."""
    salci = result["salci"]
    rating_label, emoji, css_class = get_rating(salci)

    with st.container():
        col1, col2, col3 = st.columns([2, 1, 2])

        with col1:
            p_hand = result.get("pitcher_hand", "R")
            st.markdown(f"### {result['pitcher']} ({p_hand}HP)")
            st.markdown(f"**{result['team']}** vs {result['opponent']}")
            if result.get("profile_type") and result.get("profile_type") not in ("BALANCED", "N/A", ""):
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
            st.markdown(
                f"<div style='text-align: center;'>"
                f"<span style='font-size: 2.5rem; font-weight: bold;'>{result['salci']}</span><br>"
                f"<span class='{css_class}'>{emoji} Grade {grade}</span></div>",
                unsafe_allow_html=True
            )

        with col3:
            expected_ks = result.get("expected", "--")
            floor_ks = result.get("floor")
            floor_conf = result.get("floor_confidence")
            st.markdown(f"**Expected Ks:** {expected_ks}")
            if floor_ks is not None and floor_conf is not None:
                st.markdown(
                    f"**At Least:** <span style='color:#10b981; font-weight:bold;'>{floor_ks} Ks</span> "
                    f"({floor_conf}% confidence)", unsafe_allow_html=True
                )
            else:
                st.markdown("**At Least:** --")
            k_lines = result.get("k_lines", {}) or result.get("lines", {})
            if k_lines:
                cols = st.columns(4)
                for i, (k_value, prob) in enumerate(sorted(k_lines.items())[:4]):
                    with cols[i]:
                        color = "#22c55e" if prob >= 70 else "#eab308" if prob >= 50 else "#ef4444"
                        st.markdown(
                            f"<div style='text-align:center;'><small>{k_value}+</small><br>"
                            f"<span style='color:{color}; font-weight:bold;'>{prob}%</span></div>",
                            unsafe_allow_html=True
                        )

        # SALCI v3 4-Component Breakdown
        if show_stuff_location:
            stuff    = result.get("stuff_score")
            location = result.get("location_score")
            matchup  = result.get("matchup_score")
            workload = result.get("workload_score")

            if stuff or location or matchup or workload:
                st.markdown("<div style='margin-top: 0.5rem;'>", unsafe_allow_html=True)
                col_s, col_m, col_w, col_l = st.columns(4)

                def get_component_color(score, is_100_scale=True):
                    if score is None:
                        return "#d1d5db"
                    if is_100_scale:
                        if score >= 115: return "#10b981"
                        if score >= 105: return "#22c55e"
                        if score >= 95:  return "#eab308"
                        return "#ef4444"
                    else:
                        if score >= 65: return "#10b981"
                        if score >= 50: return "#22c55e"
                        if score >= 35: return "#eab308"
                        return "#ef4444"

                with col_s:
                    if stuff:
                        sc = get_component_color(stuff, True)
                        sp = min(100, max(0, (stuff - 70) * 2))
                        st.markdown(f"""
                        <div style='text-align: center;'>
                          <div style='font-size: 0.7rem; color: #666;'>⚡ STUFF (40%)</div>
                          <div style='font-size: 1.2rem; font-weight: bold; color: {sc};'>{int(stuff)}</div>
                          <div style='background: #e5e7eb; border-radius: 4px; height: 6px; margin-top: 2px;'>
                            <div style='width: {sp}%; background: {sc}; border-radius: 4px; height: 100%;'></div>
                          </div>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='text-align: center; color: #aaa; font-size: 0.8rem;'>STUFF<br>--</div>",
                                   unsafe_allow_html=True)

                with col_m:
                    if matchup:
                        mc = get_component_color(matchup, False)
                        mp = min(100, max(0, matchup))
                        st.markdown(f"""
                        <div style='text-align: center;'>
                          <div style='font-size: 0.7rem; color: #666;'>🎯 MATCHUP (25%)</div>
                          <div style='font-size: 1.2rem; font-weight: bold; color: {mc};'>{int(matchup)}</div>
                          <div style='background: #e5e7eb; border-radius: 4px; height: 6px; margin-top: 2px;'>
                            <div style='width: {mp}%; background: {mc}; border-radius: 4px; height: 100%;'></div>
                          </div>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='text-align: center; color: #aaa; font-size: 0.8rem;'>MATCHUP<br>--</div>",
                                   unsafe_allow_html=True)

                with col_w:
                    if workload:
                        wc = get_component_color(workload, False)
                        wp = min(100, max(0, workload))
                        st.markdown(f"""
                        <div style='text-align: center;'>
                          <div style='font-size: 0.7rem; color: #666;'>⚖️ WORKLOAD (20%)</div>
                          <div style='font-size: 1.2rem; font-weight: bold; color: {wc};'>{int(workload)}</div>
                          <div style='background: #e5e7eb; border-radius: 4px; height: 6px; margin-top: 2px;'>
                            <div style='width: {wp}%; background: {wc}; border-radius: 4px; height: 100%;'></div>
                          </div>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='text-align: center; color: #aaa; font-size: 0.8rem;'>WORKLOAD<br>--</div>",
                                   unsafe_allow_html=True)

                with col_l:
                    if location:
                        lc = get_component_color(location, True)
                        lp = min(100, max(0, (location - 70) * 2))
                        st.markdown(f"""
                        <div style='text-align: center;'>
                          <div style='font-size: 0.7rem; color: #666;'>📍 LOCATION (15%)</div>
                          <div style='font-size: 1.2rem; font-weight: bold; color: {lc};'>{int(location)}</div>
                          <div style='background: #e5e7eb; border-radius: 4px; height: 6px; margin-top: 2px;'>
                            <div style='width: {lp}%; background: {lc}; border-radius: 4px; height: 100%;'></div>
                          </div>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='text-align: center; color: #aaa; font-size: 0.8rem;'>LOCATION<br>--</div>",
                                   unsafe_allow_html=True)

                st.markdown("</div>", unsafe_allow_html=True)

                stuff_breakdown = result.get("stuff_breakdown", {})
                if stuff_breakdown and result.get("is_statcast"):
                    render_arsenal_display(stuff_breakdown)

        st.progress(min(result["salci"] / 100, 1.0))
        st.markdown("---")


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
            st.markdown(f"<span class='hot-streak'>🔥 {recent['hit_streak']}-game streak</span>",
                       unsafe_allow_html=True)
        elif recent.get("hitless_streak", 0) >= 3:
            st.markdown(f"<span class='cold-streak'>❄️ {recent['hitless_streak']}-game slump</span>",
                       unsafe_allow_html=True)

    with col2:
        st.markdown(f"**L7 AVG**")
        avg = recent.get("avg", 0)
        color = "#22c55e" if avg >= 0.300 else "#eab308" if avg >= 0.250 else "#ef4444"
        st.markdown(f"<span style='color:{color}; font-size:1.1rem; font-weight:bold;'>{avg:.3f}</span>",
                   unsafe_allow_html=True)

    with col3:
        st.markdown(f"**OPS**")
        ops = recent.get("ops", 0)
        color = "#22c55e" if ops >= 0.900 else "#eab308" if ops >= 0.700 else "#ef4444"
        st.markdown(f"<span style='color:{color}; font-size:1.1rem; font-weight:bold;'>{ops:.3f}</span>",
                   unsafe_allow_html=True)

    with col4:
        st.markdown(f"**K%**")
        k_rate = recent.get("k_rate", 0)
        color = "#22c55e" if k_rate <= 0.15 else "#eab308" if k_rate <= 0.25 else "#ef4444"
        st.markdown(f"<span style='color:{color}; font-size:1.1rem; font-weight:bold;'>{k_rate:.1%}</span>",
                   unsafe_allow_html=True)

    with col5:
        st.markdown(f"<span class='{matchup_css}' style='font-size:0.75rem;'>{matchup_grade}</span>",
                   unsafe_allow_html=True)


def render_compact_summary(pitcher_results: List[Dict]):
    """Renders a clean, copy-paste-ready summary block of ALL pitchers sorted by SALCI."""
    if not pitcher_results:
        st.info("No pitchers to summarize yet.")
        return

    sorted_pitchers = sorted(pitcher_results, key=lambda x: x.get("salci", 0), reverse=True)

    st.markdown("---")
    st.markdown("### 📋 Quick Copy SALCI Summary (Highest → Lowest)")

    summary_lines = []
    for result in sorted_pitchers:
        name     = result.get("pitcher", "Unknown")
        salci    = result.get("salci", 0)
        expected = result.get("expected", "--")
        k_lines  = result.get("k_lines", {})
        lines = []
        for k_value, prob in list(k_lines.items())[:3]:
            lines.append(f"{k_value}+ @ {prob}%")
        line_str = " | ".join(lines) if lines else "No K-lines"
        summary_block = f"""**{name}**\n#SALCI: {salci}\nExpected: {expected}\nKs {line_str}"""
        summary_lines.append(summary_block.strip())

    full_summary = "\n\n".join(summary_lines)
    st.markdown(
        f"""<div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 8px;
                    font-family: monospace; white-space: pre-wrap;">{full_summary}</div>""",
        unsafe_allow_html=True
    )
    st.caption("👇 Triple-click below to copy the entire list")
    st.code(full_summary, language=None)


# =============================================================================
# CHART HELPERS (Accuracy Dashboard)
# =============================================================================

def create_accuracy_chart(accuracy_data: List[Dict]):
    if not accuracy_data:
        return None
    dates = [d["date"] for d in accuracy_data]
    accuracy = [d.get("accuracy_pct", 0) for d in accuracy_data]
    fig = go.Figure(go.Scatter(
        x=dates, y=accuracy, mode='lines+markers',
        line=dict(color="#3b82f6", width=2),
        marker=dict(size=6, color="#3b82f6"),
        fill='tozeroy', fillcolor='rgba(59,130,246,0.1)'
    ))
    fig.add_hline(y=60, line_dash="dash", line_color="#22c55e", annotation_text="Target 60%")
    fig.update_layout(
        title="Model Accuracy (Rolling 7-day)", yaxis_title="Accuracy %",
        yaxis=dict(range=[0, 100]), height=250,
        margin=dict(l=40, r=20, t=50, b=40),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    # ── Header ──────────────────────────────────────────────────────────────
    st.markdown(f'<h1 class="main-header">⚾ SALCI v{SALCI_VERSION}</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">MLB Strikeout Prediction Engine | Lineup-Aware Analytics</p>',
                unsafe_allow_html=True)

    # ── Sidebar ─────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ Settings")

        selected_date = st.date_input("📅 Date", value=datetime.today())

        preset_key = st.selectbox(
            "Model Preset",
            list(WEIGHT_PRESETS.keys()),
            format_func=lambda k: WEIGHT_PRESETS[k]["name"]
        )
        st.caption(WEIGHT_PRESETS[preset_key]["desc"])

        st.markdown("---")
        st.markdown("### 🔍 Filters")
        min_salci = st.slider("Min SALCI", 0, 80, 40)
        confirmed_only = st.checkbox("✅ Confirmed Lineups Only", value=False)
        show_hitters   = st.checkbox("🏏 Show Hitter Analysis", value=True)
        hot_hitters_only = st.checkbox("🔥 Hot Hitters Only (score ≥60)", value=False)

        st.markdown("---")
        if st.button("🔄 Refresh Lineups", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown("---")
        with st.expander("📊 About SALCI v5.2"):
            st.markdown(f"""
            **SALCI v5.2** = Strikeout Adjusted Lineup Confidence Index

            **NEW:** ⚔️ Head-to-Head Matchup Card under each game's Pitcher Cards.

            **SALCI v3 Component Weights:**

            | Component | Weight |
            |-----------|--------|
            | **Stuff**    | 40% |
            | **Matchup**  | 25% |
            | **Workload** | 20% |
            | **Location** | 15% |

            **Data Sources:**
            - 🎯 Statcast: Real physics-based metrics
            - 📊 Proxy: MLB Stats API estimates
            """)

    # ── Main content ─────────────────────────────────────────────────────────
    date_str       = selected_date.strftime("%Y-%m-%d")
    weights        = WEIGHT_PRESETS[preset_key]["weights"]
    current_season = get_current_season(selected_date)

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "⚾ Pitcher Analysis",
        "🏏 Hitter Matchups",
        "🎯 Best Bets",
        "🔥 Heat Maps",
        "📊 Charts & Share",
        "📈 Yesterday",
        "🎯 Model Accuracy"
    ])

    with st.spinner("🔍 Fetching games and lineups..."):
        games = get_games_by_date(date_str)

    if not games:
        st.warning(f"No games found for {date_str}")
        return

    st.success(f"Found **{len(games)} games** for {selected_date.strftime('%A, %B %d, %Y')}")

    # ── Lineup status ────────────────────────────────────────────────────────
    lineup_status = {}
    for game in games:
        game_pk = game["game_pk"]
        home_lineup, home_confirmed = get_confirmed_lineup(game_pk, "home")
        away_lineup, away_confirmed = get_confirmed_lineup(game_pk, "away")
        lineup_status[game_pk] = {
            "home": {"lineup": home_lineup, "confirmed": home_confirmed},
            "away": {"lineup": away_lineup, "confirmed": away_confirmed}
        }

    confirmed_count = sum(
        1 for g in games
        if lineup_status[g["game_pk"]]["home"]["confirmed"]
        or lineup_status[g["game_pk"]]["away"]["confirmed"]
    )

    if confirmed_count == 0:
        st.warning("⏳ **No lineups confirmed yet.** Lineups are typically released 1-2 hours before game time.")
    else:
        st.info(f"✅ **{confirmed_count} games** have confirmed lineups")

    # ── Process all data ─────────────────────────────────────────────────────
    all_pitcher_results: List[Dict] = []
    all_hitter_results:  List[Dict] = []

    # Also track per-game pitcher pairs for matchup cards
    # Key: game_pk → {"away": result_dict, "home": result_dict}
    game_pitcher_map: Dict[int, Dict] = {}

    progress = st.progress(0)

    for i, game in enumerate(games):
        progress.progress((i + 1) / len(games))
        game_pk      = game["game_pk"]
        game_lineups = lineup_status[game_pk]

        for side in ["home", "away"]:
            pitcher      = game.get(f"{side}_pitcher", "TBD")
            pid          = game.get(f"{side}_pid")
            pitcher_hand = game.get(f"{side}_pitcher_hand", "R")
            team         = game.get(f"{side}_team")
            opp          = game.get("away_team" if side == "home" else "home_team")
            opp_id       = game.get("away_team_id" if side == "home" else "home_team_id")
            opp_side     = "away" if side == "home" else "home"

            if not pid or pitcher == "TBD":
                continue

            p_recent  = get_recent_pitcher_stats(pid, 7)
            p_baseline = parse_season_stats(get_player_season_stats(pid, current_season))
            opp_recent  = get_team_batting_stats(opp_id, 14)
            opp_baseline = get_team_season_batting(opp_id, current_season)

            games_played = p_recent.get("games_sampled", 0) if p_recent else 0

            # Initialise component scores
            stuff_score = location_score = matchup_score = workload_score = None
            stuff_breakdown: Dict = {}
            profile_type  = "BALANCED"
            profile_desc  = ""
            salci_grade   = "C"
            is_statcast   = False
            salci_v3_result = None

            # Blend stats
            combined_stats: Dict = {}
            if p_recent:
                combined_stats.update(p_recent)
            if p_baseline:
                for key in ["K9", "K_percent", "K/BB", "P/IP"]:
                    if key in p_baseline and key in combined_stats:
                        combined_stats[key] = combined_stats[key] * 0.6 + p_baseline[key] * 0.4
                    elif key in p_baseline:
                        combined_stats[key] = p_baseline[key]

            # SALCI v3 path (Statcast)
            if SALCI_V3_AVAILABLE and combined_stats:
                try:
                    statcast_profile = None
                    if STATCAST_AVAILABLE:
                        statcast_profile = get_pitcher_statcast_profile(pid, 30)

                    if statcast_profile:
                        stuff_score, stuff_breakdown = calculate_stuff_plus(statcast_profile)
                        location_score = calculate_location_plus(statcast_profile)
                        workload_score = calculate_workload_score_v3(
                            combined_stats,
                            games_played,
                            combined_stats.get("avg_ip_per_start", 5.5)
                        )
                        opp_stats = {}
                        if opp_recent:
                            opp_stats.update(opp_recent)
                        if opp_baseline:
                            for key in ["OppK%", "OppContact%"]:
                                if key in opp_baseline and key not in opp_stats:
                                    opp_stats[key] = opp_baseline[key]

                        lineup_hitter_stats = []
                        confirmed_lineup = game_lineups[opp_side]["lineup"]
                        if confirmed_lineup:
                            for player in confirmed_lineup:
                                h_recent = get_hitter_recent_stats(player["id"], 7)
                                if h_recent:
                                    lineup_hitter_stats.append({
                                        'name': player['name'],
                                        'k_rate': h_recent.get('k_rate', 0.22),
                                        'zone_contact_pct': 1 - h_recent.get('k_rate', 0.22) * 0.8,
                                        'bat_side': player.get('bat_side', 'R')
                                    })

                        matchup_score, _ = calculate_matchup_score_v3(
                            opp_stats, lineup_hitter_stats, pitcher_hand
                        )
                        salci_v3_result = calculate_salci_v3(
                            stuff_score, location_score, matchup_score, workload_score
                        )
                        salci_grade = salci_v3_result.get('grade', 'C')
                        is_statcast = True
                    else:
                        # Proxy v3 (no Statcast)
                        workload_score = calculate_workload_score_v3(
                            combined_stats,
                            games_played,
                            combined_stats.get("avg_ip_per_start", 5.5)
                        )
                        opp_stats = {}
                        if opp_recent:
                            opp_stats.update(opp_recent)
                        if opp_baseline:
                            for key in ["OppK%", "OppContact%"]:
                                if key in opp_baseline and key not in opp_stats:
                                    opp_stats[key] = opp_baseline[key]
                        matchup_score, _ = calculate_matchup_score_v3(opp_stats, None, pitcher_hand)
                        salci_v3_result = calculate_salci_v3(None, None, matchup_score, workload_score)
                        salci_grade = salci_v3_result.get('grade', 'C')

                except Exception as e:
                    st.warning(f"SALCI v3 error for {pitcher}: {e}")

            if salci_v3_result:
                salci = salci_v3_result['salci']
                proj = calculate_expected_ks_v3(
                    salci_v3_result,
                    (p_recent or {}).get('avg_ip_per_start', 5.5)
                )
                result_dict = {
                    "pitcher":       pitcher,
                    "pitcher_id":    pid,
                    "pitcher_hand":  pitcher_hand,
                    "pitcher_k_pct": (p_baseline or p_recent or {}).get("K_percent", 0.22),
                    "team":          team,
                    "opponent":      opp,
                    "opponent_id":   opp_id,
                    "game_pk":       game_pk,
                    "salci":         salci,
                    "salci_grade":   salci_grade,
                    "expected":      proj.get("expected_ks", proj.get("expected", 5)),
                    "k_lines":       proj.get("k_lines", {}),
                    "lines":         proj.get("k_lines", {}),
                    "best_line":     proj.get("best_line", 5),
                    "breakdown":     {},
                    "lineup_confirmed": game_lineups[opp_side]["confirmed"],
                    "floor":         proj.get("floor", 5),
                    "floor_confidence": proj.get("floor_confidence", 70),
                    "volatility":    proj.get("volatility", 1.2),
                    "stuff_score":   stuff_score,
                    "location_score": location_score,
                    "matchup_score": matchup_score,
                    "workload_score": workload_score,
                    "stuff_breakdown": stuff_breakdown,
                    "profile_type":  profile_type,
                    "profile_desc":  profile_desc,
                    "is_statcast":   is_statcast,
                    "k_per_ip":      proj.get("k_per_ip"),
                    "projected_ip":  proj.get("projected_ip"),
                }
            else:
                # V1 fallback
                salci, breakdown, missing = compute_salci(
                    p_recent, p_baseline, opp_recent, opp_baseline, weights, games_played
                )
                if salci is None:
                    continue
                base_k9 = (p_baseline or p_recent or {}).get("K9", 9.0)
                proj = project_lines(salci, base_k9)
                result_dict = {
                    "pitcher":       pitcher,
                    "pitcher_id":    pid,
                    "pitcher_hand":  pitcher_hand,
                    "pitcher_k_pct": (p_baseline or p_recent or {}).get("K_percent", 0.22),
                    "team":          team,
                    "opponent":      opp,
                    "opponent_id":   opp_id,
                    "game_pk":       game_pk,
                    "salci":         salci,
                    "salci_grade":   get_rating(salci)[0][0] if salci >= 75 else "C",
                    "expected":      proj["expected"],
                    "k_lines":       proj["lines"],
                    "lines":         proj["lines"],
                    "best_line":     max((k for k, v in proj["lines"].items() if v >= 50), default=5),
                    "breakdown":     breakdown,
                    "lineup_confirmed": game_lineups[opp_side]["confirmed"],
                    "is_statcast":   False,
                    "stuff_score":   None,
                    "location_score": None,
                    "matchup_score": None,
                    "workload_score": None,
                    "profile_type":  "N/A",
                }

            all_pitcher_results.append(result_dict)

            # Store in per-game map for matchup cards
            if game_pk not in game_pitcher_map:
                game_pitcher_map[game_pk] = {}
            game_pitcher_map[game_pk][side] = result_dict

            # ── Hitter processing ────────────────────────────────────────
            if show_hitters:
                opp_lineup_info = game_lineups[opp_side]
                if opp_lineup_info["confirmed"] or not confirmed_only:
                    for player in opp_lineup_info["lineup"]:
                        h_recent = get_hitter_recent_stats(player["id"], 7)
                        h_season = get_hitter_season_stats(player["id"], current_season)
                        if h_recent:
                            h_score = compute_hitter_score(h_recent)
                            if not hot_hitters_only or h_score >= 60:
                                all_hitter_results.append({
                                    "name":        player["name"],
                                    "player_id":   player["id"],
                                    "position":    player["position"],
                                    "batting_order": player["batting_order"],
                                    "bat_side":    player["bat_side"],
                                    "team":        opp,
                                    "vs_pitcher":  pitcher,
                                    "pitcher_hand": pitcher_hand,
                                    "pitcher_k_pct": (p_baseline or p_recent or {}).get("K_percent", 0.22),
                                    "game_pk":     game_pk,
                                    "recent":      h_recent,
                                    "season":      h_season or {},
                                    "score":       h_score,
                                    "lineup_confirmed": opp_lineup_info["confirmed"]
                                })

    progress.empty()

    all_pitcher_results.sort(key=lambda x: x["salci"], reverse=True)
    all_hitter_results.sort(key=lambda x: x["score"], reverse=True)

    confirmed_pitchers = [p for p in all_pitcher_results if p.get("lineup_confirmed")]
    confirmed_hitters  = [h for h in all_hitter_results  if h.get("lineup_confirmed")]

    # Auto-save predictions
    save_predictions_with_reflection(date_str, all_pitcher_results, all_hitter_results)

    # ====================
    # TAB 1: Pitcher Analysis (with Matchup Cards)
    # ====================
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
                        if score >= 95:  return "C+"
                        if score >= 90:  return "C"
                        return "D"
                    else:
                        if score >= 70: return "A"
                        if score >= 60: return "B"
                        if score >= 50: return "C"
                        if score >= 40: return "D"
                        return "F"

                df_pitchers = pd.DataFrame([{
                    "Pitcher":  f"{p['pitcher']} ({p.get('pitcher_hand', 'R')})",
                    "Team":     p["team"],
                    "vs":       p["opponent"],
                    "SALCI":    p["salci"],
                    "Grade":    p.get("salci_grade", "C"),
                    "Stuff":    f"{int(p.get('stuff_score', 100))} ({get_grade_emoji(p.get('stuff_score', 100), True)})" if p.get('stuff_score') else "-",
                    "Match":    f"{int(p.get('matchup_score', 50))} ({get_grade_emoji(p.get('matchup_score', 50), False)})" if p.get('matchup_score') else "-",
                    "Work":     f"{int(p.get('workload_score', 50))} ({get_grade_emoji(p.get('workload_score', 50), False)})" if p.get('workload_score') else "-",
                    "Loc":      f"{int(p.get('location_score', 100))} ({get_grade_emoji(p.get('location_score', 100), True)})" if p.get('location_score') else "-",
                    "Exp K":    p["expected"],
                    "5+":       f"{p['lines'].get(5, '-')}%",
                    "6+":       f"{p['lines'].get(6, '-')}%",
                    "7+":       f"{p['lines'].get(7, '-')}%",
                    "Profile":  p.get("profile_type", "-"),
                    "Source":   "🎯" if p.get("is_statcast") else "📊",
                    "✓":        "✅" if p.get("lineup_confirmed") else "⏳",
                } for p in filtered_pitchers])

                st.dataframe(
                    df_pitchers, use_container_width=True, hide_index=True,
                    column_config={
                        "SALCI": st.column_config.NumberColumn(format="%.1f"),
                        "Exp K": st.column_config.NumberColumn(format="%.1f"),
                    }
                )
                st.markdown("---")
                st.caption("**SALCI v3 Weights:** Stuff (40%) • Matchup (25%) • Workload (20%) • Location (15%)")
                st.caption("**Source:** 🎯 = Real Statcast physics data | 📊 = Proxy metrics from MLB Stats API")

            else:
                # ═══════════════════════════════════════════════════════════
                # 🎴 PITCHER CARDS + ⚔️ MATCHUP CARDS — grouped by game
                # ═══════════════════════════════════════════════════════════
                # Build a sorted list of unique game_pks, ordered by
                # the highest SALCI in that game (most interesting game first).
                game_max_salci: Dict[int, float] = {}
                for p in filtered_pitchers:
                    gk = p["game_pk"]
                    game_max_salci[gk] = max(game_max_salci.get(gk, 0), p["salci"])

                sorted_game_pks = sorted(game_max_salci, key=game_max_salci.get, reverse=True)

                for game_pk in sorted_game_pks:
                    game_pitchers = [p for p in filtered_pitchers if p["game_pk"] == game_pk]
                    if not game_pitchers:
                        continue

                    # Pull away/home from the full pitcher map (not just filtered)
                    gmap = game_pitcher_map.get(game_pk, {})
                    away_result_full = gmap.get("away")
                    home_result_full = gmap.get("home")

                    # Game header
                    away_team = game_pitchers[0].get("opponent", "Away") if game_pitchers[0].get("team") == game_pitchers[0].get("team") else game_pitchers[0].get("team")
                    # Retrieve proper team names from first two pitchers in game
                    teams_in_game = list({p["team"] for p in game_pitchers})
                    header_label  = " @ ".join(reversed(teams_in_game)) if len(teams_in_game) == 2 else teams_in_game[0]

                    # Also pull from the game list for accurate away @ home label
                    game_info = next((g for g in games if g["game_pk"] == game_pk), None)
                    if game_info:
                        header_label = f"{game_info['away_team']} @ {game_info['home_team']}"

                    st.markdown(f"#### 🏟️ {header_label}")

                    for result in game_pitchers:
                        if result.get("lineup_confirmed"):
                            st.markdown("<span class='lineup-confirmed'>✓ Opponent Lineup Confirmed</span>",
                                       unsafe_allow_html=True)
                        else:
                            st.markdown("<span class='lineup-pending'>⏳ Lineup Pending</span>",
                                       unsafe_allow_html=True)
                        render_pitcher_card(result)

                    # ── ⚔️ MATCHUP CARD ────────────────────────────────────
                    # Only render if we have both pitchers for this game
                    if away_result_full and home_result_full:
                        render_matchup_card(
                            away_result=away_result_full,
                            home_result=home_result_full,
                            lineup_status=lineup_status,
                            game_pk=game_pk,
                        )
                    elif len(game_pitchers) == 1:
                        # Only one pitcher passed the SALCI filter — still try to show matchup
                        # by looking up the other side from the full map
                        other_side_result = None
                        for p in all_pitcher_results:
                            if p["game_pk"] == game_pk and p["pitcher_id"] != game_pitchers[0]["pitcher_id"]:
                                other_side_result = p
                                break
                        if other_side_result:
                            # Determine which is home/away
                            if game_info:
                                if game_pitchers[0]["team"] == game_info["away_team"]:
                                    render_matchup_card(game_pitchers[0], other_side_result, lineup_status, game_pk)
                                else:
                                    render_matchup_card(other_side_result, game_pitchers[0], lineup_status, game_pk)

                    st.markdown("---")

            render_compact_summary(all_pitcher_results)

    # ====================
    # TAB 2: Hitter Matchups
    # ====================
    with tab2:
        st.markdown("### 🏏 Hitter Analysis & Matchups")

        if confirmed_only:
            st.info("📋 Showing **CONFIRMED STARTERS ONLY**")

        if not all_hitter_results:
            if confirmed_only:
                st.warning("⏳ No confirmed lineups available yet.")
            else:
                st.info("Enable 'Show Hitter Analysis' in sidebar to see hitter data.")
        else:
            hot_hitters  = [h for h in all_hitter_results if h["score"] >= 70]
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

    # ====================
    # TAB 3: Best Bets
    # ====================
    with tab3:
        st.markdown("### 🎯 Best Bets of the Day")

        if not confirmed_pitchers and not confirmed_hitters:
            st.warning("⏳ No confirmed lineups yet. Best bets appear after lineups are released.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### ⚾ Top Pitcher K Props (Confirmed)")
                top_pitchers_bets = sorted(confirmed_pitchers, key=lambda x: x["salci"], reverse=True)[:5]
                if not top_pitchers_bets:
                    st.info("⏳ Waiting for lineup confirmations.")
                else:
                    for i, p in enumerate(top_pitchers_bets, 1):
                        lines = p.get("k_lines", {}) or p.get("lines", {})
                        best_line_str = ""
                        if lines:
                            eligible = {k: v for k, v in lines.items() if v >= 55}
                            if eligible:
                                bk = max(eligible)
                                best_line_str = f"| {bk}+ @ {eligible[bk]}%"
                        st.markdown(f"""
                        <div style='background: #f0fdf4; padding: 1rem; border-radius: 10px;
                                    margin-bottom: 0.5rem; border-left: 4px solid #22c55e;'>
                            <strong>#{i} {p['pitcher']} ({p.get('pitcher_hand','R')}HP)</strong>
                            — {p['team']} vs {p['opponent']}<br>
                            <span style='color:#15803d;'>SALCI {p['salci']:.1f} | Exp {p['expected']} Ks {best_line_str}</span>
                        </div>""", unsafe_allow_html=True)

            with col2:
                st.markdown("#### 🏏 Hot Hitter Props (Confirmed Starters)")
                top_hitters_bets = [h for h in confirmed_hitters if h["score"] >= 65][:5]
                if not top_hitters_bets:
                    st.info("⏳ Waiting for lineup confirmations.")
                else:
                    for i, h in enumerate(top_hitters_bets, 1):
                        r = h["recent"]
                        h_hand = h.get("bat_side", "R")
                        p_hand = h.get("pitcher_hand", "R")
                        matchup, _ = get_matchup_grade(r.get("k_rate", 0.22), h["pitcher_k_pct"], h_hand, p_hand)
                        st.markdown(f"""
                        <div style='background: #fef3c7; padding: 1rem; border-radius: 10px;
                                    margin-bottom: 0.5rem; border-left: 4px solid #f59e0b;'>
                            <span style='color: #78350f;'><strong>#{i} {h['name']} ({h_hand}HB)</strong>
                            ({h['team']}) — Batting #{h.get('batting_order','?')}</span><br>
                            <span style='color: #78350f;'>vs {h['vs_pitcher']} ({p_hand}HP) | {matchup}</span><br>
                            <span style='color: #78350f;'>L7: <strong>{r.get('avg',0):.3f} AVG</strong>
                            / {r.get('ops',0):.3f} OPS</span>
                        </div>""", unsafe_allow_html=True)

    # ====================
    # TAB 4: Heat Maps
    # ====================
    with tab4:
        st.markdown("### 🔥 Zone Heat Maps")
        if not STATCAST_AVAILABLE:
            st.warning("""
            ⚠️ **Heat Maps require Statcast data**

            To enable:
            1. `pip install pybaseball`
            2. Add `statcast_connector.py` to app folder
            3. Restart app
            """)
        else:
            if not confirmed_pitchers:
                st.info("⏳ Waiting for lineup confirmations to generate heat maps.")
            else:
                selected_pitcher = st.selectbox(
                    "Select Pitcher",
                    [p["pitcher"] for p in confirmed_pitchers],
                    key="heat_map_pitcher"
                )
                pitcher_data = next((p for p in confirmed_pitchers if p["pitcher"] == selected_pitcher), None)
                if pitcher_data:
                    pid = pitcher_data["pitcher_id"]
                    attack_map = get_pitcher_attack_map(pid, 30)
                    if attack_map:
                        st.markdown(f"#### 🎯 {selected_pitcher} — Attack Zones (L30)")
                        grid = attack_map["grid"]
                        zone_matrix = [[0] * 3 for _ in range(3)]
                        for zone in range(1, 10):
                            row, col = divmod(zone - 1, 3)
                            zone_matrix[row][col] = grid.get(zone, {}).get("usage", 0)
                        fig_hm = go.Figure(go.Heatmap(
                            z=zone_matrix,
                            colorscale="RdYlGn",
                            showscale=True,
                            text=[[f"{v:.1f}%" for v in row] for row in zone_matrix],
                            texttemplate="%{text}"
                        ))
                        fig_hm.update_layout(
                            title=f"{selected_pitcher} Attack Zone Usage",
                            height=300,
                            margin=dict(l=20, r=20, t=50, b=20)
                        )
                        st.plotly_chart(fig_hm, use_container_width=True)
                    else:
                        st.info("No heat map data available for this pitcher.")

    # ====================
    # TAB 5: Charts & Share
    # ====================
    with tab5:
        st.markdown("### 📊 Charts & Analytics")
        st.caption("*Charts update as lineups are released.*")
        st.markdown("---")

        if not confirmed_pitchers:
            st.warning("⚠️ No confirmed lineups yet. Charts will appear once lineups are released.")
            st.info("💡 Tip: Click 'Refresh Lineups' in the sidebar to check for updates.")
        else:
            st.success(f"✅ Using {len(confirmed_pitchers)} pitchers with confirmed opponent lineups")

            col_new1, col_new2, col_new3 = st.columns(3)
            with col_new1:
                st.markdown("#### 📈 Expected Ks vs SALCI")
                fig_es = create_expected_vs_salci_chart(confirmed_pitchers)
                if fig_es:
                    st.plotly_chart(fig_es, use_container_width=True)
                else:
                    st.info("Not enough data")
            with col_new2:
                st.markdown("#### 🔥 Top 10 Expected Strikeouts")
                fig_t10 = create_top_10_expected_ks_chart(confirmed_pitchers)
                if fig_t10:
                    st.plotly_chart(fig_t10, use_container_width=True)
                else:
                    st.info("No pitcher data")
            with col_new3:
                st.markdown("#### ⚡ SALCI vs Floor Confidence")
                fig_conf = create_salci_vs_confidence_chart(confirmed_pitchers)
                if fig_conf:
                    st.plotly_chart(fig_conf, use_container_width=True)
                else:
                    st.info("Not enough data")

            st.markdown("---")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### 📈 Pitcher SALCI Rankings")
                fig_p = create_pitcher_comparison_chart(confirmed_pitchers)
                if fig_p:
                    st.plotly_chart(fig_p, use_container_width=True)
            with col2:
                st.markdown("#### 🔥 Hot Hitters (L7)")
                fig_h = create_hitter_hotness_chart(confirmed_hitters)
                if fig_h:
                    st.plotly_chart(fig_h, use_container_width=True)

            st.markdown("---")

            col3, col4 = st.columns(2)
            with col3:
                st.markdown("#### 🎯 K Line Projections")
                fig_k = create_k_projection_chart(confirmed_pitchers)
                if fig_k:
                    st.plotly_chart(fig_k, use_container_width=True)

    # ====================
    # TAB 6: Yesterday
    # ====================
    with tab6:
        st.markdown("### 📈 Yesterday's Reflection")
        yesterday = get_yesterday_date()
        st.caption(f"Reviewing predictions vs actual results for **{yesterday}**")

        if not REFLECTION_AVAILABLE:
            st.warning("⚠️ Reflection module not available. Add `reflection.py` to enable this feature.")
        else:
            try:
                pred_data = load_predictions_for_reflection(yesterday)
                results   = refl.fetch_game_results(yesterday) if hasattr(refl, 'fetch_game_results') else []

                if not pred_data:
                    st.info(f"📭 No predictions found for {yesterday}. Predictions are auto-saved each day you run the app.")
                elif not results:
                    st.info(f"⏳ No game results yet for {yesterday}. Check after games complete.")
                else:
                    reflection = refl.compare_predictions_to_results(pred_data, results) if hasattr(refl, 'compare_predictions_to_results') else {}
                    if reflection:
                        m1, m2, m3 = st.columns(3)
                        with m1:
                            st.metric("Predictions Made", reflection.get("total_predictions", 0))
                        with m2:
                            st.metric("Within 1K", f"{reflection.get('within_1k_pct', 0):.0f}%")
                        with m3:
                            st.metric("Avg Error", f"{reflection.get('avg_error', 0):.1f} Ks")

                        overperf = reflection.get("overperformers", [])
                        underperf = reflection.get("underperformers", [])
                        if overperf or underperf:
                            col_a, col_b = st.columns(2)
                            with col_a:
                                st.markdown("#### 🚀 Overperformers")
                                for p in overperf[:5]:
                                    st.success(f"**{p.get('pitcher_name')}** — {p.get('actual_ks')} K (proj {p.get('expected_ks')})")
                            with col_b:
                                st.markdown("#### 📉 Underperformers")
                                for p in underperf[:5]:
                                    st.error(f"**{p.get('pitcher_name')}** — {p.get('actual_ks')} K (proj {p.get('expected_ks')})")
            except Exception as e:
                st.error(f"Reflection error: {e}")

        # Yesterday's box score hitters
        st.markdown("---")
        st.markdown("#### 🏏 Yesterday's Hot Hitters (Box Score)")
        box_hitters = get_box_score_hitters(yesterday, min_hits=2)
        if box_hitters:
            df_box = pd.DataFrame(box_hitters[:20])
            st.dataframe(df_box, use_container_width=True, hide_index=True)
        else:
            st.info("No box score data available for yesterday.")

    # ====================
    # TAB 7: Model Accuracy
    # ====================
    with tab7:
        st.markdown("### 🎯 Model Accuracy Dashboard")

        if not REFLECTION_AVAILABLE:
            st.warning("⚠️ Reflection module not available.")
        else:
            try:
                accuracy_data = refl.get_rolling_accuracy(7) if hasattr(refl, 'get_rolling_accuracy') else []
                accuracy_30   = refl.get_rolling_accuracy(30) if hasattr(refl, 'get_rolling_accuracy') else []

                if accuracy_data:
                    m1, m2, m3, m4 = st.columns(4)
                    latest = accuracy_data[-1] if accuracy_data else {}
                    with m1:
                        st.metric("7-Day Accuracy", f"{latest.get('accuracy_pct', 0):.1f}%")
                    with m2:
                        avg_30 = sum(d.get('accuracy_pct', 0) for d in accuracy_30) / max(len(accuracy_30), 1)
                        st.metric("30-Day Accuracy", f"{avg_30:.1f}%")
                    with m3:
                        st.metric("Days Tracked", len(accuracy_data))
                    with m4:
                        best = max((d.get('accuracy_pct', 0) for d in accuracy_data), default=0)
                        st.metric("Best Day", f"{best:.1f}%")

                    fig_acc = create_accuracy_chart(accuracy_data)
                    if fig_acc:
                        st.plotly_chart(fig_acc, use_container_width=True)
                else:
                    st.info("📭 No accuracy data yet. Data accumulates as you use the app each day.")
            except Exception as e:
                st.error(f"Accuracy dashboard error: {e}")


if __name__ == "__main__":
    main()
