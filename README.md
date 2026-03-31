# ⚾ SALCI v4.0 - Strikeout Adjusted Lineup Confidence Index

An advanced MLB prediction model for pitcher strikeouts and hitter matchups, featuring **Stuff vs Location analysis** and **daily reflection learning**.

## 🆕 What's New in v4.0

### Yesterday's Reflection 📈
A postgame learning layer that compares yesterday's predictions to actual results:
- Accuracy tracking (within ±1 K, ±2 K)
- Overperformers and underperformers
- Model calibration insights
- Rolling 7-day accuracy trends

### Stuff vs Location Analysis 💪🎯
Separates pitcher dominance into two components:
- **Stuff Score**: Raw pitch quality (velocity, movement, whiff rate)
- **Location Score**: Pitch placement (edge%, zone%, heart%)
- **Profile Classification**: Elite, Stuff-Dominant, Location-Dominant, Balanced, Limited

### Enhanced Visualizations 📊
- Stuff/Location progress bars on pitcher cards
- Game Day Card for Twitter/X sharing
- K Line probability charts
- Hitter K% vs AVG scatter plots

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

## Pitcher Profiles (v4.0)

| Profile | Stuff | Location | Description |
|---------|-------|----------|-------------|
| ⚡ Complete | 75+ | 75+ | True ace |
| 🔥 Stuff Dominant | 75+ | <65 | High ceiling, high variance |
| 🎯 Location Master | <65 | 75+ | Consistent, low ceiling |
| ⚖️ Balanced | 60-70 | 60-70 | Matchup-dependent |
| ⚠️ Limited | <55 | <55 | Fade in most spots |

---

## Features

- 🎯 **Pitcher Analysis** - SALCI scores with Stuff/Location breakdown
- 🏏 **Hitter Matchups** - Hot/cold streaks, platoon advantages, handedness
- 📊 **Shareable Charts** - Game Day Card, K projections, scatter plots
- 📈 **Yesterday's Reflection** - Learn from yesterday's results
- ✅ **Confirmed Lineups** - Only shows actual starters
- 💾 **Prediction Storage** - Save predictions for next-day reflection

---

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run mlb_salci_full.py
```

---

## Deployment (Streamlit Cloud)

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repo
4. Deploy!

---

## Disclaimer

⚠️ **SALCI is for entertainment purposes only.** Baseball is unpredictable. These are probabilities, not guarantees. Bet responsibly.

---

## Follow Along

🐦 Follow [#SALCI](https://twitter.com/search?q=%23SALCI) on Twitter/X for daily insights!

---

## Version History

- **v4.0** - Yesterday's Reflection, Stuff/Location analysis, enhanced charts
- **v3.2** - Handedness throughout, Game Day Card, shareable graphics
- **v3.1** - Confirmed lineup verification, hitter analysis
- **v3.0** - Streamlit web UI, interactive charts
- **v2.0** - Hitter matchups, hot/cold streaks
- **v1.0** - Basic pitcher SALCI scoring

---

Built with ❤️ and Python | SALCI © 2025

