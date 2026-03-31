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
DATA_DIR = os.environ.get("SALCI_DATA_DIR", "data")
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
    """
    Save pitcher predictions before games start.
    
    predictions format:
    {
        "date": "2025-03-30",
        "generated_at": "2025-03-30T10:30:00",
        "model_version": "4.0",
        "pitchers": [
            {
                "pitcher_id": 12345,
                "pitcher_name": "Chase Burns",
                "team": "Pirates",
                "opponent": "Reds",
                "game_pk": 746321,
                "salci_score": 78.8,
                "stuff_score": 82,
                "location_score": 71,
                "profile_type": "STUFF-DOMINANT",
                "expected_ks": 7.2,
                "k_lines": {5: 94, 6: 94, 7: 94},
                "expected_ip": 5.8,
            },
            ...
        ],
        "hitters": [
            {
                "hitter_id": 67890,
                "hitter_name": "Joey Wiemer",
                "team": "Nationals",
                "vs_pitcher": "Taijuan Walker",
                "game_pk": 746322,
                "hit_score": 85,
                "hit_probability": 0.42,
            },
            ...
        ]
    }
    """
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
    """
    Fetch actual game results from MLB API.
    
    Returns list of game results with pitcher performance.
    """
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=linescore,decisions,probablePitcher"
    
    try:
        response = requests.get(url, timeout=15)
        data = response.json()
        
        if not data.get("dates"):
            return []
        
        results = []
        
        for game in data["dates"][0].get("games", []):
            game_pk = game.get("gamePk")
            status = game.get("status", {}).get("abstractGameState", "")
            
            # Only process completed games
            if status != "Final":
                continue
            
            # Get box score for detailed stats
            box_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
            box_response = requests.get(box_url, timeout=15)
            box_data = box_response.json()
            
            for side in ["home", "away"]:
                team_data = box_data.get("teams", {}).get(side, {})
                pitchers = team_data.get("pitchers", [])
                players = team_data.get("players", {})
                
                if not pitchers:
                    continue
                
                # Get starting pitcher (first in list)
                starter_id = pitchers[0]
                starter_key = f"ID{starter_id}"
                starter_data = players.get(starter_key, {})
                
                stats = starter_data.get("stats", {}).get("pitching", {})
                
                if not stats:
                    continue
                
                # Parse innings pitched
                ip_str = stats.get("inningsPitched", "0.0")
                if "." in ip_str:
                    parts = ip_str.split(".")
                    ip = int(parts[0]) + int(parts[1]) / 3
                else:
                    ip = float(ip_str)
                
                results.append({
                    "game_pk": game_pk,
                    "date": date_str,
                    "pitcher_id": starter_id,
                    "pitcher_name": starter_data.get("person", {}).get("fullName", "Unknown"),
                    "team": team_data.get("team", {}).get("name", ""),
                    "side": side,
                    "actual_ks": int(stats.get("strikeOuts", 0)),
                    "actual_ip": round(ip, 1),
                    "hits_allowed": int(stats.get("hits", 0)),
                    "walks": int(stats.get("baseOnBalls", 0)),
                    "earned_runs": int(stats.get("earnedRuns", 0)),
                    "pitches": int(stats.get("numberOfPitches", 0)),
                    "decision": stats.get("note", ""),  # W, L, ND
                })
        
        return results
        
    except Exception as e:
        print(f"Error fetching results: {e}")
        return []


