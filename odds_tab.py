#!/usr/bin/env python3
"""
SALCI Odds Intelligence Tab — odds_tab.py
==========================================
Production-grade sportsbook edge detection and prop analysis.

Integrates with The Odds API (https://the-odds-api.com) to pull live
MLB player prop lines, then overlays SALCI projections to surface edges.

Plug-in pattern (add to mlb_salci_full.py):
--------------------------------------------
    try:
        from odds_tab import render_odds_tab
        ODDS_TAB_AVAILABLE = True
    except ImportError:
        ODDS_TAB_AVAILABLE = False

    # Inside main() tab block, add a new tab:
    tab1, ..., tab9 = st.tabs([..., "💰 Odds Intelligence"])

    with tab9:
        if ODDS_TAB_AVAILABLE:
            render_odds_tab(pitchers_data, games)
        else:
            st.error("odds_tab.py not found.")

Secrets required (st.secrets or .streamlit/secrets.toml):
    [odds]
    api_key = "YOUR_ODDS_API_KEY"          # https://the-odds-api.com
    # Optional override – defaults work for most users:
    # regions = "us"
    # markets = "batter_hits,batter_strikeouts,pitcher_strikeouts"

API key is FREE tier (500 req/month) — more than enough for daily use.
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st
import os

try:
    import pytz as _pytz
    _PYTZ_OK = True
except ImportError:
    _PYTZ_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# BALLDONTLIE INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

def fetch_balldontlie_games(date_str: str) -> list:
    """Fetch today's MLB games from BallDontLie API."""
    api_key = (
        st.secrets.get("BALLDONTLIE_API_KEY") or
        os.environ.get("BALLDONTLIE_API_KEY", "")
    )
    if not api_key:
        return []
    try:
        url = "https://api.balldontlie.io/mlb/v1/games"
        headers = {"Authorization": api_key}
        params = {"dates[]": date_str, "per_page": 30}
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            return r.json().get("data", [])
        return []
    except Exception:
        return []


def fetch_apisports_odds(date_str: str) -> list:
    """Fetch MLB odds from API-Sports as fallback when The Odds API is unavailable."""
    api_key = (
        st.secrets.get("APISPORTS_KEY") or
        os.environ.get("APISPORTS_KEY", "")
    )
    if not api_key:
        return []
    try:
        url = "https://v1.baseball.api-sports.io/odds"
        headers = {
            "x-apisports-key": api_key,
            "x-rapidapi-host": "v1.baseball.api-sports.io",
        }
        params = {
            "league":    "1",
            "season":    "2026",
            "date":      date_str,
            "bookmaker": "5",
        }
        r = requests.get(url, headers=headers, params=params, timeout=12)
        if r.status_code == 200:
            return r.json().get("response", [])
        return []
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS & CONFIG
# ─────────────────────────────────────────────────────────────────────────────

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY     = "baseball_mlb"

# Prop market keys → human labels
MARKET_LABELS: Dict[str, str] = {
    "pitcher_strikeouts":         "Pitcher Ks",
    "batter_strikeouts":          "Batter Ks",
    "batter_hits":                "Hits",
    "batter_home_runs":           "Home Runs",
    "batter_rbis":                "RBIs",
    "batter_total_bases":         "Total Bases",
    "pitcher_hits_allowed":       "Hits Allowed",
    "pitcher_earned_runs":        "Earned Runs",
    "pitcher_outs":               "Outs Recorded",
}

# Books to pull (priority order for display)
PREFERRED_BOOKS = [
    "draftkings", "fanduel", "betmgm", "caesars",
    "pointsbet", "betrivers", "unibet_us",
]

# Edge decision thresholds
EDGE_STRONG   = 0.07   # ≥ 7 %  → 🔥 STRONG VALUE
EDGE_VALUE    = 0.03   # ≥ 3 %  → ✅ VALUE
EDGE_MARGINAL = 0.00   # ≥ 0 %  → ⚠️ MARGINAL
# < 0 %                          → ❌ NO BET

# Variance penalty: if floor is this far below line, downgrade one tier
FLOOR_PENALTY_THRESHOLD = 1.0   # 1 full strikeout below line = high variance

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
/* ── Odds tab root vars ── */
.odds-root {
    --c-bg:      #0e1117;
    --c-card:    #161b22;
    --c-border:  rgba(148,163,184,0.12);
    --c-text:    #e2e8f0;
    --c-muted:   #94a3b8;
    --c-dim:     #64748b;
    --c-green:   #10b981;
    --c-yellow:  #eab308;
    --c-orange:  #f97316;
    --c-red:     #ef4444;
    --c-blue:    #3b82f6;
    --c-strong:  #34d399;
    --c-hover:   rgba(30,58,95,0.18);
}

/* ── Section header ── */
.odds-section-hdr {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: var(--c-dim);
    margin: 18px 0 8px 2px;
    border-bottom: 1px solid var(--c-border);
    padding-bottom: 4px;
}

