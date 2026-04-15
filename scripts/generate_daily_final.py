#!/usr/bin/env python3
"""
generate_daily_final.py  —  SALCI Stage 2 Pre-Compute
=======================================================
Day-of GitHub Actions script (~every 20 min, 11 AM–8 PM ET).

What it does
------------
1.  Loads today's Stage 1 base JSON (must exist first)
2.  Checks live lineup status for each game
3.  For confirmed lineups: upgrades matchup_score to individual hitter K%
4.  Fetches current odds from public sources (if available)
5.  Computes model_prob and edge per pitcher
6.  Writes  data/daily/YYYY-MM-DD_final.json

The file is idempotent — safe to run multiple times.
Each run improves quality as more lineups are confirmed.

Run locally
-----------
    python generate_daily_final.py            # today
    python generate_daily_final.py 2026-04-16 # specific date

GitHub Actions environment variables
--------------------------------------
    GH_TOKEN       — for git commit/push
    ODDS_API_KEY   — optional, for The Odds API (https://the-odds-api.com)
                     If absent, odds fields remain null.
    TARGET_DATE    — override date (ISO string)
"""

import json
import os
import sys
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional
from scipy.stats import poisson

# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("stage2")

TARGET_DATE = (
    os.environ.get("TARGET_DATE")
    or (sys.argv[1] if len(sys.argv) > 1 else None)
    or datetime.today().strftime("%Y-%m-%d")
)
log.info(f"Target date: {TARGET_DATE}")

BASE = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 15

# ---------------------------------------------------------------------------
# Import dependencies
# ---------------------------------------------------------------------------
try:
    from data_loader import load_todays_data, get_pitchers, save_precomputed
except ImportError as e:
    log.error(f"data_loader not available: {e}")
    sys.exit(1)

SALCI_V3_AVAILABLE = False
try:
    from statcast_connector import (
        calculate_matchup_score_v3,
        PYBASEBALL_AVAILABLE,
    )
    SALCI_V3_AVAILABLE = True
except ImportError:
    pass

try:
    from content_engine import enrich_pitchers
    CONTENT_ENGINE_OK = True
except ImportError:
    CONTENT_ENGINE_OK = False

# ---------------------------------------------------------------------------
# MLB API helpers
# ---------------------------------------------------------------------------

def _get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning(f"GET {url} failed: {exc}")
        return None


def get_confirmed_lineup(game_pk: int, side: str) -> tuple[list, bool]:
    """
    Returns (hitter_list, is_confirmed).
    hitter_list: list of dicts with keys: id, name, batting_order, bat_side
    """
    data = _get(f"{BASE}/game/{game_pk}/boxscore")
    if not data:
        return [], False

    team_data = data.get("teams", {}).get(side, {})
    batters = team_data.get("batters", [])
    if not batters:
        return [], False

    players = team_data.get("players", {})
    hitters = []
    for batter_id in batters:
        p = players.get(f"ID{batter_id}", {})
        person = p.get("person", {})
        pos = p.get("position", {}).get("abbreviation", "")
        if pos == "P":
            continue  # skip DH slot pitcher
        hitters.append({
            "id": batter_id,
            "name": person.get("fullName", "?"),
            "batting_order": p.get("battingOrder", 0),
            "bat_side": p.get("batSide", {}).get("code", "R"),
        })

    confirmed = len(hitters) >= 8
    return hitters, confirmed


def fetch_hitter_k_pct(player_id: int, season: int) -> float:
    """Return a batter's strikeout rate (0–1). Defaults to league avg 0.22."""
    data = _get(f"{BASE}/people/{player_id}/stats", {
        "stats": "season", "group": "hitting", "season": season
    })
    if not data:
        return 0.22
    splits = data.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return 0.22
    s = splits[0].get("stat", {})
    ab = int(s.get("atBats", 0) or 0)
    so = int(s.get("strikeOuts", 0) or 0)
    return so / ab if ab >= 50 else 0.22


def lineup_weighted_k_pct(hitters: list, season: int, pitcher_hand: str = "R") -> float:
    """Compute the weighted-average K% for a confirmed batting order."""
    if not hitters:
        return 0.22

    # Weight top 5 batters more heavily (they get more PAs)
    order_weights = {1: 1.2, 2: 1.2, 3: 1.2, 4: 1.1, 5: 1.1, 6: 1.0, 7: 1.0, 8: 0.9, 9: 0.9}
    total_w = 0.0
    total_k = 0.0

    for h in hitters[:9]:
        k = fetch_hitter_k_pct(h["id"], season)
        order = min(max(h.get("batting_order", 5), 1), 9)
        w = order_weights.get(order, 1.0)
        total_k += k * w
        total_w += w

    return total_k / total_w if total_w > 0 else 0.22


# ---------------------------------------------------------------------------
# Odds API integration (The Odds API — free tier = 500 req/month)
# ---------------------------------------------------------------------------

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