def save_daily_results(date_str: str, results: List[Dict]) -> bool:
    """Save actual game results."""
    ensure_dirs()
    
    data = {
        "date": date_str,
        "collected_at": datetime.now().isoformat(),
        "games": results
    }
    
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
    
    if not os.path.exists(filepath):
        return None
    
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
    """
    Generate Yesterday's Reflection by comparing predictions to results.
    
    Returns comprehensive reflection data.
    """
    predictions = load_daily_predictions(date_str)
    results_data = load_daily_results(date_str)
    
    if not predictions or not results_data:
        return None
    
    results = results_data.get("games", [])
    pred_pitchers = {p["pitcher_id"]: p for p in predictions.get("pitchers", [])}
    
    # Match predictions to results
    comparisons = []
    
    for result in results:
        pid = result["pitcher_id"]
        
        if pid not in pred_pitchers:
            continue
        
        pred = pred_pitchers[pid]
        
        comparison = {
            "pitcher_id": pid,
            "pitcher_name": result["pitcher_name"],
            "team": result["team"],
            
            # Predictions
            "predicted_salci": pred.get("salci_score"),
            "predicted_ks": pred.get("expected_ks"),
            "predicted_ip": pred.get("expected_ip"),
            "stuff_score": pred.get("stuff_score"),
            "location_score": pred.get("location_score"),
            "profile_type": pred.get("profile_type"),
            
            # Actuals
            "actual_ks": result["actual_ks"],
            "actual_ip": result["actual_ip"],
            
            # Deltas
            "k_delta": result["actual_ks"] - pred.get("expected_ks", 0),
            "ip_delta": result["actual_ip"] - pred.get("expected_ip", 0),
            
            # Classification
            "k_accuracy": "HIT" if abs(result["actual_ks"] - pred.get("expected_ks", 0)) <= 1.5 else (
                "OVER" if result["actual_ks"] > pred.get("expected_ks", 0) else "UNDER"
            ),
        }
        
        comparisons.append(comparison)
    
    if not comparisons:
        return None
    
    # Calculate aggregate stats
    total_projected_ks = sum(c["predicted_ks"] or 0 for c in comparisons)
    total_actual_ks = sum(c["actual_ks"] for c in comparisons)
    
    total_projected_ip = sum(c["predicted_ip"] or 0 for c in comparisons)
    total_actual_ip = sum(c["actual_ip"] for c in comparisons)
    
    hits = len([c for c in comparisons if c["k_accuracy"] == "HIT"])
    
    # Find overperformers and underperformers
    overperformers = sorted(
        [c for c in comparisons if c["k_delta"] > 1.5],
        key=lambda x: x["k_delta"],
        reverse=True
    )[:5]
    
    underperformers = sorted(
        [c for c in comparisons if c["k_delta"] < -1.5],
        key=lambda x: x["k_delta"]
    )[:5]
    
    # Analyze by profile type
    stuff_heavy = [c for c in comparisons if c.get("profile_type") == "STUFF-DOMINANT"]
    location_heavy = [c for c in comparisons if c.get("profile_type") == "LOCATION-DOMINANT"]
    
    stuff_accuracy = len([c for c in stuff_heavy if c["k_accuracy"] == "HIT"]) / len(stuff_heavy) if stuff_heavy else None
    location_accuracy = len([c for c in location_heavy if c["k_accuracy"] == "HIT"]) / len(location_heavy) if location_heavy else None
    
    # Generate insight
    insight = generate_insight(stuff_accuracy, location_accuracy, hits / len(comparisons) if comparisons else 0)
    
    reflection = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "games_tracked": len(comparisons),
        
        # Aggregate stats
        "avg_projected_ks": round(total_projected_ks / len(comparisons), 1) if comparisons else 0,
        "avg_actual_ks": round(total_actual_ks / len(comparisons), 1) if comparisons else 0,
        "avg_projected_ip": round(total_projected_ip / len(comparisons), 1) if comparisons else 0,
        "avg_actual_ip": round(total_actual_ip / len(comparisons), 1) if comparisons else 0,
        
        # Accuracy
        "projection_accuracy": round(hits / len(comparisons), 2) if comparisons else 0,
        "hits": hits,
        "overs": len([c for c in comparisons if c["k_accuracy"] == "OVER"]),
        "unders": len([c for c in comparisons if c["k_accuracy"] == "UNDER"]),
        
        # Profile analysis
        "stuff_heavy_count": len(stuff_heavy),
        "stuff_heavy_accuracy": round(stuff_accuracy, 2) if stuff_accuracy else None,
        "location_heavy_count": len(location_heavy),
        "location_heavy_accuracy": round(location_accuracy, 2) if location_accuracy else None,
        
        # Notable performances
        "overperformers": [
            {
                "name": c["pitcher_name"],
                "projected": c["predicted_ks"],
                "actual": c["actual_ks"],
                "delta": round(c["k_delta"], 1)
            }
            for c in overperformers
        ],
        "underperformers": [
            {
                "name": c["pitcher_name"],
                "projected": c["predicted_ks"],
                "actual": c["actual_ks"],
                "delta": round(c["k_delta"], 1)
            }
            for c in underperformers
        ],
        
        # Insight
        "insight": insight,
        
        # Raw comparisons for detailed analysis
        "comparisons": comparisons
    }
    
    # Save reflection
    save_reflection(date_str, reflection)
    
    return reflection


