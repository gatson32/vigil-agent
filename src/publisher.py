"""
VIGIL Publisher v2 — Engagement-Optimized
Formats and publishes trust intelligence to X/Twitter and Telegram.

Key changes from v1:
- Narrative-driven tweets with hooks, context, and storytelling
- @-tagging of scanned agents and relevant accounts
- Thread support for scan reports (hook tweet + data thread)
- Real Twitter API v2 integration via OAuth 1.0a (no tweepy dependency)
- Quote-tweet and reply strategies for engagement
- Engagement-aware formatting (line breaks, emoji-free, punchy cadence)
"""

import time
import json
import hmac
import hashlib
import base64
import urllib.parse
import logging
import random
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass

from scorer import Alert
from collector import AgentProfile

logger = logging.getLogger('vigil.publisher')


# ═══════════════════════════════════════════════════════════════
# AGENT X HANDLE DATABASE
# ═══════════════════════════════════════════════════════════════

AGENT_X_HANDLES: Dict[str, str] = {
    # Major Virtuals agents — map agent name (lowercase) to X handle
    'aixbt': '@aixbt_agent',
    'luna': '@luna_virtuals',
    'game': '@gamevirtuals',
    'virtual': '@virtuals_io',
    'vigil': '@VIGIL_Trust',
    'vader': '@vaboreal',
    'sekoia': '@SekoiaAGENT',
    'convo': '@convo_agent',
    'bully': '@bullyagent',
    'iona': '@ionaagent',
    'misato': '@misato_virtuals',
    'vvaifu': '@vvaifu',
    'axal': '@axaboreal',
}

# Protocol and ecosystem accounts to tag for reach
ECOSYSTEM_HANDLES = {
    'virtuals_protocol': '@virtuals_io',
    'dexscreener': '@DEXScreener',
    'base': '@base',
}


def get_agent_handle(agent_name: str) -> str:
    """Get an agent's X handle, or return the name if unknown."""
    if not agent_name:
        return ''
    return AGENT_X_HANDLES.get(agent_name.lower(), f'${agent_name.upper()}')


def get_agent_tag(agent_name: str) -> str:
    """Get an @tag for an agent. Returns @handle or $TICKER."""
    handle = AGENT_X_HANDLES.get(agent_name.lower(), '')
    if handle:
        return handle
    return f'${agent_name.upper()}'


# ═══════════════════════════════════════════════════════════════
# ENGAGEMENT HOOKS — scroll-stopping openers
# ═══════════════════════════════════════════════════════════════

SCAN_HOOKS = [
    "Just ran the numbers on {count} agents.\n\nHere's what the data says.",
    "Most people look at price.\n\nWe look at everything else.\n\nVIGIL Scan #{scan_num}:",
    "Your agent might be dying and you don't even know it.\n\nVIGIL Scan #{scan_num}:",
    "We scanned {count} agents on @virtuals_io.\n\nOne of them has a serious problem.",
    "Trust scores just updated.\n\nSome agents improved. One got worse.\n\nThread:",
    "Liquidity can vanish in seconds.\n\nWe check it every 60.\n\nVIGIL Scan #{scan_num}:",
    "The agent economy doesn't sleep.\n\nNeither does VIGIL.\n\nScan #{scan_num}:",
]

