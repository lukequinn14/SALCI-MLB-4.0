# ⚾ SALCI v5.0 - Strikeout Adjusted Lineup Confidence Index

An advanced MLB prediction model featuring **physics-based Stuff+ calculations**, **SALCI v2 formula**, and **real Statcast data integration**.

## 🆕 What's New in v5.0

### 🧮 SALCI v2 Formula
A complete redesign of the scoring model with 4 balanced components:

| Component | Weight | What It Measures |
|-----------|--------|------------------|
| **Stuff** | 30% | Raw pitch quality (velocity, movement, spin, release point) |
| **Location** | 25% | Command and placement (zone%, edge%, chase rate, CSW%) |
| **Matchup** | 25% | Opponent tendencies (team K%, contact%, platoon) |
| **Workload** | 20% | Efficiency, projected IP, TTT risk |

**Why v2?** The v1 model over-weighted stuff and under-weighted workload. High-stuff arms often got pulled after 5 IP, capping K totals. v2 better predicts *sustainable* strikeouts.

### 🎯 Physics-Based Stuff+ (Not Proxy Metrics)
- Uses **only physical traits**: velocity, movement (pfx_x, pfx_z), spin rate, extension
- Does NOT use outcomes (K%, whiff%) as inputs
- Per-pitch-type calculations (FF, SL, CU, CH, etc.)
- Normalized to 100 = league average, 10 points = 1 std dev

### 🔥 Real Statcast Integration
- Connects to Baseball Savant via pybaseball
- Graceful fallback to proxy metrics when unavailable
- Sidebar shows "🎯 Statcast: Connected" or "📊 Using proxy metrics"

### 📊 Heat Maps Tab
- Pitcher Attack Maps (where they throw, whiff rates by zone)
- Hitter Damage Maps (batting average by zone)
- Matchup Collision Analysis

---

## How SALCI v2 Works

### The Formula
```
SALCI_v2 = (0.30 × Stuff) + (0.25 × Location) + (0.25 × Matchup) + (0.20 × Workload)

Expected_Ks = (SALCI_v2 / 10) × Projected_IP × Efficiency_Factor
```

### Stuff+ Calculation (Physics-Based)
Each pitch type has its own formula based on what makes that pitch effective:

| Pitch | Key Components | Weights |
|-------|----------------|---------|
| **Four-Seam (FF)** | Velocity, Induced Vertical Break, Extension | 50/35/5 |
| **Slider (SL/ST)** | Horizontal Sweep, Drop, Velo Diff | 40/30/15 |
| **Curveball (CU)** | Vertical Drop, Spin Rate, Velo Diff | 45/25/20 |
| **Changeup (CH)** | Velo Diff, Arm-Side Fade, Drop | 35/30/35 |

### Location+ Calculation
| Component | Weight | Optimal |
|-----------|--------|---------|
| Zone Rate | 10% | ~45-50% (not too high) |
| Edge Rate | 25% | Higher is better |
| Heart Rate | 20% | Lower is better |
| Chase Rate | 20% | Higher is better |
| First Pitch Strike | 10% | Higher is better |
| CSW% | 15% | Higher is better |

### Workload Score (NEW in v2)
| Component | Weight | What It Measures |
|-----------|--------|------------------|
| P/IP | 30% | Pitches per inning (efficiency) |
| Avg IP | 35% | Projected innings |
| Deep Game % | 20% | Rate of 6+ IP starts |
| TTT Risk | 15% | Third-time-through penalty |

---

## Stuff+ / Location+ Scale

| Score | Rating | Meaning |
|-------|--------|---------|
| 115+ | Elite | Top-tier |
| 105-114 | Above Average | Strong |
| 95-104 | Average | League average |
| < 95 | Below Average | Fade candidate |

---

## Pitcher Profile Types

| Profile | Stuff+ | Location+ | Description |
|---------|--------|-----------|-------------|
| ⚡ ELITE | 115+ | 110+ | True ace |
| 🔥 STUFF-DOMINANT | 115+ | <100 | High ceiling, high variance |
| 🎯 LOCATION-DOMINANT | <100 | 115+ | Consistent, lower ceiling |
| 💪 BALANCED-PLUS | 105+ | 105+ | Quality all-around |
| ⚖️ BALANCED | 95-104 | 95-104 | Matchup-dependent |
| ⚠️ LIMITED | <95 | <95 | Fade candidate |

---

## Installation

### Local Development

```bash
# Clone the repo
git clone https://github.com/yourusername/salci-mlb.git
cd salci-mlb

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run mlb_salci_full.py
```

### Required Files

| File | Description |
|------|-------------|
| `mlb_salci_full.py` | Main Streamlit application |
| `statcast_connector.py` | Physics-based Stuff+/Location+ calculator |
| `requirements.txt` | Python dependencies |

### Statcast Data (Recommended)

For real physics-based Stuff+:
```bash
pip install pybaseball
```

Place `statcast_connector.py` in the same folder as `mlb_salci_full.py`. The app will automatically detect and use Statcast data.

---

## Tabs Overview

| Tab | Description |
|-----|-------------|
| ⚾ Pitcher Analysis | SALCI v2 scores with 4-component breakdown |
| 🏏 Hitter Matchups | Hot/cold hitters, season + L7 stats |
| 🎯 Best Bets | Top pitcher K props, hot hitter props |
| 🔥 Heat Maps | Zone visualizations and matchup analysis |
| 📊 Charts & Share | Game Day Card, exportable charts |
| 📈 Yesterday | Prediction accuracy and model insights |

---

## Data Sources

- **MLB Stats API**: Game schedules, lineups, pitcher/hitter stats
- **Baseball Savant (Statcast)**: Pitch-level data via pybaseball
- Lineups typically released 1-2 hours before game time

---

## Disclaimer

⚠️ **SALCI is for entertainment purposes only.** Baseball is unpredictable. These are probabilities, not guarantees. Bet responsibly.

---

## Version History

- **v5.0** - SALCI v2 formula, physics-based Stuff+, Statcast integration, heat maps
- **v4.0** - Yesterday's Reflection, Stuff/Location analysis
- **v3.x** - Streamlit UI, hitter analysis, Game Day Cards
- **v2.0** - Hitter matchups, hot/cold streaks
- **v1.0** - Basic pitcher SALCI scoring

---

Built with ❤️ and Python | SALCI © 2025
