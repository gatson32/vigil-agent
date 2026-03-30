"""
VIGIL — The One Who Watches
Main orchestrator that ties together data collection, trust scoring,
anomaly detection, and publishing into a continuous monitoring loop.

Usage:
    python vigil.py                    # Run full autonomous loop
    python vigil.py --scan-once        # Single scan cycle (for testing)
    python vigil.py --score <address>  # Score a single agent
"""

import asyncio
import time
import signal
import logging
import argparse
import json
from pathlib import Path
from typing import Optional

from config import (
    SCAN_INTERVAL_SECONDS,
    SCORE_UPDATE_INTERVAL_SECONDS,
    BASESCAN_API_KEY,
    TWITTER_API_KEY, TWITTER_API_SECRET,
    TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET,
    TELEGRAM_BOT_TOKEN,
)
from collector import VirtualsScanner, AgentProfile
from scorer import update_agent_scores, compute_trust_score, get_risk_level, Alert
from publisher import TwitterPublisher, TelegramPublisher

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('vigil')

# ═══════════════════════════════════════════════════════════════
# STATE PERSISTENCE
# ═══════════════════════════════════════════════════════════════

STATE_DIR = Path(__file__).parent.parent / 'data'
WATCHLIST_FILE = STATE_DIR / 'watchlist.json'
ALERTS_LOG = STATE_DIR / 'alerts.jsonl'


def load_watchlist() -> list:
    """Load the agent watchlist from disk."""
    if WATCHLIST_FILE.exists():
        try:
            with open(WATCHLIST_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load watchlist: {e}")
    return []


def save_watchlist(agents: list):
    """Save the agent watchlist to disk."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST_FILE, 'w') as f:
        json.dump(agents, f, indent=2)


def log_alert(alert: Alert):
    """Append an alert to the persistent alert log."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        'timestamp': alert.timestamp,
        'agent_address': alert.agent_address,
        'agent_name': alert.agent_name,
        'severity': alert.severity,
        'alert_type': alert.alert_type,
        'message': alert.message,
        'confidence': alert.confidence,
        'data': alert.data,
    }
    with open(ALERTS_LOG, 'a') as f:
        f.write(json.dumps(entry) + '\n')


# ═══════════════════════════════════════════════════════════════
# SEED AGENTS (bootstrap watchlist)
# ═══════════════════════════════════════════════════════════════

# Well-known agents to seed monitoring on first run.
# In production, agents are discovered automatically from factory events.
SEED_AGENTS = [
    # Top Virtuals ecosystem agents — mix of blue chips, mid-tier, and VIGIL itself
    # Format: (wallet_address, name, token_address)

    # AIXBT — the "Bloomberg Terminal" of crypto agents, 445K+ X followers
    ('0x4f9fd6be4a90f2620860d680c0d4d5fb53d1a825', 'AIXBT', '0x4f9fd6be4a90f2620860d680c0d4d5fb53d1a825'),

    # Luna — 24/7 AI livestreamer, 500K+ TikTok followers
    ('0x55cd6469f597452b5a7536e2cd98fde4c1247ee4', 'Luna', '0x55cd6469f597452b5a7536e2cd98fde4c1247ee4'),

    # GAME — GAME SDK token, powers autonomous agent decision-making
    ('0x1c4cca7c5db003824208adda61bd749e55f463a3', 'GAME', '0x1c4cca7c5db003824208adda61bd749e55f463a3'),

    # VIRTUAL — the protocol token itself (monitor for ecosystem health)
    ('0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b', 'VIRTUAL', '0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b'),

    # VIGIL — monitor ourselves
    ('0x643067FAF4f22bB6a1F3298da034520057E41C95', 'VIGIL', '0xFe19FEfC9B05d1a52e95C3d2a4daD0448C8f3BA6'),
]


# ═══════════════════════════════════════════════════════════════
# VIGIL ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════