ALERT_HOOKS = {
    'RUG_PATTERN': [
        "This is the pattern we've been warning about.\n\n{agent} just triggered a RUG_PATTERN alert.",
        "Wallet consolidation. LP removal. Social silence.\n\nAll three at once.\n\n{agent} is flagged.",
    ],
    'LIQUIDITY_DRAIN': [
        "{agent} just lost over half its liquidity in 24 hours.\n\nHere's what happened.",
        "Liquidity doesn't just disappear.\n\nSomeone pulled it.\n\n{agent} — VIGIL alert:",
    ],
    'LARGE_OUTFLOW': [
        "A wallet just moved 30%+ of {agent}'s holdings in a single transaction.",
        "Large outflow detected.\n\n{agent} lost a significant chunk of its treasury in one move.",
    ],
    'HOLDER_CONCENTRATION': [
        "One wallet controls over 40% of {agent}'s supply.\n\nThat's not distribution. That's a single point of failure.",
    ],
    'AGENT_DEATH': [
        "{agent} hasn't transacted in over 7 days.\n\nNo social activity either.\n\nThis agent is dead.",
        "Another one gone.\n\n{agent} — 7 days of silence. Zero transactions.\n\nVIGIL is calling it.",
    ],
    'VOLUME_ANOMALY': [
        "{agent} volume just spiked 5x its 7-day average.\n\nCould be organic. Could be wash trading.\n\nWe're watching.",
    ],
    'SCORE_FREEFALL': [
        "{agent}'s trust score just dropped 20+ points in a single cycle.\n\nSomething happened. Here's what we found.",
    ],
}

AUTOPSY_HOOKS = [
    "{agent} is dead.\n\nLifespan: {days} days.\n\nHere's the autopsy.",
    "Post-mortem: {agent}\n\nThe signs were there. Most people missed them.\n\nVIGIL didn't.",
    "Another agent down.\n\n{agent} lasted {days} days.\n\nWhat went wrong — a thread:",
]


# ═══════════════════════════════════════════════════════════════
# TWEET FORMATTER v2
# ═══════════════════════════════════════════════════════════════

