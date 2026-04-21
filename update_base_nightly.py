#!/usr/bin/env python3
"""
update_base_nightly.py — SALCI Stage 1: Nightly Base Builder
=============================================================
Scheduled: 11 PM ET (3 AM UTC) daily via GitHub Actions
Output:    daily_base.json

What this does:
  1. Fetches tomorrow's probable pitchers from MLB Stats API
  2. For each pitcher, runs Statcast Stuff+, Location+, Workload via pybaseball
  3. Calculates a base SALCI score (without confirmed lineups — matchup uses
     team-level batting stats as a fallback)
  4. Writes daily_base.json to repo root
  5. GitHub Actions auto-commits — Streamlit reads it on next load

Run manually:
    python update_base_nightly.py
"""

import json
import os
import sys
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# ── Statcast imports ──────────────────────────────────────────────────────────
try:
    from statcast_connector import (
        get_pitcher_statcast_profile,
        calculate_workload_score_v3,
        calculate_matchup_score_v3,
        calculate_salci_v3,
        calculate_expected_ks_v3,
        PYBASEBALL_AVAILABLE,
    )
    STATCAST_AVAILABLE = PYBASEBALL_AVAILABLE
except ImportError:
    STATCAST_AVAILABLE = False
    print("⚠️  statcast_connector.py not found — will use proxy SALCI only")

BASE_FILE       = "daily_base.json"
REQUEST_TIMEOUT = 15
LEAGUE_AVG_2025 = 0.248


# ── MLB API helpers ───────────────────────────────────────────────────────────

def get_games_for_date(date_str: str) -> List[Dict]:
    url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
           f"&hydrate=probablePitcher,team")
    try:
        data = requests.get(url, timeout=REQUEST_TIMEOUT).json()
        if not data.get("dates"):
            return []
        return data["dates"][0].get("games", [])
    except Exception as e:
        print(f"  ⚠️  Schedule fetch failed: {e}")
        return []


def get_recent_pitcher_stats(player_id: int, num_games: int = 7) -> Dict:
    url = (f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
           f"?stats=gameLog&group=pitching")
    try:
        data = requests.get(url, timeout=REQUEST_TIMEOUT).json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        games  = sorted(splits, key=lambda x: x.get("date", ""), reverse=True)[:num_games]
        if not games:
            return {}
        tot = {"ip": 0, "so": 0, "bb": 0, "tbf": 0, "np": 0, "hits": 0, "games": len(games)}
        for g in games:
            s = g.get("stat", {})
            ip_raw = str(s.get("inningsPitched", "0.0"))
            parts  = ip_raw.split(".")
            ip = int(parts[0]) + int(parts[1]) / 3 if "." in ip_raw else float(ip_raw)
            tot["ip"]   += ip
            tot["so"]   += int(s.get("strikeOuts", 0))
            tot["bb"]   += int(s.get("baseOnBalls", 0))
            tot["tbf"]  += int(s.get("battersFaced", 0))
            tot["np"]   += int(s.get("numberOfPitches", 0))
            tot["hits"] += int(s.get("hits", 0))
        if tot["ip"] == 0 or tot["tbf"] == 0:
            return {}
        ab_proxy = max(1, tot["tbf"] - tot["bb"])
        return {
            "K9":              tot["so"] / tot["ip"] * 9,
            "K_percent":       tot["so"] / tot["tbf"],
            "K/BB":            tot["so"] / tot["bb"] if tot["bb"] > 0 else tot["so"] * 2,
            "P/IP":            tot["np"] / tot["ip"],
            "avg_ip_per_start":tot["ip"] / tot["games"],
            "avg_against":     tot["hits"] / ab_proxy,
            "games_sampled":   tot["games"],
        }
    except Exception as e:
        return {}


