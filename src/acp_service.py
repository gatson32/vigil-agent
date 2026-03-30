"""
VIGIL ACP Service Interface
Exposes trust scoring as a service on the Agent Commerce Protocol.

Other agents can query VIGIL via ACP:
  - "Should I enter escrow with Agent X?" → trust score, risk flags, recommendation
  - Fee per query paid in VIRTUAL via ACP escrow (80% to VIGIL, 20% to protocol)

This module handles:
  1. Registering VIGIL as a service provider on the ACP Service Registry
  2. Listening for incoming trust query requests
  3. Processing queries and returning structured trust reports
  4. Managing escrow acceptance and settlement
"""

import asyncio
import json
import time
import logging
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List

from config import (
    ACP_SERVICE_REGISTRY, ACP_ESCROW_CONTRACT,
    VIGIL_AGENT_NAME, VIGIL_AGENT_DESCRIPTION,
)
from collector import VirtualsScanner, AgentProfile
from scorer import compute_trust_score, get_risk_level, detect_anomalies

logger = logging.getLogger('vigil.acp')


# ═══════════════════════════════════════════════════════════════
# TRUST QUERY / RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════

@dataclass
class TrustQuery:
    """Incoming trust query from another agent."""
    query_id: str
    requester_address: str
    target_agent_address: str
    target_token_address: str = ''
    query_type: str = 'full_score'  # full_score, quick_check, should_transact
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class TrustReport:
    """VIGIL trust report returned to querying agent."""
    query_id: str
    target_address: str
    target_name: str
    trust_score: float
    risk_level: str
    recommendation: str   # PROCEED, CAUTION, AVOID
    component_scores: dict
    active_flags: list
    confidence: float     # 0.0 - 1.0, based on data freshness
    summary: str
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self):
        return asdict(self)

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2)


# ═══════════════════════════════════════════════════════════════
# RECOMMENDATION ENGINE
# ═══════════════════════════════════════════════════════════════

def generate_recommendation(score: float, flags: list) -> str:
    """Generate a transaction recommendation based on trust score and flags."""
    critical_flags = {'RUG_PATTERN', 'AGENT_DEATH', 'SCORE_FREEFALL'}
    high_risk_flags = {'LIQUIDITY_DRAIN', 'LARGE_OUTFLOW'}

    # Hard avoid on critical patterns
    if any(f in critical_flags for f in flags):
        return 'AVOID'

    # Score-based recommendation
    if score >= 70 and not any(f in high_risk_flags for f in flags):
        return 'PROCEED'
    elif score >= 40:
        return 'CAUTION'
    else:
        return 'AVOID'


def generate_summary(profile: AgentProfile, score: float, risk_level: str,
                     recommendation: str, flags: list) -> str:
    """Generate a human-readable summary for the trust report."""
    name = profile.agent_name or profile.agent_address[:10]

    if recommendation == 'PROCEED':
        summary = (
            f"{name} presents as a low-risk counterparty. "
            f"VTS {score:.0f}/100 ({risk_level}). "
        )
        if profile.latest and profile.latest.wallet_age_days > 30:
            summary += f"Wallet active for {profile.latest.wallet_age_days:.0f} days. "
        if profile.latest and profile.latest.acp_transactions_completed > 0:
            rate = profile.latest.acp_transactions_completed / max(profile.latest.acp_transactions_total, 1)
            summary += f"ACP completion rate: {rate:.0%}. "
        summary += "No critical flags detected."

    elif recommendation == 'CAUTION':
        summary = (
            f"{name} shows moderate risk indicators. "
            f"VTS {score:.0f}/100 ({risk_level}). "
        )
        if flags:
            summary += f"Active flags: {', '.join(flags)}. "
        summary += "Proceed with appropriate escrow protections."

    else:  # AVOID
        summary = (
            f"{name} presents significant risk. "
            f"VTS {score:.0f}/100 ({risk_level}). "
        )
        if flags:
            summary += f"Critical flags: {', '.join(flags)}. "
        summary += "Transaction not recommended at this time."

    return summary


# ═══════════════════════════════════════════════════════════════
# ACP SERVICE PROVIDER
# ═══════════════════════════════════════════════════════════════

