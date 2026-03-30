"""
VIGIL Trust Scoring Engine
Computes composite trust scores and detects anomalies for all monitored agents.

Score Components (each 0-100, weighted to composite):
  - Wallet Health (25%): Age, balance stability, transaction patterns
  - ACP Track Record (25%): Service completion rate, evaluator ratings
  - Token Stability (25%): Holder distribution, liquidity, volatility
  - Activity Consistency (25%): Regular transactions, social presence, uptime

Anomaly Detection:
  - Behavioral fingerprints of rug pulls, abandonment, and fraud
  - Pre-rug pattern matching: wallet consolidation, LP removal, social silence
  - Alerts generated with severity levels and confidence scores
"""

import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from config import (
    SCORE_WEIGHTS, RISK_LEVELS,
    WALLET_CONSOLIDATION_THRESHOLD, LIQUIDITY_REMOVAL_THRESHOLD,
    LARGE_TRANSFER_THRESHOLD, HOLDER_CONCENTRATION_WARNING,
    VOLUME_SPIKE_MULTIPLIER, PRICE_DROP_ALERT,
    INACTIVITY_DAYS_WARNING, SOCIAL_SILENCE_DAYS,
    ACP_FAILURE_RATE_WARNING, ALERT_COOLDOWN_SECONDS,
)
from collector import AgentProfile, AgentSnapshot

logger = logging.getLogger('vigil.scorer')


# ═══════════════════════════════════════════════════════════════
# ALERT MODEL
# ═══════════════════════════════════════════════════════════════

@dataclass
class Alert:
    """A risk alert for a specific agent."""
    agent_address: str
    agent_name: str
    severity: str          # CRITICAL, HIGH, MODERATE, LOW
    alert_type: str        # RUG_PATTERN, LIQUIDITY_DRAIN, INACTIVITY, etc.
    message: str           # Human-readable description
    confidence: float      # 0.0 - 1.0
    timestamp: float = 0.0
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


# ═══════════════════════════════════════════════════════════════
# COMPONENT SCORERS
# ═══════════════════════════════════════════════════════════════

def score_wallet_health(profile: AgentProfile) -> float:
    """Score 0-100 based on wallet behavior patterns."""
    snap = profile.latest
    if not snap:
        return 0.0

    score = 50.0  # Start neutral

    # Wallet age: older = more trustworthy (up to +20)
    if snap.wallet_age_days > 90:
        score += 20
    elif snap.wallet_age_days > 30:
        score += 15
    elif snap.wallet_age_days > 7:
        score += 5
    elif snap.wallet_age_days < 1:
        score -= 15  # Brand new wallet is suspicious

    # Balance stability: has ETH to operate (+10)
    if snap.wallet_balance_eth > 0.01:
        score += 10
    elif snap.wallet_balance_eth < 0.001:
        score -= 10  # Running on fumes

    # Large outflows are concerning (-20)
    if snap.largest_outflow_24h > LARGE_TRANSFER_THRESHOLD:
        score -= 20

    # Transaction diversity: more counterparties = healthier (+10)
    if snap.unique_counterparties_7d > 10:
        score += 10
    elif snap.unique_counterparties_7d > 3:
        score += 5
    elif snap.unique_counterparties_7d == 0:
        score -= 10

    # Trend: compare to previous snapshot if available
    if len(profile.snapshots) >= 2:
        prev = profile.snapshots[-2]
        # Sudden balance drop is a warning
        if prev.wallet_balance_eth > 0 and snap.wallet_balance_eth > 0:
            balance_change = (snap.wallet_balance_eth - prev.wallet_balance_eth) / prev.wallet_balance_eth
            if balance_change < -0.5:  # >50% balance drop
                score -= 15

    return max(0.0, min(100.0, score))