def generate_insight(stuff_accuracy: Optional[float], location_accuracy: Optional[float], overall_accuracy: float) -> str:
    """Generate a human-readable insight from the reflection data."""
    insights = []
    
    # Overall accuracy insight
    if overall_accuracy >= 0.75:
        insights.append("Strong prediction day - model is calibrated well")
    elif overall_accuracy >= 0.60:
        insights.append("Solid prediction day - model performed above average")
    elif overall_accuracy >= 0.45:
        insights.append("Mixed results - model accuracy was average")
    else:
        insights.append("Rough day for predictions - review model assumptions")
    
    # Profile comparison insight
    if stuff_accuracy is not None and location_accuracy is not None:
        diff = stuff_accuracy - location_accuracy
        if diff > 0.15:
            insights.append("Stuff-heavy pitchers significantly outperformed location-heavy picks")
        elif diff < -0.15:
            insights.append("Location-heavy pitchers outperformed stuff-heavy picks")
        else:
            insights.append("Stuff and location profiles performed similarly")
    
    return ". ".join(insights) + "."


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
    
    if not os.path.exists(filepath):
        return None
    
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading reflection: {e}")
        return None


# =============================================================================
# ROLLING ACCURACY
# =============================================================================

def get_rolling_accuracy(days: int = 7) -> Dict:
    """
    Calculate rolling accuracy over the past N days.
    
    Returns aggregate stats for the model's recent performance.
    """
    end_date = datetime.today()
    
    all_comparisons = []
    days_with_data = 0
    
    for i in range(1, days + 1):
        check_date = (end_date - timedelta(days=i)).strftime("%Y-%m-%d")
        reflection = load_reflection(check_date)
        
        if reflection and reflection.get("comparisons"):
            all_comparisons.extend(reflection["comparisons"])
            days_with_data += 1
    
    if not all_comparisons:
        return {
            "days_analyzed": 0,
            "games_analyzed": 0,
            "message": "No historical data available"
        }
    
    total = len(all_comparisons)
    hits = len([c for c in all_comparisons if c["k_accuracy"] == "HIT"])
    
    avg_k_delta = sum(c["k_delta"] for c in all_comparisons) / total
    avg_ip_delta = sum(c["ip_delta"] for c in all_comparisons) / total
    
    return {
        "days_analyzed": days_with_data,
        "games_analyzed": total,
        "accuracy_pct": round(hits / total * 100, 1),
        "avg_k_delta": round(avg_k_delta, 2),
        "avg_ip_delta": round(avg_ip_delta, 2),
        "tendency": "OVER" if avg_k_delta > 0.5 else ("UNDER" if avg_k_delta < -0.5 else "CALIBRATED"),
        "recommendation": get_calibration_recommendation(avg_k_delta, avg_ip_delta)
    }


def get_calibration_recommendation(avg_k_delta: float, avg_ip_delta: float) -> str:
    """Generate model calibration recommendation based on recent performance."""
    recs = []
    
    if avg_k_delta > 0.75:
        recs.append("Model is under-projecting Ks - consider increasing baseline K expectations")
    elif avg_k_delta < -0.75:
        recs.append("Model is over-projecting Ks - consider reducing K expectations or adding workload penalty")
    
    if avg_ip_delta < -0.5:
        recs.append("Pitchers consistently falling short on innings - add stronger workload/pitch count factor")
    
    if not recs:
        recs.append("Model is well-calibrated - no adjustments recommended")
    
    return ". ".join(recs)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_yesterday_date() -> str:
    """Get yesterday's date string."""
    return (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")


def collect_and_reflect_yesterday() -> Optional[Dict]:
    """
    Convenience function to collect yesterday's results and generate reflection.
    Call this daily after games complete.
    """
    yesterday = get_yesterday_date()
    
    # Check if we already have reflection
    existing = load_reflection(yesterday)
    if existing:
        return existing
    
    # Check if we have predictions
    predictions = load_daily_predictions(yesterday)
    if not predictions:
        print(f"No predictions found for {yesterday}")
        return None
    
    # Fetch results
    results = fetch_game_results(yesterday)
    if not results:
        print(f"No results available for {yesterday}")
        return None
    
    # Save results
    save_daily_results(yesterday, results)
    
    # Generate reflection
    reflection = generate_reflection(yesterday)
    
    return reflection
