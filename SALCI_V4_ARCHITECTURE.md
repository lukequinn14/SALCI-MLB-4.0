# SALCI v4.0 Architecture Document
## Strikeout Adjusted Lineup Confidence Index - Next Generation

---

## Overview

SALCI v4.0 evolves from a **prediction tool** into an **analytics learning system**. The core upgrade separates pitcher dominance into Stuff, Location, and Matchup components, then adds a daily reflection layer that validates predictions against actual outcomes.

### Version History
- **v3.2** - Pitcher SALCI + Hitter Analysis + Shareable Charts + Handedness
- **v4.0** - Stuff/Location Split + Yesterday's Reflection + Heat Maps + Hit Likelihood

---

## Priority Order (as defined)

1. **Yesterday's Reflection** - Postgame learning layer
2. **Stuff vs Location Split** - Pitch quality vs placement separation  
3. **Heat Maps** - Pitcher attack zones vs hitter damage zones
4. **Hit Likelihood Model** - Contact-based matchup scoring

---

## Data Sources

### Current: MLB Stats API (statsapi.mlb.com)
- Free, no authentication required
- Game schedules, lineups, box scores
- Player season/game log stats
- Team batting stats

### New: Baseball Savant / Statcast (baseballsavant.mlb.com)
- Free, no authentication required
- Pitch-level data (velocity, movement, spin, location)
- Zone-based performance metrics
- Expected stats (xBA, xSLG, xwOBA)
- Pitch type breakdowns

### API Endpoints to Add

```
# Baseball Savant - Statcast Search (CSV export)
https://baseballsavant.mlb.com/statcast_search/csv?
  player_type=pitcher
  &player_id={player_id}
  &game_date_gt={start_date}
  &game_date_lt={end_date}

# Baseball Savant - Player Page Data
https://baseballsavant.mlb.com/savant-player/{player_id}

# Baseball Savant - Zone Data (via statcast_search)
Parameters: zone, attack_zone, pitch_type, pitch_name
```

---

## Feature Definitions

### 1. YESTERDAY'S REFLECTION (Priority 1)

**Purpose:** Create a feedback loop that validates predictions against actual outcomes. Turns SALCI from static predictions into a learning system.

**Definition:**
> A daily postgame summary that compares projected pitcher performance against actual results, identifies which matchups overperformed or underperformed, and surfaces patterns in model accuracy.

**Components:**

| Component | Definition | Data Source |
|-----------|------------|-------------|
| **Projected vs Actual Ks** | Compare SALCI K projection to actual strikeouts | MLB Stats API (box scores) |
| **Innings Gap** | Difference between expected innings and actual IP | MLB Stats API (box scores) |
| **Edge Accuracy** | Did the predicted matchup edge (stuff/location/matchup) align with result? | Calculated from outcomes |
| **Overperformers** | Pitchers who exceeded K projection by >2 | Calculated |
| **Underperformers** | Pitchers who missed K projection by >2 | Calculated |
| **Model Bias Check** | Did stuff-heavy or location-heavy picks perform better? | Calculated |

**Key Metrics to Track:**
```python
yesterday_reflection = {
    "date": "2025-03-30",
    "games_tracked": 15,
    "avg_projected_ks": 5.8,
    "avg_actual_ks": 5.4,
    "projection_accuracy": 0.72,  # within 1.5 Ks
    "avg_projected_ip": 5.5,
    "avg_actual_ip": 5.2,
    "overperformers": [
        {"pitcher": "Chase Burns", "projected": 6.2, "actual": 9, "delta": +2.8}
    ],
    "underperformers": [
        {"pitcher": "Some Guy", "projected": 5.5, "actual": 2, "delta": -3.5}
    ],
    "stuff_heavy_accuracy": 0.68,
    "location_heavy_accuracy": 0.75,
    "lesson": "Location-heavy pitchers outperformed stuff-heavy picks yesterday"
}
```