def score_acp_track_record(profile: AgentProfile) -> float:
    """Score 0-100 based on ACP transaction history."""
    snap = profile.latest
    if not snap:
        return 50.0  # Neutral if no data

    score = 50.0

    # Has registered services (+10)
    if snap.acp_services_registered > 0:
        score += 10

    # Completion rate
    if snap.acp_transactions_total > 0:
        completion_rate = snap.acp_transactions_completed / snap.acp_transactions_total
        if completion_rate > 0.9:
            score += 20
        elif completion_rate > 0.7:
            score += 10
        elif completion_rate < 0.5:
            score -= 20

        # Dispute rate
        dispute_rate = snap.acp_transactions_disputed / snap.acp_transactions_total
        if dispute_rate > ACP_FAILURE_RATE_WARNING:
            score -= 15

    # Revenue generation is positive signal
    if snap.acp_revenue_total > 100:
        score += 10
    elif snap.acp_revenue_total > 10:
        score += 5

    # Recency of ACP activity
    if snap.acp_last_transaction_age_hours < 24:
        score += 5
    elif snap.acp_last_transaction_age_hours > 168:  # > 1 week
        score -= 10

    return max(0.0, min(100.0, score))


def score_token_stability(profile: AgentProfile) -> float:
    """Score 0-100 based on token health metrics."""
    snap = profile.latest
    if not snap or not snap.token_address:
        return 50.0  # Neutral if no token data

    score = 50.0

    # Liquidity depth
    if snap.token_liquidity_usd > 50000:
        score += 15
    elif snap.token_liquidity_usd > 10000:
        score += 10
    elif snap.token_liquidity_usd < 1000:
        score -= 20  # Dangerously thin liquidity

    # Liquidity trend
    if snap.token_liquidity_change_24h < -0.3:  # >30% LP drained
        score -= 25

    # Holder concentration
    if snap.token_top_holder_pct > HOLDER_CONCENTRATION_WARNING:
        score -= 15
    elif snap.token_top_holder_pct < 0.1:
        score += 10  # Well-distributed

    # Holder count
    if snap.token_holders > 500:
        score += 10
    elif snap.token_holders > 100:
        score += 5
    elif snap.token_holders < 10:
        score -= 15

    # Price stability
    if abs(snap.token_price_change_24h) < 0.1:  # <10% change
        score += 5
    elif snap.token_price_change_24h < -PRICE_DROP_ALERT:
        score -= 15

    # Volume anomaly
    if snap.token_volume_7d_avg > 0:
        volume_ratio = snap.token_volume_24h / snap.token_volume_7d_avg
        if volume_ratio > VOLUME_SPIKE_MULTIPLIER:
            score -= 10  # Unusual volume spike (potential dump)

    return max(0.0, min(100.0, score))


def score_activity_consistency(profile: AgentProfile) -> float:
    """Score 0-100 based on consistent operational activity."""
    snap = profile.latest
    if not snap:
        return 0.0

    score = 50.0

    # Onchain activity recency
    if snap.last_onchain_activity_hours < 24:
        score += 15
    elif snap.last_onchain_activity_hours < 72:
        score += 5
    elif snap.last_onchain_activity_hours > INACTIVITY_DAYS_WARNING * 24:
        score -= 25  # Agent appears dead

    # Transaction frequency (healthy rhythm)
    if snap.tx_count_7d > 20:
        score += 10
    elif snap.tx_count_7d > 5:
        score += 5
    elif snap.tx_count_7d == 0:
        score -= 15

    # Social presence
    if snap.social_posts_7d > 10:
        score += 10
    elif snap.social_posts_7d > 3:
        score += 5
    elif snap.social_posts_7d == 0 and snap.social_followers > 100:
        score -= 10  # Had followers but went silent

    # Consistency over time: compare activity levels across snapshots
    if len(profile.snapshots) >= 3:
        recent_activity = [s.tx_count_24h for s in profile.snapshots[-3:]]
        if all(a == 0 for a in recent_activity):
            score -= 20  # Consistently dead

    return max(0.0, min(100.0, score))


