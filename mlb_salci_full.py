#!/usr/bin/env python3
"""
SALCI v5.2 - Advanced MLB Prediction System
Strikeout Adjusted Lineup Confidence Index

NEW IN v5.2:
- 🎯 Log5 Hit Probability Engine (hit_likelihood.py)
  Per-batter Hit Score (0-100) using Bill James Log5 + Statcast QoC multiplier.
  Displayed in Hitter Matchups tab with per-hitter expandable pipeline breakdown.

INCLUDED FROM v5.1:
- SALCI v3 K-Optimized Weights: Stuff 40%, Matchup 25%, Workload 20%, Location 15%
- Lineup-Level Matchup: Uses individual hitter K% when lineup confirmed
- Arsenal Display: Per-pitch Stuff+ scores on pitcher cards
- Sortable Table View with grades and K-lines
- Model Accuracy Dashboard (7-day rolling)
- Leash Factor in workload calculation
- Unified Reflection System (reflection.py)

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
import json
import os

# ---------------------------------------------------------------------------
# Statcast & Reflection Integration
# ---------------------------------------------------------------------------
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
        PYBASEBALL_AVAILABLE,
    )
    STATCAST_AVAILABLE = PYBASEBALL_AVAILABLE
    SALCI_V3_AVAILABLE = True
except ImportError as e:
    st.warning(f"⚠️ Statcast module not available: {e}")

try:
    import reflection as refl
    REFLECTION_AVAILABLE = True
except ImportError as e:
    st.warning(f"⚠️ Reflection module not available: {e}")

# ---------------------------------------------------------------------------
# Hit Likelihood Integration  ← NEW v5.2
# ---------------------------------------------------------------------------
HIT_LIKELIHOOD_AVAILABLE = False
try:
    from hit_likelihood import calculate_hitter_hit_prob, score_lineup
    HIT_LIKELIHOOD_AVAILABLE = True
except ImportError:
    pass  # Graceful — Hit Score column simply won't appear

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
SALCI_VERSION   = "5.2"
SALCI_BUILD_DATE = "2026-04-11"

# League-average constants — update each season in your Stage 1 nightly job
LEAGUE_AVG_2025 = 0.248

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title=f"SALCI v{SALCI_VERSION} - MLB Predictions",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
.main-header {
    font-size:2.5rem; font-weight:bold; text-align:center;
    background:linear-gradient(90deg,#1e3a5f,#2e5a8f);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:0;
}
.sub-header { text-align:center; color:#666; margin-top:0; margin-bottom:1.5rem; }
.lineup-confirmed {
    background:linear-gradient(135deg,#10b981,#34d399); color:white;
    padding:0.2rem 0.5rem; border-radius:10px; font-size:0.75rem; font-weight:bold;
}
.lineup-pending {
    background:linear-gradient(135deg,#f59e0b,#fbbf24); color:white;
    padding:0.2rem 0.5rem; border-radius:10px; font-size:0.75rem; font-weight:bold;
}
.hot-streak {
    background:linear-gradient(135deg,#ff6b6b,#ffa500); color:white;
    padding:0.3rem 0.6rem; border-radius:15px; font-weight:bold; font-size:0.85rem;
}
.cold-streak {
    background:linear-gradient(135deg,#4a90d9,#67b8de); color:white;
    padding:0.3rem 0.6rem; border-radius:15px; font-weight:bold; font-size:0.85rem;
}
/* Hit Score pill */
.hs-pill {
    display:inline-block; padding:0.25rem 0.7rem; border-radius:12px;
    font-weight:900; font-size:0.85rem; text-align:center; line-height:1.4;
}
.hs-elite   { background:#00C566; color:#fff; }
.hs-fav     { background:#7BCA3E; color:#fff; }
.hs-neutral { background:#F5C518; color:#333; }
.hs-unfav   { background:#FF7A00; color:#fff; }
.hs-poor    { background:#E84040; color:#fff; }
/* Misc */
.elite  { color:#10b981; font-weight:bold; }
.strong { color:#22c55e; font-weight:bold; }
.average{ color:#eab308; font-weight:bold; }
.below  { color:#f97316; font-weight:bold; }
.poor   { color:#ef4444; font-weight:bold; }
.batting-order {
    background:#f0f9ff; border-left:3px solid #3b82f6;
    padding:0.2rem 0.5rem; font-weight:bold; border-radius:3px;
}
.matchup-good    { background-color:#d4edda; color:#155724; font-weight:bold; }
.matchup-neutral { background-color:#fff3cd; color:#856404; font-weight:bold; }
.matchup-bad     { background-color:#f8d7da; color:#721c24; font-weight:bold; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------
WEIGHT_PRESETS = {
    "balanced": {
        "name": "⚖️ Balanced", "desc": "Equal weight to pitcher and matchup",
        "weights": {"K9":0.18,"K_percent":0.18,"K/BB":0.14,"P/IP":0.10,"OppK%":0.22,"OppContact%":0.18},
    },
    "pitcher": {
        "name": "💪 Pitcher Heavy", "desc": "Focus on pitcher's K ability",
        "weights": {"K9":0.28,"K_percent":0.25,"K/BB":0.20,"P/IP":0.12,"OppK%":0.08,"OppContact%":0.07},
    },
    "matchup": {
        "name": "🎯 Matchup Heavy", "desc": "Focus on opponent K tendencies",
        "weights": {"K9":0.12,"K_percent":0.10,"K/BB":0.08,"P/IP":0.08,"OppK%":0.32,"OppContact%":0.30},
    },
}

BOUNDS = {
    "K9":         (6.0, 13.0, True),
    "K_percent":  (0.15, 0.38, True),
    "K/BB":       (1.5, 7.0,  True),
    "P/IP":       (13,  18,   False),
    "OppK%":      (0.18,0.28, True),
    "OppContact%":(0.70,0.85, False),
}

COLORS = {
    "elite":"#10b981","strong":"#3b82f6","average":"#eab308","below":"#f97316","poor":"#ef4444",
    "hot":"#D85A30","cold":"#4a90d9","primary":"#1e3a5f","secondary":"#7F77DD","accent":"#1D9E75",
    "stuff":"#8b5cf6","location":"#06b6d4",
}

# ===========================================================================
# Hit Score helpers  ← NEW v5.2
# ===========================================================================

def _hs_css(score: int) -> str:
    if score >= 75: return "hs-elite"
    if score >= 60: return "hs-fav"
    if score >= 45: return "hs-neutral"
    if score >= 30: return "hs-unfav"
    return "hs-poor"

def _hs_label(score: int) -> str:
    if score >= 75: return "🔥 Elite"
    if score >= 60: return "✅ Favorable"
    if score >= 45: return "⚖️ Neutral"
    if score >= 30: return "⚠️ Unfavorable"
    return "❌ Poor"

def _build_batter_stats_for_log5(hitter: Dict, season: Dict) -> Dict:
    """Build the batter_stats dict that hit_likelihood.calculate_hitter_hit_prob expects."""
    recent = hitter.get("recent", {})
    return {
        "avg":              season.get("avg") or recent.get("avg", LEAGUE_AVG_2025),
        "xba":              hitter.get("xba"),            # None → graceful fallback in hit_likelihood
        "avg_exit_velo":    hitter.get("avg_exit_velo"),
        "avg_launch_angle": hitter.get("avg_launch_angle"),
        "barrel_pct":       hitter.get("barrel_pct"),
        "hard_hit_pct":     hitter.get("hard_hit_pct"),
        "hard_hit_pct_l14": hitter.get("hard_hit_pct_l14"),
        "l7_avg":           recent.get("avg"),             # recent form signal
        "bat_side":         hitter.get("bat_side", "R"),
    }

# ===========================================================================
# Unified storage / reflection helpers
# ===========================================================================

def save_predictions_with_reflection(date_str, all_pitcher_results, all_hitter_results):
    if not REFLECTION_AVAILABLE:
        st.error("❌ Reflection module not available — cannot save predictions")
        return False
    data = {
        "date": date_str, "model_version": SALCI_VERSION,
        "pitchers": [{
            "pitcher_id": p.get("pitcher_id"), "pitcher_name": p.get("pitcher"),
            "team": p.get("team"), "opponent": p.get("opponent"),
            "salci": p.get("salci"), "salci_grade": p.get("salci_grade"),
            "expected": p.get("expected"), "k_lines": p.get("k_lines", {}),
            "stuff_score": p.get("stuff_score"), "location_score": p.get("location_score"),
            "matchup_score": p.get("matchup_score"), "workload_score": p.get("workload_score"),
            "is_statcast": p.get("is_statcast", False), "profile_type": p.get("profile_type"),
            "lineup_confirmed": p.get("lineup_confirmed", False),
        } for p in all_pitcher_results],
        "hitters": [{
            "player_id": h.get("player_id"), "name": h.get("name"),
            "team": h.get("team"), "vs_pitcher": h.get("vs_pitcher"),
            "score": h.get("score"), "hit_prob_score": h.get("hit_prob_score"),
            "lineup_confirmed": h.get("lineup_confirmed", False),
        } for h in all_hitter_results],
    }
    try:
        if refl.save_daily_predictions(date_str, data):
            st.success(f"✅ Predictions saved for {date_str}")
            return True
        st.error("Failed to save predictions")
        return False
    except Exception as e:
        st.error(f"Error saving predictions: {e}")
        return False

def get_yesterday_date():
    return (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")

def get_current_season(date_obj):
    return date_obj.year - 1 if date_obj.month < 3 else date_obj.year

# ===========================================================================
# General helpers
# ===========================================================================

def normalize(val, min_val, max_val, higher_is_better=True):
    norm = np.clip((val - min_val) / (max_val - min_val), 0, 1)
    return norm if higher_is_better else (1 - norm)

def get_blend_weights(games_played):
    if games_played < 3:  return 0.2, 0.8
    if games_played < 7:  return 0.4, 0.6
    if games_played < 15: return 0.6, 0.4
    return 0.8, 0.2

def get_rating(salci):
    if salci >= 75: return "Elite",     "🔥", "elite"
    if salci >= 60: return "Strong",    "✅", "strong"
    if salci >= 45: return "Average",   "➖", "average"
    if salci >= 30: return "Below Avg", "⚠️", "below"
    return "Poor", "❌", "poor"

def get_hitter_rating(score):
    if score >= 80: return "🔥 On Fire",  "hot-streak"
    if score >= 60: return "✅ Hot",       "strong"
    if score >= 40: return "➖ Normal",    "average"
    if score >= 20: return "❄️ Cold",     "cold-streak"
    return "🥶 Ice Cold", "poor"

def get_salci_color(salci):
    if salci >= 75: return COLORS["elite"]
    if salci >= 60: return COLORS["strong"]
    if salci >= 45: return COLORS["average"]
    if salci >= 30: return COLORS["below"]
    return COLORS["poor"]

def get_matchup_grade(hitter_k_rate, pitcher_k_pct, hitter_hand, pitcher_hand):
    platoon_adv = 10 if (hitter_hand != pitcher_hand) else -5
    k_matchup = 0
    if hitter_k_rate < 0.18 and pitcher_k_pct > 0.28:   k_matchup =  15
    elif hitter_k_rate > 0.28 and pitcher_k_pct > 0.28: k_matchup = -15
    elif hitter_k_rate < 0.20:  k_matchup =  10
    elif hitter_k_rate > 0.30:  k_matchup = -10
    total = 50 + platoon_adv + k_matchup
    if total >= 65: return "🟢 Favorable", "matchup-good"
    if total >= 45: return "🟡 Neutral",   "matchup-neutral"
    return "🔴 Tough", "matchup-bad"

# ===========================================================================
# API — Teams / Schedule
# ===========================================================================

@st.cache_data(ttl=300)
def get_team_id_lookup():
    try:
        res = requests.get("https://statsapi.mlb.com/api/v1/teams?sportId=1", timeout=10)
        return {t["name"]: t["id"] for t in res.json().get("teams", [])}
    except: return {}

@st.cache_data(ttl=60)
def get_games_by_date(date_str):
    url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
           f"&hydrate=probablePitcher,lineups,team")
    try:
        data = requests.get(url, timeout=10).json()
        if not data.get("dates"): return []
        games = []
        for g in data["dates"][0]["games"]:
            gi = {
                "game_pk": g.get("gamePk"),
                "game_time": g.get("gameDate"),
                "status": g.get("status", {}).get("abstractGameState", ""),
                "detailed_status": g.get("status", {}).get("detailedState", ""),
                "home_team": g["teams"]["home"]["team"]["name"],
                "away_team": g["teams"]["away"]["team"]["name"],
                "home_team_id": g["teams"]["home"]["team"]["id"],
                "away_team_id": g["teams"]["away"]["team"]["id"],
                "lineups_available": False,
            }
            for side in ["home", "away"]:
                pp = g["teams"][side].get("probablePitcher")
                if pp:
                    gi[f"{side}_pitcher"]      = pp.get("fullName", "TBD")
                    gi[f"{side}_pid"]          = pp.get("id")
                    gi[f"{side}_pitcher_hand"] = pp.get("pitchHand", {}).get("code", "R")
                else:
                    gi[f"{side}_pitcher"]      = "TBD"
                    gi[f"{side}_pid"]          = None
                    gi[f"{side}_pitcher_hand"] = "R"
            games.append(gi)
        return games
    except Exception as e:
        st.error(f"Error fetching games: {e}")
        return []

@st.cache_data(ttl=60)
def get_game_boxscore(game_pk):
    try:
        return requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live", timeout=15
        ).json()
    except: return None

def get_confirmed_lineup(game_pk, team_side):
    data = get_game_boxscore(game_pk)
    if not data: return [], False
    try:
        game_data   = data.get("gameData", {})
        boxscore    = data.get("liveData", {}).get("boxscore", {})
        team_data   = boxscore.get("teams", {}).get(team_side, {})
        batting_order = team_data.get("battingOrder", [])
        if not batting_order: return [], False
        players = team_data.get("players", {})
        lineup  = []
        for i, pid_ in enumerate(batting_order):
            key  = f"ID{pid_}"
            info = players.get(key, {})
            fp   = game_data.get("players", {}).get(key, {})
            lineup.append({
                "id":            pid_,
                "name":          info.get("person", {}).get("fullName", "Unknown"),
                "position":      info.get("position", {}).get("abbreviation", ""),
                "batting_order": i + 1,
                "bat_side":      fp.get("batSide", {}).get("code", "R"),
            })
        return lineup, len(lineup) >= 9
    except Exception as e:
        st.warning(f"Error parsing lineup: {e}")
        return [], False

# ===========================================================================
# API — Pitchers
# ===========================================================================

@st.cache_data(ttl=300)
def get_player_season_stats(player_id, season):
    url = (f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
           f"?stats=season&season={season}&group=pitching")
    try:
        data = requests.get(url, timeout=10).json()
        if data.get("stats") and data["stats"][0].get("splits"):
            return data["stats"][0]["splits"][0]["stat"]
    except: pass
    return None

@st.cache_data(ttl=300)
def get_recent_pitcher_stats(player_id, num_games=7):
    url = (f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
           f"?stats=gameLog&group=pitching")
    try:
        data = requests.get(url, timeout=10).json()
        if not data.get("stats") or not data["stats"][0].get("splits"): return None
        games = sorted(data["stats"][0]["splits"],
                       key=lambda x: x.get("date", ""), reverse=True)[:num_games]
        if not games: return None
        tot = {"ip":0,"so":0,"bb":0,"tbf":0,"np":0,"hits":0,"games":len(games)}
        for g in games:
            s = g.get("stat", {})
            ip_raw = str(s.get("inningsPitched","0.0"))
            parts  = ip_raw.split(".")
            ip = int(parts[0]) + int(parts[1])/3 if "." in ip_raw else float(ip_raw)
            tot["ip"]   += ip
            tot["so"]   += int(s.get("strikeOuts", 0))
            tot["bb"]   += int(s.get("baseOnBalls", 0))
            tot["tbf"]  += int(s.get("battersFaced", 0))
            tot["np"]   += int(s.get("numberOfPitches", 0))
            tot["hits"] += int(s.get("hits", 0))
        if tot["ip"] == 0 or tot["tbf"] == 0: return None
        ab_proxy = max(1, tot["tbf"] - tot["bb"])
        return {
            "K9":              tot["so"] / tot["ip"] * 9,
            "K_percent":       tot["so"] / tot["tbf"],
            "K/BB":            tot["so"] / tot["bb"] if tot["bb"] > 0 else tot["so"] * 2,
            "P/IP":            tot["np"] / tot["ip"],
            "games_sampled":   tot["games"],
            "total_so":        tot["so"],
            "total_ip":        tot["ip"],
            "avg_ip_per_start":tot["ip"] / tot["games"],
            "avg_against":     tot["hits"] / ab_proxy,  # for Log5
        }
    except: pass
    return None

def parse_season_stats(stats):
    if not stats: return {}
    ip_raw = str(stats.get("inningsPitched","0.0"))
    parts  = ip_raw.split(".")
    ip = int(parts[0]) + int(parts[1])/3 if "." in ip_raw else float(ip_raw)
    if ip == 0: return {}
    so   = int(stats.get("strikeOuts", 0))
    bb   = int(stats.get("baseOnBalls", 0))
    tbf  = int(stats.get("battersFaced", 1))
    np_t = int(stats.get("numberOfPitches", 0))
    hits = int(stats.get("hits", 0))
    ab_proxy = max(1, tbf - bb)
    return {
        "K9":          so / ip * 9,
        "K_percent":   so / tbf,
        "K/BB":        so / bb if bb > 0 else so * 2,
        "P/IP":        np_t / ip if np_t > 0 else 15.0,
        "ERA":         float(stats.get("era", 0)),
        "WHIP":        float(stats.get("whip", 0)),
        "avg_against": hits / ab_proxy,  # for Log5
    }

# ===========================================================================
# API — Hitters
# ===========================================================================

@st.cache_data(ttl=300)
def get_hitter_recent_stats(player_id, num_games=7):
    url = (f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
           f"?stats=gameLog&group=hitting")
    try:
        data = requests.get(url, timeout=10).json()
        if not data.get("stats") or not data["stats"][0].get("splits"): return None
        games = sorted(data["stats"][0]["splits"],
                       key=lambda x: x.get("date",""), reverse=True)[:num_games]
        if not games: return None
        tot = {"ab":0,"hits":0,"doubles":0,"triples":0,"hr":0,
               "rbi":0,"bb":0,"so":0,"sb":0,"games":len(games)}
        gr_list = []
        for g in games:
            s  = g.get("stat",{})
            ab = int(s.get("atBats",0))
            h  = int(s.get("hits",0))
            tot["ab"]      += ab
            tot["hits"]    += h
            tot["doubles"] += int(s.get("doubles",0))
            tot["triples"] += int(s.get("triples",0))
            tot["hr"]      += int(s.get("homeRuns",0))
            tot["rbi"]     += int(s.get("rbi",0))
            tot["bb"]      += int(s.get("baseOnBalls",0))
            tot["so"]      += int(s.get("strikeOuts",0))
            tot["sb"]      += int(s.get("stolenBases",0))
            if ab > 0: gr_list.append({"date":g.get("date"),"hits":h,"ab":ab})
        if tot["ab"] == 0: return None
        avg = tot["hits"] / tot["ab"]
        slg = (tot["hits"] + tot["doubles"] + 2*tot["triples"] + 3*tot["hr"]) / tot["ab"]
        obp = (tot["hits"]+tot["bb"])/(tot["ab"]+tot["bb"]) if (tot["ab"]+tot["bb"])>0 else 0
        ops = obp + slg
        hit_streak = hitless_streak = 0
        for gr in gr_list:
            if gr["hits"] > 0: hit_streak += 1
            else: break
        for gr in gr_list:
            if gr["hits"] == 0: hitless_streak += 1
            else: break
        return {
            "avg":avg,"obp":obp,"slg":slg,"ops":ops,
            "k_rate":tot["so"]/tot["ab"],"hr":tot["hr"],"rbi":tot["rbi"],
            "sb":tot["sb"],"hits":tot["hits"],"ab":tot["ab"],"so":tot["so"],
            "games":tot["games"],"hit_streak":hit_streak,"hitless_streak":hitless_streak,
        }
    except: pass
    return None

@st.cache_data(ttl=3600)
def get_hitter_season_stats(player_id, season):
    url = (f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
           f"?stats=season&season={season}&group=hitting")
    try:
        data = requests.get(url, timeout=10).json()
        if data.get("stats") and data["stats"][0].get("splits"):
            s  = data["stats"][0]["splits"][0]["stat"]
            ab = int(s.get("atBats", 1))
            return {
                "avg":float(s.get("avg",0)),"obp":float(s.get("obp",0)),
                "slg":float(s.get("slg",0)),"ops":float(s.get("ops",0)),
                "hr":int(s.get("homeRuns",0)),"rbi":int(s.get("rbi",0)),
                "k_rate":int(s.get("strikeOuts",0))/ab if ab>0 else 0,
                "ab":ab,
            }
    except: pass
    return None

@st.cache_data(ttl=300)
def get_team_batting_stats(team_id, days=14):
    end_date   = datetime.today()
    start_date = end_date - timedelta(days=days)
    url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}"
           f"&startDate={start_date.strftime('%Y-%m-%d')}&endDate={end_date.strftime('%Y-%m-%d')}")
    try:
        dates = requests.get(url, timeout=10).json().get("dates", [])
        game_ids = [g["gamePk"] for d in dates for g in d.get("games", [])]
        tot = {"pa":0,"so":0,"hits":0,"ab":0}
        for gid in game_ids[:7]:
            try:
                box = requests.get(f"https://statsapi.mlb.com/api/v1/game/{gid}/boxscore",
                                   timeout=10).json().get("teams",{})
                for side in ["home","away"]:
                    if box.get(side,{}).get("team",{}).get("id") == team_id:
                        st2 = box[side].get("teamStats",{}).get("batting",{})
                        tot["so"]   += int(st2.get("strikeOuts",0))
                        tot["pa"]   += int(st2.get("plateAppearances",0))
                        tot["hits"] += int(st2.get("hits",0))
                        tot["ab"]   += int(st2.get("atBats",0))
                        break
            except: continue
        if tot["pa"] == 0: return None
        return {
            "OppK%":      tot["so"]/tot["pa"],
            "OppContact%":tot["hits"]/tot["ab"] if tot["ab"]>0 else 0.25,
        }
    except: pass
    return None

@st.cache_data(ttl=3600)
def get_team_season_batting(team_id, season):
    url = (f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
           f"?stats=season&season={season}&group=hitting")
    try:
        data = requests.get(url, timeout=10).json()
        if data.get("stats") and data["stats"][0].get("splits"):
            s  = data["stats"][0]["splits"][0]["stat"]
            pa = int(s.get("plateAppearances",1))
            so = int(s.get("strikeOuts",0))
            ab = int(s.get("atBats",1))
            return {"OppK%":so/pa,"OppContact%":int(s.get("hits",0))/ab}
    except: pass
    return None

@st.cache_data(ttl=3600)
def get_yesterday_hitter_leaders(date_str, min_hits=2):
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}",
            timeout=15).json()
        if not data.get("dates"): return []
        hitters = []
        for game in data["dates"][0].get("games",[]):
            game_pk = game.get("gamePk")
            if game.get("status",{}).get("abstractGameState","") != "Final": continue
            try:
                box = requests.get(
                    f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore",
                    timeout=15).json()
                for side in ["home","away"]:
                    td = box.get("teams",{}).get(side,{})
                    tn = td.get("team",{}).get("name","Unknown")
                    for bid in td.get("batters",[]):
                        pk = f"ID{bid}"
                        pd_ = td.get("players",{}).get(pk,{})
                        st2 = pd_.get("stats",{}).get("batting",{})
                        if st2:
                            h = int(st2.get("hits",0))
                            if h >= min_hits or int(st2.get("homeRuns",0)) >= 1:
                                hitters.append({
                                    "player_name":pd_.get("person",{}).get("fullName","Unknown"),
                                    "team":tn,"hits":h,
                                    "ab":int(st2.get("atBats",0)),
                                    "hr":int(st2.get("homeRuns",0)),
                                    "rbi":int(st2.get("rbi",0)),
                                    "so":int(st2.get("strikeOuts",0)),
                                })
            except: continue
        hitters.sort(key=lambda x:(x["hits"],x["hr"],x["rbi"]),reverse=True)
        return hitters
    except: return []

# ===========================================================================
# Scoring helpers
# ===========================================================================

def compute_salci(p_recent, p_baseline, opp_recent, opp_baseline, weights, games_played=5):
    rw, bw = get_blend_weights(games_played)
    ps = {}
    for m in ["K9","K_percent","K/BB","P/IP"]:
        rv = (p_recent   or {}).get(m)
        bv = (p_baseline or {}).get(m)
        if rv is not None and bv is not None: ps[m] = rw*rv + bw*bv
        elif rv is not None: ps[m] = rv
        elif bv is not None: ps[m] = bv
    os_ = {}
    for m in ["OppK%","OppContact%"]:
        rv = (opp_recent   or {}).get(m)
        bv = (opp_baseline or {}).get(m)
        if rv is not None and bv is not None: os_[m] = rw*rv + bw*bv
        elif rv is not None: os_[m] = rv
        elif bv is not None: os_[m] = bv
    score = total_w = 0.0
    breakdown = {}; missing = []
    for metric, weight in weights.items():
        val = {**ps,**os_}.get(metric)
        if val is not None:
            bn = BOUNDS.get(metric)
            if bn:
                nv = normalize(val, bn[0], bn[1], bn[2])
                score += weight*nv; total_w += weight
                breakdown[metric] = {"raw":val,"norm":nv,"weight":weight}
        elif weight > 0.05: missing.append(metric)
    if total_w == 0: return None, {}, missing
    return round((score/total_w)*100, 1), breakdown, missing

def compute_hitter_score(recent, baseline=None):
    if not recent: return 50
    score = weights_total = 0
    if recent.get("avg"):
        score += normalize(recent["avg"],0.180,0.380,True)*100*0.25; weights_total += 0.25
    if recent.get("ops"):
        score += normalize(recent["ops"],0.550,1.100,True)*100*0.25; weights_total += 0.25
    if recent.get("k_rate") is not None:
        score += normalize(recent["k_rate"],0.35,0.10,False)*100*0.15; weights_total += 0.15
    base = (score/weights_total*100) if weights_total > 0 else 50
    bonus = 0
    if recent.get("hit_streak",0) >= 3:    bonus += min(recent["hit_streak"]*3, 15)
    if recent.get("hitless_streak",0) >= 2: bonus -= min(recent["hitless_streak"]*5, 20)
    if recent.get("hr",0) >= 1:            bonus += min(recent["hr"]*5, 15)
    return max(0, min(100, (base+bonus)*1.1))

def project_lines(salci, base_k9=9.0):
    expected = (base_k9*5.5/9)*(0.7+(salci/100)*0.6)
    lines = {}
    for k in range(3,9):
        diff = k - expected
        if diff <= -2:   prob = 92
        elif diff <= -1: prob = 80
        elif diff <= 0:  prob = 65
        elif diff <= 1:  prob = 45
        elif diff <= 2:  prob = 28
        else:            prob = 15
        prob = max(5, min(95, prob + (salci-50)/10))
        lines[k] = round(prob)
    return {"expected":round(expected,1),"lines":lines}

# ===========================================================================
# Chart helpers (unchanged from v5.1)
# ===========================================================================

def create_pitcher_comparison_chart(pr):
    if not pr: return None
    top = sorted(pr,key=lambda x:x["salci"],reverse=True)[:10][::-1]
    names  = [f"{p['pitcher'].split()[-1]} ({p.get('pitcher_hand','R')})" for p in top]
    scores = [p["salci"] for p in top]
    fig = go.Figure(go.Bar(
        y=names,x=scores,orientation='h',
        marker_color=[get_salci_color(s) for s in scores],
        text=[str(s) for s in scores],textposition='outside',
    ))
    fig.add_vline(x=75,line_dash="dash",line_color="#10b981",line_width=2)
    fig.add_vline(x=60,line_dash="dot", line_color="#3b82f6",line_width=1)
    fig.update_layout(
        title="Today's Top SALCI Pitchers",xaxis_title="SALCI Score",
        xaxis=dict(range=[0,100]),height=400,
        margin=dict(l=100,r=50,t=80,b=60),
        plot_bgcolor='rgba(0,0,0,0)',paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig

def create_hitter_hotness_chart(hr_):
    if not hr_: return None
    top = sorted(hr_,key=lambda x:x["score"],reverse=True)[:8]
    names = [f"{h['name'].split()[-1]} ({h.get('bat_side','R')})" for h in top]
    fig = go.Figure()
    fig.add_trace(go.Bar(name='AVG (L7)',x=names,
        y=[h["recent"].get("avg",0) for h in top],marker_color=COLORS["hot"],
        text=[f".{int(a*1000):03d}" for a in [h["recent"].get("avg",0) for h in top]],
        textposition='outside'))
    fig.add_trace(go.Bar(name='OPS (L7)',x=names,
        y=[h["recent"].get("ops",0) for h in top],marker_color=COLORS["secondary"],
        text=[f"{o:.3f}" for o in [h["recent"].get("ops",0) for h in top]],
        textposition='outside'))
    fig.update_layout(title="Hottest Hitters (Last 7 Games)",barmode='group',height=350,
        margin=dict(l=50,r=50,t=80,b=80),
        plot_bgcolor='rgba(0,0,0,0)',paper_bgcolor='rgba(0,0,0,0)',)
    return fig

def create_salci_breakdown_chart():
    fig = go.Figure(data=[go.Pie(
        labels=['Stuff (40%)','Matchup (25%)','Workload (20%)','Location (15%)'],
        values=[40,25,20,15],hole=0.6,
        marker_colors=['#8b5cf6','#3b82f6','#eab308','#06b6d4'],
        textinfo='label+percent',textposition='outside',
    )])
    fig.update_layout(title="SALCI v3 Weight Distribution",height=350,
        margin=dict(l=20,r=20,t=60,b=60),showlegend=False,
        annotations=[dict(text="SALCI<br>v3",x=0.5,y=0.5,font=dict(size=14),showarrow=False)])
    return fig

def create_expected_vs_salci_chart(pitchers):
    if len(pitchers) < 3: return None
    df = pd.DataFrame([{"Pitcher":p.get("pitcher",""),"SALCI":p.get("salci",0),
        "Expected Ks":p.get("expected",0),"Floor":p.get("floor",0),
        "Profile":p.get("profile_type","Balanced")} for p in pitchers])
    fig = px.scatter(df,x="SALCI",y="Expected Ks",hover_name="Pitcher",
        color="Profile",size="Floor",title="Expected Strikeouts vs SALCI Score")
    fig.update_layout(height=420,template="plotly_dark")
    return fig

def create_top_10_expected_ks_chart(pitchers):
    if not pitchers: return None
    df = pd.DataFrame([{"Pitcher":p.get("pitcher",""),"Expected Ks":p.get("expected",0),
        "At Least":f"{p.get('floor',0)}+ Ks","Confidence":p.get("floor_confidence",0)}
        for p in pitchers]).nlargest(10,"Expected Ks")
    fig = go.Figure(go.Bar(y=df["Pitcher"],x=df["Expected Ks"],
        text=df["At Least"]+" ("+df["Confidence"].astype(str)+"%)",
        textposition="inside",orientation="h",marker=dict(color="#10b981",opacity=0.85)))
    fig.update_layout(title="Top 10 Projected Strikeouts",xaxis_title="Expected Strikeouts",
        height=500,template="plotly_dark",yaxis=dict(autorange="reversed"))
    return fig

def create_salci_vs_confidence_chart(pitchers):
    if len(pitchers) < 3: return None
    df = pd.DataFrame([{"Pitcher":p.get("pitcher","")[:15],"SALCI":p.get("salci",0),
        "Floor Confidence":p.get("floor_confidence",0),"Expected Ks":p.get("expected",0)}
        for p in pitchers])
    fig = px.scatter(df,x="SALCI",y="Floor Confidence",hover_name="Pitcher",
        size="Expected Ks",title="SALCI Score vs Floor Confidence (%)")
    fig.update_layout(height=420,template="plotly_dark")
    return fig

def create_matchup_scatter(hr_):
    if not hr_ or len(hr_) < 3: return None
    names  = [f"{h['name'].split()[-1]} ({h.get('bat_side','R')})" for h in hr_]
    k_rates = [h["recent"].get("k_rate",0.22)*100 for h in hr_]
    avgs    = [h["recent"].get("avg",0.250) for h in hr_]
    colors  = [get_salci_color(h["score"]) if h["score"] >= 50 else COLORS["cold"] for h in hr_]
    fig = go.Figure(go.Scatter(
        x=k_rates,y=avgs,mode='markers+text',
        marker=dict(size=12,color=colors,line=dict(width=1,color='white')),
        text=names,textposition='top center',textfont=dict(size=8),
    ))
    fig.add_hline(y=0.270,line_dash="dash",line_color="#ccc",line_width=1)
    fig.add_vline(x=22,   line_dash="dash",line_color="#ccc",line_width=1)
    fig.update_layout(title="Hitter Profile: K% vs AVG (L7)",
        xaxis_title="K%",yaxis_title="AVG",height=400,
        plot_bgcolor='rgba(0,0,0,0)',paper_bgcolor='rgba(0,0,0,0)')
    return fig

def create_stuff_location_chart(pr_):
    if not pr_: return None
    filtered = [p for p in pr_ if p.get("stuff_score") and p.get("location_score")]
    if len(filtered) < 3: return None
    names  = [f"{p['pitcher'].split()[-1]} ({p.get('pitcher_hand','R')})" for p in filtered]
    fig = go.Figure(go.Scatter(
        x=[p["stuff_score"] for p in filtered],
        y=[p["location_score"] for p in filtered],
        mode='markers+text',
        marker=dict(size=[max(8,p["salci"]/5) for p in filtered],
                    color=[get_salci_color(p["salci"]) for p in filtered],
                    line=dict(width=1,color='white')),
        text=names,textposition='top center',textfont=dict(size=9),
    ))
    fig.add_hline(y=60,line_dash="dash",line_color="#ccc")
    fig.add_vline(x=60,line_dash="dash",line_color="#ccc")
    fig.update_layout(title="Pitcher Profiles: Stuff vs Location",
        xaxis_title="Stuff Score",yaxis_title="Location Score",
        xaxis=dict(range=[20,100]),yaxis=dict(range=[20,100]),
        height=450,plot_bgcolor='rgba(0,0,0,0)',paper_bgcolor='rgba(0,0,0,0)')
    return fig

def create_k_projection_chart(pr_):
    if not pr_: return None
    top = sorted(pr_,key=lambda x:x["salci"],reverse=True)[:5]
    names  = [f"{p['pitcher'].split()[-1]} ({p.get('pitcher_hand','R')})" for p in top]
    kld    = []
    for p in top:
        kd = p.get("k_lines",{}) or p.get("lines",{})
        kld.append([kd.get(k,50) for k in sorted(kd.keys())[:4]] if kd else [50,40,30,20])
    fig = go.Figure()
    first_kl = sorted((top[0].get("k_lines",{}) or {}).keys()) if top else [5,6,7,8]
    if not first_kl: first_kl = [5,6,7,8]
    for idx, label in enumerate([f"{k}+" for k in first_kl[:4]]):
        fig.add_trace(go.Bar(
            name=label,x=names,
            y=[row[idx] if idx < len(row) else 0 for row in kld],
            text=[f"{row[idx]}%" if idx < len(row) else "" for row in kld],
            textposition='outside',
        ))
    fig.update_layout(title="K Line Probabilities (Top Pitchers)",
        yaxis=dict(range=[0,100]),barmode='group',height=350,
        plot_bgcolor='rgba(0,0,0,0)',paper_bgcolor='rgba(0,0,0,0)')
    return fig

# ===========================================================================
# Pitcher card helpers
# ===========================================================================

def render_arsenal_display(stuff_breakdown):
    if not stuff_breakdown: return
    pitch_names = {
        'FF':('4-Seam','#ef4444'),'SI':('Sinker','#f97316'),'FC':('Cutter','#eab308'),
        'SL':('Slider','#22c55e'),'ST':('Sweeper','#14b8a6'),'CU':('Curve','#3b82f6'),
        'KC':('KnuckleC','#6366f1'),'CH':('Change','#a855f7'),'FS':('Splitter','#ec4899'),
        'SV':('Slurve','#06b6d4'),
    }
    pitches = sorted(
        [{"type":pt,"stuff":d.get("stuff_plus",100),"velo":d.get("velocity",0),
          "usage":d.get("usage_pct",0),"whiff":d.get("observed_whiff_pct",0)}
         for pt,d in stuff_breakdown.items()
         if isinstance(d,dict) and d.get("usage_pct",0) >= 5],
        key=lambda x:x["usage"],reverse=True,
    )
    if not pitches: return
    st.markdown("<div style='padding:8px;background:rgba(0,0,0,0.03);border-radius:8px;'>", unsafe_allow_html=True)
    st.markdown("<div style='font-size:0.7rem;color:#666;margin-bottom:4px;'>🎪 ARSENAL</div>", unsafe_allow_html=True)
    cols = st.columns(min(len(pitches),5))
    for i, p in enumerate(pitches[:5]):
        with cols[i]:
            name, color = pitch_names.get(p["type"],(p["type"],'#6b7280'))
            s = p["stuff"]
            sc = "#10b981" if s>=115 else "#22c55e" if s>=105 else "#6b7280" if s>=95 else "#ef4444"
            bg = f"rgba(16,185,129,.1)" if s>=115 else f"rgba(34,197,94,.1)" if s>=105 else f"rgba(107,114,128,.1)" if s>=95 else f"rgba(239,68,68,.1)"
            st.markdown(f"""
            <div style='background:{bg};border:1px solid {color};border-radius:6px;padding:6px;'>
                <div style='font-size:.75rem;font-weight:bold;color:{color};'>{name}</div>
                <div style='font-size:.65rem;color:#666;'>{p['velo']:.0f} mph · {p['usage']:.0f}%</div>
                <div style='font-size:.85rem;font-weight:bold;color:{sc};'>Stuff+ {int(s)}</div>
                <div style='font-size:.6rem;color:#888;'>Whiff {p['whiff']:.0f}%</div>
            </div>""", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

def render_pitcher_card(result, show_stuff_location=True):
    salci = result["salci"]
    _, emoji, css_class = get_rating(salci)
    with st.container():
        c1,c2,c3 = st.columns([2,1,2])
        with c1:
            ph = result.get("pitcher_hand","R")
            st.markdown(f"### {result['pitcher']} ({ph}HP)")
            st.markdown(f"**{result['team']}** vs {result['opponent']}")
            if result.get("profile_type") not in (None,"BALANCED","N/A"):
                em = {"ELITE":"⚡","STUFF-DOMINANT":"🔥","LOCATION-DOMINANT":"🎯",
                      "BALANCED-PLUS":"💪","ONE-TOOL":"📊","LIMITED":"⚠️"}.get(result["profile_type"],"❓")
                st.markdown(f"<span style='font-size:.85rem;'>{em} {result['profile_type']}</span>", unsafe_allow_html=True)
            badge = "🎯 Statcast" if result.get("is_statcast") else "📊 Stats API"
            bc    = "#10b981" if result.get("is_statcast") else "#6b7280"
            st.markdown(f"<span style='font-size:.7rem;background:{bc};color:white;padding:2px 6px;border-radius:4px;'>{badge}</span>", unsafe_allow_html=True)
        with c2:
            grade = result.get("salci_grade","C")
            st.markdown(f"<div style='text-align:center;'>"
                        f"<span style='font-size:2.5rem;font-weight:bold;'>{salci}</span><br>"
                        f"<span class='{css_class}'>{emoji} Grade {grade}</span></div>", unsafe_allow_html=True)
        with c3:
            exp = result.get("expected","--")
            fl  = result.get("floor"); fc = result.get("floor_confidence")
            st.markdown(f"**Expected Ks:** {exp}")
            if fl is not None and fc is not None:
                st.markdown(f"**At Least:** <span style='color:#10b981;font-weight:bold;'>{fl} Ks</span> ({fc}% confidence)", unsafe_allow_html=True)
            kl = result.get("k_lines",{}) or result.get("lines",{})
            if kl:
                cols = st.columns(4)
                for i,(kv,prob) in enumerate(sorted(kl.items())[:4]):
                    with cols[i]:
                        col = "#22c55e" if prob>=70 else "#eab308" if prob>=50 else "#ef4444"
                        st.markdown(f"<div style='text-align:center;'><small>{kv}+</small><br>"
                                    f"<span style='color:{col};font-weight:bold;'>{prob}%</span></div>", unsafe_allow_html=True)
        if show_stuff_location:
            st_s = result.get("stuff_score"); lo_s = result.get("location_score")
            ma_s = result.get("matchup_score"); wl_s = result.get("workload_score")
            if any([st_s,lo_s,ma_s,wl_s]):
                cols4 = st.columns(4)
                def cc(sc,i100=True):
                    if sc is None: return "#d1d5db"
                    if i100: return "#10b981" if sc>=115 else "#22c55e" if sc>=105 else "#eab308" if sc>=95 else "#ef4444"
                    return "#10b981" if sc>=65 else "#22c55e" if sc>=50 else "#eab308" if sc>=35 else "#ef4444"
                for col_, lbl, sc, i100, pct_fn in [
                    (cols4[0],"⚡ STUFF (40%)",   st_s, True,  lambda v: min(100,max(0,(v-70)*2))),
                    (cols4[1],"🎯 MATCHUP (25%)", ma_s, False, lambda v: v),
                    (cols4[2],"📊 WORKLOAD (20%)",wl_s, False, lambda v: v),
                    (cols4[3],"📍 LOCATION (15%)",lo_s, True,  lambda v: min(100,max(0,(v-70)*2))),
                ]:
                    with col_:
                        if sc:
                            c_ = cc(sc,i100); pct = pct_fn(sc)
                            st.markdown(f"""
                            <div style='text-align:center;'>
                                <div style='font-size:.7rem;color:#666;'>{lbl}</div>
                                <div style='font-size:1.2rem;font-weight:bold;color:{c_};'>{int(sc)}</div>
                                <div style='background:#e5e7eb;border-radius:4px;height:6px;margin-top:2px;'>
                                    <div style='width:{pct}%;background:{c_};border-radius:4px;height:100%;'></div>
                                </div>
                            </div>""", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<div style='text-align:center;color:#aaa;font-size:.8rem;'>{lbl.split()[0]}<br>--</div>", unsafe_allow_html=True)
                sb = result.get("stuff_breakdown",{})
                if sb and result.get("is_statcast"):
                    render_arsenal_display(sb)
        st.progress(min(salci/100,1.0))
        st.markdown("---")

def render_compact_summary(pr_):
    if not pr_: return
    sorted_p = sorted(pr_,key=lambda x:x.get("salci",0),reverse=True)
    st.markdown("---")
    st.markdown("### 📋 Quick Copy SALCI Summary")
    lines = []
    for p in sorted_p:
        kl = p.get("k_lines",{})
        line_str = " | ".join([f"{k}+ @ {v}%" for k,v in list(kl.items())[:3]]) or "No K-lines"
        lines.append(f"**{p.get('pitcher','?')}**\n#SALCI: {p.get('salci',0)}\nExpected: {p.get('expected','--')}\nKs {line_str}")
    full = "\n\n".join(lines)
    st.markdown(f"<div style='background:rgba(255,255,255,.05);padding:16px;border-radius:8px;font-family:monospace;white-space:pre-wrap;'>{full}</div>", unsafe_allow_html=True)
    st.caption("👇 Triple-click below to copy")
    st.code(full, language=None)

# ===========================================================================
# Hitter card  ← UPDATED v5.2: Hit Score column added
# ===========================================================================

def render_hitter_card(hitter: Dict, show_batting_order: bool = True):
    """Render hitter card with stats, matchup grade, and Log5 Hit Score."""
    score   = hitter.get("score", 50)
    recent  = hitter.get("recent", {})
    season  = hitter.get("season", {})
    hs      = hitter.get("hit_prob_score")

    matchup_grade, matchup_css = get_matchup_grade(
        recent.get("k_rate", 0.22),
        hitter.get("pitcher_k_pct", 0.22),
        hitter.get("bat_side", "R"),
        hitter.get("pitcher_hand", "R"),
    )

    if HIT_LIKELIHOOD_AVAILABLE and hs is not None:
        col1, col2, col3, col4, col5, col6 = st.columns([2.5, 1.2, 1.2, 1.2, 1.0, 1.0])
    else:
        col1, col2, col3, col4, col5 = st.columns([2.5, 1.2, 1.2, 1.2, 1])
        col6 = None

    with col1:
        badge = (f"<span class='batting-order'>#{hitter['batting_order']}</span> "
                 if show_batting_order and hitter.get("batting_order") else "")
        st.markdown(f"{badge}**{hitter['name']}** ({hitter.get('position','')})", unsafe_allow_html=True)
        st.markdown(
            f"<span style='font-size:.8rem;color:#555;'>"
            f"{hitter.get('bat_side','R')}HB · {season.get('ab',0)} AB (2025)</span>",
            unsafe_allow_html=True)
        if recent.get("hit_streak",0) >= 3:
            st.markdown(f"<span class='hot-streak'>🔥 {recent['hit_streak']}-game hit streak</span>", unsafe_allow_html=True)
        elif recent.get("hitless_streak",0) >= 3:
            st.markdown(f"<span class='cold-streak'>❄️ {recent['hitless_streak']}-game hitless</span>", unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div style='text-align:center;'>
            <div style='font-size:.7rem;color:#666;'>AVG</div>
            <div style='font-size:1rem;font-weight:bold;'>{recent.get('avg',0):.3f}</div>
            <div style='font-size:.7rem;color:#888;'>L7</div>
            <div style='font-size:.85rem;color:#666;'>{season.get('avg',0):.3f}</div>
            <div style='font-size:.65rem;color:#aaa;'>Season</div>
        </div>""", unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div style='text-align:center;'>
            <div style='font-size:.7rem;color:#666;'>OPS</div>
            <div style='font-size:1rem;font-weight:bold;'>{recent.get('ops',0):.3f}</div>
            <div style='font-size:.7rem;color:#888;'>L7</div>
            <div style='font-size:.85rem;color:#666;'>{season.get('ops',0):.3f}</div>
            <div style='font-size:.65rem;color:#aaa;'>Season</div>
        </div>""", unsafe_allow_html=True)

    with col4:
        kr = recent.get("k_rate",0)*100
        kc = "#10b981" if kr<20 else "#eab308" if kr<28 else "#ef4444"
        st.markdown(f"""
        <div style='text-align:center;'>
            <div style='font-size:.7rem;color:#666;'>K% (L7)</div>
            <div style='font-size:1rem;font-weight:bold;color:{kc};'>{kr:.1f}%</div>
        </div>""", unsafe_allow_html=True)

    with col5:
        st.markdown(
            f"<div class='{matchup_css}' style='padding:.5rem;border-radius:5px;text-align:center;font-size:.8rem;'>"
            f"{matchup_grade}</div>",
            unsafe_allow_html=True)

    # Hit Score pill  ← NEW v5.2
    if col6 is not None and hs is not None:
        with col6:
            css_cls = _hs_css(hs)
            lbl     = _hs_label(hs)
            st.markdown(
                f"<div class='hs-pill {css_cls}'>"
                f"<div style='font-size:.6rem;'>HIT SCORE</div>"
                f"<div style='font-size:1.15rem;'>{hs}</div>"
                f"<div style='font-size:.6rem;'>{lbl}</div>"
                f"</div>",
                unsafe_allow_html=True)


# ===========================================================================
# Hit Score breakdown expander  ← NEW v5.2
# ===========================================================================

def render_hit_score_breakdown(hitter: Dict):
    """
    Expandable section showing the full Log5 pipeline for one hitter.
    Placed directly below render_hitter_card() in Tab 2.
    """
    hs   = hitter.get("hit_prob_score")
    bd   = hitter.get("hit_prob_breakdown", {})
    name = hitter.get("name", "Unknown")
    if hs is None or not bd:
        return

    with st.expander(f"📊 {name} — Hit Score {hs}/100 · full breakdown"):
        # ── Pipeline summary strip ──────────────────────────────────────────
        pipe = bd.get("pipeline", {})
        pc1, pc2, pc3, pc4 = st.columns(4)
        pc1.metric("Log5 base probability",  f"{pipe.get('log5_prob',0):.1%}")
        pc2.metric("After contact quality",  f"{pipe.get('after_contact_adj',0):.1%}")
        pc3.metric("After context adj",      f"{pipe.get('after_context_adj',0):.1%}")
        pc4.metric("Final Hit Score",         f"{hs} / 100")

        # ── Layer 1: Log5 ───────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### 🧮 Layer 1 — Log5 Base Probability")
        l5 = bd.get("log5", {})
        lc1, lc2, lc3 = st.columns(3)
        lc1.metric("Batter AVG (season)",        f"{l5.get('batter_avg',0):.3f}")
        lc2.metric("Pitcher AVG against",        f"{l5.get('pitcher_avg',0):.3f}")
        lc3.metric("League AVG",                 f"{l5.get('league_avg',0):.3f}")
        st.caption("Bill James Log5 formula — P(hit) = B(1−P) / [B(1−P) + P(1−B)]")

        # ── Layer 2: Contact quality ────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### ⚡ Layer 2 — Statcast Quality-of-Contact Multiplier")
        cq  = bd.get("contact_quality", {})
        ev  = cq.get("exit_velo", {})
        la  = cq.get("launch_angle", {})
        bar = cq.get("barrel_rate", {})
        xba = cq.get("xba_spread", {})

        qc1, qc2, qc3, qc4, qc5 = st.columns(5)
        qc1.metric("Exit Velo",     f"{ev.get('value','—')} mph",
                   help="Sigmoid-scaled vs league mean · weight 35%")
        qc2.metric("Launch Angle",  f"{la.get('value','—')}°",
                   help="Sweet-spot 8°–32° · weight 25%")
        qc3.metric("Barrel %",      f"{bar.get('value','—')}%",
                   help="Linear 0–20% scale · weight 25%")
        qc4.metric("xBA − AVG",     f"{xba.get('spread',0):+.3f}",
                   help="Positive = batter owed hits by regression · weight 15%")
        qc5.metric("QoC multiplier", f"×{cq.get('multiplier',1.0):.2f}")

        if la.get("sweet_spot"):
            st.success(f"✅ Launch angle {la.get('value','?')}° is inside the 8°–32° sweet-spot window")
        else:
            st.warning(f"⚠️ Launch angle {la.get('value','?')}° is outside the 8°–32° sweet-spot window")

        if ev.get("value") == round(88.5, 1) and bar.get("value") == round(7.5, 1):
            st.caption("ℹ️ Statcast fields not yet available — using league-average defaults for QoC layer."
                       " Add `avg_exit_velo`, `barrel_pct`, etc. to the nightly Stage 1 payload for a sharper signal.")

        # ── Layer 3: Context ────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### 🧩 Layer 3 — Contextual Adjustments")
        ctx = bd.get("contextual", {})
        rf  = ctx.get("recent_form", {})
        pl  = ctx.get("platoon", {})
        hh  = ctx.get("hard_hit_l14", {})
        xc1, xc2, xc3 = st.columns(3)
        xc1.metric(
            "Recent form (L7 AVG)",
            f"{rf.get('adj',0):+.4f}",
            delta=f"L7: {rf.get('l7_avg','?'):.3f} vs season: {rf.get('season','?'):.3f}"
                  if "l7_avg" in rf else rf.get("note","—"),
        )
        xc2.metric(
            "Platoon edge",
            f"{pl.get('adj',0):+.4f}",
            delta=("Same-hand — slight disadvantage" if pl.get("same_hand")
                   else "Opposite-hand — slight advantage"),
        )
        xc3.metric(
            "Hard-hit L14",
            f"{hh.get('adj',0):+.4f}",
            delta=(f"{hh.get('value','?')}% hard-hit rate (L14)"
                   if hh.get("value") else hh.get("note","—")),
        )
        st.caption(f"Total contextual adjustment: {ctx.get('total_adj',0):+.4f} probability points")
        st.caption("Anchoring: league-average matchup → Hit Score 50 | maximum hit probability → 100")


# ===========================================================================
# Main app
# ===========================================================================

def main():
    # ── data_loader import and Pro gate MUST be first — sidebar uses is_pro() ──
    from data_loader import (
        load_todays_data, get_pitchers, source_banner,
        confirmed_lineup_count, strip_pro_fields, check_pro_password,
        PRO_FIELDS,
    )

    def is_pro() -> bool:
        return check_pro_password(st.session_state.get("pro_password", ""))

    st.markdown(f"<h1 class='main-header'>⚾ SALCI v{SALCI_VERSION}</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='sub-header'>Advanced MLB Prediction System · Stuff + Location + Hit Probability</p>",
        unsafe_allow_html=True)

    # ── Sidebar ─────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Settings")
        if STATCAST_AVAILABLE:    st.success("🎯 Statcast: Connected")
        else:                     st.info("📊 Statcast: Using proxy metrics")
        if REFLECTION_AVAILABLE:  st.success("💾 Reflection: Connected")
        else:                     st.info("⚠️ Reflection: Not available")
        if HIT_LIKELIHOOD_AVAILABLE: st.success("🎯 Hit Probability: Active")
        else:                        st.warning("⚠️ hit_likelihood.py not found")
        st.markdown("---")
        selected_date = st.date_input(
            "📅 Select Date", value=datetime.today(),
            min_value=datetime.today()-timedelta(days=7),
            max_value=datetime.today()+timedelta(days=7),
        )
        st.markdown("---")
        preset_key = st.selectbox(
            "Pitcher Model Weights", options=list(WEIGHT_PRESETS.keys()),
            format_func=lambda x: WEIGHT_PRESETS[x]["name"])
        st.caption(WEIGHT_PRESETS[preset_key]["desc"])
        st.markdown("---")
        st.subheader("Filters")
        min_salci       = st.slider("Min Pitcher SALCI", 0, 80, 0, 5)
        show_hitters    = st.checkbox("Show Hitter Analysis", value=True)
        confirmed_only  = st.checkbox("Confirmed Lineups Only", value=True)
        hot_hitters_only= st.checkbox("Hot Hitters Only (Score ≥ 60)", value=False)
        st.markdown("---")
        if st.button("🔄 Refresh Lineups", use_container_width=True):
            st.cache_data.clear(); st.rerun()
        st.caption("💡 Lineups typically post 1-2 hours before game time.")
        st.markdown("---")
        with st.expander(f"📊 About SALCI v{SALCI_VERSION}"):
            st.markdown(f"""
