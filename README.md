# ⚾ SALCI v5.0 - Strikeout Adjusted Lineup Confidence Index

An advanced MLB prediction model for pitcher strikeouts and hitter matchups, now featuring **real Statcast data integration**, **zone heat maps**, and **progressive analytics**.

## 🆕 What's New in v5.0

### 🎯 Real Statcast Integration
- **True Stuff+ / Location+ scores** calculated from pitch-level Statcast data
- Velocity, spin rate, movement, and whiff rate for each pitch type
- Zone-by-zone performance metrics
- Graceful fallback to proxy metrics when Statcast unavailable

### 🔥 Zone Heat Maps (NEW!)
Interactive visualizations showing:
- **Pitcher Attack Maps** - Where pitchers throw most and how effective each zone is
- **Hitter Damage Maps** - Where hitters do the most damage (BA by zone)
- **Matchup Collision Analysis** - Overlap between pitcher attack zones and hitter damage zones

### 📊 Enhanced Pitcher Arsenal Display
- Per-pitch-type Stuff+ scores (FF, SL, CH, CU, etc.)
- Velocity and movement breakdowns
- Primary weapon identification

### Everything from v4.0
- Yesterday's Reflection (postgame learning)
- Stuff vs Location analysis
- Game Day Cards for social sharing
- Confirmed lineup verification

---

## How SALCI Works

SALCI combines pitcher metrics with opponent tendencies to predict strikeout performance:

### Pitcher Metrics (60%)
| Metric | Description | Weight |
|--------|-------------|--------|
| K/9 | Strikeouts per 9 innings | 18% |
| K% | Strikeout rate | 18% |
| K/BB | Strikeout to walk ratio | 14% |
| P/IP | Pitches per inning (efficiency) | 10% |

### Matchup Factors (40%)
| Metric | Description | Weight |
|--------|-------------|--------|
| Opp K% | Opponent team's strikeout rate | 22% |
| Opp Contact% | Opponent's contact rate | 18% |

---

## SALCI Rating Scale

| Score | Rating | Meaning |
|-------|--------|---------|
| 75+ | 🔥 Elite | Top-tier K potential |
| 60-74 | ✅ Strong | Above average |
| 45-59 | ➖ Average | Coin flip |
| 30-44 | ⚠️ Below Avg | Fade territory |
| <30 | ❌ Poor | Stay away |

---

## Stuff+ / Location+ (v5.0)

### Stuff+ (Pitch Quality)
Measures raw pitch "nastiness":
- Fastball velocity
- Movement (horizontal + vertical)
- Spin rate
- Whiff rate
- Velocity differentials

### Location+ (Command)
Measures pitch placement:
- Zone rate (pitches in strike zone)
- Edge rate (painting corners)
- Heart rate (avoiding middle-middle)
- Chase rate induced
- First pitch strike %

### Pitcher Profiles

| Profile | Stuff+ | Location+ | Description |
|---------|--------|-----------|-------------|
| ⚡ ELITE | 115+ | 110+ | True ace |
| 🔥 STUFF-DOMINANT | 115+ | <100 | High ceiling, high variance |
| 🎯 LOCATION-DOMINANT | <100 | 115+ | Consistent, lower ceiling |
| ⚖️ BALANCED | 100-110 | 100-110 | Solid all-around |
| ⚠️ LIMITED | <95 | <95 | Fade candidate |

---

## Features

- 🎯 **Pitcher Analysis** - SALCI scores with real Stuff+/Location+
- 🏏 **Hitter Matchups** - Hot/cold streaks, platoon advantages
- 🔥 **Heat Maps** - Zone-by-zone attack and damage visualizations
- 📊 **Shareable Charts** - Game Day Card, K projections
- 📈 **Yesterday's Reflection** - Learn from yesterday's results
- ✅ **Confirmed Lineups** - Only shows actual starters
- 💾 **Prediction Storage** - Save predictions for next-day reflection

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
| `statcast_connector.py` | Statcast/pybaseball integration |
| `requirements.txt` | Python dependencies |

### Statcast Data (Optional but Recommended)

For real Statcast data:
1. Install pybaseball: `pip install pybaseball`
2. Place `statcast_connector.py` in the same folder as `mlb_salci_full.py`
3. The app will automatically detect and use Statcast data

Without pybaseball installed, the app will use proxy metrics (still functional, just less precise).

---

## Deployment (Streamlit Cloud)

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repo
4. Deploy!

**Note:** Streamlit Cloud may have issues with pybaseball due to network restrictions. The app will fall back to proxy metrics automatically.

---

## Tabs Overview

| Tab | Description |
|-----|-------------|
| ⚾ Pitcher Analysis | Full pitcher cards with SALCI, Stuff+, Location+ |
| 🏏 Hitter Matchups | Hot/cold hitters, season + L7 stats |
| 🎯 Best Bets | Top pitcher K props, hot hitter props |
| 🔥 Heat Maps | Zone visualizations and matchup analysis |
| 📊 Charts & Share | Game Day Card, exportable charts |
| 📈 Yesterday | Prediction accuracy and model insights |

---

## Disclaimer

⚠️ **SALCI is for entertainment purposes only.** Baseball is unpredictable. These are probabilities, not guarantees. Bet responsibly.

---

## Follow Along

🐦 Follow [#SALCI](https://twitter.com/search?q=%23SALCI) on Twitter/X for daily insights!

---

## Version History

- **v5.0** - Statcast integration, zone heat maps, matchup collision analysis
- **v4.0** - Yesterday's Reflection, Stuff/Location analysis, enhanced charts
- **v3.2** - Handedness throughout, Game Day Card, shareable graphics
- **v3.1** - Confirmed lineup verification, hitter analysis
- **v3.0** - Streamlit web UI, interactive charts
- **v2.0** - Hitter matchups, hot/cold streaks
- **v1.0** - Basic pitcher SALCI scoring

---

Built with ❤️ and Python | SALCI © 2025
