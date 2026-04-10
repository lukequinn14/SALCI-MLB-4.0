"""
SALCI Prediction Storage & Reflection System
v4.1 — Fixed key names, auto-collection, robust error handling

WORKFLOW:
  Morning (before games):
    app calls save_daily_predictions(date, data)
    → writes salci_data/predictions/YYYY-MM-DD.json

  Evening (after games complete):
    app calls collect_and_reflect_yesterday()
    → fetches MLB box scores via API
    → writes salci_data/results/YYYY-MM-DD.json
    → generates salci_data/reflections/YYYY-MM-DD.json
    → returns full reflection dict for display

  Tab 6 (Yesterday):
    loads reflection for yesterday, renders comparison tables

  Tab 7 (Model Accuracy):
    calls get_rolling_accuracy(7) and get_rolling_accuracy(30)
    returns dict with keys: accuracy_pct, avg_k_delta, tendency,
    days_analyzed, games_analyzed, mae, over_pct, under_pct
"""

import json
import os
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# ---------------------------------------------------------------------------
# Storage paths  (override via env var for Streamlit Cloud / Docker)
# ---------------------------------------------------------------------------
DATA_DIR        = os.environ.get("SALCI_DATA_DIR", "salci_data")
PREDICTIONS_DIR = os.path.join(DATA_DIR, "predictions")
RESULTS_DIR     = os.path.join(DATA_DIR, "results")
REFLECTIONS_DIR = os.path.join(DATA_DIR, "reflections")


def ensure_dirs():
    """Create storage directories if they don't exist."""
    for d in [PREDICTIONS_DIR, RESULTS_DIR, REFLECTIONS_DIR]:
        os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------------------
# Prediction storage
# ---------------------------------------------------------------------------