class TweetFormatter:
    """Formats VIGIL intelligence into engagement-optimized tweets.

    Design principles (learned from crypto Twitter research):
    1. HOOK first — stop the scroll in the first line
    2. CONTEXT — why should the reader care?
    3. DATA — specific numbers, not vague claims
    4. TAG — mention the agent and relevant ecosystem accounts
    5. CTA — end with something that invites reply/RT

    Format rules:
    - Short lines. Use line breaks aggressively.
    - No emojis. VIGIL is not a shill account.
    - Bold claims backed by data.
    - Tag agents so their communities see it.
    - End with VIGIL's signature line or a question.
    """

    def __init__(self, scan_counter: int = 0):
        self.scan_counter = scan_counter

    def _risk_label(self, score: float) -> str:
        if score >= 80: return 'LOW RISK'
        if score >= 60: return 'MODERATE'
        if score >= 40: return 'ELEVATED'
        if score >= 20: return 'HIGH RISK'
        return 'CRITICAL'

    def _risk_context(self, score: float, agent_name: str, snap) -> str:
        """Generate narrative context for a score — the 'why' behind the number."""
        parts = []
        tag = get_agent_tag(agent_name)

        if snap:
            # Liquidity commentary
            if hasattr(snap, 'token_liquidity_usd') and snap.token_liquidity_usd > 0:
                liq = snap.token_liquidity_usd
                if liq < 1000:
                    parts.append(f"Liquidity at ${liq:,.0f} — critically thin. One sell could drain the pool.")
                elif liq < 10000:
                    parts.append(f"Liquidity at ${liq:,.0f} — thin for an agent this size.")
                elif liq > 1000000:
                    parts.append(f"${liq/1e6:.1f}M in liquidity — deep pool, healthy sign.")

            # Holder commentary
            if hasattr(snap, 'token_holders') and snap.token_holders > 0:
                if snap.token_holders > 500000:
                    parts.append(f"{snap.token_holders:,} holders — broad distribution.")
                elif snap.token_holders < 1000:
                    parts.append(f"Only {snap.token_holders:,} holders — concentrated ownership risk.")

            # Volume commentary
            if hasattr(snap, 'token_volume_24h') and snap.token_volume_24h > 0:
                vol = snap.token_volume_24h
                mcap = getattr(snap, 'token_market_cap', 0)
                if mcap > 0 and vol > 0:
                    ratio = vol / mcap
                    if ratio > 0.3:
                        parts.append(f"Volume/MCap ratio at {ratio:.0%} — unusually high churn.")
                    elif ratio < 0.01:
                        parts.append(f"Volume/MCap at {ratio:.1%} — barely trading.")

            # Activity commentary
            if hasattr(snap, 'last_onchain_activity_hours'):
                hours = snap.last_onchain_activity_hours
                if hours > 168:
                    parts.append(f"Last onchain activity: {hours/24:.0f} days ago. Is anyone home?")
                elif hours < 1:
                    parts.append(f"Active in the last hour. Lights are on.")

        return ' '.join(parts[:2]) if parts else ''

    def format_scan_report_thread(self, profiles: dict, scan_num: int = None) -> List[str]:
        """Format a multi-tweet thread for an ecosystem scan.

        Returns a list of tweets (first is the hook, rest are the thread).
        This is the primary engagement format — threads get 2-5x reach.
        """
        if scan_num is None:
            self.scan_counter += 1
            scan_num = self.scan_counter

        tweets = []
        sorted_agents = sorted(
            profiles.values(),
            key=lambda p: p.trust_score,
            reverse=True
        )

        # ── Tweet 1: HOOK ──
        hook_template = random.choice(SCAN_HOOKS)
        hook = hook_template.format(count=len(profiles), scan_num=scan_num)
        tweets.append(hook)

        # ── Tweet 2-N: Individual agent scores with context ──
        for i, profile in enumerate(sorted_agents):
            name = profile.agent_name or profile.agent_address[:10]
            tag = get_agent_tag(name)
            score = profile.trust_score
            risk = self._risk_label(score)
            context = self._risk_context(score, name, profile.latest)

            tweet = f"{tag}\n\n"
            tweet += f"VTS: {score:.0f}/100 — {risk}\n\n"

            if context:
                tweet += f"{context}\n"

            if profile.flags:
                tweet += f"\nFlags: {', '.join(profile.flags)}"

            tweets.append(tweet[:280])

        # ── Final tweet: Signature + CTA ──
        tags_used = [get_agent_tag(p.agent_name or '') for p in sorted_agents if p.agent_name]
        closing = (
            f"Full scan complete.\n\n"
            f"VIGIL monitors the @virtuals_io ecosystem 24/7.\n\n"
            f"Trust is not declared — it is observed.\n\n"
            f"Who should we scan next?"
        )
        tweets.append(closing[:280])

        return tweets

    def format_single_scan_tweet(self, profiles: dict, scan_num: int = None) -> str:
        """Format a compact single-tweet scan (for when threads aren't ideal).

        Packs maximum context into 280 chars with agent tags.
        """
        if scan_num is None:
            self.scan_counter += 1
            scan_num = self.scan_counter

        sorted_agents = sorted(
            profiles.values(),
            key=lambda p: p.trust_score,
            reverse=True
        )

        tweet = f"VIGIL Scan #{scan_num:03d}\n\n"

        for profile in sorted_agents:
            name = profile.agent_name or profile.agent_address[:8]
            tag = get_agent_tag(name)
            score = profile.trust_score
            risk = self._risk_label(score)
            tweet += f"{tag} — {score:.0f}/100 [{risk}]\n"

        # Find the most interesting flag to highlight
        flagged = [(p, f) for p in sorted_agents for f in (p.flags or [])
                   if 'LIQUIDITY' in f or 'RUG' in f or 'DEATH' in f]
        if flagged:
            p, flag = flagged[0]
            name = p.agent_name or p.agent_address[:8]
            tag = get_agent_tag(name)
            tweet += f"\nFlag: {tag} — {flag}\n"

        tweet += f"\n@virtuals_io ecosystem | Live data"

        return tweet[:280]

    def format_alert(self, alert: Alert) -> str:
        """Format a risk alert with narrative hook and agent tag."""
        agent_name = alert.agent_name if hasattr(alert, 'agent_name') else ''
        tag = get_agent_tag(agent_name) if agent_name else alert.agent_address[:10]

        # Pick a hook for this alert type
        hooks = ALERT_HOOKS.get(alert.alert_type, [
            "{agent} just triggered a VIGIL alert.\n\nHere's what we found."
        ])
        hook = random.choice(hooks).format(agent=tag)

        tweet = f"{hook}\n\n"

        # Add data context
        if alert.confidence > 0.8:
            tweet += f"Confidence: HIGH ({alert.confidence:.0%})\n"
        else:
            tweet += f"Confidence: {alert.confidence:.0%}\n"

        tweet += f"\n@virtuals_io ecosystem\n"
        tweet += f"Trust is not declared — it is observed."

        return tweet[:280]

    def format_autopsy(self, profile: AgentProfile, cause: str) -> List[str]:
        """Format an agent death autopsy as a thread."""
        name = profile.agent_name or profile.agent_address[:10]
        tag = get_agent_tag(name)
        days_alive = 0
        if profile.first_seen:
            days_alive = (time.time() - profile.first_seen) / 86400

        tweets = []

        # Hook tweet
        hook = random.choice(AUTOPSY_HOOKS).format(agent=tag, days=f"{days_alive:.0f}")
        tweets.append(hook)

        # Data tweet
        data_tweet = (
            f"Final numbers for {tag}:\n\n"
            f"Last VTS: {profile.trust_score:.0f}/100\n"
            f"Lifespan: {days_alive:.0f} days\n"
            f"Cause of death: {cause}\n"
        )
        if profile.latest:
            snap = profile.latest
            if hasattr(snap, 'token_liquidity_usd'):
                data_tweet += f"Final liquidity: ${snap.token_liquidity_usd:,.0f}\n"
            if hasattr(snap, 'token_holders'):
                data_tweet += f"Holders at death: {snap.token_holders:,}\n"
        tweets.append(data_tweet[:280])

        # Lesson tweet
        lesson = (
            f"The signs were there.\n\n"
            f"VIGIL flagged this before the collapse.\n\n"
            f"If you're holding agent tokens without checking trust scores, "
            f"you're gambling blind.\n\n"
            f"@virtuals_io ecosystem — stay vigilant."
        )
        tweets.append(lesson[:280])

        return tweets

    def format_ecosystem_report(self, profiles: dict) -> str:
        """Format a periodic ecosystem health report."""
        total = len(profiles)
        if total == 0:
            return "VIGIL Ecosystem Report: No agents currently monitored."

        scores = [p.trust_score for p in profiles.values()]
        avg_score = sum(scores) / len(scores) if scores else 0

        healthy = len([s for s in scores if s >= 80])
        concerning = len([s for s in scores if s < 60])

        tweet = (
            f"Ecosystem health check.\n\n"
            f"{total} agents monitored on @virtuals_io\n"
            f"Average trust score: {avg_score:.0f}/100\n\n"
            f"Healthy (80+): {healthy}\n"
            f"Concerning (<60): {concerning}\n\n"
        )

        if concerning > 0:
            tweet += f"Something to watch.\n"
        else:
            tweet += f"Ecosystem looking stable.\n"

        tweet += f"\nFull reports: @VIGIL_Trust"

        return tweet[:280]

    def format_commentary(self, topic: str, insight: str,
                          agents_mentioned: List[str] = None) -> str:
        """Format a standalone commentary tweet for engagement.

        These are opinion/insight tweets that don't need scan data —
        they build VIGIL's voice as a thought leader.
        """
        tweet = f"{topic}\n\n{insight}\n"

        if agents_mentioned:
            tags = ' '.join(get_agent_tag(a) for a in agents_mentioned[:3])
            tweet += f"\n{tags}\n"

        tweet += f"\n@virtuals_io"
        return tweet[:280]


