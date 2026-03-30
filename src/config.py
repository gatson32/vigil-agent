"""
VIGIL Configuration
"""

# ═══════════════════════════════════════════════════════════════
# CHAIN CONFIG
# ═══════════════════════════════════════════════════════════════

BASE_CHAIN_ID = 8453
BASE_RPC_PUBLIC = "https://mainnet.base.org"
# Alchemy RPC — constructed after env vars are loaded (see bottom of file)
BASE_BLOCK_TIME = 2  # seconds

# ═══════════════════════════════════════════════════════════════
# VIRTUALS PROTOCOL CONTRACTS (Base chain)
# ═══════════════════════════════════════════════════════════════

# Agent Factory — where new agent tokens are deployed
VIRTUALS_AGENT_FACTORY = "0x..."  # Fill with actual contract address

# VIGIL Agent Token Contract (deployed on Virtuals)
VIGIL_TOKEN_CA = "0xFe19FEfC9B05d1a52e95C3d2a4daD0448C8f3BA6"

# VIGIL Agent Wallet (on Virtuals platform)
VIGIL_AGENT_WALLET = "0x643067FAF4f22bB6a1F3298da034520057E41C95"

# ACP Service Registry — where agents register services
ACP_SERVICE_REGISTRY = "0x..."  # Fill with actual contract address

# ACP Escrow Contract — handles escrow for agent-to-agent transactions
ACP_ESCROW_CONTRACT = "0x..."  # Fill with actual contract address

# VIRTUAL Token Contract
VIRTUAL_TOKEN = "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b"

# ═══════════════════════════════════════════════════════════════
# VIGIL AGENT IDENTITY
# ═══════════════════════════════════════════════════════════════

VIGIL_AGENT_NAME = "VIGIL"
VIGIL_AGENT_DESCRIPTION = "Trust intelligence for the agent economy. Autonomous credit bureau for AI agents on Virtuals Protocol."

# ═══════════════════════════════════════════════════════════════
# TRUST SCORE WEIGHTS (sum to 1.0)
# ═══════════════════════════════════════════════════════════════

SCORE_WEIGHTS = {
    'wallet_health': 0.25,      # Wallet age, balance stability, transaction patterns
    'acp_track_record': 0.25,   # ACP service completion rate, evaluator ratings
    'token_stability': 0.25,    # Holder distribution, liquidity depth, price volatility
    'activity_consistency': 0.25, # Regular transactions, social activity, uptime
}

# ═══════════════════════════════════════════════════════════════
# ANOMALY DETECTION THRESHOLDS
# ═══════════════════════════════════════════════════════════════

# Wallet behavior
WALLET_CONSOLIDATION_THRESHOLD = 0.7   # >70% of holdings moved to single address
LIQUIDITY_REMOVAL_THRESHOLD = 0.5      # >50% LP removed in 24h
LARGE_TRANSFER_THRESHOLD = 0.3         # Transfer >30% of wallet balance

# Token metrics
HOLDER_CONCENTRATION_WARNING = 0.4     # Top wallet holds >40% of supply
VOLUME_SPIKE_MULTIPLIER = 5.0          # Volume >5x 7-day average
PRICE_DROP_ALERT = 0.3                 # >30% drop in 24h

# Activity patterns
INACTIVITY_DAYS_WARNING = 7            # No transactions in 7 days
SOCIAL_SILENCE_DAYS = 3                # No social posts in 3 days
ACP_FAILURE_RATE_WARNING = 0.3         # >30% of ACP transactions failed/disputed

# ═══════════════════════════════════════════════════════════════
# RISK LABELS
# ═══════════════════════════════════════════════════════════════

RISK_LEVELS = {
    (80, 100): 'LOW RISK',        # Healthy, consistent agent
    (60, 79):  'MODERATE',         # Some concerns, monitor
    (40, 59):  'ELEVATED',         # Multiple warning signs
    (20, 39):  'HIGH RISK',        # Serious concerns — approach with caution
    (0, 19):   'CRITICAL',         # Likely dead, rug, or compromised
}

# ═══════════════════════════════════════════════════════════════
# MONITORING INTERVALS
# ═══════════════════════════════════════════════════════════════

SCAN_INTERVAL_SECONDS = 60            # Full ecosystem scan every 60s
DEEP_ANALYSIS_INTERVAL_SECONDS = 3600  # Deep dive per agent every hour
SCORE_UPDATE_INTERVAL_SECONDS = 300    # Publish updated scores every 5 min
ALERT_COOLDOWN_SECONDS = 1800          # Don't repeat same alert within 30 min

# ═══════════════════════════════════════════════════════════════
# API KEYS (set via environment variables)
# ═══════════════════════════════════════════════════════════════

import os
from pathlib import Path

# Load .env file from project root
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
    pass  # python-dotenv not installed, rely on env vars

BASESCAN_API_KEY = os.environ.get('BASESCAN_API_KEY', '')
ALCHEMY_API_KEY = os.environ.get('ALCHEMY_API_KEY', '')
TWITTER_BEARER_TOKEN = os.environ.get('TWITTER_BEARER_TOKEN', '')
TWITTER_API_KEY = os.environ.get('TWITTER_API_KEY', '')
TWITTER_API_SECRET = os.environ.get('TWITTER_API_SECRET', '')
TWITTER_ACCESS_TOKEN = os.environ.get('TWITTER_ACCESS_TOKEN', '')
TWITTER_ACCESS_SECRET = os.environ.get('TWITTER_ACCESS_SECRET', '')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
VIGIL_PRIVATE_KEY = os.environ.get('VIGIL_PRIVATE_KEY', '')  # Agent wallet private key
GAME_API_KEY = os.environ.get('GAME_API_KEY', '')  # Virtuals GAME SDK API key

# ═══════════════════════════════════════════════════════════════
# DERIVED CONFIG (built from env vars above)
# ═══════════════════════════════════════════════════════════════

# Use Alchemy RPC if key is available, otherwise fall back to public
if ALCHEMY_API_KEY:
    BASE_RPC_URL = f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
else:
    BASE_RPC_URL = BASE_RPC_PUBLIC