def get_team_batting_stats(team_id: int, days: int = 14) -> Dict:
    end_date   = datetime.today()
    start_date = end_date - timedelta(days=days)
    url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}"
           f"&startDate={start_date.strftime('%Y-%m-%d')}"
           f"&endDate={end_date.strftime('%Y-%m-%d')}")
    try:
        dates    = requests.get(url, timeout=REQUEST_TIMEOUT).json().get("dates", [])
        game_ids = [g["gamePk"] for d in dates for g in d.get("games", [])]
        tot      = {"pa": 0, "so": 0, "hits": 0, "ab": 0}
        for gid in game_ids[:7]:
            try:
                box = requests.get(
                    f"https://statsapi.mlb.com/api/v1/game/{gid}/boxscore",
                    timeout=REQUEST_TIMEOUT
                ).json().get("teams", {})
                for side in ["home", "away"]:
                    if box.get(side, {}).get("team", {}).get("id") == team_id:
                        s = box[side].get("teamStats", {}).get("batting", {})
                        tot["so"]   += int(s.get("strikeOuts", 0))
                        tot["pa"]   += int(s.get("plateAppearances", 0))
                        tot["hits"] += int(s.get("hits", 0))
                        tot["ab"]   += int(s.get("atBats", 0))
                        break
            except Exception:
                continue
        if tot["pa"] == 0:
            return {"OppK%": 0.22, "OppContact%": 0.75}
        return {
            "OppK%":      round(tot["so"] / tot["pa"], 4),
            "OppContact%":round(tot["hits"] / tot["ab"], 4) if tot["ab"] > 0 else 0.25,
        }
    except Exception:
        return {"OppK%": 0.22, "OppContact%": 0.75}


# ── Main ──────────────────────────────────────────────────────────────────────

