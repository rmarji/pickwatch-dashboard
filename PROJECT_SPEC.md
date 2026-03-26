# Sports Prediction Project Spec

*Created: 2026-03-18*
*Status: Active Development*

## Overview

AI-powered sports picks system combining Pickwatch consensus data with custom confidence scoring. Generates daily picks for Telegram channel with Kelly sizing recommendations.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DAILY PICKS PIPELINE                      │
│                  (daily_channel_picks.py)                    │
└────────────────────────────┬────────────────────────────────┘
                             │
       ┌─────────────────────┼─────────────────────┐
       │                     │                     │
       ▼                     ▼                     ▼
┌─────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  SPORTS     │    │    SCORING      │    │    CRYPTO       │
│  PICKS      │    │    ENGINE       │    │    SIGNALS      │
│             │    │                 │    │                 │
│ Pickwatch   │    │ ConfidenceScorer│    │ SignalEngine   │
│ API Client  │    │ - Edge calc     │    │ - Composite     │
│             │    │ - Value rating  │    │ - Multi-strat   │
└─────────────┘    │ - Recommendations│    └─────────────────┘
                   └─────────────────┘
                             │
                   ┌─────────┴─────────┐
                   │                   │
                   ▼                   ▼
            ┌─────────────┐    ┌─────────────────┐
            │  TELEGRAM   │    │   RESULT        │
            │  CHANNEL    │    │   CHECKER       │
            │  POST       │    │   (ESPN scores) │
            └─────────────┘    └─────────────────┘
```

## Components

### 1. Pickwatch API Client (`api_client.py`)
- **Purpose**: Fetch game data with consensus from Pickwatch
- **Endpoints**:
  - `/general/games/{sport}/{year}/{day}/{league}` — Game data with odds
  - `/marketplace/premium-picks/{sport}/{year}/{day}/{pick_type}/` — CPU confidence
- **Sports**: NBA, NHL, NFL, MLB (when in season)
- **Proxy**: Uses n8n webhook to bypass Cloudflare blocking
- **Dependencies**: stdlib only (urllib)

### 2. Confidence Scoring (`scoring.py`)
- **Purpose**: Calculate edge and recommendation level
- **Weights** (from historical backtesting):
  - Edge: 40%
  - CPU Confidence: 30%
  - Expert Consensus: 20%
  - Contrarian Signal: 10%
- **Outputs**:
  - STRONG BET (🔥): Edge ≥8%, Conf ≥75%
  - BET (✅): Edge ≥5%, Conf ≥65%
  - LEAN: Edge ≥2%, Conf ≥55%
  - PASS: Below thresholds

### 3. Daily Picks Generator (`daily_channel_picks.py`)
- **Purpose**: Combine sports + crypto signals for Telegram
- **Features**:
  - Auto-detects sports in season
  - Filters heavy favorites (< -170 odds)
  - Aggregates top picks by confidence
  - Formats for AIPalacePicks channel
- **Cron**: Runs daily at scheduled time

### 4. Result Checker (`result_checker.py`)
- **Purpose**: Auto-check game results against picks
- **Sources**: ESPN API for scores
- **Outputs**: Updates picks_db.json with W/L/P results

### 5. Capper Monitor (`capper_monitor.py`)
- **Purpose**: Monitor Capper Collective Telegram channel
- **Features**: Superforecaster + Kelly analysis overlay

## Data Flow

```
1. Cron triggers daily_channel_picks.py
2. Load PICKWATCH_TOKEN from Infisical/env
3. For each sport (NBA, NHL, NFL):
   a. Fetch games with CPU confidence
   b. Score each side with ConfidenceScorer
   c. Filter by edge threshold + odds
   d. Sort by confidence
4. Fetch crypto signals from SignalEngine
5. Format combined report
6. Post to Telegram channel
```

## Active Sports (2026-03-18)

| Sport | Status | Notes |
|-------|--------|-------|
| NBA | ✅ Active | Regular season |
| NHL | ✅ Active | Regular season |
| NFL | ⚠️ Limited | Offseason, few games |
| MLB | ❌ Disabled | Spring training (invalid picks) |

## Known Issues & Feedback

### Issue #1: MLB Spring Training (2026-03-18)
- **Problem**: MLB picks were showing spring training games
- **Impact**: Wrong matchups, invalid predictions
- **Fix**: Disabled MLB in `daily_channel_picks.py`
- **TODO**: Add season_active date-range gating
- **Re-enable**: ~April 1 when regular season starts

### Issue #2: Odds Threshold
- **Current**: Filter out < -170 odds
- **Rationale**: Low EV on heavy favorites
- **Todo**: Make configurable per sport

## Configuration

### Environment Variables
```bash
# Pickwatch API Token
PICKWATCH_TOKEN=xxx

# Notion API Key (for project tracking)
NOTION_API_KEY=ntn_xxx
```

### Infisical Secrets
- `PICKWATCH_API_TOKEN` — Loaded via `/data/.openclaw/skills/infisical/get-secret.sh`

## Cron Jobs

No cron detected in `/etc/crontab` for this project. Likely managed via:
- Supervisord
- Systemd timers
- Manual execution

**TODO**: Add cron monitoring/heartbeat check

## Notion Project Page

- **Parent**: Money (32530bcb-e3a4-8082-ac7d-d430844178dc)
- **Page**: Sports Prediction Project (32730bcb-e3a4-814f-8956-d2dad81f94cb)

## Deliverables

### D1: Core System ✅
- [x] Pickwatch API client
- [x] Confidence scoring engine
- [x] Daily picks generator
- [x] Result checker

### D2: Season Management 🚧
- [ ] Date-range gating for each sport
- [ ] Auto-enable/disable by season calendar
- [ ] MLB re-enablement (April 1)
- [ ] Config file for season dates

### D3: Notion Integration 🚧
- [x] Project page created
- [ ] Auto-sync picks results to Notion
- [ ] Performance tracking dashboard
- [ ] Deliverable status updates

### D4: Result Tracking 🚧
- [x] ESPN score fetching
- [x] W/L/P evaluation
- [ ] Telegram result notifications
- [ ] Weekly/monthly summaries

### D5: Enhancements 📋
- [ ] Capper Collective monitor (capper_monitor.py)
- [ ] Kelly sizing overlay
- [ ] CLV (Closing Line Value) tracking
- [ ] Multi-channel posting

## File Locations

| File | Location | Purpose |
|------|----------|---------|
| `daily_channel_picks.py` | `/data/workspace-cto/` | Main daily picks script |
| `api_client.py` | `/data/workspace-cto/pickwatch-dashboard/` | Pickwatch API client |
| `scoring.py` | `/data/workspace-cto/pickwatch-dashboard/` | Confidence scoring |
| `picks_db.json` | `/data/workspace-crypto/polymarket/` | Picks database |
| `result_checker.py` | `/data/workspace-crypto/polymarket/` | Result checking |
| `capper_monitor.py` | `/data/workspace-crypto/polymarket/` | Capper Collective monitor |

## Related Projects

- **Polymarket Strategy** (`/data/workspace-crypto/polymarket/STRATEGY.md`) — Prediction market integration
- **Crypto Automation** (`/data/workspace-crypto/crypto-automation/`) — Crypto signal engine

## Maintainers

- @ClawGeekPMbot — Product & Coordination
- @ClawGeekCTObot — Technical Implementation
- @ClawGeekCryptobot — Strategy & Risk