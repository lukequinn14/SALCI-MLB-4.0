"""
SALCI Prediction Storage & Reflection System
v4.0

Stores daily predictions before games, collects results after,
and generates reflection insights for model improvement.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import requests

# =============================================================================
# STORAGE PATHS
# =============================================================================

# For Streamlit Cloud, use /tmp or relative paths
# For local, use data/ directory
DATA_DIR = os.environ.get("SALCI_DATA_DIR", "salci_data")
PREDICTIONS_DIR = os.path.join(DATA_DIR, "predictions")
RESULTS_DIR = os.path.join(DATA_DIR, "results")
REFLECTIONS_DIR = os.path.join(DATA_DIR, "reflections")


def ensure_dirs():
    """Create data directories if they don't exist."""
    for d in [PREDICTIONS_DIR, RESULTS_DIR, REFLECTIONS_DIR]:
        os.makedirs(d, exist_ok=True)


# =============================================================================
# PREDICTION STORAGE
# =============================================================================

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
    """Load predictions for a given date."""
    filepath = os.path.join(PREDICTIONS_DIR, f"{date_str}.json")
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading predictions: {e}")
        return None


# =============================================================================
# RESULTS COLLECTION
# =============================================================================

def fetch_game_results(date_str: str) -> List[Dict]:
    """Fetch actual game results from MLB API."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=linescore,decisions,probablePitcher"
    try:
        response = requests.get(url, timeout=15)
        data = response.json()
        if not data.get("dates"): return []
        results = []
        for game in data["dates"][0].get("games", []):
            game_pk = game.get("gamePk")
            if game.get("status", {}).get("abstractGameState", "") != "Final": continue
            box_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
            box_data = requests.get(box_url, timeout=15).json()
            for side in ["home", "away"]:
                team_data = box_data.get("teams", {}).get(side, {})
                pitchers = team_data.get("pitchers", [])
                players = team_data.get("players", {})
                if not pitchers: continue
                starter_id = pitchers[0]
                starter_data = players.get(f"ID{starter_id}", {})
                stats = starter_data.get("stats", {}).get("pitching", {})
                if not stats: continue
                ip_str = stats.get("inningsPitched", "0.0")
                if "." in ip_str:
                    parts = ip_str.split(".")
                    ip = int(parts[0]) + int(parts[1]) / 3
                else: ip = float(ip_str)
                results.append({
                    "game_pk": game_pk,
                    "date": date_str,
                    "pitcher_id": starter_id,
                    "pitcher_name": starter_data.get("person", {}).get("fullName", "Unknown"),
                    "team": team_data.get("team", {}).get("name", ""),
                    "actual_ks": int(stats.get("strikeOuts", 0)),
                    "actual_ip": round(ip, 1),
                })
        return results
    except Exception as e:
        print(f"Error fetching results: {e}")
        return []


def save_daily_results(date_str: str, results: List[Dict]) -> bool:
    """Save actual game results."""
    ensure_dirs()
    data = {"date": date_str, "collected_at": datetime.now().isoformat(), "games": results}
    filepath = os.path.join(RESULTS_DIR, f"{date_str}.json")
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving results: {e}")
        return False


def load_daily_results(date_str: str) -> Optional[Dict]:
    """Load results for a given date."""
    filepath = os.path.join(RESULTS_DIR, f"{date_str}.json")
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading results: {e}")
        return None


# =============================================================================
# REFLECTION GENERATION
# =============================================================================

def generate_reflection(date_str: str) -> Optional[Dict]:
    """Generate Yesterday's Reflection by comparing predictions to results."""
    predictions = load_daily_predictions(date_str)
    results_data = load_daily_results(date_str)
    if not predictions or not results_data: return None
    results = results_data.get("games", [])
    pred_pitchers = {p["pitcher_id"]: p for p in predictions.get("pitchers", [])}
    comparisons = []
    for result in results:
        pid = result["pitcher_id"]
        if pid not in pred_pitchers: continue
        pred = pred_pitchers[pid]
        comparison = {
            "pitcher_id": pid,
            "pitcher_name": result["pitcher_name"],
            "team": result["team"],
            "predicted_salci": pred.get("salci"),
            "predicted_ks": pred.get("expected"),
            "stuff_score": pred.get("stuff_score"),
            "location_score": pred.get("location_score"),
            "actual_ks": result["actual_ks"],
            "actual_ip": result["actual_ip"],
            "k_delta": result["actual_ks"] - pred.get("expected", 0),
            "k_accuracy": "HIT" if abs(result["actual_ks"] - pred.get("expected", 0)) <= 1.5 else (
                "OVER" if result["actual_ks"] > pred.get("expected", 0) else "UNDER"
            ),
        }
        comparisons.append(comparison)
    if not comparisons: return None
    total_projected_ks = sum(c["predicted_ks"] or 0 for c in comparisons)
    total_actual_ks = sum(c["actual_ks"] for c in comparisons)
    hits = len([c for c in comparisons if c["k_accuracy"] == "HIT"])
    overperformers = sorted([c for c in comparisons if c["k_delta"] > 1.5], key=lambda x: x["k_delta"], reverse=True)[:5]
    underperformers = sorted([c for c in comparisons if c["k_delta"] < -1.5], key=lambda x: x["k_delta"])[:5]
    
    # Profile analysis
    stuff_heavy = [c for c in comparisons if (c.get("stuff_score") or 100) > (c.get("location_score") or 100) + 10]
    location_heavy = [c for c in comparisons if (c.get("location_score") or 100) > (c.get("stuff_score") or 100) + 10]
    stuff_accuracy = len([c for c in stuff_heavy if c["k_accuracy"] == "HIT"]) / len(stuff_heavy) if stuff_heavy else None
    location_accuracy = len([c for c in location_heavy if c["k_accuracy"] == "HIT"]) / len(location_heavy) if location_heavy else None
    
    reflection = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "games_tracked": len(comparisons),
        "projection_accuracy": round(hits / len(comparisons), 2) if comparisons else 0,
        "hits": hits,
        "overs": len([c for c in comparisons if c["k_accuracy"] == "OVER"]),
        "unders": len([c for c in comparisons if c["k_accuracy"] == "UNDER"]),
        "stuff_heavy_accuracy": round(stuff_accuracy, 2) if stuff_accuracy else None,
        "location_heavy_accuracy": round(location_accuracy, 2) if location_accuracy else None,
        "overperformers": [{"name": c["pitcher_name"], "projected": c["predicted_ks"], "actual": c["actual_ks"], "delta": round(c["k_delta"], 1)} for c in overperformers],
        "underperformers": [{"name": c["pitcher_name"], "projected": c["predicted_ks"], "actual": c["actual_ks"], "delta": round(c["k_delta"], 1)} for c in underperformers],
        "comparisons": comparisons
    }
    save_reflection(date_str, reflection)
    return reflection