# ═══════════════════════════════════════════════════════════════
# COMPOSITE SCORER
# ═══════════════════════════════════════════════════════════════

def compute_trust_score(profile: AgentProfile) -> Tuple[float, dict]:
    """Compute the composite VIGIL Trust Score (VTS) for an agent.
    Returns (score, component_scores_dict).
    """
    components = {
        'wallet_health': score_wallet_health(profile),
        'acp_track_record': score_acp_track_record(profile),
        'token_stability': score_token_stability(profile),
        'activity_consistency': score_activity_consistency(profile),
    }

    composite = sum(
        components[k] * SCORE_WEIGHTS[k]
        for k in components
    )

    return round(composite, 1), components


def get_risk_level(score: float) -> str:
    """Map a trust score to a risk level label."""
    for (low, high), label in RISK_LEVELS.items():
        if low <= score <= high:
            return label
    return 'UNKNOWN'


# ═══════════════════════════════════════════════════════════════
# ANOMALY DETECTION
# ═══════════════════════════════════════════════════════════════

def detect_anomalies(profile: AgentProfile) -> List[Alert]:
    """Run anomaly detection on an agent profile. Returns list of alerts."""
    alerts = []
    snap = profile.latest
    if not snap:
        return alerts

    name = profile.agent_name or profile.agent_address[:10]

    # ── Pre-Rug Pattern: Wallet Consolidation + LP Drain ──
    if (snap.largest_outflow_24h > WALLET_CONSOLIDATION_THRESHOLD
            and snap.token_liquidity_change_24h < -LIQUIDITY_REMOVAL_THRESHOLD):
        alerts.append(Alert(
            agent_address=profile.agent_address,
            agent_name=name,
            severity='CRITICAL',
            alert_type='RUG_PATTERN',
            message=(
                f"{name}: Wallet consolidation ({snap.largest_outflow_24h:.0%} outflow) "
                f"coinciding with liquidity drain ({snap.token_liquidity_change_24h:.0%}). "
                f"Classic pre-rug behavioral fingerprint."
            ),
            confidence=0.85,
            data={
                'outflow_pct': snap.largest_outflow_24h,
                'lp_change_pct': snap.token_liquidity_change_24h,
            }
        ))

    # ── Liquidity Drain (standalone) ──
    elif snap.token_liquidity_change_24h < -LIQUIDITY_REMOVAL_THRESHOLD:
        alerts.append(Alert(
            agent_address=profile.agent_address,
            agent_name=name,
            severity='HIGH',
            alert_type='LIQUIDITY_DRAIN',
            message=(
                f"{name}: Significant liquidity removal detected "
                f"({snap.token_liquidity_change_24h:.0%} in 24h). "
                f"Remaining liquidity: ${snap.token_liquidity_usd:,.0f}."
            ),
            confidence=0.7,
            data={'lp_change_pct': snap.token_liquidity_change_24h}
        ))

    # ── Large Wallet Outflow ──
    if snap.largest_outflow_24h > LARGE_TRANSFER_THRESHOLD:
        alerts.append(Alert(
            agent_address=profile.agent_address,
            agent_name=name,
            severity='MODERATE',
            alert_type='LARGE_OUTFLOW',
            message=(
                f"{name}: Large outflow detected — "
                f"{snap.largest_outflow_24h:.0%} of wallet balance moved in 24h."
            ),
            confidence=0.6,
            data={'outflow_pct': snap.largest_outflow_24h}
        ))

    # ── Holder Concentration Warning ──
    if snap.token_top_holder_pct > HOLDER_CONCENTRATION_WARNING:
        alerts.append(Alert(
            agent_address=profile.agent_address,
            agent_name=name,
            severity='MODERATE',
            alert_type='HOLDER_CONCENTRATION',
            message=(
                f"{name}: Top wallet holds {snap.token_top_holder_pct:.0%} of token supply. "
                f"High concentration risk."
            ),
            confidence=0.65,
            data={'top_holder_pct': snap.token_top_holder_pct}
        ))

    # ── Agent Death Pattern: Inactivity + Social Silence ──
    if (snap.last_onchain_activity_hours > INACTIVITY_DAYS_WARNING * 24
            and snap.social_posts_7d == 0):
        alerts.append(Alert(
            agent_address=profile.agent_address,
            agent_name=name,
            severity='HIGH',
            alert_type='AGENT_DEATH',
            message=(
                f"{name}: No onchain activity in {snap.last_onchain_activity_hours/24:.0f} days "
                f"and zero social posts in 7 days. Agent appears abandoned."
            ),
            confidence=0.75,
            data={
                'inactive_days': snap.last_onchain_activity_hours / 24,
                'social_posts_7d': snap.social_posts_7d,
            }
        ))

    # ── Volume Anomaly (potential pump & dump) ──
    if snap.token_volume_7d_avg > 0:
        volume_ratio = snap.token_volume_24h / snap.token_volume_7d_avg
        if volume_ratio > VOLUME_SPIKE_MULTIPLIER:
            alerts.append(Alert(
                agent_address=profile.agent_address,
                agent_name=name,
                severity='MODERATE',
                alert_type='VOLUME_ANOMALY',
                message=(
                    f"{name}: Volume spike — 24h volume is {volume_ratio:.1f}x the 7-day average. "
                    f"Potential coordinated activity."
                ),
                confidence=0.55,
                data={'volume_ratio': volume_ratio}
            ))

    # ── Score Trajectory: Rapid Decline ──
    if len(profile.snapshots) >= 3:
        # Compare current score to 3 snapshots ago
        recent_scores = []
        for s in profile.snapshots[-3:]:
            temp_profile = AgentProfile(agent_address=profile.agent_address)
            temp_profile.snapshots = [s]
            sc, _ = compute_trust_score(temp_profile)
            recent_scores.append(sc)

        if len(recent_scores) >= 2:
            score_delta = recent_scores[-1] - recent_scores[0]
            if score_delta < -20:  # Dropped 20+ points
                alerts.append(Alert(
                    agent_address=profile.agent_address,
                    agent_name=name,
                    severity='HIGH',
                    alert_type='SCORE_FREEFALL',
                    message=(
                        f"{name}: Trust score in freefall — "
                        f"dropped {abs(score_delta):.0f} points over recent snapshots. "
                        f"Current score: {profile.trust_score:.0f}."
                    ),
                    confidence=0.7,
                    data={'score_delta': score_delta}
                ))

    return alerts


def update_agent_scores(profiles: dict) -> List[Alert]:
    """Update trust scores and run anomaly detection for all agents.
    Returns all generated alerts.
    """
    all_alerts = []

    for addr, profile in profiles.items():
        # Compute new score
        score, components = compute_trust_score(profile)
        profile.trust_score = score
        profile.risk_level = get_risk_level(score)

        # Run anomaly detection
        alerts = detect_anomalies(profile)

        # Filter by cooldown (don't repeat same alert type within cooldown)
        now = time.time()
        new_alerts = []
        for alert in alerts:
            if now - profile.last_alert_time > ALERT_COOLDOWN_SECONDS:
                new_alerts.append(alert)

        if new_alerts:
            profile.last_alert_time = now
            profile.flags = [a.alert_type for a in new_alerts]
            all_alerts.extend(new_alerts)
        else:
            # Clear old flags if no new alerts
            if now - profile.last_alert_time > ALERT_COOLDOWN_SECONDS * 2:
                profile.flags = []

        logger.debug(
            f"{profile.agent_name}: VTS={score:.0f} ({profile.risk_level}) "
            f"components={components} flags={profile.flags}"
        )

    return all_alerts