**SALCI v{SALCI_VERSION}** — Strikeout Adjusted Lineup Confidence Index

**New in v5.2 — Log5 Hit Probability:**
- Layer 1: Bill James Log5 (batter AVG vs pitcher AVG-against vs league)
- Layer 2: Statcast QoC multiplier ×0.70–1.30 (exit velo 35%, barrels 25%, launch angle 25%, xBA spread 15%)
- Layer 3: Contextual ±5 pts (L7 form, platoon, hard-hit L14)
- Full expandable breakdown per hitter in the Hitter Matchups tab

**SALCI v3 Weights:** Stuff 40% · Matchup 25% · Workload 20% · Location 15%
            """)


        st.markdown("---")
        st.markdown("### 🔒 SALCI Pro")
        if is_pro():
            st.success("🔓 Pro access active")
        else:
            st.text_input("Patreon password", type="password",
                          key="pro_password",
                          placeholder="Enter your password")
            st.caption("[Get Pro access →](https://patreon.com/YOURPAGE)")
            st.caption("Pro unlocks: K-lines, floor, Stuff+, arsenal, matchup scores")

    # ── Setup ────────────────────────────────────────────────────────────────
    date_str       = selected_date.strftime("%Y-%m-%d")
    weights        = WEIGHT_PRESETS[preset_key]["weights"]
    current_season = get_current_season(selected_date)

    tab1,tab2,tab3,tab4,tab5,tab6,tab7 = st.tabs([
        "⚾ Pitcher Analysis","🏏 Hitter Matchups","🎯 Best Bets",
        "🔥 Heat Maps","📊 Charts & Share","📈 Yesterday","🎯 Model Accuracy",
    ])

    with st.spinner("🔍 Fetching games and lineups..."):
        games = get_games_by_date(date_str)
    if not games:
        st.warning(f"No games found for {date_str}"); return
    st.success(f"Found **{len(games)} games** for {selected_date.strftime('%A, %B %d, %Y')}")

    lineup_status: Dict = {}
    for game in games:
        gpk = game["game_pk"]
        hl, hc = get_confirmed_lineup(gpk, "home")
        al, ac = get_confirmed_lineup(gpk, "away")
        lineup_status[gpk] = {
            "home": {"lineup": hl, "confirmed": hc},
            "away": {"lineup": al, "confirmed": ac},
        }

    confirmed_count = sum(1 for g in games
        if lineup_status[g["game_pk"]]["home"]["confirmed"]
        or lineup_status[g["game_pk"]]["away"]["confirmed"])
    if confirmed_count == 0:
        st.warning("⏳ No lineups confirmed yet.")
    else:
        st.info(f"✅ **{confirmed_count} games** have confirmed lineups")

    # =========================================================
    # DATA LOADING — Smart JSON loader (pre-computed files)
    # Falls back to live computation if no JSON found today
    # =========================================================
    precomputed_data, data_source = load_todays_data(date_str)

    all_pitcher_results: List[Dict] = []
    all_hitter_results:  List[Dict] = []

    if precomputed_data is not None:
        # ── Fast path: read pre-computed JSON ─────────────────────────
        all_pitcher_results = get_pitchers(precomputed_data)

        banner_msg, banner_level = source_banner(precomputed_data, data_source)
        if banner_level == "success":
            st.success(banner_msg)
        elif banner_level == "info":
            st.info(banner_msg)
        else:
            st.warning(banner_msg)

        # Pull hitter results from stored lineup data (if final file has them)
        if show_hitters:
            for p in all_pitcher_results:
                if not p.get("lineup_confirmed") or not p.get("lineup"):
                    continue
                for player in p.get("lineup", []):
                    h_recent = get_hitter_recent_stats(player["id"], 7)
                    h_season = get_hitter_season_stats(player["id"], current_season)
                    if h_recent:
                        h_score = compute_hitter_score(h_recent)
                        if not hot_hitters_only or h_score >= 60:
                            entry: Dict = {
                                "name":          player["name"],
                                "player_id":     player["id"],
                                "position":      player.get("position", ""),
                                "batting_order": player.get("batting_order"),
                                "bat_side":      player.get("bat_side", "R"),
                                "team":          p.get("opponent", ""),
                                "vs_pitcher":    p.get("pitcher", p.get("pitcher_name", "")),
                                "pitcher_hand":  p.get("pitcher_hand", "R"),
                                "pitcher_k_pct": p.get("pitcher_k_pct", 0.22),
                                "pitcher_avg_against": p.get("pitcher_avg_against", LEAGUE_AVG_2025),
                                "game_pk":       p.get("game_pk"),
                                "recent":        h_recent,
                                "season":        h_season or {},
                                "score":         h_score,
                                "lineup_confirmed": p.get("lineup_confirmed", False),
                                "xba": None, "avg_exit_velo": None,
                                "avg_launch_angle": None, "barrel_pct": None,
                                "hard_hit_pct": None, "hard_hit_pct_l14": None,
                                "hit_prob_score": None, "hit_prob_breakdown": {},
                            }
                            if HIT_LIKELIHOOD_AVAILABLE:
                                try:
                                    bs = _build_batter_stats_for_log5(entry, h_season or {})
                                    ps = {"avg_against": p.get("pitcher_avg_against", LEAGUE_AVG_2025),
                                          "pitcher_hand": p.get("pitcher_hand", "R")}
                                    hs_val, hs_bd = calculate_hitter_hit_prob(bs, ps, league_avg=LEAGUE_AVG_2025)
                                    entry["hit_prob_score"]     = hs_val
                                    entry["hit_prob_breakdown"] = hs_bd
                                except Exception:
                                    pass
                            all_hitter_results.append(entry)

    else:
        # ── Slow path: live computation (no JSON found for today) ──────
        st.warning("⚠️ No pre-computed data found for today — running live calculations. This may take 30–60 seconds.")

        progress = st.progress(0)

        for i, game in enumerate(games):
            progress.progress((i+1)/len(games))
            gpk  = game["game_pk"]
            glu  = lineup_status[gpk]

            for side in ["home","away"]:
                pitcher      = game.get(f"{side}_pitcher","TBD")
                pid          = game.get(f"{side}_pid")
                pitcher_hand = game.get(f"{side}_pitcher_hand","R")
                team         = game.get(f"{side}_team")
                opp          = game.get("away_team" if side=="home" else "home_team")
                opp_id       = game.get("away_team_id" if side=="home" else "home_team_id")
                opp_side     = "away" if side=="home" else "home"
                if not pid or pitcher=="TBD": continue

                p_recent    = get_recent_pitcher_stats(pid, 7)
                p_baseline  = parse_season_stats(get_player_season_stats(pid, current_season))
                opp_recent  = get_team_batting_stats(opp_id, 14)
                opp_baseline= get_team_season_batting(opp_id, current_season)
                games_played= (p_recent or {}).get("games_sampled",0)

                r_aa = (p_recent   or {}).get("avg_against", LEAGUE_AVG_2025)
                b_aa = (p_baseline or {}).get("avg_against", LEAGUE_AVG_2025)
                blended_aa = r_aa*0.6 + b_aa*0.4

                cs = {}
                if p_recent:   cs.update(p_recent)
                if p_baseline:
                    for k in ["K9","K_percent","K/BB","P/IP"]:
                        if k in p_baseline and k in cs: cs[k] = cs[k]*0.6+p_baseline[k]*0.4
                        elif k in p_baseline:           cs[k] = p_baseline[k]
                opp_s = {}
                if opp_recent:   opp_s.update(opp_recent)
                if opp_baseline:
                    for k in ["OppK%","OppContact%"]:
                        if k in opp_baseline and k in opp_s: opp_s[k] = opp_s[k]*0.6+opp_baseline[k]*0.4
                        elif k in opp_baseline:              opp_s[k] = opp_baseline[k]

                stuff_sc=loc_sc=match_sc=work_sc=None; sb_={}; pt_="BALANCED"; pdc_=""; sg_="C"; isc=False; sv3=None

                if SALCI_V3_AVAILABLE and STATCAST_AVAILABLE:
                    try:
                        prof = get_pitcher_statcast_profile(pid, days=30)
                        if prof:
                            stuff_sc=prof.get("stuff_plus",100); loc_sc=prof.get("location_plus",100)
                            sb_=prof.get("by_pitch_type",{}); pt_=prof.get("profile_type","BALANCED")
                            pdc_=prof.get("profile_description","")
                            avg_ip=(p_recent or {}).get("avg_ip_per_start",5.5)
                            work_sc,_=calculate_workload_score_v3({"P/IP":cs.get("P/IP",16.0),"avg_ip":avg_ip})
                            ol_info=glu[opp_side]; lhs=None
                            if ol_info.get("confirmed") and ol_info.get("lineup"):
                                lhs=[]
                                for pl_ in ol_info["lineup"]:
                                    hr_=get_hitter_recent_stats(pl_["id"],7)
                                    if hr_: lhs.append({"name":pl_["name"],"k_rate":hr_.get("k_rate",0.22),
                                        "zone_contact_pct":1-hr_.get("k_rate",0.22)*0.8,"bat_side":pl_.get("bat_side","R")})
                            match_sc,_=calculate_matchup_score_v3(opp_s,lhs,pitcher_hand)
                            sv3=calculate_salci_v3(stuff_sc,loc_sc,match_sc,work_sc)
                            sg_=sv3.get("grade","C"); isc=True
                    except Exception as e:
                        st.warning(f"SALCI v3 error for {pitcher}: {e}")

                if sv3:
                    salci=sv3["salci"]
                    proj=calculate_expected_ks_v3(sv3,(p_recent or {}).get("avg_ip_per_start",5.5))
                    all_pitcher_results.append({
                        "pitcher":pitcher,"pitcher_name":pitcher,"pitcher_id":pid,
                        "pitcher_hand":pitcher_hand,
                        "pitcher_k_pct":(p_baseline or p_recent or {}).get("K_percent",0.22),
                        "pitcher_avg_against":blended_aa,
                        "team":team,"opponent":opp,"opponent_id":opp_id,"game_pk":gpk,
                        "salci":salci,"salci_grade":sg_,
                        "expected":proj.get("expected_ks",proj.get("expected",5)),
                        "k_lines":proj.get("k_lines",{}),"lines":proj.get("k_lines",{}),
                        "best_line":proj.get("best_line",5),"breakdown":{},
                        "lineup_confirmed":glu[opp_side]["confirmed"],
                        "floor":proj.get("floor",5),"floor_confidence":proj.get("floor_confidence",70),
                        "volatility":proj.get("volatility",1.2),
                        "stuff_score":stuff_sc,"location_score":loc_sc,
                        "matchup_score":match_sc,"workload_score":work_sc,
                        "stuff_breakdown":sb_,"profile_type":pt_,"profile_desc":pdc_,
                        "is_statcast":isc,"k_per_ip":proj.get("k_per_ip"),
                        "projected_ip":proj.get("projected_ip"),
                    })
                else:
                    salci,bd_,_=compute_salci(p_recent,p_baseline,opp_recent,opp_baseline,weights,games_played)
                    if salci is not None:
                        base_k9=(p_baseline or p_recent or {}).get("K9",9.0)
                        proj=project_lines(salci,base_k9)
                        lines_dict = proj.get("lines", {})
                        # Safe best_line — fallback to highest k if no line >= 50
                        above_50 = [k for k,v in lines_dict.items() if v >= 50]
                        safe_best = max(above_50) if above_50 else (max(lines_dict.keys()) if lines_dict else 5)
                        # Grade from SALCI score
                        if salci >= 75:   _grade = "A"
                        elif salci >= 60: _grade = "B"
                        elif salci >= 45: _grade = "C"
                        elif salci >= 30: _grade = "D"
                        else:             _grade = "F"
                        all_pitcher_results.append({
                            "pitcher":pitcher,"pitcher_name":pitcher,"pitcher_id":pid,
                            "pitcher_hand":pitcher_hand,
                            "pitcher_k_pct":(p_baseline or p_recent or {}).get("K_percent",0.22),
                            "pitcher_avg_against":blended_aa,
                            "team":team,"opponent":opp,"opponent_id":opp_id,"game_pk":gpk,
                            "salci":salci,"salci_grade":_grade,
                            "expected":proj["expected"],"k_lines":lines_dict,"lines":lines_dict,
                            "best_line":safe_best,
                            "breakdown":bd_,"lineup_confirmed":glu[opp_side]["confirmed"],
                            "is_statcast":False,"stuff_score":None,"location_score":None,"profile_type":"N/A",
                        })

                if show_hitters:
                    ol_info = glu[opp_side]
                    if ol_info["confirmed"] or not confirmed_only:
                        for pl_ in ol_info["lineup"]:
                            hr_ = get_hitter_recent_stats(pl_["id"],7)
                            hs_ = get_hitter_season_stats(pl_["id"],current_season)
                            if hr_:
                                h_score = compute_hitter_score(hr_)
                                if not hot_hitters_only or h_score >= 60:
                                    entry: Dict = {
                                        "name":pl_["name"],"player_id":pl_["id"],
                                        "position":pl_["position"],"batting_order":pl_["batting_order"],
                                        "bat_side":pl_["bat_side"],"team":opp,"vs_pitcher":pitcher,
                                        "pitcher_hand":pitcher_hand,
                                        "pitcher_k_pct":(p_baseline or p_recent or {}).get("K_percent",0.22),
                                        "pitcher_avg_against":blended_aa,"game_pk":gpk,
                                        "recent":hr_,"season":hs_ or {},"score":h_score,
                                        "lineup_confirmed":ol_info["confirmed"],
                                        "xba":None,"avg_exit_velo":None,"avg_launch_angle":None,
                                        "barrel_pct":None,"hard_hit_pct":None,"hard_hit_pct_l14":None,
                                        "hit_prob_score":None,"hit_prob_breakdown":{},
                                    }
                                    if HIT_LIKELIHOOD_AVAILABLE:
                                        try:
                                            bs=_build_batter_stats_for_log5(entry,hs_ or {})
                                            ps={"avg_against":blended_aa,"pitcher_hand":pitcher_hand}
                                            hs_val,hs_bd=calculate_hitter_hit_prob(bs,ps,league_avg=LEAGUE_AVG_2025)
                                            entry["hit_prob_score"]=hs_val; entry["hit_prob_breakdown"]=hs_bd
                                        except Exception: pass
                                    all_hitter_results.append(entry)

        progress.empty()
    all_pitcher_results.sort(key=lambda x:x["salci"],reverse=True)
    # ── Apply Pro gate to pitcher data ───────────────────────────────
    _pro_user = is_pro()
    if not _pro_user:
        all_pitcher_results = [strip_pro_fields(p) for p in all_pitcher_results]

    all_hitter_results.sort(key=lambda x:x["score"],reverse=True)

    # =========================================================
    # TAB 1: Pitcher Analysis
    # =========================================================
    with tab1:
        st.markdown("### 🎯 Pitcher Strikeout Predictions (SALCI v3)")
        fp = [p for p in all_pitcher_results if p["salci"]>=min_salci]
        if not fp:
            st.info("No pitchers match your filters.")
        else:
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total Pitchers",len(fp))
            c2.metric("🔥 Elite (A)",  len([p for p in fp if p["salci"]>=75]))
            c3.metric("✅ Strong (B)", len([p for p in fp if 60<=p["salci"]<75]))
            c4.metric("📋 Confirmed",  len([p for p in fp if p.get("lineup_confirmed")]))
            st.markdown("---")
            view_mode = st.radio("View Mode",["📊 Component Table","🎴 Pitcher Cards"],horizontal=True,index=0)
            if view_mode=="📊 Component Table":
                def gg(sc,i=True):
                    if i: return "A+" if sc>=115 else "A" if sc>=110 else "B+" if sc>=105 else "B" if sc>=100 else "C+" if sc>=95 else "C" if sc>=90 else "D"
                    return "A" if sc>=70 else "B" if sc>=60 else "C" if sc>=50 else "D" if sc>=40 else "F"
                df_p = pd.DataFrame([{
                    "Pitcher":f"{p['pitcher']} ({p.get('pitcher_hand','R')})",
                    "Team":p["team"],"vs":p["opponent"],"SALCI":p["salci"],"Grade":p.get("salci_grade","C"),
                    "Stuff":f"{int(p.get('stuff_score',100))} ({gg(p.get('stuff_score',100),True)})" if p.get("stuff_score") else "-",
                    "Match":f"{int(p.get('matchup_score',50))} ({gg(p.get('matchup_score',50),False)})" if p.get("matchup_score") else "-",
                    "Work": f"{int(p.get('workload_score',50))} ({gg(p.get('workload_score',50),False)})" if p.get("workload_score") else "-",
                    "Loc":  f"{int(p.get('location_score',100))} ({gg(p.get('location_score',100),True)})" if p.get("location_score") else "-",
                    "Exp K":p["expected"],
                    "5+":f"{p['lines'].get(5,'-')}%","6+":f"{p['lines'].get(6,'-')}%","7+":f"{p['lines'].get(7,'-')}%",
                    "Profile":p.get("profile_type","-"),
                    "Src":"🎯" if p.get("is_statcast") else "📊",
                    "✓":"✅" if p.get("lineup_confirmed") else "⏳",
                } for p in fp])
                st.dataframe(df_p,use_container_width=True,hide_index=True,
                    column_config={"SALCI":st.column_config.NumberColumn(format="%.1f"),
                                   "Exp K":st.column_config.NumberColumn(format="%.1f")})
            else:
                for result in fp:
                    badge = ("<span class='lineup-confirmed'>✓ Opponent Lineup Confirmed</span>"
                             if result.get("lineup_confirmed")
                             else "<span class='lineup-pending'>⏳ Lineup Pending</span>")
                    st.markdown(badge, unsafe_allow_html=True)
                    render_pitcher_card(result)
            render_compact_summary(all_pitcher_results)

    # =========================================================
    # TAB 2: Hitter Matchups  ← UPDATED v5.2
    # =========================================================
    with tab2:
        st.markdown("### 🏏 Hitter Analysis & Matchups")

        if HIT_LIKELIHOOD_AVAILABLE:
            st.info(
                "🎯 **Log5 Hit Scores active** — each hitter shows a 0–100 Hit Score. "
                "Expand any row for the full probability pipeline breakdown."
            )
        else:
            st.warning(
                "⚠️ `hit_likelihood.py` not found — Hit Scores unavailable. "
                "Place the file alongside `mlb_salci_full.py` and restart."
            )

        if confirmed_only:
            st.info("📋 Showing **CONFIRMED STARTERS ONLY**")

        if not all_hitter_results:
            if confirmed_only:
                st.warning("⏳ No confirmed lineups yet.")
            else:
                st.info("Enable 'Show Hitter Analysis' in the sidebar.")
        else:
            hot_h  = [h for h in all_hitter_results if h["score"]>=70]
            cold_h = [h for h in all_hitter_results if h["score"]<=30]

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("#### 🔥 Hottest Hitters")
                if hot_h:
                    for h in hot_h[:8]:
                        render_hitter_card(h, show_batting_order=True)
                        render_hit_score_breakdown(h)          # ← NEW v5.2
                        st.markdown("")
                else:
                    st.info("No hot hitters in confirmed lineups yet.")

            with col2:
                st.markdown("#### ❄️ Coldest Hitters (Fade Candidates)")
                if cold_h:
                    for h in cold_h[:8]:
                        render_hitter_card(h, show_batting_order=True)
                        render_hit_score_breakdown(h)          # ← NEW v5.2
                        st.markdown("")
                else:
                    st.info("No cold hitters in confirmed lineups yet.")

            # ── All starters table ───────────────────────────────────────────
            st.markdown("---")
            st.markdown("#### 📊 All Confirmed Starters")
            rows = []
            for h in all_hitter_results:
                row = {
                    "Order":      f"#{h['batting_order']}" if h.get("batting_order") else "-",
                    "Player":     h["name"],
                    "Bats":       h.get("bat_side","R"),
                    "AB":         h.get("season",{}).get("ab",0),
                    "Team":       h["team"],
                    "Pos":        h["position"],
                    "vs Pitcher": h["vs_pitcher"],
                    "P Hand":     h.get("pitcher_hand","R"),
                    "AVG (L7)":   f"{h['recent'].get('avg',0):.3f}",
                    "OPS (L7)":   f"{h['recent'].get('ops',0):.3f}",
                    "K% (L7)":    f"{h['recent'].get('k_rate',0)*100:.1f}%",
                    "Confirmed":  "✅" if h.get("lineup_confirmed") else "⏳",
                }
                if HIT_LIKELIHOOD_AVAILABLE:
                    hs = h.get("hit_prob_score")
                    row["Hit Score"] = f"{hs}  {_hs_label(hs)}" if hs is not None else "—"
                rows.append(row)
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # ── Full breakdown section sorted by Hit Score ───────────────────
            if HIT_LIKELIHOOD_AVAILABLE and all_hitter_results:
                st.markdown("---")
                st.markdown("#### 🔍 Full Hit Score Breakdown — All Starters")
                st.caption("Sorted highest Hit Score → lowest. Expand any row to see the Log5 pipeline.")
                sorted_hs = sorted(
                    [h for h in all_hitter_results if h.get("hit_prob_score") is not None],
                    key=lambda x: x["hit_prob_score"], reverse=True,
                )
                for h in sorted_hs:
                    render_hit_score_breakdown(h)

    # =========================================================
    # TAB 3: Best Bets
    # =========================================================
    with tab3:
        st.markdown("### 🎯 Today's Best Bets")
        conf_h = [h for h in all_hitter_results if h.get("lineup_confirmed")]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### ⚾ Top Pitcher K Props")
            top_p = [p for p in all_pitcher_results if p["salci"]>=60][:5]
            if not top_p: st.info("No elite pitcher picks available.")
            else:
                for i,p in enumerate(top_p,1):
                    _,emoji,_=get_rating(p["salci"])
                    lb="✅" if p.get("lineup_confirmed") else "⏳"
                    ph=p.get("pitcher_hand","R")
                    st.markdown(f"""
                    <div style='background:#e0f2fe;padding:1rem;border-radius:10px;
                                margin-bottom:.5rem;border-left:4px solid #3b82f6;'>
                        <strong>#{i} {p['pitcher']} ({ph}HP)</strong> ({p['team']} vs {p['opponent']}) {lb}<br>
                        {emoji} SALCI: {p['salci']}<br>
                        Expected: <strong>{p['expected']} Ks</strong><br>
                        5+ @ {p['lines'].get(5,'?')}% | 6+ @ {p['lines'].get(6,'?')}% | 7+ @ {p['lines'].get(7,'?')}%
                    </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown("#### 🏏 Hot Hitter Props")
            if HIT_LIKELIHOOD_AVAILABLE:
                top_h = sorted(
                    [h for h in conf_h if (h.get("hit_prob_score") or 0) >= 55],
                    key=lambda x:x.get("hit_prob_score",0), reverse=True)[:5]
            else:
                top_h = [h for h in conf_h if h["score"]>=65][:5]
            if not top_h: st.info("⏳ Waiting for lineup confirmations.")
            else:
                for i,h in enumerate(top_h,1):
                    r=h["recent"]; hh_=h.get("bat_side","R"); ph_=h.get("pitcher_hand","R")
                    mg,_=get_matchup_grade(r.get("k_rate",0.22),h["pitcher_k_pct"],hh_,ph_)
                    hs_str=(f"Hit Score: <strong>{h.get('hit_prob_score')}</strong> {_hs_label(h.get('hit_prob_score',50))}<br>"
                            if HIT_LIKELIHOOD_AVAILABLE and h.get("hit_prob_score") else "")
                    st.markdown(f"""
                    <div style='background:#fef3c7;padding:1rem;border-radius:10px;
                                margin-bottom:.5rem;border-left:4px solid #f59e0b;'>
                        <strong>#{i} {h['name']} ({hh_}HB)</strong> ({h['team']}) — Batting #{h.get('batting_order','?')}<br>
                        vs {h['vs_pitcher']} ({ph_}HP) | {mg}<br>
                        {hs_str}L7: <strong>{r.get('avg',0):.3f} AVG</strong> / {r.get('ops',0):.3f} OPS
                    </div>""", unsafe_allow_html=True)

    # =========================================================
    # TAB 4: Heat Maps
    # =========================================================
    with tab4:
        st.markdown("### 🔥 Zone Heat Maps")
        if not STATCAST_AVAILABLE:
            st.warning("⚠️ Heat Maps require Statcast data. `pip install pybaseball` and restart.")
        else:
            cp2, ch2 = st.columns(2)
            with cp2:
                st.markdown("#### 🎯 Pitcher Attack Map")
                if all_pitcher_results:
                    p_opts = {f"{p['pitcher']} ({p['team']})":p for p in all_pitcher_results}
                    sel_p  = st.selectbox("Select Pitcher",list(p_opts.keys()),key="hm_p")
                    if sel_p:
                        sp = p_opts[sel_p]
                        with st.spinner("Loading..."):
                            am = get_pitcher_attack_map(sp.get("pitcher_id"), days=30)
                        if am and am.get("grid"):
                            zg=am["grid"]; zd,td=[],[]
                            for row in [3,2,1]:
                                rv,rt=[],[]
                                for col_ in [1,2,3]:
                                    z=(row-1)*3+col_; zi=zg.get(z,{})
                                    rv.append(zi.get("whiff_pct",20))
                                    rt.append(f"Zone {z}<br>Usage:{zi.get('usage',0):.0f}%<br>Whiff:{zi.get('whiff_pct',20):.0f}%")
                                zd.append(rv); td.append(rt)
                            fig=go.Figure(go.Heatmap(z=zd,text=td,texttemplate="%{text}",
                                textfont={"size":10},colorscale=[[0,'#ef4444'],[.5,'#fbbf24'],[1,'#22c55e']],
                                showscale=True,colorbar=dict(title="Whiff%")))
                            fig.update_layout(title=f"{sp['pitcher']} Attack Zones (L30D)",
                                xaxis=dict(showticklabels=False),yaxis=dict(showticklabels=False),height=350)
                            st.plotly_chart(fig,use_container_width=True)
                        else: st.info("No heat map data for this pitcher")
            with ch2:
                st.markdown("#### 💥 Hitter Damage Map")
                if all_hitter_results:
                    h_opts = {f"{h['name']} ({h['team']})":h for h in all_hitter_results[:20]}
                    sel_h  = st.selectbox("Select Hitter",list(h_opts.keys()),key="hm_h")
                    if sel_h:
                        sh = h_opts[sel_h]
                        with st.spinner("Loading..."):
                            dm = get_hitter_damage_map(sh.get("player_id"), days=30)
                        if dm and dm.get("grid"):
                            zg=dm["grid"]; zd,td=[],[]
                            for row in [3,2,1]:
                                rv,rt=[],[]
                                for col_ in [1,2,3]:
                                    z=(row-1)*3+col_; zi=zg.get(z,{})
                                    ba=zi.get("ba",0.250)
                                    rv.append(ba)
                                    rt.append(f"Zone {z}<br>BA:{ba:.3f}<br>Swing:{zi.get('swing_pct',50):.0f}%")
                                zd.append(rv); td.append(rt)
                            fig=go.Figure(go.Heatmap(z=zd,text=td,texttemplate="%{text}",
                                textfont={"size":10},colorscale=[[0,'#3b82f6'],[.4,'#fbbf24'],[1,'#ef4444']],
                                showscale=True,colorbar=dict(title="BA")))
                            fig.update_layout(title=f"{sh['name']} Damage Zones (L30D)",
                                xaxis=dict(showticklabels=False),yaxis=dict(showticklabels=False),height=350)
                            st.plotly_chart(fig,use_container_width=True)

    # =========================================================
    # TAB 5: Charts & Share
    # =========================================================
    with tab5:
        st.markdown("### 📊 Shareable Charts & Insights")
        conf_p = [p for p in all_pitcher_results if p.get("lineup_confirmed")]
        conf_h2= [h for h in all_hitter_results  if h.get("lineup_confirmed")]
        if not conf_p:
            st.warning("⚠️ No confirmed lineups yet.")
        else:
            st.success(f"✅ Using {len(conf_p)} pitchers with confirmed lineups")
            n1,n2,n3=st.columns(3)
            with n1:
                st.markdown("#### 📈 Expected Ks vs SALCI")
                fig=create_expected_vs_salci_chart(conf_p)
                if fig: st.plotly_chart(fig,use_container_width=True)
            with n2:
                st.markdown("#### 🔥 Top 10 Expected Ks")
                fig=create_top_10_expected_ks_chart(conf_p)
                if fig: st.plotly_chart(fig,use_container_width=True)
            with n3:
                st.markdown("#### ⚡ SALCI vs Floor Confidence")
                fig=create_salci_vs_confidence_chart(conf_p)
                if fig: st.plotly_chart(fig,use_container_width=True)
            st.markdown("---")
            c1,c2=st.columns(2)
            with c1:
                st.markdown("#### 📈 SALCI Rankings")
                fig=create_pitcher_comparison_chart(conf_p)
                if fig: st.plotly_chart(fig,use_container_width=True)
            with c2:
                st.markdown("#### 🔥 Hot Hitters (L7)")
                fig=create_hitter_hotness_chart(conf_h2)
                if fig: st.plotly_chart(fig,use_container_width=True)
            st.markdown("---")
            c3,c4=st.columns(2)
            with c3:
                st.markdown("#### 🎯 K Line Projections")
                fig=create_k_projection_chart(conf_p)
                if fig: st.plotly_chart(fig,use_container_width=True)
            with c4:
                st.markdown("#### 🧮 SALCI v3 Weights")
                st.plotly_chart(create_salci_breakdown_chart(),use_container_width=True)
            st.markdown("---")
            st.markdown("#### 📊 Hitter K% vs AVG")
            fig=create_matchup_scatter(conf_h2)
            if fig: st.plotly_chart(fig,use_container_width=True)
            st.markdown("---")
            st.markdown("#### ⚡ Stuff vs Location")
            fig=create_stuff_location_chart(conf_p)
            if fig: st.plotly_chart(fig,use_container_width=True)

    # ======================
    # TAB 6: Yesterday's Reflection
    # ======================
    with tab6:
        st.markdown("### 📈 Yesterday's Reflection")
        st.markdown("Compare SALCI predictions against actual box-score results.")
        st.markdown("---")

        if not REFLECTION_AVAILABLE:
            st.error("❌ `reflection.py` not found. Place it alongside `mlb_salci_full.py` and restart.")
        else:
            # ── Date selector (default = yesterday) ──────────────────────────────
            yesterday_dt  = datetime.today() - timedelta(days=1)
            reflect_date  = st.date_input(
                "📅 Analyze date",
                value=yesterday_dt,
                max_value=yesterday_dt,
                min_value=yesterday_dt - timedelta(days=30),
                key="reflect_date_picker",
            )
            reflect_str = reflect_date.strftime("%Y-%m-%d")

            # ── Step 1: Save today's predictions ─────────────────────────────────
            with st.expander("📥 Step 1 — Save today's predictions (do this BEFORE games start)", expanded=False):
                st.markdown(
                    "Saving locks in your SALCI scores and K projections so they can be "
                    "compared against actual box scores after games finish."
                )
                today_str = date_str  # from main() scope
                existing_preds = refl.load_daily_predictions(today_str)
                if existing_preds:
                    saved_at = existing_preds.get("saved_at", "unknown time")
                    st.success(f"✅ Predictions already saved for **{today_str}** at {saved_at[:19]}")
                    st.caption(f"{len(existing_preds.get('pitchers', []))} pitchers · "
                               f"{len(existing_preds.get('hitters', []))} hitters stored")
                    if st.button("🔄 Overwrite with current predictions", key="overwrite_preds"):
                        save_predictions_with_reflection(today_str, all_pitcher_results, all_hitter_results)
                else:
                    if st.button("💾 Save today's predictions now", use_container_width=True, key="save_preds_btn"):
                        save_predictions_with_reflection(today_str, all_pitcher_results, all_hitter_results)

            st.markdown("---")

            # ── Step 2: Collect results & generate reflection ─────────────────────
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button(f"🔄 Collect results & generate reflection for {reflect_str}",
                             use_container_width=True, key="collect_results_btn"):
                    with st.spinner("Fetching MLB box scores…"):
                        reflection_data = refl.collect_and_reflect_date(reflect_str, force=True)
                    if reflection_data:
                        st.success("✅ Reflection generated successfully!")
                    else:
                        preds_exist = refl.load_daily_predictions(reflect_str) is not None
                        if not preds_exist:
                            st.warning(f"⚠️ No saved predictions found for {reflect_str}. "
                                       f"You need to save predictions before games start.")
                        else:
                            st.warning("⚠️ No completed games found for that date yet. "
                                       "Try again after games finish.")
            with col_btn2:
                existing_ref = refl.load_reflection(reflect_str)
                if existing_ref:
                    gen_at = existing_ref.get("generated_at", "")[:19]
                    st.info(f"📂 Reflection cached from {gen_at}")

            # ── Load & display reflection ─────────────────────────────────────────
            reflection_data = refl.load_reflection(reflect_str)

            if not reflection_data:
                st.info(
                    f"No reflection data for **{reflect_str}** yet.\n\n"
                    "**To get started:**\n"
                    "1. Use Step 1 above to save predictions before today's games\n"
                    "2. Come back after games complete and click 'Collect results'\n"
                    "3. The model will compare your SALCI projections to actual box scores"
                )
            else:
                rf = reflection_data
                n  = rf.get("games_tracked", 0)

                # ── Headline metrics ──────────────────────────────────────────────
                st.markdown(f"#### 📊 {reflect_date.strftime('%A, %B %d')} — {n} starters tracked")

                m1, m2, m3, m4, m5 = st.columns(5)
                acc = rf.get("accuracy_pct", 0)
                delta = rf.get("avg_k_delta", 0)
                mae   = rf.get("mae", 0)

                m1.metric("✅ Hit Rate",        f"{acc:.1f}%",
                          help="Projections within ±1.5 Ks of actual")
                m2.metric("📈 Avg Projected Ks", f"{rf.get('avg_predicted_ks', 0):.1f}")
                m3.metric("📊 Avg Actual Ks",    f"{rf.get('avg_actual_ks', 0):.1f}")
                m4.metric("⚖️ Avg K Delta",      f"{delta:+.2f}",
                          delta_color="inverse",
                          help="Positive = model ran LOW (actual > projected)")
                m5.metric("📐 MAE",              f"{mae:.2f} Ks",
                          help="Mean absolute error across all starters")

                # Hit / Over / Under breakdown
                h_count = rf.get("hits",  0)
                o_count = rf.get("overs", 0)
                u_count = rf.get("unders",0)
                st.markdown(
                    f"<div style='display:flex;gap:1rem;margin:0.5rem 0;'>"
                    f"<span style='background:#10b981;color:white;padding:0.2rem 0.8rem;border-radius:8px;'>✅ HIT: {h_count}</span>"
                    f"<span style='background:#3b82f6;color:white;padding:0.2rem 0.8rem;border-radius:8px;'>📈 OVER: {o_count} ({rf.get('over_pct',0):.0f}%)</span>"
                    f"<span style='background:#f97316;color:white;padding:0.2rem 0.8rem;border-radius:8px;'>📉 UNDER: {u_count} ({rf.get('under_pct',0):.0f}%)</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )

                # ── Lesson / Insight ──────────────────────────────────────────────
                if rf.get("lesson"):
                    st.info(f"💡 **Insight:** {rf['lesson']}")

                st.markdown("---")

                # ── Over / Under performer columns ────────────────────────────────
                col_o, col_u = st.columns(2)

                with col_o:
                    st.markdown("#### 🔥 Overperformers")
                    overs_list = rf.get("overperformers", [])
                    if overs_list:
                        for p in overs_list:
                            salci_str = f"SALCI {p['salci']:.0f}" if p.get("salci") else ""
                            st.markdown(
                                f"<div style='background:#d1fae5;border-left:4px solid #10b981;"
                                f"border-radius:6px;padding:0.6rem 1rem;margin-bottom:0.4rem;'>"
                                f"<strong>{p['name']}</strong> · {p.get('team','')}"
                                f"{'  ·  ' + salci_str if salci_str else ''}<br>"
                                f"Projected <strong>{p['predicted']:.1f}</strong> → "
                                f"Actual <strong>{p['actual']}</strong> "
                                f"<span style='color:#10b981;font-weight:bold;'>(+{p['delta']:.1f} Ks)</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )
                    else:
                        st.caption("No pitchers exceeded projection by more than 1.5 Ks.")

                with col_u:
                    st.markdown("#### ❄️ Underperformers")
                    unders_list = rf.get("underperformers", [])
                    if unders_list:
                        for p in unders_list:
                            salci_str = f"SALCI {p['salci']:.0f}" if p.get("salci") else ""
                            st.markdown(
                                f"<div style='background:#fee2e2;border-left:4px solid #ef4444;"
                                f"border-radius:6px;padding:0.6rem 1rem;margin-bottom:0.4rem;'>"
                                f"<strong>{p['name']}</strong> · {p.get('team','')}"
                                f"{'  ·  ' + salci_str if salci_str else ''}<br>"
                                f"Projected <strong>{p['predicted']:.1f}</strong> → "
                                f"Actual <strong>{p['actual']}</strong> "
                                f"<span style='color:#ef4444;font-weight:bold;'>({p['delta']:+.1f} Ks)</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )
                    else:
                        st.caption("No pitchers missed projection by more than 1.5 Ks.")

                # ── Full comparison table ─────────────────────────────────────────
                st.markdown("---")
                st.markdown("#### 📋 Full Comparison Table")

                comparisons = rf.get("comparisons", [])
                if comparisons:
                    rows = []
                    for c in sorted(comparisons, key=lambda x: abs(x["k_delta"]), reverse=True):
                        acc_icon = "✅" if c["k_accuracy"] == "HIT" else "📈" if c["k_accuracy"] == "OVER" else "📉"
                        rows.append({
                            "Pitcher":     c["pitcher_name"],
                            "Team":        c.get("team", ""),
                            "SALCI":       f"{c['predicted_salci']:.1f}" if c.get("predicted_salci") else "—",
                            "Projected K": f"{c['predicted_ks']:.1f}",
                            "Actual K":    str(c["actual_ks"]),
                            "Delta":       f"{c['k_delta']:+.1f}",
                            "IP":          f"{c['actual_ip']:.1f}",
                            "Result":      f"{acc_icon} {c['k_accuracy']}",
                        })
                    st.dataframe(
                        pd.DataFrame(rows),
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Delta": st.column_config.TextColumn("Δ Ks"),
                            "Result": st.column_config.TextColumn("Result"),
                        }
                    )
                else:
                    st.info("No individual comparison data available.")

                # ── Profile accuracy breakdown ────────────────────────────────────
                stuff_acc = rf.get("stuff_heavy_accuracy")
                loc_acc   = rf.get("location_heavy_accuracy")
                if stuff_acc is not None or loc_acc is not None:
                    st.markdown("---")
                    st.markdown("#### 🧪 Profile Accuracy")
                    pa1, pa2 = st.columns(2)
                    if stuff_acc is not None:
                        pa1.metric("🔥 Stuff-Heavy Pitchers", f"{stuff_acc*100:.0f}% hit rate")
                    if loc_acc is not None:
                        pa2.metric("🎯 Location-Heavy Pitchers", f"{loc_acc*100:.0f}% hit rate")


    # ======================
    # TAB 7: Model Accuracy
    # ======================
    with tab7:
        st.markdown("### 🎯 SALCI Model Accuracy Dashboard")
        st.markdown("Rolling accuracy metrics built from saved reflections.")
        st.markdown("---")

        if not REFLECTION_AVAILABLE:
            st.error("❌ `reflection.py` not found.")
        else:
            window = st.radio("Lookback window", ["7 days", "14 days", "30 days"],
                              horizontal=True, key="accuracy_window")
            days_map = {"7 days": 7, "14 days": 14, "30 days": 30}
            n_days   = days_map[window]

            ra = refl.get_rolling_accuracy(n_days)

            if ra.get("games_analyzed", 0) == 0:
                st.info(
                    f"No accuracy data for the past {n_days} days yet.\n\n"
                    "**How to build history:**\n"
                    "1. Save predictions every day before games start (Tab 6 → Step 1)\n"
                    "2. Collect results each evening (Tab 6 → 'Collect results')\n"
                    "3. Accuracy will accumulate here automatically"
                )
            else:
                # ── Top-line metrics ──────────────────────────────────────────────
                st.markdown(f"#### Last {n_days} days — {ra['games_analyzed']} pitcher-games")

                tendency_color = {"OVER": "#3b82f6", "UNDER": "#f97316", "CALIBRATED": "#10b981"}.get(
                    ra.get("tendency", "CALIBRATED"), "#6b7280"
                )
                tendency_label = {
                    "OVER":       "📈 Running LOW — model under-projects Ks",
                    "UNDER":      "📉 Running HIGH — model over-projects Ks",
                    "CALIBRATED": "⚖️ Well calibrated",
                }.get(ra.get("tendency", "CALIBRATED"), "")

                st.markdown(
                    f"<div style='background:{tendency_color}22;border:1px solid {tendency_color};"
                    f"border-radius:8px;padding:0.6rem 1rem;margin-bottom:1rem;'>"
                    f"<strong style='color:{tendency_color};'>{tendency_label}</strong></div>",
                    unsafe_allow_html=True
                )

                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("✅ Hit Rate",       f"{ra['accuracy_pct']:.1f}%",
                          help="% of projections within ±1.5 Ks")
                c2.metric("📐 MAE",            f"{ra['mae']:.2f} Ks",
                          help="Mean absolute error across all starters")
                c3.metric("⚖️ Avg Δ",         f"{ra['avg_k_delta']:+.2f} Ks",
                          delta_color="inverse",
                          help="+ means model ran LOW (actual > projected)")
                c4.metric("📈 Over %",         f"{ra['over_pct']:.0f}%")
                c5.metric("📉 Under %",        f"{ra['under_pct']:.0f}%")

                st.caption(f"Based on {ra['days_analyzed']} days with data out of last {n_days} days.")

                # ── Day-by-day chart ──────────────────────────────────────────────
                daily = ra.get("daily", [])
                if len(daily) >= 2:
                    st.markdown("---")
                    st.markdown("#### 📈 Daily Accuracy Trend")

                    import plotly.graph_objects as go
                    from plotly.subplots import make_subplots

                    fig = make_subplots(specs=[[{"secondary_y": True}]])

                    fig.add_trace(go.Bar(
                        x=[d["date"] for d in daily],
                        y=[d["accuracy_pct"] for d in daily],
                        name="Hit Rate %",
                        marker_color="#10b981",
                        opacity=0.7,
                    ), secondary_y=False)

                    fig.add_trace(go.Scatter(
                        x=[d["date"] for d in daily],
                        y=[d["avg_k_delta"] for d in daily],
                        name="Avg Δ Ks",
                        mode="lines+markers",
                        line=dict(color="#3b82f6", width=2),
                        marker=dict(size=6),
                    ), secondary_y=True)

                    fig.add_hline(y=0,   line_dash="dot", line_color="#6b7280",
                                  secondary_y=True, annotation_text="Zero bias")
                    fig.add_hline(y=70,  line_dash="dash", line_color="#10b981",
                                  secondary_y=False, annotation_text="70% target")

                    fig.update_layout(
                        height=350,
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        margin=dict(l=40, r=40, t=40, b=40),
                    )
                    fig.update_yaxes(title_text="Hit Rate %",   range=[0, 100], secondary_y=False)
                    fig.update_yaxes(title_text="Avg K Delta",  secondary_y=True)
                    st.plotly_chart(fig, use_container_width=True)

                # ── Day-by-day table ──────────────────────────────────────────────
                if daily:
                    st.markdown("---")
                    st.markdown("#### 📋 Day-by-Day Summary")
                    df_daily = pd.DataFrame([{
                        "Date":        d["date"],
                        "Games":       d["games"],
                        "Hit Rate":    f"{d['accuracy_pct']:.1f}%",
                        "Avg Δ Ks":    f"{d['avg_k_delta']:+.2f}",
                        "MAE":         f"{d['mae']:.2f}",
                    } for d in reversed(daily)])
                    st.dataframe(df_daily, use_container_width=True, hide_index=True)

                # ── Instructions if sparse data ───────────────────────────────────
                if ra["days_analyzed"] < 3:
                    st.markdown("---")
                    st.info(
                        f"📊 Only **{ra['days_analyzed']} day(s)** of data so far. "
                        "Save predictions daily for at least a week to see meaningful trends."
                    )


if __name__ == "__main__":
    main()
