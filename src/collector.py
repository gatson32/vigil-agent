"""
VIGIL Data Collector
Monitors onchain data for all Virtuals Protocol agents on Base chain.

Collects:
  - Agent wallet transactions and balance history
  - ACP service registry events (new services, completions, disputes)
  - Agent token metrics (holders, liquidity, volume, price)
  - Social activity signals (X/Twitter post frequency)
"""

import asyncio
import time
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

try:
    from web3 import Web3
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from config import (
    BASE_RPC_URL, BASESCAN_API_KEY, ALCHEMY_API_KEY,
    SCAN_INTERVAL_SECONDS, DEEP_ANALYSIS_INTERVAL_SECONDS,
)

logger = logging.getLogger('vigil.collector')


# ═══════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentSnapshot:
    """Point-in-time snapshot of an agent's observable state."""
    agent_address: str
    agent_name: str = ''
    token_address: str = ''
    timestamp: float = 0.0

    # Wallet metrics
    wallet_balance_eth: float = 0.0
    wallet_balance_virtual: float = 0.0
    wallet_age_days: float = 0.0
    tx_count_24h: int = 0
    tx_count_7d: int = 0
    largest_outflow_24h: float = 0.0  # As fraction of total balance
    unique_counterparties_7d: int = 0

    # Token metrics
    token_price_usd: float = 0.0
    token_price_change_24h: float = 0.0
    token_market_cap: float = 0.0
    token_volume_24h: float = 0.0
    token_volume_7d_avg: float = 0.0
    token_holders: int = 0
    token_top_holder_pct: float = 0.0  # % held by largest wallet
    token_liquidity_usd: float = 0.0
    token_liquidity_change_24h: float = 0.0  # % change

    # ACP metrics
    acp_services_registered: int = 0
    acp_transactions_total: int = 0
    acp_transactions_completed: int = 0
    acp_transactions_disputed: int = 0
    acp_revenue_total: float = 0.0
    acp_avg_evaluation_score: float = 0.0
    acp_last_transaction_age_hours: float = 0.0

    # Activity metrics
    last_onchain_activity_hours: float = 0.0
    social_posts_24h: int = 0
    social_posts_7d: int = 0
    social_followers: int = 0
    social_engagement_rate: float = 0.0

    def to_dict(self):
        return asdict(self)


@dataclass
class AgentProfile:
    """Persistent profile tracking an agent over time."""
    agent_address: str
    agent_name: str = ''
    token_address: str = ''
    first_seen: float = 0.0
    snapshots: List[AgentSnapshot] = field(default_factory=list)
    trust_score: float = 50.0  # Default neutral score
    risk_level: str = 'MODERATE'
    flags: List[str] = field(default_factory=list)
    last_alert_time: float = 0.0

    @property
    def latest(self) -> Optional[AgentSnapshot]:
        return self.snapshots[-1] if self.snapshots else None

    def add_snapshot(self, snapshot: AgentSnapshot):
        self.snapshots.append(snapshot)
        # Keep last 168 snapshots (7 days at hourly resolution)
        if len(self.snapshots) > 168:
            self.snapshots = self.snapshots[-168:]


# ═══════════════════════════════════════════════════════════════
# BASESCAN API CLIENT
# ═══════════════════════════════════════════════════════════════

class BasescanClient:
    """Fetches onchain data from Basescan API."""

    BASE_URL = "https://api.basescan.org/api"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30) if HAS_HTTPX else None

    async def get_transactions(self, address: str, start_block: int = 0,
                                sort: str = 'desc', limit: int = 100) -> List[dict]:
        """Get normal transactions for an address."""
        if not self.client:
            return []
        params = {
            'module': 'account',
            'action': 'txlist',
            'address': address,
            'startblock': start_block,
            'sort': sort,
            'page': 1,
            'offset': limit,
            'apikey': self.api_key,
        }
        try:
            resp = await self.client.get(self.BASE_URL, params=params)
            data = resp.json()
            if data.get('status') == '1':
                return data.get('result', [])
        except Exception as e:
            logger.error(f"Basescan txlist error for {address}: {e}")
        return []

    async def get_token_transfers(self, address: str, token_address: str = '',
                                   limit: int = 100) -> List[dict]:
        """Get ERC-20 token transfers for an address."""
        if not self.client:
            return []
        params = {
            'module': 'account',
            'action': 'tokentx',
            'address': address,
            'sort': 'desc',
            'page': 1,
            'offset': limit,
            'apikey': self.api_key,
        }
        if token_address:
            params['contractaddress'] = token_address
        try:
            resp = await self.client.get(self.BASE_URL, params=params)
            data = resp.json()
            if data.get('status') == '1':
                return data.get('result', [])
        except Exception as e:
            logger.error(f"Basescan tokentx error for {address}: {e}")
        return []

    async def get_balance(self, address: str) -> float:
        """Get ETH balance for an address (in ETH)."""
        if not self.client:
            return 0.0
        params = {
            'module': 'account',
            'action': 'balance',
            'address': address,
            'tag': 'latest',
            'apikey': self.api_key,
        }
        try:
            resp = await self.client.get(self.BASE_URL, params=params)
            data = resp.json()
            if data.get('status') == '1':
                return int(data['result']) / 1e18
        except Exception as e:
            logger.error(f"Basescan balance error for {address}: {e}")
        return 0.0


# ═══════════════════════════════════════════════════════════════
# DEXSCREENER CLIENT (Token Metrics)
# ═══════════════════════════════════════════════════════════════

