#!/usr/bin/env python3
"""
SALCI Generate Reflection Script
==================================
Runs at ~11 PM ET daily via GitHub Actions (after all games finish).

What it does:
  1. Loads today's saved predictions from data/predictions/YYYY-MM-DD.json
  2. Fetches actual box-score results from MLB Stats API
  3. Compares predicted Ks vs actual Ks for every pitcher
  4. Builds a structured reflection with accuracy stats, over/underperformers
  5. Commits data/reflections/YYYY-MM-DD.json to GitHub (persistent storage)

The Streamlit app's Yesterday tab reads directly from data/reflections/ —
zero manual steps needed.

Usage:
  python scripts/generate_reflection.py              # yesterday
  python scripts/generate_reflection.py 2025-04-12   # specific date
"""

import base64
import json
import os
import sys
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT        = os.path.join(os.path.dirname(__file__), "..")
PREDICTIONS_DIR  = os.path.join(REPO_ROOT, "data", "predictions")
REFLECTIONS_DIR  = os.path.join(REPO_ROOT, "data", "reflections")


def ensure_dirs():
    os.makedirs(PREDICTIONS_DIR, exist_ok=True)
    os.makedirs(REFLECTIONS_DIR, exist_ok=True)


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# LOAD PREDICTIONS
# ─────────────────────────────────────────────────────────────────────────────

