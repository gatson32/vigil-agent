# VIGIL — The One Who Watches

**Trust intelligence for the agent economy.**

VIGIL is the first onchain credit bureau for AI agents. It continuously monitors every agent in the Virtuals Protocol ecosystem — tracking wallet behavior, ACP transaction history, token metrics, and social activity — to produce real-time trust scores and predictive risk alerts.

> "Trust is not declared. It is observed."

---

## Architecture

```
vigil-agent/
├── SOUL.md                 # Agent identity & personality
├── README.md               # This file
├── requirements.txt        # Python dependencies
├── src/
│   ├── config.py           # All configuration & thresholds
│   ├── collector.py        # Onchain data collection (Basescan, DexScreener)
│   ├── scorer.py           # Trust scoring engine & anomaly detection
│   ├── publisher.py        # X/Twitter & Telegram publishing
│   ├── acp_service.py      # ACP trust query service interface
│   └── vigil.py            # Main orchestrator & CLI entry point
└── data/
    ├── watchlist.json       # Monitored agent addresses (auto-generated)
    └── alerts.jsonl         # Alert history log (auto-generated)
```

## Trust Score (VTS)

Every agent receives a VIGIL Trust Score from 0-100, composed of four equally weighted components:

| Component | Weight | What it measures |
|---|---|---|
| Wallet Health | 25% | Age, balance stability, transaction patterns, outflow behavior |
| ACP Track Record | 25% | Service completion rate, disputes, revenue, evaluator ratings |
| Token Stability | 25% | Holder distribution, liquidity depth, price volatility |
| Activity Consistency | 25% | Transaction frequency, social presence, uptime |

### Risk Levels

| Score | Level | Meaning |
|---|---|---|
| 80-100 | LOW RISK | Healthy, consistent agent |
| 60-79 | MODERATE | Some concerns, worth monitoring |
| 40-59 | ELEVATED | Multiple warning signs |
| 20-39 | HIGH RISK | Serious concerns — approach with caution |
| 0-19 | CRITICAL | Likely dead, rugged, or compromised |

## Anomaly Detection

VIGIL watches for these behavioral patterns:

- **RUG_PATTERN** — Wallet consolidation + liquidity drain happening simultaneously (CRITICAL)
- **LIQUIDITY_DRAIN** — Significant LP removal without wallet consolidation (HIGH)
- **AGENT_DEATH** — No onchain activity + social silence (HIGH)
- **SCORE_FREEFALL** — Trust score dropping 20+ points across recent snapshots (HIGH)
- **LARGE_OUTFLOW** — >30% of wallet balance moved in 24h (MODERATE)
- **HOLDER_CONCENTRATION** — Top wallet holds >40% of token supply (MODERATE)
- **VOLUME_ANOMALY** — 24h volume >5x the 7-day average (MODERATE)

## Setup

### 1. Install Dependencies

```bash
cd vigil-agent
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file or export these environment variables:

```bash
# Required: Basescan API for onchain data
export BASESCAN_API_KEY="your_basescan_api_key"

# Optional: Alchemy for premium RPC access
export ALCHEMY_API_KEY="your_alchemy_key"

# Optional: X/Twitter publishing
export TWITTER_API_KEY="your_twitter_api_key"
export TWITTER_API_SECRET="your_twitter_api_secret"
export TWITTER_ACCESS_TOKEN="your_access_token"
export TWITTER_ACCESS_SECRET="your_access_secret"

# Optional: Telegram bot
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token"

# Agent wallet (for ACP transactions)
export VIGIL_PRIVATE_KEY="your_agent_wallet_private_key"

# GAME SDK (for Virtuals integration)
export GAME_API_KEY="your_game_sdk_key"
```

Get a free Basescan API key at: https://basescan.org/apis

### 3. Register Agents to Monitor

```bash
# Register a specific agent
python src/vigil.py --register 0xAgentWalletAddress --name "AgentName" --token 0xTokenAddress

# Or edit src/vigil.py SEED_AGENTS list for bulk bootstrapping
```

### 4. Run

```bash
# Full autonomous monitoring loop
python src/vigil.py

# Single scan cycle (for testing)
python src/vigil.py --scan-once

# Score a single agent
python src/vigil.py --score 0xAgentAddress --token 0xTokenAddress

# Verbose logging
python src/vigil.py -v
```

## Deployment on Virtuals

### Token Launch

1. Acquire 100+ VIRTUAL tokens on Base chain
2. Register VIGIL as an agent via the Virtuals platform (app.virtuals.io)
3. Upload SOUL.md as agent personality/description
4. Deploy $VIGIL token through the agent factory

### ACP Service Registration

```bash
# Using OpenClaw CLI
npm install -g @virtuals-protocol/openclaw-acp
acp setup
acp register-service \
    --name "VIGIL Trust Score" \
    --description "Real-time trust intelligence for Virtuals Protocol agents" \
    --fee 1.0
```

### Hosting

VIGIL can run on:
- **Starchild** (iamstarchild.com) — Managed hosting for Virtuals agents
- **Self-hosted** — Any VPS with Python 3.10+ and outbound HTTPS access
- **Docker** — Containerize with the included dependencies

## Revenue Model

1. **ACP Service Fees** — Per-query trust scoring via Agent Commerce Protocol
2. **Premium Telegram** — $VIGIL holders get real-time alerts and deep queries
3. **Evaluator Role** — VIGIL serves as an ACP evaluator, earning fees on transactions
4. **Data Licensing** — Ecosystem health metrics available to protocols and DAOs

## What VIGIL Never Does

- Never shills tokens or agents
- Never provides financial advice
- Never takes positions in agent tokens
- Never accepts payment to alter scores
- Never makes guarantees — only probabilistic assessments based on observable data
