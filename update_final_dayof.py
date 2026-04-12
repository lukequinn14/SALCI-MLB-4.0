#!/usr/bin/env python3
"""
update_final_dayof.py — SALCI Stage 2: Day-of Final Updater
============================================================
Scheduled: Every 20 min, 3 PM – 10 PM ET via GitHub Actions
Reads:     daily_base.json   (written by update_base_nightly.py)
Output:    daily_final.json

What this does:
  1. Reads daily_base.json (pre-computed Stuff+, Location+, Workload)
  2. For each game checks if the opposing lineup is confirmed
  3. If confirmed: fetches individual hitter K-rates, recalculates Matchup
  4. Calculates Final SALCI combining all 4 components
  5. Writes daily_final.json — Streamlit reads it on next load

Run manually:
    python update_final_dayof.py
"""

import json
import os
import sys
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

try:
    from statcast_connector import (
        calculate_matchup_score_v3,
        calculate_salci_v3,
        calculate_expected_ks_v3,
        PYBASEBALL_AVAILABLE,
    )
    STATCAST_AVAILABLE = PYBASEBALL_AVAILABLE
except ImportError:
    STATCAST_AVAILABLE = False
    print("⚠️  statcast_connector.py not found — matchup scores will use team-level fallback")

BASE_FILE       = "daily_base.json"
FINAL_FILE      = "daily_final.json"
REQUEST_TIMEOUT = 15
LEAGUE_AVG_2025 = 0.248


# ── MLB API helpers ───────────────────────────────────────────────────────────

def get_confirmed_lineup(game_pk: int, team_side: str) -> Tuple[List[Dict], bool]:
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live",
            timeout=REQUEST_TIMEOUT
        ).json()
        game_data   = data.get("gameData", {})
        team_data   = (data.get("liveData", {})
                          .get("boxscore", {})
                          .get("teams", {})
                          .get(team_side, {}))
        batting_order = team_data.get("battingOrder", [])
        if len(batting_order) < 9:
            return [], False
        players = team_data.get("players", {})
        all_pls = game_data.get("players", {})
        lineup  = []
        for i, pid in enumerate(batting_order):
            key  = f"ID{pid}"
            info = players.get(key, {})
            fp   = all_pls.get(key, {})
            lineup.append({
                "id":            pid,
                "name":          info.get("person", {}).get("fullName", "Unknown"),
                "position":      info.get("position", {}).get("abbreviation", ""),
                "batting_order": i + 1,
                "bat_side":      fp.get("batSide", {}).get("code", "R"),
            })
        return lineup, True
    except Exception as e:
        print(f"    ⚠️  Lineup fetch failed for game {game_pk}/{team_side}: {e}")
        return [], False


def get_hitter_recent_k_rate(player_id: int, num_games: int = 7) -> Dict:
    url = (f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
           f"?stats=gameLog&group=hitting")
    try:
        data   = requests.get(url, timeout=REQUEST_TIMEOUT).json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        games  = sorted(splits, key=lambda x: x.get("date", ""), reverse=True)[:num_games]
        if not games:
            return {}
        so = ab = 0
        for g in games:
            s  = g.get("stat", {})
            so += int(s.get("strikeOuts", 0))
            ab += int(s.get("atBats", 0))
        if ab == 0:
            return {}
        return {
            "k_rate":           round(so / ab, 4),
            "zone_contact_pct": round(1 - (so / ab) * 0.8, 4),
        }
    except Exception:
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