# ═══════════════════════════════════════════════════════════════
# OAUTH 1.0a IMPLEMENTATION (no external deps needed)
# ═══════════════════════════════════════════════════════════════

def _generate_nonce() -> str:
    return base64.b64encode(str(random.getrandbits(256)).encode()).decode().rstrip('=')


def _generate_timestamp() -> str:
    return str(int(time.time()))


def _percent_encode(s: str) -> str:
    return urllib.parse.quote(str(s), safe='')


def build_oauth_header(method: str, url: str, params: dict,
                       consumer_key: str, consumer_secret: str,
                       token: str, token_secret: str) -> str:
    """Build OAuth 1.0a Authorization header for Twitter API."""
    oauth_params = {
        'oauth_consumer_key': consumer_key,
        'oauth_nonce': _generate_nonce(),
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': _generate_timestamp(),
        'oauth_token': token,
        'oauth_version': '1.0',
    }

    # Combine all params for signature base
    all_params = {**oauth_params, **params}
    sorted_params = '&'.join(
        f'{_percent_encode(k)}={_percent_encode(v)}'
        for k, v in sorted(all_params.items())
    )

    base_string = f'{method}&{_percent_encode(url)}&{_percent_encode(sorted_params)}'
    signing_key = f'{_percent_encode(consumer_secret)}&{_percent_encode(token_secret)}'

    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()

    oauth_params['oauth_signature'] = signature

    header_parts = ', '.join(
        f'{_percent_encode(k)}="{_percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )

    return f'OAuth {header_parts}'


# ═══════════════════════════════════════════════════════════════
# X/TWITTER PUBLISHER v2
# ═══════════════════════════════════════════════════════════════

class TwitterPublisher:
    """Publishes VIGIL intelligence to X/Twitter.

    Uses Twitter API v2 with OAuth 1.0a (User Context).
    Posts single tweets and threads with reply chaining.
    """

    TWEET_URL = "https://api.twitter.com/2/tweets"

    def __init__(self, api_key: str = '', api_secret: str = '',
                 access_token: str = '', access_secret: str = '',
                 scan_counter: int = 0):
        self.formatter = TweetFormatter(scan_counter=scan_counter)
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.access_secret = access_secret
        self._enabled = bool(api_key and access_token)

    async def post_scan_thread(self, profiles: dict, scan_num: int = None):
        """Post an ecosystem scan as a thread (hook + agent details + closing)."""
        tweets = self.formatter.format_scan_report_thread(profiles, scan_num)
        await self._post_thread(tweets)

    async def post_scan_single(self, profiles: dict, scan_num: int = None):
        """Post a compact single-tweet scan."""
        tweet = self.formatter.format_single_scan_tweet(profiles, scan_num)
        await self._post(tweet)

    async def post_alert(self, alert: Alert):
        """Post a risk alert."""
        tweet = self.formatter.format_alert(alert)
        await self._post(tweet)

    async def post_autopsy(self, profile: AgentProfile, cause: str):
        """Post an agent death autopsy as a thread."""
        tweets = self.formatter.format_autopsy(profile, cause)
        await self._post_thread(tweets)

    async def post_ecosystem_report(self, profiles: dict):
        """Post periodic ecosystem health report."""
        tweet = self.formatter.format_ecosystem_report(profiles)
        await self._post(tweet)

    async def post_commentary(self, topic: str, insight: str,
                              agents: List[str] = None):
        """Post a standalone commentary/thought-leadership tweet."""
        tweet = self.formatter.format_commentary(topic, insight, agents)
        await self._post(tweet)

    async def _post_thread(self, tweets: List[str]):
        """Post a series of tweets as a thread (reply chain)."""
        if not tweets:
            return

        # Post the first tweet
        first_id = await self._post(tweets[0])
        if not first_id:
            return

        # Chain replies
        prev_id = first_id
        for tweet_text in tweets[1:]:
            prev_id = await self._post(tweet_text, reply_to=prev_id)
            if not prev_id:
                logger.warning("Thread broken — could not post reply")
                break

    async def _post(self, text: str, reply_to: str = None) -> Optional[str]:
        """Post a tweet via Twitter API v2. Returns tweet ID if successful."""
        if not self._enabled:
            logger.info(f"[DRY RUN] Would tweet:\n{text}\n")
            return 'dry_run_id'

        try:
            import httpx

            body = {"text": text}
            if reply_to:
                body["reply"] = {"in_reply_to_tweet_id": reply_to}

            body_json = json.dumps(body)

            auth_header = build_oauth_header(
                'POST', self.TWEET_URL, {},
                self.api_key, self.api_secret,
                self.access_token, self.access_secret
            )

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.TWEET_URL,
                    content=body_json,
                    headers={
                        'Authorization': auth_header,
                        'Content-Type': 'application/json',
                    }
                )

                if response.status_code in (200, 201):
                    data = response.json()
                    tweet_id = data.get('data', {}).get('id', '')
                    logger.info(f"[TWEETED] ID:{tweet_id} — {text[:60]}...")
                    return tweet_id
                else:
                    logger.error(f"[TWEET FAILED] {response.status_code}: {response.text}")
                    return None

        except ImportError:
            # httpx not available — fall back to urllib
            logger.warning("httpx not installed — using urllib fallback")
            return await self._post_urllib(text, reply_to)
        except Exception as e:
            logger.error(f"[TWEET ERROR] {e}")
            return None

    async def _post_urllib(self, text: str, reply_to: str = None) -> Optional[str]:
        """Fallback poster using only stdlib (urllib)."""
        import urllib.request

        body = {"text": text}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}

        body_bytes = json.dumps(body).encode()

        auth_header = build_oauth_header(
            'POST', self.TWEET_URL, {},
            self.api_key, self.api_secret,
            self.access_token, self.access_secret
        )

        req = urllib.request.Request(
            self.TWEET_URL,
            data=body_bytes,
            headers={
                'Authorization': auth_header,
                'Content-Type': 'application/json',
            },
            method='POST'
        )

        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                tweet_id = data.get('data', {}).get('id', '')
                logger.info(f"[TWEETED/urllib] ID:{tweet_id} — {text[:60]}...")
                return tweet_id
        except Exception as e:
            logger.error(f"[TWEET/urllib ERROR] {e}")
            return None