def save_daily_predictions(date_str: str, predictions: Dict) -> bool:
    """Save pitcher predictions before games start."""
    ensure_dirs()
    predictions["saved_at"] = datetime.now().isoformat()
    filepath = os.path.join(PREDICTIONS_DIR, f"{date_str}.json")
    try:
        with open(filepath, "w") as f:
            json.dump(predictions, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving predictions: {e}")
        return False


def load_daily_predictions(date_str: str) -> Optional[Dict]:
    """Load predictions for a given date. Returns None if not found."""
    filepath = os.path.join(PREDICTIONS_DIR, f"{date_str}.json")
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading predictions: {e}")
        return None


def list_prediction_dates() -> List[str]:
    """Return sorted list of dates that have saved predictions."""
    ensure_dirs()
    dates = []
    for fname in os.listdir(PREDICTIONS_DIR):
        if fname.endswith(".json"):
            dates.append(fname.replace(".json", ""))
    return sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# Results collection  (MLB Stats API box scores)
# ---------------------------------------------------------------------------

def fetch_game_results(date_str: str) -> List[Dict]:
    """
    Fetch actual starting-pitcher results from completed games on date_str.

    Returns list of dicts:
        pitcher_id, pitcher_name, team, actual_ks, actual_ip, game_pk
    """
    schedule_url = (
        f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
        f"&hydrate=linescore,decisions,probablePitcher"
    )
    results = []
    try:
        sched = requests.get(schedule_url, timeout=15).json()
        if not sched.get("dates"):
            return []

        for game in sched["dates"][0].get("games", []):
            game_pk = game.get("gamePk")
            # Only process finished games
            if game.get("status", {}).get("abstractGameState", "") != "Final":
                continue

            try:
                box_url  = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
                box_data = requests.get(box_url, timeout=15).json()

                for side in ["home", "away"]:
                    td      = box_data.get("teams", {}).get(side, {})
                    pitchers= td.get("pitchers", [])
                    players = td.get("players", {})

                    if not pitchers:
                        continue

                    # First pitcher in the list = starting pitcher
                    starter_id   = pitchers[0]
                    starter_data = players.get(f"ID{starter_id}", {})
                    p_stats      = starter_data.get("stats", {}).get("pitching", {})

                    if not p_stats:
                        continue

                    # Parse innings pitched  (e.g. "6.2" = 6⅔)
                    ip_str = str(p_stats.get("inningsPitched", "0.0"))
                    if "." in ip_str:
                        whole, frac = ip_str.split(".")
                        ip = int(whole) + int(frac) / 3
                    else:
                        ip = float(ip_str)

                    results.append({
                        "game_pk":      game_pk,
                        "date":         date_str,
                        "pitcher_id":   starter_id,
                        "pitcher_name": starter_data.get("person", {}).get("fullName", "Unknown"),
                        "team":         td.get("team", {}).get("name", ""),
                        "actual_ks":    int(p_stats.get("strikeOuts", 0)),
                        "actual_ip":    round(ip, 2),
                    })

            except Exception as e:
                print(f"Error processing game {game_pk}: {e}")
                continue

    except Exception as e:
        print(f"Error fetching schedule for {date_str}: {e}")

    return results


def save_daily_results(date_str: str, results: List[Dict]) -> bool:
    """Save raw box-score results."""
    ensure_dirs()
    data     = {"date": date_str, "collected_at": datetime.now().isoformat(), "games": results}
    filepath = os.path.join(RESULTS_DIR, f"{date_str}.json")
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving results: {e}")
        return False


def load_daily_results(date_str: str) -> Optional[Dict]:
    """Load saved box-score results. Returns None if not found."""
    filepath = os.path.join(RESULTS_DIR, f"{date_str}.json")
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading results: {e}")
        return None


# ---------------------------------------------------------------------------
# Reflection generation
# ---------------------------------------------------------------------------

def generate_reflection(date_str: str) -> Optional[Dict]:
    """
    Compare saved predictions against actual results and write a reflection file.

    Requires both predictions and results to exist for date_str.
    Returns the reflection dict, or None if data is missing.
    """
    predictions  = load_daily_predictions(date_str)
    results_data = load_daily_results(date_str)

    if not predictions or not results_data:
        return None

    results       = results_data.get("games", [])
    pred_pitchers = {int(p["pitcher_id"]): p for p in predictions.get("pitchers", []) if p.get("pitcher_id")}
    comparisons   = []

    for result in results:
        pid = int(result["pitcher_id"])
        if pid not in pred_pitchers:
            continue

        pred          = pred_pitchers[pid]
        predicted_ks  = pred.get("expected") or pred.get("predicted_ks") or 0
        actual_ks     = result["actual_ks"]
        k_delta       = actual_ks - predicted_ks

        comparisons.append({
            "pitcher_id":       pid,
            "pitcher_name":     result["pitcher_name"],
            "team":             result["team"],
            "predicted_salci":  pred.get("salci"),
            "predicted_ks":     predicted_ks,
            "stuff_score":      pred.get("stuff_score"),
            "location_score":   pred.get("location_score"),
            "matchup_score":    pred.get("matchup_score"),
            "workload_score":   pred.get("workload_score"),
            "actual_ks":        actual_ks,
            "actual_ip":        result["actual_ip"],
            "k_delta":          round(k_delta, 2),
            # HIT = within 1.5 Ks of projection
            "k_accuracy": (
                "HIT"   if abs(k_delta) <= 1.5 else
                "OVER"  if actual_ks > predicted_ks else
                "UNDER"
            ),
        })

    if not comparisons:
        return None

    n        = len(comparisons)
    hits     = [c for c in comparisons if c["k_accuracy"] == "HIT"]
    overs    = [c for c in comparisons if c["k_accuracy"] == "OVER"]
    unders   = [c for c in comparisons if c["k_accuracy"] == "UNDER"]

    avg_predicted = sum(c["predicted_ks"] for c in comparisons) / n
    avg_actual    = sum(c["actual_ks"]    for c in comparisons) / n
    avg_k_delta   = sum(c["k_delta"]      for c in comparisons) / n
    mae           = sum(abs(c["k_delta"]) for c in comparisons) / n

    # Profile-level accuracy
    stuff_heavy    = [c for c in comparisons if (c.get("stuff_score") or 100) > (c.get("location_score") or 100) + 10]
    location_heavy = [c for c in comparisons if (c.get("location_score") or 100) > (c.get("stuff_score") or 100) + 10]

    stuff_acc    = (len([c for c in stuff_heavy    if c["k_accuracy"] == "HIT"]) / len(stuff_heavy)    if stuff_heavy    else None)
    location_acc = (len([c for c in location_heavy if c["k_accuracy"] == "HIT"]) / len(location_heavy) if location_heavy else None)

    overperformers  = sorted([c for c in comparisons if c["k_delta"] >  1.5], key=lambda x: x["k_delta"], reverse=True)[:5]
    underperformers = sorted([c for c in comparisons if c["k_delta"] < -1.5], key=lambda x: x["k_delta"])[:5]

    # Auto-generate a plain-English lesson
    lesson = _generate_lesson(avg_k_delta, stuff_acc, location_acc, len(hits), n)

    reflection = {
        "date":               date_str,
        "generated_at":       datetime.now().isoformat(),
        "games_tracked":      n,
        # Accuracy counts
        "hits":               len(hits),
        "overs":              len(overs),
        "unders":             len(unders),
        # Key metrics (used by get_rolling_accuracy)
        "accuracy_pct":       round(len(hits) / n * 100, 1),
        "avg_k_delta":        round(avg_k_delta, 2),
        "mae":                round(mae, 2),
        "over_pct":           round(len(overs)  / n * 100, 1),
        "under_pct":          round(len(unders) / n * 100, 1),
        # Averages
        "avg_predicted_ks":   round(avg_predicted, 2),
        "avg_actual_ks":      round(avg_actual, 2),
        # Profile accuracy
        "stuff_heavy_accuracy":    round(stuff_acc,    2) if stuff_acc    is not None else None,
        "location_heavy_accuracy": round(location_acc, 2) if location_acc is not None else None,
        # Sorted performer lists
        "overperformers":  [{"name": c["pitcher_name"], "team": c["team"],
                             "predicted": c["predicted_ks"], "actual": c["actual_ks"],
                             "delta": c["k_delta"], "salci": c.get("predicted_salci")}
                            for c in overperformers],
        "underperformers": [{"name": c["pitcher_name"], "team": c["team"],
                             "predicted": c["predicted_ks"], "actual": c["actual_ks"],
                             "delta": c["k_delta"], "salci": c.get("predicted_salci")}
                            for c in underperformers],
        "lesson":          lesson,
        # Full comparison rows (for detailed table display)
        "comparisons":     comparisons,
    }

    save_reflection(date_str, reflection)
    return reflection


def _generate_lesson(avg_k_delta, stuff_acc, location_acc, hits, total) -> str:
    """Return a plain-English insight string from the day's data."""
    parts = []
    accuracy_pct = round(hits / total * 100) if total else 0
    parts.append(f"Model hit {accuracy_pct}% of K projections within 1.5 Ks ({hits}/{total} starters).")

    if avg_k_delta > 0.5:
        parts.append(f"Projections ran LOW by {avg_k_delta:+.1f} Ks on average — consider boosting K estimates.")
    elif avg_k_delta < -0.5:
        parts.append(f"Projections ran HIGH by {abs(avg_k_delta):.1f} Ks on average — consider trimming K estimates.")
    else:
        parts.append("Projections were well-calibrated.")

    if stuff_acc is not None and location_acc is not None:
        if stuff_acc > location_acc + 0.10:
            parts.append(f"Stuff-heavy pitchers outperformed location-heavy pitchers ({stuff_acc:.0%} vs {location_acc:.0%} accuracy).")
        elif location_acc > stuff_acc + 0.10:
            parts.append(f"Location-heavy pitchers outperformed stuff-heavy pitchers ({location_acc:.0%} vs {stuff_acc:.0%} accuracy).")

    return " ".join(parts)


def save_reflection(date_str: str, reflection: Dict) -> bool:
    """Persist reflection to disk."""
    ensure_dirs()
    filepath = os.path.join(REFLECTIONS_DIR, f"{date_str}.json")
    try:
        with open(filepath, "w") as f:
            json.dump(reflection, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving reflection: {e}")
        return False


def load_reflection(date_str: str) -> Optional[Dict]:
    """Load reflection for a given date. Returns None if not found."""
    filepath = os.path.join(REFLECTIONS_DIR, f"{date_str}.json")
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading reflection: {e}")
        return None


# ---------------------------------------------------------------------------
# Rolling accuracy  (used by Tab 7 — Model Accuracy)
# ---------------------------------------------------------------------------

def get_rolling_accuracy(days: int = 7) -> Dict:
    """
    Aggregate accuracy metrics across the past `days` days.

    Returns dict with keys:
        days_analyzed    — how many days had reflection data
        games_analyzed   — total pitcher-game comparisons
        accuracy_pct     — % projections within 1.5 Ks (0-100)
        avg_k_delta      — mean (actual - predicted); positive = ran low
        mae              — mean absolute error in Ks
        over_pct         — % that went OVER
        under_pct        — % that went UNDER
        tendency         — "OVER" | "UNDER" | "CALIBRATED"
        daily            — list of per-day summary dicts
    """
    all_comparisons = []
    days_with_data  = 0
    daily           = []

    for i in range(1, days + 1):
        check_date = (datetime.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        ref        = load_reflection(check_date)
        if ref and ref.get("comparisons"):
            all_comparisons.extend(ref["comparisons"])
            days_with_data += 1
            daily.append({
                "date":         check_date,
                "games":        ref.get("games_tracked", 0),
                "accuracy_pct": ref.get("accuracy_pct", 0),
                "avg_k_delta":  ref.get("avg_k_delta", 0),
                "mae":          ref.get("mae", 0),
            })

    if not all_comparisons:
        return {
            "days_analyzed":  0,
            "games_analyzed": 0,
            "accuracy_pct":   0,
            "avg_k_delta":    0,
            "mae":            0,
            "over_pct":       0,
            "under_pct":      0,
            "tendency":       "NO DATA",
            "daily":          [],
            "message":        "No historical data yet. Save predictions before games, then collect results afterward.",
        }

    n         = len(all_comparisons)
    hits      = len([c for c in all_comparisons if c["k_accuracy"] == "HIT"])
    overs     = len([c for c in all_comparisons if c["k_accuracy"] == "OVER"])
    unders    = len([c for c in all_comparisons if c["k_accuracy"] == "UNDER"])
    delta_avg = sum(c["k_delta"] for c in all_comparisons) / n
    mae       = sum(abs(c["k_delta"]) for c in all_comparisons) / n

    tendency = ("OVER" if delta_avg > 0.5 else "UNDER" if delta_avg < -0.5 else "CALIBRATED")

    return {
        "days_analyzed":  days_with_data,
        "games_analyzed": n,
        "accuracy_pct":   round(hits  / n * 100, 1),
        "avg_k_delta":    round(delta_avg, 2),
        "mae":            round(mae,       2),
        "over_pct":       round(overs  / n * 100, 1),
        "under_pct":      round(unders / n * 100, 1),
        "tendency":       tendency,
        "daily":          sorted(daily, key=lambda x: x["date"]),
    }


# ---------------------------------------------------------------------------
# High-level convenience
# ---------------------------------------------------------------------------

def collect_and_reflect_yesterday() -> Optional[Dict]:
    """
    One-call function: fetch yesterday's box scores, save them,
    then generate and return the reflection.

    - If reflection already exists for yesterday, returns it immediately.
    - If predictions for yesterday don't exist, returns None.
    """
    yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Already done today → return cached
    existing = load_reflection(yesterday)
    if existing:
        return existing

    # Need predictions to have been saved
    predictions = load_daily_predictions(yesterday)
    if not predictions:
        return None

    # Fetch box scores
    results = fetch_game_results(yesterday)
    if not results:
        return None

    save_daily_results(yesterday, results)
    return generate_reflection(yesterday)


def collect_and_reflect_date(date_str: str, force: bool = False) -> Optional[Dict]:
    """
    Same as collect_and_reflect_yesterday but for any arbitrary date.
    Pass force=True to re-generate even if a reflection already exists.
    """
    if not force:
        existing = load_reflection(date_str)
        if existing:
            return existing

    predictions = load_daily_predictions(date_str)
    if not predictions:
        return None

    results = fetch_game_results(date_str)
    if not results:
        return None

    save_daily_results(date_str, results)
    return generate_reflection(date_str)