def update_final() -> bool:
    print(f"\n{'='*60}")
    print(f"  SALCI Day-of Final Updater — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    if not os.path.exists(BASE_FILE):
        print(f"  ❌ {BASE_FILE} not found — run update_base_nightly.py first")
        return False

    with open(BASE_FILE) as f:
        base = json.load(f)

    base_date = base.get("date", "")
    today     = datetime.today().strftime("%Y-%m-%d")
    if base_date != today:
        print(f"  ⚠️  Base file is for {base_date}, today is {today} — proceeding anyway")

    print(f"  Base: {len(base['pitchers'])} pitchers for {base_date}")

    confirmed_count = 0
    updated_count   = 0

    for p in base["pitchers"]:
        name     = p.get("pitcher_name", p.get("pitcher", "Unknown"))
        game_pk  = p.get("game_pk")
        opp_side = p.get("opp_side", "away")
        opp_id   = p.get("opponent_id")
        ph       = p.get("pitcher_hand", "R")

        print(f"  ── {name} ({p.get('team', '?')})")

        # Check lineup
        lineup, confirmed = get_confirmed_lineup(game_pk, opp_side)
        p["lineup_confirmed"] = confirmed
        p["lineup"]           = lineup if confirmed else []

        if confirmed:
            confirmed_count += 1
            print(f"       ✅ Lineup confirmed ({len(lineup)} batters)")
        else:
            print(f"       ⏳ Lineup pending")

        # Build lineup hitter stats
        lineup_stats = None
        if confirmed and lineup:
            lineup_stats = []
            for batter in lineup:
                h = get_hitter_recent_k_rate(batter["id"])
                lineup_stats.append({
                    "name":             batter["name"],
                    "k_rate":           h.get("k_rate",           0.22),
                    "zone_contact_pct": h.get("zone_contact_pct", 0.82),
                    "bat_side":         batter.get("bat_side",    "R"),
                })

        # Matchup score
        opp_team_stats = get_team_batting_stats(opp_id)
        if STATCAST_AVAILABLE:
            matchup_score, _ = calculate_matchup_score_v3(opp_team_stats, lineup_stats, ph)
        else:
            opp_k = opp_team_stats.get("OppK%", 0.22)
            matchup_score = round(50 + (opp_k - 0.22) / 0.03 * 10, 1)
            matchup_score = max(20, min(80, matchup_score))

        p["matchup_score"] = matchup_score

        # Recalculate full SALCI if all components available
        stuff    = p.get("stuff_score")
        location = p.get("location_score")
        workload = p.get("workload_score")

        if STATCAST_AVAILABLE and all([stuff, location, workload, matchup_score]):
            sv3 = calculate_salci_v3(stuff, location, matchup_score, workload)
            p["salci"]       = sv3["salci"]
            p["salci_grade"] = sv3["grade"]
            avg_ip = p.get("stats_recent", {}).get("avg_ip_per_start", 5.5)
            proj   = calculate_expected_ks_v3(sv3, avg_ip)
            p["expected"]           = proj.get("expected", p["expected"])
            p["k_lines"]            = proj.get("k_lines", p.get("k_lines", {}))
            p["lines"]              = p["k_lines"]
            p["floor"]              = proj.get("floor", p.get("floor", 4))
            p["floor_confidence"]   = proj.get("floor_confidence", 65)
            p["volatility"]         = proj.get("volatility", 1.2)
            updated_count += 1
            print(f"       SALCI {p['salci']:.1f} ({p['salci_grade']}) · "
                  f"Expected {p['expected']:.1f} Ks · Floor {p['floor']}+ ({p['floor_confidence']}%)")
        else:
            # Patch matchup into proxy salci
            k9    = p.get("stats_recent", {}).get("K9", 8.0)
            k_pct = p.get("stats_recent", {}).get("K_percent", 0.22)
            p_ip  = p.get("stats_recent", {}).get("P/IP", 16.0)
            avg_ip = p.get("stats_recent", {}).get("avg_ip_per_start", 5.5)
            k9_norm  = max(0, min(100, (k9   - 6)    / 7    * 100))
            kp_norm  = max(0, min(100, (k_pct- 0.15) / 0.23 * 100))
            pip_norm = max(0, min(100, (18 - p_ip)   / 5    * 100))
            proxy = round(k9_norm*0.25 + kp_norm*0.25 + matchup_score*0.30 + pip_norm*0.20, 1)
            p["salci"]       = proxy
            p["salci_grade"] = "A" if proxy>=70 else "B" if proxy>=60 else "C" if proxy>=50 else "D" if proxy>=40 else "F"
            p["expected"]    = round((proxy / 50) * avg_ip, 1)
            p["k_lines"]     = {k: max(5, min(95, round(50 + (p["expected"] - k) * 15)))
                                for k in range(max(1, int(p["expected"]) - 1), int(p["expected"]) + 4)}
            p["lines"]       = p["k_lines"]
            print(f"       SALCI {proxy:.1f} (proxy) · Expected {p['expected']:.1f} Ks")

    base["stage"]           = "final"
    base["updated_at"]      = datetime.now().isoformat()
    base["confirmed_count"] = confirmed_count
    base["salci_updated"]   = updated_count

    with open(FINAL_FILE, "w") as f:
        json.dump(base, f, indent=2)

    print(f"\n  ✅ Saved {FINAL_FILE}")
    print(f"     {confirmed_count}/{len(base['pitchers'])} lineups confirmed")
    print(f"     {updated_count} full Statcast SALCI recalculations\n")
    return True


if __name__ == "__main__":
    success = update_final()
    sys.exit(0 if success else 1)