/* ── Verdict badges ── */
.badge-strong  { background:rgba(16,185,129,0.20); color:#34d399; padding:2px 8px; border-radius:4px; font-size:0.72rem; font-weight:700; letter-spacing:0.4px; }
.badge-value   { background:rgba(59,130,246,0.20);  color:#93c5fd; padding:2px 8px; border-radius:4px; font-size:0.72rem; font-weight:700; }
.badge-marginal{ background:rgba(234,179,8,0.18);   color:#fde047; padding:2px 8px; border-radius:4px; font-size:0.72rem; font-weight:700; }
.badge-nobet   { background:rgba(239,68,68,0.15);   color:#fca5a5; padding:2px 8px; border-radius:4px; font-size:0.72rem; font-weight:700; }

/* ── Main odds table ── */
.odds-table { width:100%; border-collapse:collapse; font-size:0.82rem; font-family:'SF Mono','Fira Code',monospace; }
.odds-table th {
    text-align:left; padding:8px 12px;
    border-bottom:1px solid var(--c-border);
    color:var(--c-dim); font-size:0.73rem;
    letter-spacing:0.9px; text-transform:uppercase;
    font-weight:600; white-space:nowrap;
    background:rgba(22,27,34,0.70);
}
.odds-table td {
    padding:7px 12px;
    border-bottom:1px solid rgba(148,163,184,0.06);
    color:var(--c-text); vertical-align:middle; white-space:nowrap;
}
.odds-table tr:hover td { background:var(--c-hover); }
.odds-table .strong-row td { border-left: 3px solid #10b981; background:rgba(16,185,129,0.04); }
.odds-table .value-row td  { border-left: 3px solid #3b82f6; background:rgba(59,130,246,0.03); }
.odds-table .pos   { color:var(--c-green); font-weight:700; }
.odds-table .neg   { color:var(--c-red);   font-weight:700; }
.odds-table .warn  { color:var(--c-yellow); font-weight:600; }

/* ── Play card ── */
.play-card {
    background: var(--c-card);
    border: 1px solid var(--c-border);
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 14px;
    transition: border-color 0.2s;
}
.play-card:hover { border-color: rgba(16,185,129,0.40); }
.play-card .rank { font-size: 1.5rem; font-weight: 900; color: var(--c-strong); line-height:1; }
.play-card .title { font-size: 1.0rem; font-weight: 700; color: var(--c-text); margin: 2px 0; }
.play-card .subtitle { font-size: 0.78rem; color: var(--c-muted); }
.play-card .edge-val { font-size: 1.6rem; font-weight: 900; color: var(--c-green); line-height:1; }
.play-card .edge-lbl { font-size: 0.68rem; color: var(--c-dim); text-transform:uppercase; letter-spacing:0.8px; }
.play-card .analysis { font-size: 0.83rem; color: var(--c-muted); line-height: 1.6; margin-top: 10px; border-top: 1px solid var(--c-border); padding-top: 8px; }
.play-card .dist-bar { font-size: 0.80rem; font-family: monospace; color: var(--c-text); margin: 8px 0 2px; }
.play-card .conf-bar { font-size: 0.75rem; font-family: monospace; color: var(--c-dim); }

/* ── API status banner ── */
.api-banner {
    border-radius: 8px;
    padding: 10px 16px;
    display: flex;
    gap: 10px;
    align-items: center;
    font-size: 0.84rem;
    margin-bottom: 14px;
}
.api-banner.ok   { background:rgba(16,185,129,0.10); border:1px solid rgba(16,185,129,0.30); }
.api-banner.warn { background:rgba(234,179,8,0.10);  border:1px solid rgba(234,179,8,0.30); }
.api-banner.err  { background:rgba(239,68,68,0.10);  border:1px solid rgba(239,68,68,0.30); }

/* ── Social post box ── */
.social-box {
    background: var(--c-card);
    border: 1px solid var(--c-border);
    border-radius: 8px;
    padding: 14px 16px;
    font-size: 0.84rem;
    line-height: 1.65;
    color: var(--c-text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    white-space: pre-wrap;
}

/* ── Quota pill ── */
.quota-pill {
    display: inline-block;
    background: rgba(59,130,246,0.15);
    color: #93c5fd;
    border: 1px solid rgba(59,130,246,0.30);
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.4px;
}
</style>
"""

# ─────────────────────────────────────────────────────────────────────────────
# ODDS API CLIENT
# ─────────────────────────────────────────────────────────────────────────────

def _get_api_key() -> Optional[str]:
    """
    Pull Odds API key — tries every format people commonly use.

    Format A (canonical):  [odds] section  ->  api_key = "..."
    Format B:              flat             ->  ODDS_API_KEY = "..."
    Format C:              flat             ->  api_key = "..."  (no section)
    Format D:              environment var  ->  ODDS_API_KEY
    """
    import os

    # A: [odds] / api_key  (the documented format)
    try:
        key = st.secrets["odds"]["api_key"]
        if key:
            return str(key)
    except Exception:
        pass

    # B: flat ODDS_API_KEY
    try:
        key = st.secrets["ODDS_API_KEY"]
        if key:
            return str(key)
    except Exception:
        pass

    # C: flat api_key (user forgot the [odds] header)
    try:
        key = st.secrets["api_key"]
        if key:
            return str(key)
    except Exception:
        pass

    # D: environment variable
    return os.environ.get("ODDS_API_KEY") or None


@st.cache_data(ttl=3600)  # 1-hour cache — conserves free-tier quota
def fetch_mlb_player_props(
    markets: str = "pitcher_strikeouts,batter_hits,batter_home_runs,batter_total_bases",
    regions: str = "us",
    bookmakers: str = "",
) -> Tuple[Optional[List[Dict]], Optional[Dict]]:
    """
    Fetch MLB player prop odds from The Odds API.

    Returns:
        (events_list, quota_info)  — quota_info has 'remaining' and 'used' keys.
        Returns (None, None) on error.
    """
    api_key = _get_api_key()
    if not api_key:
        return None, None

    url = f"{ODDS_API_BASE}/sports/{SPORT_KEY}/events"
    # Step 1: get today's event IDs
    try:
        r = requests.get(url, params={"apiKey": api_key}, timeout=10)
        if r.status_code != 200:
            return None, {"error": r.text, "status": r.status_code}
        events_meta = r.json()
    except Exception as e:
        return None, {"error": str(e)}

    if not events_meta:
        return [], {}

    results: List[Dict] = []
    quota_info: Dict = {}

    # Step 2: pull props per event (batch by event to stay within quota)
    for ev in events_meta[:10]:   # cap at 10 games — max 11 requests per refresh
        event_id = ev.get("id")
        if not event_id:
            continue
        params: Dict = {
            "apiKey": api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
        if bookmakers:
            params["bookmakers"] = bookmakers

        prop_url = f"{ODDS_API_BASE}/sports/{SPORT_KEY}/events/{event_id}/odds"
        try:
            pr = requests.get(prop_url, params=params, timeout=12)
            quota_info = {
                "remaining": pr.headers.get("x-requests-remaining", "?"),
                "used":      pr.headers.get("x-requests-used", "?"),
            }
            if pr.status_code == 200:
                data = pr.json()
                data["_home_team"] = ev.get("home_team", "")
                data["_away_team"] = ev.get("away_team", "")
                data["_commence_time"] = ev.get("commence_time", "")
                results.append(data)
        except Exception:
            continue

    return results, quota_info


# ─────────────────────────────────────────────────────────────────────────────
# ODDS MATH
# ─────────────────────────────────────────────────────────────────────────────

def american_to_implied(odds: int) -> float:
    """Convert American odds integer → implied probability (0–1)."""
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def normalize_overround(prob_over: float, prob_under: float) -> Tuple[float, float]:
    """Remove vig: normalize two-sided market to sum to 1.0."""
    total = prob_over + prob_under
    if total <= 0:
        return prob_over, prob_under
    return prob_over / total, prob_under / total


def estimate_model_prob(
    projection: float,
    floor: float,
    line: float,
    variance_factor: float = 1.0,
) -> float:
    """
    Estimate P(outcome > line) from a projection + floor.

    Uses a logistic CDF approximation — better than normal for count data.
    variance_factor: higher = fatter tails (HR = 1.5, Ks = 1.0, hits = 1.1)
    """
    gap = projection - line          # positive → projection above line
    spread = max(projection - floor, 0.5)   # proxy for std dev
    # Logistic scale parameter s = spread / 1.35  (matches normal σ)
    s = (spread / 1.35) * variance_factor
    if s == 0:
        return 1.0 if gap > 0 else 0.0
    # Logistic CDF: P(X > line) ≈ 1 / (1 + exp(-gap/s))
    try:
        return 1.0 / (1.0 + math.exp(-gap / s))
    except OverflowError:
        return 1.0 if gap > 0 else 0.0


def calculate_edge(model_prob: float, implied_prob: float) -> float:
    """Edge = model probability − implied probability."""
    return model_prob - implied_prob


def classify_edge(
    edge: float,
    floor: float,
    line: float,
    high_variance: bool = False,
) -> Tuple[str, str]:
    """
    Returns (verdict_key, display_label).
    Downgrades one tier if floor << line (high volatility).
    """
    floor_risk = (line - floor) > FLOOR_PENALTY_THRESHOLD
    downgrade  = floor_risk or high_variance

    if edge >= EDGE_STRONG:
        base = "strong"
    elif edge >= EDGE_VALUE:
        base = "value"
    elif edge >= EDGE_MARGINAL:
        base = "marginal"
    else:
        return "nobet", "❌ NO BET"

    if downgrade and base == "strong":
        base = "value"
    elif downgrade and base == "value":
        base = "marginal"

    labels = {
        "strong":  "🔥 STRONG VALUE",
        "value":   "✅ VALUE",
        "marginal": "⚠️ MARGINAL",
    }
    return base, labels[base]


def confidence_bar(prob: float, width: int = 10) -> str:
    """Generate ASCII confidence bar: ████████░░ (8/10)"""
    filled = round(prob * width)
    bar    = "█" * filled + "░" * (width - filled)
    return f"{bar} ({filled}/{width})"


def dist_visual(floor: float, projection: float, ceiling: Optional[float], line: float) -> str:
    """
    One-line distribution visual:
    Floor ──── Proj ──── Ceil  │ Line │
    """
    parts = [f"Floor {floor:.1f}"]
    parts.append(f"──── Proj {projection:.1f} ────")
    if ceiling:
        parts.append(f"Ceil {ceiling:.1f}")
    line_marker = f"  │ Line {line:.1f} │"
    return "  ".join(parts) + line_marker


# ─────────────────────────────────────────────────────────────────────────────
# PROP EXTRACTION FROM RAW ODDS API RESPONSE
# ─────────────────────────────────────────────────────────────────────────────

def extract_props_from_event(event: Dict) -> List[Dict]:
    """
    Flatten an Odds API event object into a list of prop dicts.
    Each dict: {player, team, opponent, prop_type, line, odds_over,
                odds_under, implied_over, implied_under, bookmaker}
    """
    home  = event.get("_home_team", "")
    away  = event.get("_away_team", "")
    props: List[Dict] = []

    for book in event.get("bookmakers", []):
        book_key   = book.get("key", "")
        book_title = book.get("title", book_key)
        for market in book.get("markets", []):
            mkt_key = market.get("key", "")
            label   = MARKET_LABELS.get(mkt_key, mkt_key)

            # Group outcomes by player + point (line)
            player_lines: Dict[str, Dict] = {}
            for outcome in market.get("outcomes", []):
                name        = outcome.get("description") or outcome.get("name", "")
                side        = outcome.get("name", "")  # "Over" / "Under"
                point       = outcome.get("point", 0.0)
                price       = outcome.get("price", 0)
                player_key  = f"{name}|{point}"

                if player_key not in player_lines:
                    player_lines[player_key] = {
                        "player": name,
                        "line":   float(point),
                        "odds_over":  None,
                        "odds_under": None,
                    }
                if side.lower() == "over":
                    player_lines[player_key]["odds_over"] = price
                elif side.lower() == "under":
                    player_lines[player_key]["odds_under"] = price

            for pk, pl in player_lines.items():
                if pl["odds_over"] is None or pl["odds_under"] is None:
                    continue
                impl_over  = american_to_implied(pl["odds_over"])
                impl_under = american_to_implied(pl["odds_under"])
                norm_over, norm_under = normalize_overround(impl_over, impl_under)
                props.append({
                    "player":        pl["player"],
                    "team":          "",   # enriched later from SALCI data
                    "opponent":      "",
                    "home_team":     home,
                    "away_team":     away,
                    "prop_type":     label,
                    "prop_key":      mkt_key,
                    "line":          pl["line"],
                    "odds_over":     pl["odds_over"],
                    "odds_under":    pl["odds_under"],
                    "implied_over":  round(norm_over * 100, 1),
                    "implied_under": round(norm_under * 100, 1),
                    "bookmaker":     book_title,
                    "book_key":      book_key,
                    "raw_impl_over": impl_over,
                })
    return props


# ─────────────────────────────────────────────────────────────────────────────
# SALCI PROJECTION OVERLAY
# ─────────────────────────────────────────────────────────────────────────────

def _fuzzy_name_match(name_a: str, name_b: str) -> bool:
    """Simple last-name + first-initial match (handles 'Gerrit Cole' ↔ 'G. Cole')."""
    a = name_a.strip().lower()
    b = name_b.strip().lower()
    if a == b:
        return True
    # Last name match
    last_a = a.split()[-1] if a.split() else a
    last_b = b.split()[-1] if b.split() else b
    if last_a == last_b and len(last_a) > 3:
        return True
    return False


def enrich_props_with_salci(
    props: List[Dict],
    pitchers_data: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    Attempt to match each prop to a SALCI pitcher projection.
    Adds: projection, floor, ceiling, salci_score, source
    """
    enriched = []
    pitcher_map: Dict[str, Dict] = {}
    if pitchers_data:
        for p in pitchers_data:
            name = p.get("name", p.get("pitcher_name", ""))
            pitcher_map[name.lower()] = p

    for prop in props:
        prop = dict(prop)
        player = prop.get("player", "")
        prop_key = prop.get("prop_key", "")
        line = prop.get("line", 0.0)
        projection = ceiling = floor = salci_score = None

        # ── Pitcher strikeout props ──
        if prop_key == "pitcher_strikeouts" and pitcher_map:
            for pname, pdata in pitcher_map.items():
                if _fuzzy_name_match(player, pname):
                    projection = pdata.get("expected", pdata.get("expected_ks"))
                    salci_score = pdata.get("salci")
                    # Derive floor / ceiling from SALCI score & projection
                    if projection is not None:
                        floor   = round(max(0, projection * 0.65), 1)
                        ceiling = round(projection * 1.40, 1)
                    prop["team"]     = pdata.get("team", "")
                    prop["opponent"] = pdata.get("opponent", "")
                    break

        # ── Generic fallback: synthetic projection from odds line ──
        # When no SALCI data: project = line + small over-bias
        if projection is None:
            projection = line + 0.35
            floor      = round(max(0, line - 1.0), 1)
            ceiling    = round(line + 2.0, 1)
            prop["_synthetic"] = True
        else:
            prop["_synthetic"] = False

        prop["projection"]  = round(projection, 2)
        prop["floor"]       = round(floor, 2) if floor is not None else round(max(0, projection - 1.5), 2)
        prop["ceiling"]     = round(ceiling, 2) if ceiling is not None else round(projection + 2.0, 2)
        prop["salci_score"] = salci_score

        # ── Variance factor by prop type ──
        var_map = {
            "pitcher_strikeouts": 1.0,
            "batter_strikeouts":  1.1,
            "batter_hits":        1.1,
            "batter_home_runs":   1.6,
            "batter_total_bases": 1.3,
            "batter_rbis":        1.4,
        }
        vf = var_map.get(prop_key, 1.0)
        high_var = vf >= 1.4

        model_prob   = estimate_model_prob(projection, prop["floor"], line, vf)
        implied_prob = prop["raw_impl_over"]
        edge         = calculate_edge(model_prob, implied_prob)
        verdict_key, verdict_label = classify_edge(
            edge, prop["floor"], line, high_var
        )

        prop["model_prob"]    = round(model_prob * 100, 1)
        prop["edge"]          = round(edge * 100, 1)
        prop["verdict_key"]   = verdict_key
        prop["verdict_label"] = verdict_label
        prop["confidence"]    = confidence_bar(model_prob)
        prop["dist_visual"]   = dist_visual(
            prop["floor"], projection, prop["ceiling"], line
        )
        prop["high_variance"] = high_var
        enriched.append(prop)

    return enriched


# ─────────────────────────────────────────────────────────────────────────────
# DEDUPLICATION — keep best line per player+prop+side
# ─────────────────────────────────────────────────────────────────────────────

def deduplicate_props(props: List[Dict]) -> List[Dict]:
    """
    For each (player, prop_type, line) keep one row per bookmaker.
    Then for display pick the book with highest edge (best odds for Over).
    """
    # group by player+prop
    groups: Dict[str, List[Dict]] = {}
    for p in props:
        key = f"{p['player']}|{p['prop_key']}|{p['line']}"
        groups.setdefault(key, []).append(p)

    best = []
    for key, rows in groups.items():
        # Sort by preferred book, then by edge descending
        def book_score(r: Dict) -> Tuple[int, float]:
            bk = r.get("book_key", "")
            priority = PREFERRED_BOOKS.index(bk) if bk in PREFERRED_BOOKS else 99
            return (priority, -r.get("edge", -999))
        best.append(sorted(rows, key=book_score)[0])

    return best


# ─────────────────────────────────────────────────────────────────────────────
# TOP PLAYS REPORT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_top_plays_report(props: List[Dict], top_n: int = 5) -> str:
    """
    Generate hedge-fund style text report for top N plays.
    """
    actionable = [p for p in props if p["verdict_key"] in ("strong", "value")]
    actionable.sort(key=lambda x: -x["edge"])
    top = actionable[:top_n]

    if not top:
        return "No actionable edges detected in current market."

    lines = [
        "═" * 62,
        "  SALCI ODDS INTELLIGENCE — TOP PLAYS REPORT",
        f"  Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "═" * 62,
        "",
    ]

    for i, p in enumerate(top, 1):
        gap    = p["projection"] - p["line"]
        synth  = " [synthetic proj]" if p.get("_synthetic") else ""
        lines += [
            f"#{i}  {p['player'].upper()}  —  {p['prop_type']} O{p['line']}",
            f"    Book: {p['bookmaker']}  |  Odds: {_fmt_odds(p['odds_over'])}  |  {p['verdict_label']}",
            f"    Line: {p['line']}  |  Projection: {p['projection']}{synth}  |  Floor: {p['floor']}",
            f"    Implied: {p['implied_over']}%  |  Model: {p['model_prob']}%  |  Edge: +{p['edge']}%",
            f"    Confidence: {p['confidence']}",
            f"    {p['dist_visual']}",
            "",
            _explain_edge(p),
            "",
            "─" * 62,
            "",
        ]

    lines += [
        "  RISK FLAGS",
        "  ─────────",
    ]
    for p in top:
        flags = []
        if p["high_variance"]:
            flags.append("HIGH VARIANCE")
        if p["floor"] < p["line"] - 1.5:
            flags.append(f"FLOOR {p['floor']} significantly below line")
        if p.get("_synthetic"):
            flags.append("No SALCI projection — synthetic estimate only")
        if flags:
            lines.append(f"  {p['player']}: {' | '.join(flags)}")
        else:
            lines.append(f"  {p['player']}: No major flags")

    lines += ["", "═" * 62]
    return "\n".join(lines)


def _explain_edge(p: Dict) -> str:
    gap   = p["projection"] - p["line"]
    lines = []
    if gap > 0:
        lines.append(
            f"    WHY: Model projects {p['projection']} vs book line {p['line']} "
            f"(+{gap:.2f} gap). "
        )
    else:
        lines.append(
            f"    WHY: Tight gap ({gap:+.2f}) but market mispriced — "
            f"implied {p['implied_over']}% vs model {p['model_prob']}%."
        )
    if p["salci_score"]:
        lines.append(f"    SALCI Score {p['salci_score']:.0f} anchors the projection.")
    lines.append(
        f"    Floor {p['floor']} provides stability buffer. "
        + ("HIGH VARIANCE — treat as speculative." if p["high_variance"] else "Manageable variance.")
    )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SOCIAL POST GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def generate_social_posts(props: List[Dict]) -> Tuple[str, str]:
    """
    Returns (analyst_post, viral_post) for the best single play.
    """
    actionable = [p for p in props if p["verdict_key"] in ("strong", "value")]
    if not actionable:
        return ("No actionable plays today.", "No plays today. 🔍")

    actionable.sort(key=lambda x: -x["edge"])
    best = actionable[0]
    date_str = datetime.utcnow().strftime("%b %d")

    analyst = (
        f"SALCI MLB PROPS — {date_str}\n\n"
        f"TOP PLAY: {best['player']} {best['prop_type']} O{best['line']} "
        f"({_fmt_odds(best['odds_over'])})\n\n"
        f"Model: {best['model_prob']}%  |  Implied: {best['implied_over']}%  |  Edge: +{best['edge']}%\n"
        f"Projection: {best['projection']}  |  Floor: {best['floor']}  |  Line: {best['line']}\n\n"
        f"Confidence: {best['confidence']}\n\n"
        f"The market is pricing this at {best['implied_over']}% implied probability. "
        f"SALCI has {best['player']} projecting to {best['projection']} — "
        f"a {best['projection'] - best['line']:+.1f} gap above the book line. "
        f"Floor at {best['floor']} keeps downside manageable.\n\n"
        f"Verdict: {best['verdict_label']}\n\n"
        "#SALCI #MLBProps #EdgeDetection"
    )

    viral = (
        f"🔥 SHARP PLAY ALERT — {date_str}\n\n"
        f"{best['player']} {best['prop_type']} OVER {best['line']}\n"
        f"({_fmt_odds(best['odds_over'])})\n\n"
        f"Our model: {best['model_prob']}% | Book: {best['implied_over']}%\n"
        f"+{best['edge']}% EDGE 🎯\n\n"
        f"Floor {best['floor']} · Proj {best['projection']} · Line {best['line']}\n\n"
        f"#MLBBets #SharpMoney #PropBets"
    )

    return analyst, viral


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_odds(o: Optional[int]) -> str:
    if o is None:
        return "—"
    return f"+{o}" if o > 0 else str(o)


def _verdict_badge(key: str, label: str) -> str:
    class_map = {
        "strong":  "badge-strong",
        "value":   "badge-value",
        "marginal": "badge-marginal",
        "nobet":   "badge-nobet",
    }
    cls = class_map.get(key, "badge-nobet")
    return f'<span class="{cls}">{label}</span>'


def _edge_class(edge: float) -> str:
    if edge >= 7:
        return "pos"
    elif edge >= 3:
        return "pos"
    elif edge >= 0:
        return "warn"
    return "neg"


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL PROP ENTRY (fallback when no API key)
# ─────────────────────────────────────────────────────────────────────────────

def render_manual_entry(form_key: str = "manual_props_form") -> List[Dict]:
    """
    Let users input props manually when API key isn't configured.
    Returns list of raw prop dicts matching extract_props_from_event format.
    form_key must be unique per call site to avoid Streamlit duplicate-key errors.
    """
    st.markdown(
        '<p class="odds-section-hdr">✏️ Manual Prop Entry</p>',
        unsafe_allow_html=True,
    )
    st.caption(
        "No API key configured — enter props manually for instant edge analysis."
    )

    with st.form(form_key):
        cols = st.columns([2, 1.5, 1.2, 1.0, 1.0, 1.0])
        with cols[0]: player   = st.text_input("Player", placeholder="Gerrit Cole")
        with cols[1]: prop_lbl = st.selectbox("Prop Type", list(MARKET_LABELS.values()))
        with cols[2]: line     = st.number_input("Line", min_value=0.0, value=6.5, step=0.5)
        with cols[3]: odds_ov  = st.number_input("Odds (Over)", value=-120, step=5)
        with cols[4]: proj     = st.number_input("SALCI Proj", min_value=0.0, value=7.2, step=0.1)
        with cols[5]: floor_v  = st.number_input("Floor", min_value=0.0, value=5.5, step=0.5)
        submitted = st.form_submit_button("➕ Add Prop", use_container_width=True)

    if submitted and player:
        # Reverse-lookup market key from label
        mkt_key = next(
            (k for k, v in MARKET_LABELS.items() if v == prop_lbl),
            "pitcher_strikeouts",
        )
        # Synthetic under odds (assume -vig mirror)
        impl_over  = american_to_implied(int(odds_ov))
        # Under implied = 1 - over + small vig cushion
        impl_under = 1 - impl_over + 0.04
        # Convert back to american
        if impl_under >= 0.5:
            odds_un = -round((impl_under / (1 - impl_under)) * 100)
        else:
            odds_un = round(((1 / impl_under) - 1) * 100)

        prop = {
            "player":         player,
            "team":           "",
            "opponent":       "",
            "home_team":      "",
            "away_team":      "",
            "prop_type":      prop_lbl,
            "prop_key":       mkt_key,
            "line":           float(line),
            "odds_over":      int(odds_ov),
            "odds_under":     int(odds_un),
            "implied_over":   round(impl_over * 100, 1),
            "implied_under":  round(impl_under * 100, 1),
            "bookmaker":      "Manual Entry",
            "book_key":       "manual",
            "raw_impl_over":  impl_over,
            # Pre-fill SALCI data
            "projection":     round(float(proj), 2),
            "floor":          round(float(floor_v), 2),
            "ceiling":        round(float(proj) * 1.35, 2),
            "salci_score":    None,
            "_synthetic":     False,
        }

        if "manual_props" not in st.session_state:
            st.session_state.manual_props = []
        st.session_state.manual_props.append(prop)
        st.success(f"✅ Added: {player} {prop_lbl} O{line}")
        st.rerun()

    return st.session_state.get("manual_props", [])


# ─────────────────────────────────────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────────────────────────────────────

def _render_header() -> None:
    st.markdown(
        '<div style="margin-bottom:4px">'
        '<h2 style="margin:0;font-size:1.6rem;font-weight:800">💰 Odds Intelligence</h2>'
        '<p style="margin:2px 0 0;font-size:0.83rem;color:#64748b">'
        'SALCI model projections × live sportsbook lines → quantified edge detection'
        '</p></div>',
        unsafe_allow_html=True,
    )


def _render_api_status(quota: Optional[Dict], prop_count: int,
                       apisports_status: str = "") -> None:
    if quota is None:
        # Debug: show what keys ARE present in secrets so user can diagnose
        debug_info = ""
        try:
            import streamlit as _st
            keys = list(_st.secrets.keys())
            debug_info = f" (secrets keys found: {keys})" if keys else " (secrets appears empty)"
        except Exception:
            debug_info = " (could not read secrets)"
        st.markdown(
            '<div class="api-banner warn odds-root">'
            f'⚠️ <strong>No API key configured.</strong>  '
            f'Add <code>[odds]<br>api_key = "your_key"</code> to '
            f'<code>.streamlit/secrets.toml</code> or Streamlit Cloud secrets.{debug_info}'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    if "error" in quota:
        st.markdown(
            f'<div class="api-banner err odds-root">❌ Odds API error: {quota["error"]}</div>',
            unsafe_allow_html=True,
        )
        return

    rem  = quota.get("remaining", "?")
    used = quota.get("used", "?")
    fetched_at = datetime.utcnow().strftime("%H:%M UTC")
    as_pill = (
        f'&nbsp;<span class="quota-pill">📡 API-Sports: {apisports_status}</span>'
        if apisports_status else ""
    )
    st.markdown(
        f'<div class="api-banner ok odds-root">'
        f'✅ <strong>The Odds API — Live</strong> &nbsp;|&nbsp; '
        f'{prop_count} props loaded &nbsp;'
        f'<span class="quota-pill">Fetched: {fetched_at}</span> &nbsp;'
        f'<span class="quota-pill">Quota: {used} used / {rem} remaining</span>'
        f'{as_pill}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_props_table(props: List[Dict], show_nobet: bool = False) -> None:
    display = props if show_nobet else [p for p in props if p["verdict_key"] != "nobet"]
    if not display:
        st.caption("No props match current filters.")
        return

    # Sort: strong first, then by edge descending
    order = {"strong": 0, "value": 1, "marginal": 2, "nobet": 3}
    display.sort(key=lambda x: (order.get(x["verdict_key"], 3), -x["edge"]))

    header_cells = "".join(
        f"<th>{h}</th>"
        for h in ["Player", "Prop", "Line", "Odds", "Implied %", "Model %", "Edge %", "Floor", "Confidence", "Verdict"]
    )

    rows_html = ""
    for p in display:
        vk     = p["verdict_key"]
        row_cls = "strong-row" if vk == "strong" else ("value-row" if vk == "value" else "")
        ec     = _edge_class(p["edge"])
        edge_sign = f"+{p['edge']:.1f}%" if p["edge"] >= 0 else f"{p['edge']:.1f}%"
        rows_html += (
            f'<tr class="{row_cls}">'
            f'<td><strong>{p["player"]}</strong></td>'
            f'<td>{p["prop_type"]}</td>'
            f'<td style="text-align:center">{p["line"]}</td>'
            f'<td style="text-align:center">{_fmt_odds(p["odds_over"])}</td>'
            f'<td style="text-align:center">{p["implied_over"]:.1f}%</td>'
            f'<td style="text-align:center">{p["model_prob"]:.1f}%</td>'
            f'<td class="{ec}" style="text-align:center">{edge_sign}</td>'
            f'<td style="text-align:center">{p["floor"]}</td>'
            f'<td style="font-family:monospace;font-size:0.75rem">{p["confidence"]}</td>'
            f'<td>{_verdict_badge(vk, p["verdict_label"])}</td>'
            f'</tr>'
        )

    st.markdown(
        '<div style="overflow-x:auto;border-radius:8px;border:1px solid rgba(148,163,184,0.12);padding:0">'
        '<table class="odds-table">'
        f'<thead><tr>{header_cells}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        '</table></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "🔥 STRONG (≥7% edge)  ✅ VALUE (3–7%)  ⚠️ MARGINAL (0–3%)  ·  "
        "Green row = Strong Value  Blue row = Value  ·  "
        "Confidence bar = model probability (10pt scale)"
    )


def _render_top_play_cards(props: List[Dict], top_n: int = 5) -> None:
    actionable = [p for p in props if p["verdict_key"] in ("strong", "value")]
    actionable.sort(key=lambda x: -x["edge"])
    top = actionable[:top_n]

    if not top:
        st.info("No strong or value plays in current prop set.")
        return

    for i, p in enumerate(top, 1):
        synth_note = " *(synthetic projection)*" if p.get("_synthetic") else ""
        gap        = p["projection"] - p["line"]
        gap_str    = f"+{gap:.2f}" if gap >= 0 else f"{gap:.2f}"
        vk         = p["verdict_key"]
        badge_cls  = "badge-strong" if vk == "strong" else "badge-value"

        st.markdown(
            f'<div class="play-card odds-root">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'  <div>'
            f'    <div class="rank">#{i}</div>'
            f'    <div class="title">{p["player"]} — {p["prop_type"]} Over {p["line"]}</div>'
            f'    <div class="subtitle">{p["bookmaker"]}  ·  {_fmt_odds(p["odds_over"])}  ·  '
            f'      {p.get("home_team","")} vs {p.get("away_team","")}</div>'
            f'  </div>'
            f'  <div style="text-align:right">'
            f'    <div class="edge-val">+{p["edge"]:.1f}%</div>'
            f'    <div class="edge-lbl">EDGE</div>'
            f'    <div style="margin-top:4px"><span class="{badge_cls}">{p["verdict_label"]}</span></div>'
            f'  </div>'
            f'</div>'
            f'<div class="dist-bar">{p["dist_visual"]}</div>'
            f'<div class="conf-bar">Confidence: {p["confidence"]}</div>'
            f'<div class="analysis">'
            f'  <strong>WHY:</strong> Projection {p["projection"]}{synth_note} is {gap_str} above the book line {p["line"]}. '
            f'  Market prices this at <strong>{p["implied_over"]:.1f}%</strong> implied — '
            f'  SALCI model says <strong>{p["model_prob"]:.1f}%</strong>. '
            f'  Floor at {p["floor"]} {"provides downside cushion." if p["floor"] >= p["line"] - 1.0 else "is below the line — elevated variance."}'
            + (f'  <strong>HIGH VARIANCE PROP</strong> — treat as speculative.' if p["high_variance"] else "")
            + (f'  <em>No SALCI pitcher data found — synthetic projection.</em>' if p.get("_synthetic") else "")
            + f'</div></div>',
            unsafe_allow_html=True,
        )


def _render_market_filter(props: List[Dict]) -> List[Dict]:
    """Sidebar filters for the odds table."""
    markets   = sorted(set(p["prop_type"] for p in props))
    bookmakers = sorted(set(p["bookmaker"] for p in props))
    verdicts  = ["strong", "value", "marginal", "nobet"]

    with st.sidebar.expander("💰 Odds Filters", expanded=False):
        sel_markets = st.multiselect(
            "Prop Types", markets, default=markets, key="odds_mkt_filter"
        )
        sel_books = st.multiselect(
            "Bookmakers", bookmakers, default=bookmakers, key="odds_book_filter"
        )
        sel_verdicts = st.multiselect(
            "Verdicts", verdicts,
            default=["strong", "value", "marginal"],
            key="odds_verdict_filter",
        )
        min_edge = st.slider("Min Edge %", -15.0, 20.0, -5.0, 0.5, key="odds_edge_slider")

    return [
        p for p in props
        if p["prop_type"] in sel_markets
        and p["bookmaker"] in sel_books
        and p["verdict_key"] in sel_verdicts
        and p["edge"] >= min_edge
    ]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDER ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def render_odds_tab(
    pitchers_data: Optional[List[Dict]] = None,
    games: Optional[List[Dict]] = None,
) -> None:
    """
    Call this from mlb_salci_full.py inside the Odds Intelligence tab.

    Parameters
    ----------
    pitchers_data : list of pitcher dicts from SALCI (each must have
                    'name', 'expected'/'expected_ks', 'salci', 'team')
    games         : list of game dicts (for display context)
    """
    st.markdown(_CSS, unsafe_allow_html=True)
    _render_header()

    # ── Live Scores sidebar widget ────────────────────────────────────────────
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    bdl_games = fetch_balldontlie_games(today_str)
    if bdl_games:
        with st.sidebar.expander("📡 Live Scores", expanded=True):
            for g in bdl_games:
                home   = g.get("home_team", {}).get("abbreviation", "HOM")
                away   = g.get("visitor_team", {}).get("abbreviation", "AWY")
                hs     = g.get("home_team_score")
                vs     = g.get("visitor_team_score")
                status = g.get("status", "")
                inning = g.get("inning") or g.get("time", "")
                if hs is not None and vs is not None and status not in ("", "Scheduled"):
                    label = f"{away} {vs} – {home} {hs}"
                    if inning:
                        label += f"  ({inning})"
                else:
                    raw_dt = g.get("date", "")
                    if raw_dt and _PYTZ_OK:
                        try:
                            import pytz as _tz
                            dt    = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                            label = f"{away} vs {home}  " + dt.astimezone(
                                _tz.timezone("America/New_York")
                            ).strftime("%-I:%M %p ET")
                        except Exception:
                            label = f"{away} vs {home}"
                    else:
                        label = f"{away} vs {home}"
                st.caption(label)

    api_key  = _get_api_key()
    all_props: List[Dict] = []
    quota_info: Optional[Dict] = None
    apisports_status: str = ""

    # ── Tabs inside the Odds tab ──────────────────────────────────────────────
    inner_tab1, inner_tab2, inner_tab3, inner_tab4, inner_tab5 = st.tabs([
        "📊 Props Table",
        "🏆 Top Plays",
        "📋 Full Report",
        "📣 Social Posts",
        "🎰 Parlay Builder",
    ])

    # ── Refresh button — only way to trigger a fresh API call ────────────────
    if st.button("🔄 Refresh Odds", help="Clears cache and fetches fresh lines (costs API quota)"):
        st.cache_data.clear()
        st.rerun()

    # ── Fetch / build props ───────────────────────────────────────────────────
    with st.spinner("Fetching live sportsbook lines…"):
        if api_key:
            # Configurable markets via secrets
            try:
                markets = st.secrets.get("odds", {}).get(
                    "markets",
                    "pitcher_strikeouts,batter_hits,batter_home_runs,batter_total_bases",
                )
                regions = st.secrets.get("odds", {}).get("regions", "us")
            except Exception:
                markets = "pitcher_strikeouts,batter_hits,batter_home_runs,batter_total_bases"
                regions = "us"

            events, quota_info = fetch_mlb_player_props(markets=markets, regions=regions)
            if events:
                raw_props = []
                for ev in events:
                    raw_props.extend(extract_props_from_event(ev))
                all_props = deduplicate_props(raw_props)

            # ── API-Sports fallback (only when Odds API returned nothing) ──
            if not all_props:
                as_date = datetime.utcnow().strftime("%Y-%m-%d")
                as_data = fetch_apisports_odds(as_date)
                if as_data:
                    apisports_status = "Connected"
                elif os.environ.get("APISPORTS_KEY") or (
                    st.secrets.get("APISPORTS_KEY") if hasattr(st, "secrets") else None
                ):
                    apisports_status = "Unavailable"
        else:
            quota_info = None
            # No Odds API key — try API-Sports as sole source
            as_date = datetime.utcnow().strftime("%Y-%m-%d")
            as_data = fetch_apisports_odds(as_date)
            if as_data:
                apisports_status = "Connected"
            elif os.environ.get("APISPORTS_KEY"):
                apisports_status = "Unavailable"

    # Add any manually entered props
    manual = st.session_state.get("manual_props", [])
    all_props.extend(manual)

    # Enrich with SALCI projections
    if all_props:
        all_props = enrich_props_with_salci(all_props, pitchers_data)

    # API status banner (shown on all sub-tabs)
    for tab in (inner_tab1, inner_tab2, inner_tab3, inner_tab4, inner_tab5):
        with tab:
            _render_api_status(quota_info, len(all_props), apisports_status)

    # Apply sidebar filters
    filtered = _render_market_filter(all_props) if all_props else []

    # ── TAB 1: Props Table ────────────────────────────────────────────────────
    with inner_tab1:
        st.markdown('<p class="odds-section-hdr">Player Prop Edge Analysis</p>', unsafe_allow_html=True)

        show_nobet = st.checkbox("Show NO BET rows", value=False, key="odds_show_nobet")

        if not filtered and not api_key:
            # No API key — show manual entry
            manual_props = render_manual_entry(form_key="manual_form_tab1a")
            if manual_props:
                enriched_manual = enrich_props_with_salci(manual_props, pitchers_data)
                _render_props_table(enriched_manual, show_nobet=True)
        elif filtered:
            _render_props_table(filtered, show_nobet=show_nobet)
        else:
            st.info("No props to display. Configure an API key or add props manually.")
            render_manual_entry(form_key="manual_form_tab1b")

    # ── TAB 2: Top Plays ──────────────────────────────────────────────────────
    with inner_tab2:
        st.markdown('<p class="odds-section-hdr">Ranked Value Plays</p>', unsafe_allow_html=True)

        n_top = st.slider("Show top N plays", 3, 10, 5, key="odds_top_n")
        if filtered:
            _render_top_play_cards(filtered, top_n=n_top)
        else:
            st.info("Add props via API or manual entry to see ranked plays.")
            # Allow manual entry here too — unique key required
            manual_from_tab2 = render_manual_entry(form_key="manual_form_tab2")
            if manual_from_tab2:
                enriched = enrich_props_with_salci(manual_from_tab2, pitchers_data)
                _render_top_play_cards(enriched, top_n=n_top)

    # ── TAB 3: Full Report ────────────────────────────────────────────────────
    with inner_tab3:
        st.markdown('<p class="odds-section-hdr">Hedge Fund–Style Analysis Report</p>', unsafe_allow_html=True)

        props_for_report = filtered or enrich_props_with_salci(
            st.session_state.get("manual_props", []), pitchers_data
        )
        if props_for_report:
            report = generate_top_plays_report(props_for_report, top_n=5)
            st.code(report, language="")

            # Market inefficiency summary
            strong_ct  = sum(1 for p in props_for_report if p["verdict_key"] == "strong")
            value_ct   = sum(1 for p in props_for_report if p["verdict_key"] == "value")
            synth_ct   = sum(1 for p in props_for_report if p.get("_synthetic"))
            high_var_ct = sum(1 for p in props_for_report if p["high_variance"])

            st.markdown('<p class="odds-section-hdr">Market Inefficiency Summary</p>', unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("🔥 Strong Value", strong_ct, help="Edge ≥ 7%")
            with c2:
                st.metric("✅ Value Plays", value_ct, help="Edge 3–7%")
            with c3:
                st.metric("⚠️ High Variance", high_var_ct, help="HRs, RBIs — fat tails")
            with c4:
                st.metric("🔬 Synthetic Proj", synth_ct, help="No SALCI data matched")
        else:
            st.info("No props loaded. Use the Props Table tab to enter data.")

    # ── TAB 4: Social Posts ───────────────────────────────────────────────────
    with inner_tab4:
        st.markdown('<p class="odds-section-hdr">Auto-Generated Social Content</p>', unsafe_allow_html=True)

        props_for_social = filtered or enrich_props_with_salci(
            st.session_state.get("manual_props", []), pitchers_data
        )
        analyst_post, viral_post = generate_social_posts(props_for_social)

        st.markdown("**Analyst-Style Post** — data-heavy, syndicate tone")
        st.markdown(f'<div class="social-box odds-root">{analyst_post}</div>', unsafe_allow_html=True)
        st.button("📋 Copy Analyst Post", key="copy_analyst",
                  help="Select text above and copy manually (Streamlit doesn't support clipboard)")

        st.markdown("---")
        st.markdown("**Viral-Style Post** — punchy, engagement-optimized")
        st.markdown(f'<div class="social-box odds-root">{viral_post}</div>', unsafe_allow_html=True)
        st.button("📋 Copy Viral Post", key="copy_viral")

        st.caption(
            "⚠️ **Disclaimer:** SALCI projections are probabilistic models, "
            "not guarantees. Edge calculations are estimates. Bet responsibly."
        )

    # ── TAB 5: Parlay Builder ─────────────────────────────────────────────────
    with inner_tab5:
        st.markdown('<p class="odds-section-hdr">Parlay Builder</p>',
                    unsafe_allow_html=True)
        st.caption(
            "Legs are sourced from pitcher strikeout props where SALCI floor "
            "exceeds the book line. Only non-synthetic projections are shown."
        )

        # Filter to pitcher K props with real SALCI projections
        k_props = [
            p for p in all_props
            if ("strikeout" in p.get("prop_key", "").lower()
                or "pitcher" in p.get("prop_key", "").lower())
            and not p.get("_synthetic")
        ]

        high_conf = sorted(
            [p for p in k_props if p.get("floor", 0) - p.get("line", 0) >= 2],
            key=lambda x: x.get("floor", 0) - x.get("line", 0),
            reverse=True,
        )
        value_legs = sorted(
            [p for p in k_props
             if 1 <= p.get("floor", 0) - p.get("line", 0) < 2],
            key=lambda x: x.get("floor", 0) - x.get("line", 0),
            reverse=True,
        )

        if not k_props:
            st.info(
                "No eligible parlay legs found. "
                "Legs appear once pitcher K props with SALCI projections are loaded."
            )
        else:
            col_hc, col_val = st.columns(2)

            selected_legs: List[Dict] = []

            def _leg_card(col, prop: Dict, leg_key: str) -> bool:
                gap = round(prop.get("floor", 0) - prop.get("line", 0), 1)
                last = prop.get("player", "Unknown").split()[-1]
                label = (
                    f"{last} O{prop['line']} Ks  "
                    f"Floor {prop['floor']}  Gap +{gap}"
                )
                with col:
                    checked = st.checkbox(label, key=leg_key)
                    st.caption(
                        f"Implied: {prop['implied_over']}%  ·  "
                        f"Model: {prop['model_prob']}%  ·  "
                        f"Book: {_fmt_odds(prop['odds_over'])}"
                    )
                return checked

            with col_hc:
                st.markdown("**⚡ High Confidence Legs (Floor − Line ≥ 2)**")
                if not high_conf:
                    st.caption("None today.")
                for i, p in enumerate(high_conf):
                    if _leg_card(col_hc, p, f"parlay_hc_{i}"):
                        selected_legs.append(p)

            with col_val:
                st.markdown("**💪 Value Legs (Floor − Line ≥ 1)**")
                if not value_legs:
                    st.caption("None today.")
                for i, p in enumerate(value_legs):
                    if _leg_card(col_val, p, f"parlay_val_{i}"):
                        selected_legs.append(p)

            st.markdown("---")
            st.markdown("#### 🧮 Build Parlay")

            if not selected_legs:
                st.info("Check legs above to build your parlay.")
            else:
                # Combined implied probability (model probs, as decimals)
                combined_prob = 1.0
                for leg in selected_legs:
                    combined_prob *= leg["model_prob"] / 100.0

                # Convert combined probability to American odds
                if combined_prob >= 0.5:
                    combined_american = -round((combined_prob / (1 - combined_prob)) * 100)
                else:
                    combined_american = round(((1 / combined_prob) - 1) * 100)

                c_prob, c_odds = st.columns(2)
                with c_prob:
                    st.metric("Model Confidence", f"{combined_prob * 100:.1f}%")
                with c_odds:
                    st.metric("Suggested Parlay Odds", _fmt_odds(combined_american))

                # Build copyable parlay text
                leg_lines = "\n".join(
                    f"  ✅ {p.get('player','').split()[-1]} "
                    f"OVER {p['line']} Ks  "
                    f"(Floor: {p['floor']}, Gap: +{round(p.get('floor',0)-p.get('line',0),1)})"
                    for p in selected_legs
                )
                parlay_text = (
                    f"SALCI PARLAY 🔥\n"
                    f"{leg_lines}\n"
                    f"Combined: ~{_fmt_odds(combined_american)} odds"
                    f" | {combined_prob*100:.0f}% model confidence\n"
                    f"#SALCI #MLB"
                )

                st.code(parlay_text, language="")
                st.caption(
                    "⚠️ Disclaimer: SALCI projections are probabilistic estimates, "
                    "not guarantees. Bet responsibly."
                )


# ─────────────────────────────────────────────────────────────────────────────
# STANDALONE DEMO (python odds_tab.py)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Quick math smoke test — no API call needed
    print("=== SALCI Odds Intelligence — Module Test ===\n")

    test_cases = [
        ("Gerrit Cole",    "Pitcher Ks",  "pitcher_strikeouts", 6.5,  -130, 8.1, 6.0, None),
        ("Logan Webb",     "Pitcher Ks",  "pitcher_strikeouts", 5.5,  -115, 5.8, 4.5, None),
        ("Cody Bellinger", "Hits",        "batter_hits",        0.5,  -175, 0.7, 0.3, None),
        ("Aaron Judge",    "Home Runs",   "batter_home_runs",   0.5,  +135, 0.45, 0.0, None),
    ]

    print(f"{'Player':<18} {'Prop':<14} {'Line':<6} {'Odds':<7} {'Impl%':<7} {'Model%':<8} {'Edge%':<7} {'Verdict'}")
    print("-" * 85)

    for player, prop_lbl, prop_key, line, odds, proj, floor, ceil_ in test_cases:
        var_map = {"pitcher_strikeouts": 1.0, "batter_hits": 1.1, "batter_home_runs": 1.6}
        vf      = var_map.get(prop_key, 1.0)
        impl    = american_to_implied(odds)
        model   = estimate_model_prob(proj, floor, line, vf)
        edge    = calculate_edge(model, impl)
        vk, vl  = classify_edge(edge, floor, line, vf >= 1.4)
        print(
            f"{player:<18} {prop_lbl:<14} {line:<6} {_fmt_odds(odds):<7} "
            f"{impl*100:<6.1f}% {model*100:<7.1f}% {edge*100:<+6.1f}%  {vl}"
        )

    print("\n✅ Module OK")