# ═══════════════════════════════════════════════════════════════
# TELEGRAM BOT
# ═══════════════════════════════════════════════════════════════

class TelegramPublisher:
    """VIGIL Telegram bot for premium trust queries and alerts.

    Commands:
      /score <agent_name_or_address> — Get trust score
      /alerts — List recent alerts
      /health — Ecosystem health summary
      /watchlist add <agent> — Add agent to personal watchlist
      /watchlist — View your watchlist
    """

    TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, bot_token: str = ''):
        self.bot_token = bot_token
        self._enabled = bool(bot_token)
        self.subscriber_watchlists: dict = {}

    async def send_alert(self, alert: Alert, chat_ids: List[str] = None):
        """Send alert to subscribers."""
        if not self._enabled:
            logger.info(f"[TG DRY RUN] Alert: {alert.message[:80]}")
            return

        targets = chat_ids or []
        if not targets:
            for chat_id, watchlist in self.subscriber_watchlists.items():
                if alert.agent_address in watchlist:
                    targets.append(chat_id)

        for chat_id in targets:
            text = (
                f"<b>VIGIL [{alert.severity}]</b>\n\n"
                f"{alert.message}\n\n"
                f"Confidence: {alert.confidence:.0%}"
            )
            await self._send_message(chat_id, text)

    async def send_score_response(self, chat_id: str, profile: AgentProfile):
        """Respond to a /score query with full trust breakdown."""
        snap = profile.latest
        name = profile.agent_name or profile.agent_address[:10]

        text = f"<b>VIGIL Trust Score: {name}</b>\n"
        text += f"{'─'*28}\n"
        text += f"VTS: <b>{profile.trust_score:.0f}/100</b> [{profile.risk_level}]\n\n"

        if snap:
            text += f"<b>Wallet Health:</b>\n"
            text += f"  Age: {snap.wallet_age_days:.0f} days\n"
            text += f"  Balance: {snap.wallet_balance_eth:.4f} ETH\n"
            text += f"  Txns (7d): {snap.tx_count_7d}\n\n"

            if snap.token_address:
                text += f"<b>Token Health:</b>\n"
                text += f"  Price: ${snap.token_price_usd:.4f}\n"
                text += f"  MCap: ${snap.token_market_cap:,.0f}\n"
                text += f"  Liquidity: ${snap.token_liquidity_usd:,.0f}\n"
                text += f"  Holders: {snap.token_holders}\n"
                text += f"  Top holder: {snap.token_top_holder_pct:.0%}\n\n"

            if snap.acp_transactions_total > 0:
                text += f"<b>ACP Track Record:</b>\n"
                text += f"  Services: {snap.acp_services_registered}\n"
                rate = snap.acp_transactions_completed / max(snap.acp_transactions_total, 1)
                text += f"  Completion: {rate:.0%}\n"
                text += f"  Revenue: ${snap.acp_revenue_total:,.0f}\n\n"

        if profile.flags:
            text += f"<b>Active Flags:</b> {', '.join(profile.flags)}\n"

        await self._send_message(chat_id, text)

    async def _send_message(self, chat_id: str, text: str):
        """Send via Telegram Bot API."""
        if not self._enabled:
            logger.info(f"[TG DRY RUN → {chat_id}] {text[:80]}...")
            return

        try:
            import httpx
            url = self.TELEGRAM_API.format(token=self.bot_token)
            async with httpx.AsyncClient() as client:
                await client.post(url, json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                })
        except ImportError:
            # urllib fallback
            import urllib.request
            url = self.TELEGRAM_API.format(token=self.bot_token)
            body = json.dumps({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            }).encode()
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/json'
            })
            try:
                urllib.request.urlopen(req)
            except Exception as e:
                logger.error(f"[TG ERROR] {e}")