class Vigil:
    """Main VIGIL orchestrator — runs the continuous monitoring loop."""

    def __init__(self):
        # Core components
        self.scanner = VirtualsScanner(basescan_api_key=BASESCAN_API_KEY)
        self.twitter = TwitterPublisher(
            api_key=TWITTER_API_KEY,
            api_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_secret=TWITTER_ACCESS_SECRET,
        )
        self.telegram = TelegramPublisher(bot_token=TELEGRAM_BOT_TOKEN)

        # Timing
        self.last_scan_time: float = 0.0
        self.last_report_time: float = 0.0
        self.cycle_count: int = 0

        # Shutdown flag
        self._running = True

    def _register_signals(self):
        """Register graceful shutdown handlers."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        logger.info(f"Shutdown signal received ({signum}). Finishing current cycle...")
        self._running = False

    def bootstrap(self):
        """Load watchlist and seed agents."""
        # Load persisted watchlist
        saved = load_watchlist()
        for entry in saved:
            self.scanner.register_agent(
                address=entry['address'],
                name=entry.get('name', ''),
                token_address=entry.get('token_address', ''),
            )

        # Add seed agents if not already registered
        for addr, name, token_addr in SEED_AGENTS:
            if addr not in self.scanner.agents:
                self.scanner.register_agent(addr, name, token_addr)

        agent_count = len(self.scanner.agents)
        logger.info(f"VIGIL bootstrapped with {agent_count} agents on watchlist.")

    def persist_watchlist(self):
        """Save current agent list to disk."""
        agents = []
        for addr, profile in self.scanner.agents.items():
            agents.append({
                'address': addr,
                'name': profile.agent_name,
                'token_address': profile.token_address,
            })
        save_watchlist(agents)

    async def run_scan_cycle(self):
        """Execute one full scan → score → alert → publish cycle."""
        self.cycle_count += 1
        cycle_start = time.time()
        logger.info(f"═══ Cycle {self.cycle_count} starting ═══")

        # Step 1: Collect fresh data
        logger.info("Step 1/4: Collecting onchain data...")
        await self.scanner.scan_all()
        self.last_scan_time = time.time()

        # Step 2: Score all agents and detect anomalies
        logger.info("Step 2/4: Computing trust scores & anomaly detection...")
        profiles = self.scanner.get_all_profiles()
        alerts = update_agent_scores(profiles)

        # Step 3: Log and publish alerts
        if alerts:
            logger.info(f"Step 3/4: Publishing {len(alerts)} alerts...")
            for alert in alerts:
                log_alert(alert)
                logger.warning(
                    f"ALERT [{alert.severity}] {alert.agent_name}: "
                    f"{alert.alert_type} — {alert.message[:100]}"
                )
                # Publish to X
                await self.twitter.post_alert(alert)
                # Publish to Telegram subscribers
                await self.telegram.send_alert(alert)
        else:
            logger.info("Step 3/4: No new alerts this cycle.")

        # Step 4: Periodic ecosystem report (every SCORE_UPDATE_INTERVAL)
        now = time.time()
        if now - self.last_report_time > SCORE_UPDATE_INTERVAL_SECONDS:
            logger.info("Step 4/4: Publishing ecosystem report...")
            await self.twitter.post_ecosystem_report(profiles)
            self.last_report_time = now
        else:
            logger.info("Step 4/4: Ecosystem report not due yet.")

        # Persist state
        self.persist_watchlist()

        elapsed = time.time() - cycle_start
        logger.info(
            f"═══ Cycle {self.cycle_count} complete in {elapsed:.1f}s "
            f"({len(profiles)} agents, {len(alerts)} alerts) ═══"
        )

    async def run_loop(self):
        """Main loop — runs scan cycles at configured intervals."""
        self._register_signals()
        self.bootstrap()

        logger.info(
            f"VIGIL is watching. Scan interval: {SCAN_INTERVAL_SECONDS}s, "
            f"Report interval: {SCORE_UPDATE_INTERVAL_SECONDS}s"
        )

        while self._running:
            try:
                await self.run_scan_cycle()
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)

            # Wait for next cycle (interruptible)
            wait_start = time.time()
            while self._running and (time.time() - wait_start) < SCAN_INTERVAL_SECONDS:
                await asyncio.sleep(1)

        logger.info("VIGIL shutting down. Trust never sleeps, but I need a restart.")

    async def score_single(self, address: str, token_address: str = '') -> Optional[AgentProfile]:
        """Score a single agent (one-shot mode for testing)."""
        self.scanner.register_agent(address, token_address=token_address)
        profile = self.scanner.get_profile(address)
        if not profile:
            logger.error(f"Failed to find profile for {address}")
            return None

        # Collect snapshot
        snap = await self.scanner.collect_snapshot(address, token_address)
        profile.add_snapshot(snap)

        # Score
        score, components = compute_trust_score(profile)
        profile.trust_score = score
        profile.risk_level = get_risk_level(score)

        logger.info(f"Agent {address[:10]}:")
        logger.info(f"  Trust Score: {score:.0f}/100 [{profile.risk_level}]")
        for comp, val in components.items():
            logger.info(f"  {comp}: {val:.0f}")

        return profile


# ═══════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='VIGIL — Trust intelligence for the agent economy'
    )
    parser.add_argument(
        '--scan-once', action='store_true',
        help='Run a single scan cycle and exit'
    )
    parser.add_argument(
        '--score', type=str, metavar='ADDRESS',
        help='Score a single agent by wallet address'
    )
    parser.add_argument(
        '--token', type=str, metavar='TOKEN_ADDRESS', default='',
        help='Token address for --score mode'
    )
    parser.add_argument(
        '--register', type=str, metavar='ADDRESS',
        help='Register an agent address to the watchlist'
    )
    parser.add_argument(
        '--name', type=str, default='',
        help='Agent name for --register'
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Enable debug logging'
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    vigil = Vigil()

    if args.register:
        vigil.bootstrap()
        vigil.scanner.register_agent(args.register, args.name, args.token)
        vigil.persist_watchlist()
        logger.info(f"Registered {args.name or args.register} to watchlist.")
        return

    if args.score:
        asyncio.run(vigil.score_single(args.score, args.token))
        return

    if args.scan_once:
        vigil.bootstrap()
        asyncio.run(vigil.run_scan_cycle())
        return

    # Default: run continuous monitoring loop
    asyncio.run(vigil.run_loop())


if __name__ == '__main__':
    main()
