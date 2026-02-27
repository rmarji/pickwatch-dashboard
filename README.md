# Pickwatch Dashboard

AI-powered sports betting analysis using Pickwatch data.

## Quick Start

```bash
# Get today's NBA picks
python3 picks.py nba

# Get picks for a specific date
python3 picks.py nfl 2026-02-28

# JSON output
python3 picks.py nba --json
```

## Components

### `scoring.py` - Confidence Scoring System

Based on historical analysis of 3,965 MLB games:
- **+Edge bets**: 70% win rate (strongest signal)
- **96%+ confidence**: 60.8% win rate
- **3-4 star value**: 66-69% win rate

The algorithm weights:
- Edge (true prob vs implied): 50%
- Expert consensus: 35%
- Expert vs Fan divergence: 15%

### `api_client.py` - Pickwatch API Client

Fetches data from:
- `/general/games/{sport}/{year}/{day}` - Game data with consensus
- `/marketplace/premium-picks/...` - CPU confidence (requires premium)

### `picks.py` - CLI Tool

Outputs formatted picks for Telegram or JSON.

## Recommendation Levels

| Level | Criteria | Historical WR |
|-------|----------|---------------|
| 🔥 STRONG BET | Edge ≥8%, Conf ≥75% | ~70% |
| ✅ BET | Edge ≥5%, Conf ≥65% | ~65% |
| 👀 LEAN | Edge ≥2%, Conf ≥55% | ~58% |
| ❌ PASS | Below thresholds | - |

## Configuration

Set `PICKWATCH_TOKEN` in `/data/workspace-cto/config/pickwatch.env`:

```
PICKWATCH_TOKEN=your_token_here
```

## Dependencies

None! Uses Python stdlib only.