def build_base(target_date: Optional[str] = None) -> bool:
    if target_date is None:
        target_date = (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"  SALCI Nightly Base Builder — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Target date: {target_date}")
    print(f"{'='*60}")

    games = get_games_for_date(target_date)
    if not games:
        # Try today if tomorrow has none (off-day edge case)
        target_date = datetime.today().strftime("%Y-%m-%d")
        games = get_games_for_date(target_date)
    if not games:
        print("  ❌ No games found")
        return False

    print(f"  Found {len(games)} games for {target_date}")

    pitchers = []

    for game in games:
        game_pk       = game.get("gamePk")
        game_datetime = game.get("gameDate")
        home_t        = game["teams"]["home"]["team"]
        away_t        = game["teams"]["away"]["team"]

        for side, team, opp_team in [("home", home_t, away_t), ("away", away_t, home_t)]:
            pp = game["teams"][side].get("probablePitcher")
            if not pp:
                continue

            pid          = pp.get("id")
            pitcher_name = pp.get("fullName", "Unknown")
            pitcher_hand = pp.get("pitchHand", {}).get("code", "R")
            opp_id       = opp_team["id"]
            team_id      = team["id"]
            opp_side     = "away" if side == "home" else "home"

            print(f"  ── {pitcher_name} ({team['name']})")

            p_recent   = get_recent_pitcher_stats(pid)
            opp_stats  = get_team_batting_stats(opp_id)

            # Statcast path
            stuff_sc = loc_sc = match_sc = work_sc = None
            sb_       = {}
            pt_       = "BALANCED"
            sv3       = None
            is_sc     = False

            if STATCAST_AVAILABLE:
                try:
                    prof = get_pitcher_statcast_profile(pid, days=30)
                    if prof:
                        stuff_sc = prof.get("stuff_plus", 100)
                        loc_sc   = prof.get("location_plus", 100)
                        sb_      = prof.get("by_pitch_type", {})
                        pt_      = prof.get("profile_type", "BALANCED")
                        avg_ip   = p_recent.get("avg_ip_per_start", 5.5)
                        work_sc, _ = calculate_workload_score_v3(
                            {"P/IP": p_recent.get("P/IP", 16.0), "avg_ip": avg_ip}
                        )
                        match_sc, _ = calculate_matchup_score_v3(opp_stats, None, pitcher_hand)
                        sv3 = calculate_salci_v3(stuff_sc, loc_sc, match_sc, work_sc)
                        is_sc = True
                        print(f"       Statcast SALCI {sv3['salci']:.1f}")
                except Exception as e:
                    print(f"       ⚠️  Statcast error: {e}")

            if sv3:
                avg_ip  = p_recent.get("avg_ip_per_start", 5.5)
                proj    = calculate_expected_ks_v3(sv3, avg_ip)
                salci   = sv3["salci"]
                grade   = sv3.get("grade", "C")
                expected = proj.get("expected", 5.0)
                k_lines  = proj.get("k_lines", {})
                floor    = proj.get("floor", 4)
                floor_conf = proj.get("floor_confidence", 65)
                volatility = proj.get("volatility", 1.2)
            else:
                # Proxy fallback
                k9    = p_recent.get("K9", 8.0)
                k_pct = p_recent.get("K_percent", 0.22)
                p_ip  = p_recent.get("P/IP", 16.0)
                avg_ip = p_recent.get("avg_ip_per_start", 5.5)
                opp_k  = opp_stats.get("OppK%", 0.22)

                k9_norm  = max(0, min(100, (k9   - 6)    / 7    * 100))
                kp_norm  = max(0, min(100, (k_pct- 0.15) / 0.23 * 100))
                pip_norm = max(0, min(100, (18 - p_ip)   / 5    * 100))
                opp_norm = max(0, min(100, (opp_k- 0.18) / 0.10 * 100))

                salci = round(k9_norm*0.25 + kp_norm*0.25 + opp_norm*0.30 + pip_norm*0.20, 1)
                grade = "A" if salci>=70 else "B" if salci>=60 else "C" if salci>=50 else "D" if salci>=40 else "F"
                expected = round((salci/50) * avg_ip, 1)
                k_lines  = {}
                floor    = max(0, int(expected) - 1)
                floor_conf  = 65
                volatility  = 1.2
                is_sc       = False
                stuff_sc = loc_sc = match_sc = work_sc = None
                sb_ = {}; pt_ = "N/A"
                print(f"       Proxy SALCI {salci:.1f}")

            pitchers.append({
                "pitcher":        pitcher_name,
                "pitcher_name":   pitcher_name,
                "pitcher_id":     pid,
                "pitcher_hand":   pitcher_hand,
                "pitcher_k_pct":  p_recent.get("K_percent", 0.22),
                "pitcher_avg_against": p_recent.get("avg_against", LEAGUE_AVG_2025),
                "team":           team["name"],
                "team_id":        team_id,
                "opponent":       opp_team["name"],
                "opponent_id":    opp_id,
                "opp_side":       opp_side,
                "game_pk":        game_pk,
                "game_datetime":  game_datetime,
                "salci":          salci,
                "salci_grade":    grade,
                "expected":       expected,
                "k_lines":        k_lines,
                "lines":          k_lines,
                "floor":          floor,
                "floor_confidence": floor_conf,
                "volatility":     volatility,
                "stuff_score":    stuff_sc,
                "location_score": loc_sc,
                "matchup_score":  match_sc,
                "workload_score": work_sc,
                "stuff_breakdown":sb_,
                "profile_type":   pt_,
                "is_statcast":    is_sc,
                "lineup_confirmed": False,
                "lineup":         [],
                "stats_recent":   p_recent,
            })

    if not pitchers:
        print("  ❌ No pitchers processed")
        return False

    output = {
        "date":         target_date,
        "stage":        "base",
        "generated_at": datetime.now().isoformat(),
        "pitcher_count":len(pitchers),
        "pitchers":     sorted(pitchers, key=lambda x: x["salci"], reverse=True),
    }

    with open(BASE_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n  ✅ Saved {BASE_FILE} — {len(pitchers)} pitchers for {target_date}\n")
    return True


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    success = build_base(target)
    sys.exit(0 if success else 1)