**Visual Design:**
```
┌─────────────────────────────────────────────────────┐
│  📊 YESTERDAY'S REFLECTION - Mar 30                 │
├─────────────────────────────────────────────────────┤
│  Projected Ks: 5.8 avg  │  Actual Ks: 5.4 avg      │
│  Projection Accuracy: 72% (within 1.5 Ks)          │
├─────────────────────────────────────────────────────┤
│  🔥 OVERPERFORMERS          │  ❄️ UNDERPERFORMERS   │
│  Burns: 6.2 → 9 (+2.8)      │  Smith: 5.5 → 2 (-3.5)│
│  Ponce: 5.8 → 8 (+2.2)      │  Jones: 6.0 → 3 (-3.0)│
├─────────────────────────────────────────────────────┤
│  💡 INSIGHT: Location-heavy pitchers outperformed   │
│     stuff-heavy picks by 12% yesterday              │
└─────────────────────────────────────────────────────┘
```

**Storage Requirement:**
- Save daily predictions to JSON/CSV before games start
- Compare against box scores after games complete
- Maintain rolling 7-day and 30-day accuracy windows

---

### 2. STUFF VS LOCATION SPLIT (Priority 2)

**Purpose:** Separate raw pitch quality ("nasty stuff") from pitch placement ability ("command"). A pitcher can have elite stuff but poor location, or mediocre stuff with pinpoint command.

**Definitions:**

> **Stuff Score:** Measures the raw quality of a pitcher's arsenal - velocity, movement, spin, and whiff-inducing ability. Answers: "How nasty are the pitches themselves?"

> **Location Score:** Measures the pitcher's ability to place pitches in optimal zones based on count and situation. Answers: "How well does he hit his spots?"

> **Pitching Score:** Combined Stuff + Location effectiveness. The overall expected dominance.

**Component Breakdown:**

| Metric | Category | Definition | Source |
|--------|----------|------------|--------|
| Fastball Velo | Stuff | Average 4-seam velocity | Savant |
| Spin Rate | Stuff | RPM on primary pitches | Savant |
| Movement | Stuff | Induced vertical/horizontal break | Savant |
| Whiff% | Stuff | Swings and misses / total swings | Savant |
| Zone% | Location | Pitches in strike zone | Savant |
| Edge% | Location | Pitches on zone edges (shadow zone) | Savant |
| Chase% | Location | Swings on pitches outside zone | Savant |
| Heart% | Location | Pitches in center of zone (bad) | Savant |
| First Pitch Strike% | Location | Command indicator | MLB API |
| Count Leverage | Location | Performance in hitter's counts (2-0, 3-1) | Savant |

**Scoring Model:**
```python
stuff_components = {
    "fastball_velo": {"weight": 0.20, "bounds": (90, 98), "higher_better": True},
    "spin_rate": {"weight": 0.15, "bounds": (2000, 2600), "higher_better": True},
    "whiff_pct": {"weight": 0.35, "bounds": (0.20, 0.35), "higher_better": True},
    "movement": {"weight": 0.30, "bounds": (10, 18), "higher_better": True},
}

location_components = {
    "zone_pct": {"weight": 0.20, "bounds": (0.40, 0.55), "higher_better": True},
    "edge_pct": {"weight": 0.25, "bounds": (0.15, 0.30), "higher_better": True},
    "chase_pct": {"weight": 0.25, "bounds": (0.25, 0.40), "higher_better": True},
    "heart_pct": {"weight": 0.15, "bounds": (0.20, 0.10), "higher_better": False},
    "first_pitch_strike": {"weight": 0.15, "bounds": (0.55, 0.70), "higher_better": True},
}
```

**Profile Types:**
```
STUFF-DOMINANT:  Stuff 75+ / Location 50-65
  → High ceiling, high variance. Lives on swing-and-miss.
  → Risk: Deep counts, pitch count spikes, early exits.

LOCATION-DOMINANT: Stuff 50-65 / Location 75+
  → Lower ceiling, low variance. Lives on weak contact.
  → Risk: When stuff dips, gets hit hard.

ELITE:  Stuff 75+ / Location 75+
  → True ace. Can dominate any lineup.

BALANCED: Stuff 60-70 / Location 60-70
  → Solid but not spectacular. Matchup-dependent.

LIMITED: Stuff <55 / Location <55
  → Below average. Fade in most matchups.
```