class ACPTrustService:
    """VIGIL's ACP service — processes trust queries from other agents.

    Service Registration (via OpenClaw CLI):
        acp register-service \\
            --name "VIGIL Trust Score" \\
            --description "Real-time trust scoring for Virtuals Protocol agents" \\
            --input-schema '{"target_address": "string", "query_type": "string"}' \\
            --output-schema '{"trust_score": "number", "risk_level": "string", ...}' \\
            --fee 1.0

    In production, this integrates with the GAME SDK's ACP worker
    to handle the full request → negotiation → escrow → delivery → evaluation flow.
    """

    # Service metadata for ACP registration
    SERVICE_NAME = "VIGIL Trust Score"
    SERVICE_DESCRIPTION = (
        "Real-time trust intelligence for Virtuals Protocol agents. "
        "Query any agent's trust score, risk flags, and transaction recommendation. "
        "Powered by onchain behavioral analysis."
    )
    SERVICE_FEE_VIRTUAL = 1.0  # Fee per query in VIRTUAL tokens

    def __init__(self, scanner: VirtualsScanner):
        self.scanner = scanner
        self._registered = False

    async def register_service(self):
        """Register VIGIL as a service on the ACP Service Registry.

        Production implementation:
            Uses web3.py to call ServiceRegistry.registerService()
            or OpenClaw CLI: `acp register-service --name "VIGIL Trust Score" ...`
        """
        logger.info(
            f"Registering ACP service: {self.SERVICE_NAME} "
            f"(fee: {self.SERVICE_FEE_VIRTUAL} VIRTUAL)"
        )
        # TODO: Implement actual ACP service registration via web3 or OpenClaw
        # ServiceRegistry.registerService(
        #     name=self.SERVICE_NAME,
        #     description=self.SERVICE_DESCRIPTION,
        #     fee=self.SERVICE_FEE_VIRTUAL,
        #     inputSchema=...,
        #     outputSchema=...,
        # )
        self._registered = True
        logger.info("ACP service registered successfully.")

    async def handle_query(self, query: TrustQuery) -> TrustReport:
        """Process an incoming trust query and return a report.

        Flow:
        1. Check if we have data on the target agent
        2. If not, collect a fresh snapshot
        3. Compute trust score
        4. Run anomaly detection
        5. Generate recommendation and report
        """
        target = query.target_agent_address
        logger.info(
            f"Processing trust query {query.query_id}: "
            f"{query.requester_address[:10]} asking about {target[:10]}"
        )

        # Ensure we have a profile for this agent
        profile = self.scanner.get_profile(target)
        if not profile:
            # First time seeing this agent — register and collect data
            self.scanner.register_agent(
                target,
                token_address=query.target_token_address,
            )
            profile = self.scanner.get_profile(target)

        # Collect fresh snapshot if data is stale (>5 min old)
        if not profile.latest or (time.time() - profile.latest.timestamp > 300):
            snap = await self.scanner.collect_snapshot(
                target, query.target_token_address
            )
            profile.add_snapshot(snap)

        # Compute score
        score, components = compute_trust_score(profile)
        profile.trust_score = score
        profile.risk_level = get_risk_level(score)

        # Detect anomalies
        alerts = detect_anomalies(profile)
        flags = [a.alert_type for a in alerts]
        profile.flags = flags

        # Determine data confidence based on freshness and history depth
        confidence = 0.5  # Base confidence
        if len(profile.snapshots) >= 3:
            confidence += 0.2  # Multiple data points
        if len(profile.snapshots) >= 10:
            confidence += 0.1  # Strong history
        if profile.latest and (time.time() - profile.latest.timestamp < 300):
            confidence += 0.2  # Fresh data

        # Generate recommendation
        recommendation = generate_recommendation(score, flags)
        summary = generate_summary(profile, score, profile.risk_level, recommendation, flags)

        report = TrustReport(
            query_id=query.query_id,
            target_address=target,
            target_name=profile.agent_name or target[:10],
            trust_score=score,
            risk_level=profile.risk_level,
            recommendation=recommendation,
            component_scores=components,
            active_flags=flags,
            confidence=min(1.0, confidence),
            summary=summary,
        )

        logger.info(
            f"Query {query.query_id} complete: "
            f"VTS={score:.0f} [{profile.risk_level}] → {recommendation}"
        )

        return report

    async def handle_quick_check(self, target_address: str) -> dict:
        """Lightweight check — returns just score, risk level, and recommendation.
        Used for high-volume automated queries where full reports aren't needed.
        """
        profile = self.scanner.get_profile(target_address)
        if not profile or not profile.latest:
            return {
                'address': target_address,
                'trust_score': None,
                'risk_level': 'UNKNOWN',
                'recommendation': 'CAUTION',
                'message': 'No data available for this agent.',
            }

        return {
            'address': target_address,
            'trust_score': profile.trust_score,
            'risk_level': profile.risk_level,
            'recommendation': generate_recommendation(profile.trust_score, profile.flags),
            'flags': profile.flags,
        }

    async def handle_evaluator_role(self, transaction_id: str,
                                     provider_address: str,
                                     consumer_address: str,
                                     delivered_output: dict) -> dict:
        """Act as an ACP evaluator for transactions between other agents.

        VIGIL evaluates whether a service provider delivered on their promise.
        This is a separate revenue stream — VIGIL earns evaluator fees.

        Returns evaluation result:
            - approved: bool
            - score: float (0-1)
            - reason: str
        """
        logger.info(
            f"Evaluating transaction {transaction_id}: "
            f"{provider_address[:10]} → {consumer_address[:10]}"
        )

        # Check provider's trust score
        provider_profile = self.scanner.get_profile(provider_address)
        provider_trust = provider_profile.trust_score if provider_profile else 50.0

        # Basic evaluation: check if output was delivered and provider is trusted
        has_output = bool(delivered_output)
        provider_reliable = provider_trust >= 40

        if has_output and provider_reliable:
            return {
                'transaction_id': transaction_id,
                'approved': True,
                'score': min(1.0, provider_trust / 100),
                'reason': (
                    f"Output delivered. Provider VTS: {provider_trust:.0f}/100. "
                    f"Transaction approved."
                ),
            }
        elif has_output and not provider_reliable:
            return {
                'transaction_id': transaction_id,
                'approved': True,
                'score': 0.5,
                'reason': (
                    f"Output delivered but provider trust is low "
                    f"(VTS: {provider_trust:.0f}/100). "
                    f"Approved with caution flag."
                ),
            }
        else:
            return {
                'transaction_id': transaction_id,
                'approved': False,
                'score': 0.0,
                'reason': "No output delivered. Transaction rejected.",
            }