class DexScreenerClient:
    """Fetches token price, volume, liquidity from DexScreener API."""

    BASE_URL = "https://api.dexscreener.com/latest/dex"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15) if HAS_HTTPX else None

    async def get_token_info(self, token_address: str) -> dict:
        """Get token pair data from DexScreener."""
        if not self.client:
            return {}
        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/tokens/{token_address}"
            )
            data = resp.json()
            pairs = data.get('pairs', [])
            if pairs:
                # Return the pair with highest liquidity
                return max(pairs, key=lambda p: float(p.get('liquidity', {}).get('usd', 0)))
        except Exception as e:
            logger.error(f"DexScreener error for {token_address}: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════
# VIRTUALS ECOSYSTEM SCANNER
# ═══════════════════════════════════════════════════════════════

class VirtualsScanner:
    """Discovers and monitors all agents in the Virtuals Protocol ecosystem."""

    def __init__(self, basescan_api_key: str):
        self.basescan = BasescanClient(basescan_api_key)
        self.dexscreener = DexScreenerClient()
        self.agents: Dict[str, AgentProfile] = {}
        self.last_full_scan: float = 0.0

    async def discover_agents(self) -> List[str]:
        """Discover agent addresses from Virtuals Agent Factory contract events.

        In production, this monitors the AgentCreated events from the factory contract.
        For now, returns a placeholder that will be populated from the Virtuals API.
        """
        # TODO: Monitor Agent Factory contract for AgentCreated events
        # TODO: Query Virtuals API at app.virtuals.io for agent listing
        # TODO: Monitor ACP Service Registry for new service registrations
        logger.info("Agent discovery running...")
        return list(self.agents.keys())

    async def collect_snapshot(self, agent_address: str,
                                token_address: str = '') -> AgentSnapshot:
        """Collect a full data snapshot for a single agent."""
        snap = AgentSnapshot(
            agent_address=agent_address,
            timestamp=time.time(),
        )

        # Wallet data
        snap.wallet_balance_eth = await self.basescan.get_balance(agent_address)

        txs = await self.basescan.get_transactions(agent_address, limit=200)
        now = time.time()

        if txs:
            # Wallet age
            oldest_tx = min(txs, key=lambda t: int(t.get('timeStamp', now)))
            snap.wallet_age_days = (now - int(oldest_tx.get('timeStamp', now))) / 86400

            # Transaction frequency
            day_ago = now - 86400
            week_ago = now - 604800
            snap.tx_count_24h = len([t for t in txs if int(t.get('timeStamp', 0)) > day_ago])
            snap.tx_count_7d = len([t for t in txs if int(t.get('timeStamp', 0)) > week_ago])

            # Largest outflow as fraction of balance
            outflows = [
                int(t.get('value', 0)) / 1e18
                for t in txs
                if t.get('from', '').lower() == agent_address.lower()
                and int(t.get('timeStamp', 0)) > day_ago
            ]
            if outflows and snap.wallet_balance_eth > 0:
                snap.largest_outflow_24h = max(outflows) / (snap.wallet_balance_eth + sum(outflows))

            # Unique counterparties
            counterparties = set()
            for t in txs:
                if int(t.get('timeStamp', 0)) > week_ago:
                    counterparties.add(t.get('to', '').lower())
                    counterparties.add(t.get('from', '').lower())
            counterparties.discard(agent_address.lower())
            counterparties.discard('')
            snap.unique_counterparties_7d = len(counterparties)

            # Last activity
            newest_tx = max(txs, key=lambda t: int(t.get('timeStamp', 0)))
            snap.last_onchain_activity_hours = (now - int(newest_tx.get('timeStamp', now))) / 3600

        # Token data (if token address known)
        if token_address:
            snap.token_address = token_address
            pair_data = await self.dexscreener.get_token_info(token_address)
            if pair_data:
                snap.token_price_usd = float(pair_data.get('priceUsd', 0) or 0)
                price_change = pair_data.get('priceChange', {})
                snap.token_price_change_24h = float(price_change.get('h24', 0) or 0) / 100
                snap.token_market_cap = float(pair_data.get('marketCap', 0) or 0)
                volume = pair_data.get('volume', {})
                snap.token_volume_24h = float(volume.get('h24', 0) or 0)
                liq = pair_data.get('liquidity', {})
                snap.token_liquidity_usd = float(liq.get('usd', 0) or 0)

        return snap

    async def scan_all(self):
        """Run a collection cycle across all known agents."""
        agent_addresses = await self.discover_agents()
        logger.info(f"Scanning {len(agent_addresses)} agents...")

        for addr in agent_addresses:
            profile = self.agents.get(addr)
            if not profile:
                continue
            try:
                snap = await self.collect_snapshot(addr, profile.token_address)
                snap.agent_name = profile.agent_name
                profile.add_snapshot(snap)
            except Exception as e:
                logger.error(f"Error scanning {addr}: {e}")

            # Rate limit: don't hammer APIs
            await asyncio.sleep(0.5)

        self.last_full_scan = time.time()
        logger.info(f"Scan complete. {len(agent_addresses)} agents updated.")

    def register_agent(self, address: str, name: str = '', token_address: str = ''):
        """Manually register an agent to monitor."""
        if address not in self.agents:
            self.agents[address] = AgentProfile(
                agent_address=address,
                agent_name=name,
                token_address=token_address,
                first_seen=time.time(),
            )
            logger.info(f"Registered agent: {name} ({address})")

    def get_all_profiles(self) -> Dict[str, AgentProfile]:
        return self.agents

    def get_profile(self, address: str) -> Optional[AgentProfile]:
        return self.agents.get(address)