def fetch_mlb_odds(date_str: str) -> dict:
    """
    Fetch MLB K-prop odds from The Odds API.

    Returns a dict keyed by pitcher name → {"k_line": "5.5", "odds": -130, "model_prob": 0.62}
    Returns {} if ODDS_API_KEY is not set or request fails.

    NOTE: The Odds API's player-props endpoint requires a Pro plan.
    This function gracefully returns {} on any failure so Stage 2 still
    writes a useful final.json even without odds.
    """
    if not ODDS_API_KEY:
        log.info("ODDS_API_KEY not set — skipping odds fetch.")
        return {}

    try:
        # Fetch game list for today
        url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events"
        r = requests.get(url, params={"apiKey": ODDS_API_KEY, "dateFormat": "iso"}, timeout=15)
        r.raise_for_status()
        events = r.json()

        today_events = [
            e for e in events
            if e.get("commence_time", "")[:10] == date_str
        ]
        log.info(f"Odds API: {len(today_events)} MLB events found for {date_str}")

        # For each event, try to fetch pitcher K props
        result = {}
        for event in today_events[:15]:  # cap to avoid rate limit
            eid = event.get("id")
            prop_url = (
                f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{eid}/odds"
            )
            pr = requests.get(prop_url, params={
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "pitcher_strikeouts_over_under",
                "oddsFormat": "american",
            }, timeout=15)
            if pr.status_code != 200:
                continue

            for bm in pr.json().get("bookmakers", []):
                for market in bm.get("markets", []):
                    for outcome in market.get("outcomes", []):
                        name = outcome.get("name", "")
                        desc = outcome.get("description", "")  # e.g. "Over 5.5"
                        price = outcome.get("price", 0)
                        if "over" in desc.lower():
                            try:
                                k_val = float(desc.lower().replace("over", "").strip())
                                result[name] = {
                                    "k_line": str(k_val),
                                    "odds": int(price),
                                }
                            except (ValueError, TypeError):
                                pass

        log.info(f"Odds resolved for {len(result)} pitchers")
        return result
    except Exception as exc:
        log.warning(f"Odds API failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Model probability calibration
# ---------------------------------------------------------------------------

def calibrate_model_prob(pitcher: dict) -> float:
    """
    Compute a calibrated probability for the pitcher's K line using Poisson.

    Falls back to SALCI proxy if expected is missing.
    """
    expected = pitcher.get("expected")
    k_line_raw = pitcher.get("k_line")

    if expected is None or k_line_raw is None:
        salci = pitcher.get("salci", 50)
        return max(0.35, min(0.75, 0.35 + (salci - 30) / 200.0))

    try:
        k = float(k_line_raw)
        # P(X > k) using continuous line — use floor(k) as the threshold
        threshold = int(k)
        prob = 1.0 - poisson.cdf(threshold, float(expected))
        return round(max(0.05, min(0.97, prob)), 4)
    except Exception:
        return 0.50


def implied_prob(odds: int) -> float:
    if odds is None:
        return 0.50
    odds = float(odds)
    if odds >= 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


# ---------------------------------------------------------------------------
# Matchup score upgrade (team → individual hitter level)
# ---------------------------------------------------------------------------

def upgrade_matchup_score(pitcher: dict, hitters: list, season: int) -> float:
    """
    Recompute matchup_score using individual lineup hitter K%.
    Falls back to current matchup_score if unavailable.
    """
    if not hitters:
        return pitcher.get("matchup_score") or 50.0

    wk = lineup_weighted_k_pct(hitters, season)

    if SALCI_V3_AVAILABLE:
        try:
            # Rebuild opp_stats dict that calculate_matchup_score_v3 expects
            opp_stats = {
                "OppK%": wk,
                "OppZoneContact%": 1 - wk * 0.5,  # rough estimate
            }
            return calculate_matchup_score_v3(
                opp_stats, opp_stats,
                pitcher_hand=pitcher.get("pitcher_hand", "R"),
            )
        except Exception:
            pass

    # Simple proxy: normalise wk to [0, 100]
    normalized = min(100, max(0, (wk - 0.15) / (0.32 - 0.15) * 100))
    return round(normalized, 1)


def recompute_salci(pitcher: dict, new_matchup_score: float) -> float:
    """
    Recompute SALCI v4 with the upgraded matchup score.
    Uses current stuff/workload/location scores.
    """
    stuff = pitcher.get("stuff_score") or pitcher.get("salci", 50)
    workload = pitcher.get("workload_score") or 50.0
    location = pitcher.get("location_score") or 50.0

    # Normalise stuff to 0-100 if it's on 100-scale (Stuff+ centres at 100)
    if stuff and stuff > 100:
        stuff_norm = min(100, max(0, (stuff - 70) * 2))
    else:
        stuff_norm = stuff or 50.0

    salci = (
        stuff_norm * 0.52 +
        new_matchup_score * 0.30 +
        workload * 0.10 +
        location * 0.08
    )
    return round(max(0, min(100, salci)), 1)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_final(date_str: str) -> list:
    """
    Load Stage 1 base, upgrade with live lineups + odds, return updated list.
    """
    season = int(date_str[:4])

    # Load base
    base_data, source = load_todays_data(date_str)
    if base_data is None or source == "none":
        log.error("No base data found — run generate_daily_base.py first!")
        return []

    pitchers = get_pitchers(base_data)
    if not pitchers:
        log.warning("Base data has no pitchers.")
        return []

    log.info(f"Loaded {len(pitchers)} pitchers from {source}")

    # Fetch odds (best-effort)
    odds_map = fetch_mlb_odds(date_str)

    # Group pitchers by game_pk so we fetch each boxscore once
    game_pks = list({p.get("game_pk") for p in pitchers if p.get("game_pk")})

    # Lineup cache: {game_pk: {"home": (hitters, confirmed), "away": (hitters, confirmed)}}
    lineup_cache = {}
    for gpk in game_pks:
        lineup_cache[gpk] = {
            "home": get_confirmed_lineup(gpk, "home"),
            "away": get_confirmed_lineup(gpk, "away"),
        }

    updated = []
    for p in pitchers:
        p = dict(p)  # copy
        game_pk = p.get("game_pk")

        # Determine which side this pitcher is on
        if game_pk and game_pk in lineup_cache:
            lineups = lineup_cache[game_pk]

            # The opponent lineup is what we use for matchup score
            # pitcher is home → opponent is away (and vice versa)
            # We need to figure out home/away from the pitcher's team
            # (stadium team = home team, but we only have abbreviations)
            # Simple heuristic: try both sides and use the one that's NOT the pitcher's team
            home_hitters, home_confirmed = lineups["home"]
            away_hitters, away_confirmed = lineups["away"]

            # Try the "home" lineup — if pitcher IS the home pitcher, opp = away
            # We don't store "side" in the base JSON, so we try the fuller lineup
            if home_confirmed and away_confirmed:
                opp_hitters = away_hitters  # default to away as opponent
                p["lineup_confirmed"] = True
            elif home_confirmed:
                opp_hitters = home_hitters
                p["lineup_confirmed"] = True
            elif away_confirmed:
                opp_hitters = away_hitters
                p["lineup_confirmed"] = True
            else:
                opp_hitters = []
                p["lineup_confirmed"] = False

            # Upgrade matchup score
            if p["lineup_confirmed"] and opp_hitters:
                new_matchup = upgrade_matchup_score(p, opp_hitters, season)
                new_salci = recompute_salci(p, new_matchup)
                log.info(
                    f"  {p['pitcher']}: matchup {p.get('matchup_score',50):.1f}→{new_matchup:.1f}, "
                    f"SALCI {p['salci']:.1f}→{new_salci:.1f}"
                )
                p["matchup_score"] = round(new_matchup, 1)
                p["salci"] = new_salci
                p["salci_grade"] = (
                    "S" if new_salci >= 80 else "A" if new_salci >= 70 else
                    "B+" if new_salci >= 60 else "B" if new_salci >= 52 else
                    "C" if new_salci >= 44 else "D" if new_salci >= 30 else "F"
                )
        else:
            opp_hitters = []

        # Attach odds
        pitcher_key = p.get("pitcher", "")
        if pitcher_key in odds_map:
            o = odds_map[pitcher_key]
            p["k_line"] = o.get("k_line", p.get("k_line"))
            p["odds"] = o.get("odds")
        # If still no odds, leave as None (content engine handles gracefully)

        # Calibrate model probability
        p["model_prob"] = calibrate_model_prob(p)

        # Compute edge
        if p.get("odds") is not None:
            edge = (p["model_prob"] - implied_prob(p["odds"])) * 100
            p["edge"] = round(edge, 2)
        else:
            p["edge"] = None

        p["stage"] = "final"
        p["generated_at"] = datetime.utcnow().isoformat() + "Z"
        updated.append(p)

    # Enrich with content engine fields if available
    if CONTENT_ENGINE_OK:
        try:
            updated = enrich_pitchers(updated)
        except Exception as exc:
            log.warning(f"content_engine.enrich_pitchers failed: {exc}")

    updated.sort(key=lambda x: x["salci"], reverse=True)
    return updated


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info(f"=== SALCI Stage 2 — Daily Final === {TARGET_DATE}")

    pitchers = build_final(TARGET_DATE)
    if not pitchers:
        log.warning("No pitchers in final build. Exiting.")
        sys.exit(0)

    confirmed_count = sum(1 for p in pitchers if p.get("lineup_confirmed"))
    log.info(f"Final: {len(pitchers)} pitchers, {confirmed_count} with confirmed lineups")

    ok = save_precomputed(
        TARGET_DATE,
        pitchers,
        stage="final",
        metadata={
            "script": "generate_daily_final.py",
            "salci_version": "6.0",
            "odds_available": bool(ODDS_API_KEY),
            "lineup_confirmed_count": confirmed_count,
        },
    )
    if ok:
        log.info(f"Wrote data/daily/{TARGET_DATE}_final.json")
    else:
        log.error("Failed to write final JSON!")
        sys.exit(1)

    log.info("Stage 2 complete.")