def load_predictions(date_str: str) -> Optional[Dict]:
    """Load predictions saved by save_predictions.py."""
    path = os.path.join(PREDICTIONS_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        log(f"  No predictions file found: {path}")
        return None
    with open(path) as f:
        return json.load(f)


def load_predictions_from_github(date_str: str) -> Optional[Dict]:
    """
    Fallback: fetch predictions JSON directly from GitHub raw content.
    Used when the Actions runner doesn't have the file locally (e.g. first run).
    """
    token   = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    gh_repo = os.environ.get("GH_REPO")
    if not token or not gh_repo:
        return None

    url = (
        f"https://api.github.com/repos/{gh_repo}/contents/"
        f"data/predictions/{date_str}.json"
    )
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            import base64 as b64
            content = b64.b64decode(r.json()["content"]).decode()
            return json.loads(content)
    except Exception as e:
        log(f"  Could not fetch predictions from GitHub: {e}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# MLB API — BOX SCORES
# ─────────────────────────────────────────────────────────────────────────────

def get_game_pks_for_date(date_str: str) -> List[int]:
    """Return all game PKs that are Final for a given date."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("dates"):
            return []
        pks = []
        for g in data["dates"][0].get("games", []):
            if g.get("status", {}).get("abstractGameState", "") == "Final":
                pks.append(g["gamePk"])
        return pks
    except Exception as e:
        log(f"  ERROR fetching schedule: {e}")
        return []


def get_pitcher_results_from_boxscore(game_pk: int) -> List[Dict]:
    """
    Parse a game's boxscore and return actual pitching stats for every pitcher.
    Returns list of dicts with pitcher_id, pitcher_name, team, actual_ks, actual_ip.
    """
    url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(f"    ERROR boxscore {game_pk}: {e}")
        return []

    results = []
    for side in ("home", "away"):
        team_data = data.get("teams", {}).get(side, {})
        team_name = team_data.get("team", {}).get("name", "Unknown")

        for pid in team_data.get("pitchers", []):
            pkey   = f"ID{pid}"
            pdata  = team_data.get("players", {}).get(pkey, {})
            stats  = pdata.get("stats", {}).get("pitching", {})

            if not stats:
                continue

            # Parse IP (MLB stores "6.2" as 6 + 2/3 innings)
            ip_raw = str(stats.get("inningsPitched", "0.0"))
            parts  = ip_raw.split(".")
            ip     = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)

            so = int(stats.get("strikeOuts", 0))
            np = int(stats.get("numberOfPitches", 0))

            # Only include starting pitchers (faced enough batters OR 3+ IP)
            tbf = int(stats.get("battersFaced", 0))
            if ip < 1.0 and tbf < 4:
                continue

            results.append({
                "game_pk":     game_pk,
                "pitcher_id":  pid,
                "pitcher_name": pdata.get("person", {}).get("fullName", "Unknown"),
                "team":        team_name,
                "actual_ks":   so,
                "actual_ip":   round(ip, 2),
                "pitch_count": np,
                "note":        stats.get("note", ""),
            })

    return results


def fetch_all_results(date_str: str) -> List[Dict]:
    """Fetch actual pitching results for all Final games on date_str."""
    log(f"  Fetching box scores for {date_str} …")
    pks = get_game_pks_for_date(date_str)
    log(f"  Found {len(pks)} Final games")

    all_results = []
    for pk in pks:
        game_results = get_pitcher_results_from_boxscore(pk)
        all_results.extend(game_results)
        log(f"    game {pk}: {len(game_results)} pitchers")

    return all_results


# ─────────────────────────────────────────────────────────────────────────────
# REFLECTION GENERATION
# ─────────────────────────────────────────────────────────────────────────────

# "HIT" = predicted within this many Ks
K_ACCURACY_THRESHOLD = 1.5


def classify_accuracy(k_delta: float) -> str:
    """Label a prediction: HIT / OVER / UNDER."""
    if abs(k_delta) <= K_ACCURACY_THRESHOLD:
        return "HIT"
    return "OVER" if k_delta > 0 else "UNDER"


def generate_reflection(date_str: str, predictions: Dict, results: List[Dict]) -> Dict:
    """
    Core comparison logic:
      predictions  — from save_predictions.py
      results      — from MLB box scores
    Returns a structured reflection dict ready to be saved + displayed.
    """
    # Build lookup: pitcher_id → prediction
    pred_by_id: Dict[int, Dict] = {
        int(p["pitcher_id"]): p
        for p in predictions.get("pitchers", [])
    }

    comparisons = []
    unmatched_results = []

    for result in results:
        pid  = int(result["pitcher_id"])
        pred = pred_by_id.get(pid)

        if not pred:
            unmatched_results.append(result["pitcher_name"])
            continue

        predicted_ks = pred.get("expected") or 0.0
        actual_ks    = result["actual_ks"]
        k_delta      = actual_ks - predicted_ks

        comparisons.append({
            "pitcher_id":     pid,
            "pitcher_name":   result["pitcher_name"],
            "team":           result["team"],
            # Prediction side
            "predicted_salci":  pred.get("salci"),
            "salci_grade":      pred.get("salci_grade"),
            "predicted_ks":     round(predicted_ks, 1),
            "projected_ip":     pred.get("projected_ip"),
            "stuff_score":      pred.get("stuff_score"),
            "location_score":   pred.get("location_score"),
            "matchup_score":    pred.get("matchup_score"),
            "workload_score":   pred.get("workload_score"),
            "k_lines":          pred.get("k_lines", {}),
            # Actual side
            "actual_ks":        actual_ks,
            "actual_ip":        result["actual_ip"],
            "pitch_count":      result.get("pitch_count"),
            # Analysis
            "k_delta":          round(k_delta, 1),
            "k_accuracy":       classify_accuracy(k_delta),
        })

    if not comparisons:
        log("  No comparisons possible — no prediction/result overlap")
        return {
            "date":            date_str,
            "generated_at":    datetime.now().isoformat(),
            "status":          "no_overlap",
            "games_tracked":   0,
            "comparisons":     [],
            "summary":         {},
        }

    # ── Aggregate stats ──────────────────────────────────────────────────────
    n       = len(comparisons)
    hits    = [c for c in comparisons if c["k_accuracy"] == "HIT"]
    overs   = [c for c in comparisons if c["k_accuracy"] == "OVER"]
    unders  = [c for c in comparisons if c["k_accuracy"] == "UNDER"]

    avg_pred   = sum(c["predicted_ks"] for c in comparisons) / n
    avg_actual = sum(c["actual_ks"]    for c in comparisons) / n
    avg_delta  = sum(c["k_delta"]      for c in comparisons) / n

    # Top overperformers & underperformers
    overperformers  = sorted([c for c in comparisons if c["k_delta"] >  1.5],
                              key=lambda x: x["k_delta"], reverse=True)[:5]
    underperformers = sorted([c for c in comparisons if c["k_delta"] < -1.5],
                              key=lambda x: x["k_delta"])[:5]

    # Profile breakdown (Stuff-heavy vs Location-heavy accuracy)
    stuff_heavy = [
        c for c in comparisons
        if (c.get("stuff_score") or 100) > (c.get("location_score") or 100) + 10
    ]
    loc_heavy = [
        c for c in comparisons
        if (c.get("location_score") or 100) > (c.get("stuff_score") or 100) + 10
    ]

    def acc_pct(lst):
        if not lst:
            return None
        return round(sum(1 for c in lst if c["k_accuracy"] == "HIT") / len(lst) * 100, 1)

    # Generate insight sentence
    tendency = (
        "overprojecting (model runs HOT)" if avg_delta < -0.5
        else "underprojecting (model runs COLD)" if avg_delta > 0.5
        else "well-calibrated"
    )

    s_acc = acc_pct(stuff_heavy)
    l_acc = acc_pct(loc_heavy)
    if s_acc is not None and l_acc is not None:
        if l_acc > s_acc + 5:
            profile_insight = f"Location-dominant pitchers outperformed stuff-heavy picks ({l_acc}% vs {s_acc}% accuracy)"
        elif s_acc > l_acc + 5:
            profile_insight = f"Stuff-dominant pitchers outperformed location picks ({s_acc}% vs {l_acc}% accuracy)"
        else:
            profile_insight = "Stuff-heavy and location-heavy pitchers performed similarly"
    else:
        profile_insight = "Insufficient profile data for comparison"

    reflection = {
        "date":          date_str,
        "generated_at":  datetime.now().isoformat(),
        "status":        "complete",
        "games_tracked": n,
        "summary": {
            "avg_predicted_ks":   round(avg_pred,   1),
            "avg_actual_ks":      round(avg_actual, 1),
            "avg_k_delta":        round(avg_delta,  2),
            "accuracy_pct":       round(len(hits) / n * 100, 1),
            "hits":               len(hits),
            "overs":              len(overs),
            "unders":             len(unders),
            "tendency":           tendency,
            "stuff_heavy_accuracy":    s_acc,
            "location_heavy_accuracy": l_acc,
            "profile_insight":    profile_insight,
        },
        "overperformers":  [
            {
                "pitcher_name": c["pitcher_name"],
                "team":         c["team"],
                "predicted_ks": c["predicted_ks"],
                "actual_ks":    c["actual_ks"],
                "k_delta":      c["k_delta"],
                "salci":        c["predicted_salci"],
            }
            for c in overperformers
        ],
        "underperformers": [
            {
                "pitcher_name": c["pitcher_name"],
                "team":         c["team"],
                "predicted_ks": c["predicted_ks"],
                "actual_ks":    c["actual_ks"],
                "k_delta":      c["k_delta"],
                "salci":        c["predicted_salci"],
            }
            for c in underperformers
        ],
        "unmatched_pitchers": unmatched_results,
        "comparisons": comparisons,
    }

    return reflection


# ─────────────────────────────────────────────────────────────────────────────
# PERSIST TO GITHUB
# ─────────────────────────────────────────────────────────────────────────────

def save_locally(date_str: str, data: Dict) -> str:
    ensure_dirs()
    path = os.path.join(REFLECTIONS_DIR, f"{date_str}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    log(f"  Saved → {path}")
    return path


def commit_to_github(local_path: str, repo_path: str, commit_msg: str) -> bool:
    token   = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    gh_repo = os.environ.get("GH_REPO")
    if not token or not gh_repo:
        log("  WARN: GH_TOKEN/GH_REPO not set — skipping GitHub commit")
        return False

    api_url = f"https://api.github.com/repos/{gh_repo}/contents/{repo_path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    sha = None
    try:
        r = requests.get(api_url, headers=headers, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass

    payload = {"message": commit_msg, "content": content_b64}
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(api_url, headers=headers, json=payload, timeout=30)
        if r.status_code in (200, 201):
            log(f"  ✅ GitHub commit OK: {repo_path}")
            return True
        log(f"  ERROR: {r.status_code} — {r.text[:300]}")
        return False
    except Exception as e:
        log(f"  ERROR: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Default: reflect on yesterday (script runs late at night / early AM)
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    log(f"=== generate_reflection.py  date={date_str} ===")

    # Check if reflection already exists
    existing_path = os.path.join(REFLECTIONS_DIR, f"{date_str}.json")
    if os.path.exists(existing_path):
        log(f"  Reflection already exists locally for {date_str} — skipping")
        sys.exit(0)

    # Load predictions
    predictions = load_predictions(date_str) or load_predictions_from_github(date_str)
    if not predictions:
        log(f"  No predictions found for {date_str} — cannot generate reflection")
        sys.exit(1)

    log(f"  Loaded {len(predictions.get('pitchers', []))} predictions")

    # Fetch results
    results = fetch_all_results(date_str)
    if not results:
        log(f"  No results found for {date_str} — games may not be final yet")
        sys.exit(1)

    log(f"  Fetched {len(results)} pitcher results")

    # Generate reflection
    reflection = generate_reflection(date_str, predictions, results)
    log(f"  Reflection: {reflection['games_tracked']} comparisons, "
        f"accuracy={reflection.get('summary', {}).get('accuracy_pct', 'N/A')}%")

    # Save
    local = save_locally(date_str, reflection)
    commit_to_github(
        local,
        f"data/reflections/{date_str}.json",
        f"chore(data): reflection {date_str} "
        f"[{reflection['games_tracked']} games, "
        f"{reflection.get('summary', {}).get('accuracy_pct', '?')}% acc]",
    )

    log("=== Done ===")


if __name__ == "__main__":
    main()