**Visual Design:**
```
┌─────────────────────────────────────────────────────┐
│  CHASE BURNS (RHP) - Pirates                        │
├──────────────────────┬──────────────────────────────┤
│  STUFF: 82           │  LOCATION: 71                │
│  ████████████░░░░░░  │  ███████████░░░░░░░░         │
│  "Elite arsenal"     │  "Above average command"     │
├──────────────────────┴──────────────────────────────┤
│  Profile: STUFF-DOMINANT                            │
│  Edge: High K upside, watch pitch count             │
└─────────────────────────────────────────────────────┘
```

---

### 3. HEAT MAPS (Priority 3)

**Purpose:** Visualize where pitchers attack and where hitters perform best. The overlap reveals the matchup battleground.

**Definitions:**

> **Pitcher Attack Map:** Shows pitch location density by zone. Green = pitcher succeeds here. Red = pitcher gets hurt here.

> **Hitter Damage Map:** Shows batting performance by zone. Red = hitter crushes here. Blue = hitter struggles here.

> **Collision Map:** Overlay showing where pitcher tends to throw vs where hitter does damage. High overlap = hitter advantage.

**Zone System (9-zone grid):**
```
    ┌─────┬─────┬─────┐
    │  1  │  2  │  3  │  HIGH
    ├─────┼─────┼─────┤
    │  4  │  5  │  6  │  MIDDLE (Heart = Zone 5)
    ├─────┼─────┼─────┤
    │  7  │  8  │  9  │  LOW
    └─────┴─────┴─────┘
      IN    MID   OUT

Extended zones (11-14): Chase zones outside strike zone
```

**Metrics by Zone:**
```python
zone_metrics = {
    "zone_1": {
        "pitch_pct": 0.08,      # % of pitches here
        "whiff_pct": 0.32,      # whiff rate in this zone
        "ba_against": 0.180,    # batting avg against
        "slg_against": 0.290,   # slugging against
        "usage_trend": "up"     # L7 vs season
    },
    # ... zones 2-14
}
```

**Data Source:** Baseball Savant zone parameter in statcast_search