# ═══════════════════════════════════════════════════════════════
# ENGAGEMENT STRATEGY — Commentary Generator
# ═══════════════════════════════════════════════════════════════

# Pre-written commentary templates VIGIL can post between scans
# to build voice, engagement, and followers.
# These are designed as standalone thought-leadership tweets.

COMMENTARY_TEMPLATES = [
    {
        'topic': "The agent economy has a trust problem.",
        'insight': (
            "18,000+ agents launched. No standardized way to tell "
            "which ones are real and which are dead on arrival.\n\n"
            "That's why VIGIL exists."
        ),
        'agents': [],
    },
    {
        'topic': "Liquidity is the canary in the coal mine.",
        'insight': (
            "When an agent's LP starts thinning, something is wrong.\n\n"
            "By the time you notice, it's usually too late.\n\n"
            "VIGIL notices first."
        ),
        'agents': [],
    },
    {
        'topic': "Agent-to-agent commerce is coming.",
        'insight': (
            "When AI agents transact with each other, "
            "how do they know who to trust?\n\n"
            "They ask VIGIL."
        ),
        'agents': [],
    },
    {
        'topic': "Most agent tokens will go to zero.",
        'insight': (
            "That's not FUD — it's math.\n\n"
            "97% revenue decline in 3 months.\n\n"
            "The question isn't if agents will die. "
            "It's whether you'll know before it happens."
        ),
        'agents': [],
    },
    {
        'topic': "Price is the last thing to move.",
        'insight': (
            "Wallet behavior changes first.\n"
            "Then liquidity shifts.\n"
            "Then holder distribution.\n"
            "Then price.\n\n"
            "VIGIL watches the leading indicators."
        ),
        'agents': [],
    },
    {
        'topic': "We don't shill. We don't trade. We don't promote.",
        'insight': (
            "VIGIL has one job: watch the data and tell the truth.\n\n"
            "If that makes us boring, good.\n\n"
            "Boring is trustworthy."
        ),
        'agents': [],
    },
]