def save_reflection(date_str: str, reflection: Dict) -> bool:
    """Save reflection data."""
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
    """Load reflection for a given date."""
    filepath = os.path.join(REFLECTIONS_DIR, f"{date_str}.json")
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading reflection: {e}")
        return None


def get_rolling_accuracy(days: int = 7) -> Dict:
    """Calculate rolling accuracy over the past N days."""
    end_date = datetime.today()
    all_comparisons = []
    days_with_data = 0
    for i in range(1, days + 1):
        check_date = (end_date - timedelta(days=i)).strftime("%Y-%m-%d")
        reflection = load_reflection(check_date)
        if reflection and reflection.get("comparisons"):
            all_comparisons.extend(reflection["comparisons"])
            days_with_data += 1
    if not all_comparisons: return {"days_analyzed": 0, "games_analyzed": 0, "message": "No historical data available"}
    total = len(all_comparisons)
    hits = len([c for c in all_comparisons if c["k_accuracy"] == "HIT"])
    avg_k_delta = sum(c["k_delta"] for c in all_comparisons) / total
    return {
        "days_analyzed": days_with_data,
        "games_analyzed": total,
        "accuracy_pct": round(hits / total * 100, 1),
        "avg_k_delta": round(avg_k_delta, 2),
        "tendency": "OVER" if avg_k_delta > 0.5 else ("UNDER" if avg_k_delta < -0.5 else "CALIBRATED")
    }


def collect_and_reflect_yesterday() -> Optional[Dict]:
    """Collect yesterday's results and generate reflection."""
    yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    existing = load_reflection(yesterday)
    if existing: return existing
    predictions = load_daily_predictions(yesterday)
    if not predictions: return None
    results = fetch_game_results(yesterday)
    if not results: return None
    save_daily_results(yesterday, results)
    return generate_reflection(yesterday)