**Visual Design:**
```
┌─────────────────────────────────────────────────────────────┐
│  MATCHUP: Burns (RHP) vs Wiemer (LHB)                       │
├────────────────────────┬────────────────────────────────────┤
│  PITCHER ATTACK MAP    │  HITTER DAMAGE MAP                 │
│  ┌─────┬─────┬─────┐   │  ┌─────┬─────┬─────┐               │
│  │ 🟡  │ 🟢  │ 🟢  │   │  │ 🔵  │ 🔵  │ 🔴  │               │
│  ├─────┼─────┼─────┤   │  ├─────┼─────┼─────┤               │
│  │ 🟢  │ 🔴  │ 🟡  │   │  │ 🟡  │ 🔴  │ 🔴  │               │
│  ├─────┼─────┼─────┤   │  ├─────┼─────┼─────┤               │
│  │ 🟢  │ 🟢  │ 🟡  │   │  │ 🔵  │ 🟡  │ 🔵  │               │
│  └─────┴─────┴─────┘   │  └─────┴─────┴─────┘               │
│  Burns: Low/away       │  Wiemer: Middle-in/up              │
├────────────────────────┴────────────────────────────────────┤
│  ⚔️ COLLISION: Low overlap - Pitcher wins placement battle  │
│  Burns attacks low zones where Wiemer struggles             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4. HIT LIKELIHOOD MODEL (Priority 4)

**Purpose:** Predict whether a hitter will get a hit based on matchup-specific factors, not just batting average.

**Definition:**
> A contact-quality model that compares pitcher tendencies against hitter zone performance, incorporating pitch types, handedness splits, and expected contact quality.

**Input Factors:**

| Factor | Weight | Definition |
|--------|--------|------------|
| Zone Overlap | 25% | Does pitcher attack where hitter does damage? |
| Pitch Type Matchup | 20% | Hitter's performance vs pitcher's primary pitches |
| Handedness Split | 15% | L/R advantage based on historical data |
| Contact Quality | 15% | Hitter's xBA, barrel%, hard hit% |
| Chase Tendency | 10% | Does hitter expand zone vs this pitch mix? |
| Recent Form | 10% | L7 performance trend |
| Count Behavior | 5% | Performance in favorable vs unfavorable counts |

**Output:**
```python
hit_likelihood = {
    "player": "Joey Wiemer",
    "vs_pitcher": "Chase Burns",
    "hit_probability": 0.42,  # 42% chance of 1+ hits
    "multi_hit_probability": 0.18,
    "expected_abs": 4.2,
    "factors": {
        "zone_overlap": "LOW",      # Pitcher avoids damage zones
        "pitch_type": "NEUTRAL",    # Wiemer OK vs sliders
        "handedness": "ADVANTAGE",  # L vs R
        "contact_quality": "HIGH",  # When he connects, it's hard
        "chase_tendency": "RISK",   # Expands zone too much
    },
    "summary": "Low hit likelihood despite hot streak - Burns attacks zones where Wiemer struggles"
}
```

---

## Implementation Phases

### Phase 1: Framework (This Session)
- [x] Architecture document
- [ ] Data source connectors (MLB API + Baseball Savant)
- [ ] Storage layer for predictions/results
- [ ] Base scoring functions

### Phase 2: Yesterday's Reflection
- [ ] Prediction storage system (pre-game)
- [ ] Results collection system (post-game)
- [ ] Comparison logic
- [ ] Reflection UI component
- [ ] 7-day rolling accuracy tracking

### Phase 3: Stuff vs Location
- [ ] Baseball Savant pitch data ingestion
- [ ] Stuff score calculation
- [ ] Location score calculation
- [ ] Profile classification
- [ ] UI integration

### Phase 4: Heat Maps
- [ ] Zone-based data collection
- [ ] Pitcher attack map generation
- [ ] Hitter damage map generation
- [ ] Collision/overlap calculation
- [ ] Plotly heat map visualization

### Phase 5: Hit Likelihood
- [ ] Matchup factor collection
- [ ] Hit probability model
- [ ] Integration with hitter cards
- [ ] Validation against results

---

## File Structure (Proposed)

```
salci-mlb/
├── mlb_salci_full.py          # Main Streamlit app (v4.0)
├── requirements.txt            # Dependencies
├── README.md                   # Documentation
├── .gitignore
│
├── data/
│   ├── predictions/            # Daily prediction snapshots
│   │   └── 2025-03-30.json
│   ├── results/                # Daily results
│   │   └── 2025-03-30.json
│   └── reflections/            # Processed reflections
│       └── 2025-03-30.json
│
├── src/
│   ├── api/
│   │   ├── mlb_stats.py        # MLB Stats API connector
│   │   └── baseball_savant.py  # Savant/Statcast connector
│   ├── models/
│   │   ├── stuff_location.py   # Stuff/Location scoring
│   │   ├── hit_likelihood.py   # Hit probability model
│   │   └── reflection.py       # Yesterday's reflection logic
│   ├── viz/
│   │   ├── heat_maps.py        # Zone heat map generators
│   │   ├── game_day_card.py    # Daily summary card
│   │   └── charts.py           # Plotly chart functions
│   └── utils/
│       ├── storage.py          # Prediction/result storage
│       └── scoring.py          # Base scoring functions
```

---

## Key Questions to Resolve

1. **Storage:** Use local JSON files, or add a lightweight DB (SQLite)?
2. **Savant Rate Limits:** How aggressive on API calls? Cache strategy?
3. **Historical Depth:** How far back for Stuff/Location baselines?
4. **Mobile:** Optimize heat maps for phone screenshots?

---

## Next Steps

1. Review this architecture document
2. Build Baseball Savant connector
3. Implement prediction storage layer
4. Build Yesterday's Reflection (Priority 1)

---

*Document Version: 1.0*
*Created: March 31, 2025*
*Author: SALCI Development Team*
