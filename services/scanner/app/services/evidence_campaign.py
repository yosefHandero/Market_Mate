"""Evidence campaigns: frozen strategy+config windows for live-forward collection.

A campaign is opened the first time a scan runs and stays active until a
meaningful strategy or evidence-relevant configuration change alters the config
fingerprint. On such a change the active campaign is closed
(``close_reason="config_change"``) and a new one opened, so incompatible results
never mix in the same qualifying sample.

The fingerprint intentionally covers only evidence-relevant settings (not every
knob), documented in ``_FINGERPRINT_SETTING_KEYS``; trivial, non-evidence tweaks
do not churn campaigns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select

from app.config import Settings, get_settings
from app.core.strategy_contract import STRATEGY_ID, STRATEGY_VERSION
from app.core.weekly_patterns import FEATURE_VERSION
from app.db import SessionLocal
from app.models.scan import EvidenceCampaignORM
from app.services.walk_forward_proof import code_commit


# Evidence-relevant settings whose change should start a new campaign.
# Membership is live-scan identity: watchlists, thresholds, weekly prediction,
# candidate filters, calibration, selection, friction, evidence classification,
# shared proof_* quality knobs the live weekly path reads, and provider-overlay
# toggles that can change stored signal/score/confidence/ranking/selection.
# Excluded on purpose: walk-forward-admin-only proof window/pilot keys, auth,
# scheduler, cache TTLs, paper-loop/portfolio sizing, and other operational
# knobs that cannot change prediction results under unchanged market inputs.
_FINGERPRINT_SETTING_KEYS = (
    # Watchlists / universe
    "watchlist",
    "crypto_watchlist",
    # Trade-gate evidence thresholds (also used by risk path)
    "trade_gate_enabled",
    "trade_gate_horizon",
    "trade_gate_min_evaluated_count",
    "trade_gate_min_win_rate",
    "trade_gate_min_avg_return",
    "trade_gate_crypto_buy_min_evaluated_count",
    "trade_gate_allowed_signals",
    # Intraday signal thresholds
    "signal_buy_threshold",
    "signal_sell_threshold",
    "signal_margin",
    "signal_crypto_buy_threshold",
    "signal_crypto_sell_threshold",
    "signal_crypto_margin",
    # Weekly horizon / friction
    "weekly_forward_days",
    "weekly_primary_horizon_enabled",
    "stock_slippage_bps",
    "stock_spread_bps",
    "stock_fee_bps",
    "crypto_slippage_bps",
    "crypto_spread_bps",
    "crypto_fee_bps",
    # Strategy identity + top-pick selection
    "scanner_strategy_variant",
    "top_pick_limit",
    "upside_prob_shrinkage_k",
    "health_max_stale_minutes",
    "provider_max_bar_age_minutes",
    # Live weekly prediction / calibration / filters
    "weekly_apply_calibration_map",
    "weekly_apply_proof_candidate_filters",
    "weekly_forward_tolerance_days",
    "weekly_hold_return_tolerance_pct",
    "weekly_daily_lookback_bars_min",
    "weekly_daily_lookback_bars_preferred",
    "weekly_daily_lookback_bars_max",
    "weekly_daily_bar_max_age_days_stock",
    "weekly_daily_bar_max_age_days_crypto",
    "weekly_trust_window_days",
    "trust_recent_window_days",
    "calibration_min_signal_samples",
    "calibration_min_score_band_samples",
    "validation_win_threshold_pct",
    "validation_false_positive_threshold_pct",
    # Evidence classification / pattern trust gates
    "weekly_out_of_sample_holdout_ratio",
    "track_hold_outcomes",
    "weekly_pattern_gate_min_historical_samples",
    "weekly_pattern_gate_min_backfilled_samples",
    "weekly_pattern_gate_min_live_forward_samples",
    "weekly_pattern_gate_min_out_of_sample_samples",
    "weekly_pattern_gate_min_win_rate",
    "weekly_pattern_gate_min_avg_return",
    # Shared proof_* knobs read by the live weekly prediction path
    "proof_step_days",
    "proof_momentum_lookback_days",
    "proof_min_expected_value_pct",
    "proof_rsi_overbought",
    "proof_min_pattern_samples",
    "proof_min_pattern_edge_pct",
    "proof_require_buy_hold_baseline",
    "proof_volume_lookback_days",
    "proof_min_volume_median_ratio",
    # Provider overlays that can change score, confidence, eligibility, or ranking
    "news_trigger_abs_move_pct",
    "sec_enhanced_enabled",
    "marketdata_options_enabled",
    "binance_enabled",
    "deribit_enabled",
    "fred_enabled",
    "internal_breadth_enabled",
    "defillama_enabled",
)


def campaign_config_fingerprint(settings: Settings) -> str:
    """Stable SHA-256 over strategy identity + evidence-relevant settings."""
    payload: dict[str, Any] = {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "feature_version": FEATURE_VERSION,
    }
    for key in _FINGERPRINT_SETTING_KEYS:
        payload[key] = getattr(settings, key, None)
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CampaignProvenance:
    """Immutable snapshot of the active campaign for stamping prediction rows."""

    campaign_id: str
    strategy_version: str
    feature_version: str
    config_fingerprint: str
    code_commit: str | None


@dataclass(frozen=True)
class CampaignSummary:
    campaign_id: str
    started_at: datetime
    ended_at: datetime | None
    status: str
    strategy_id: str
    strategy_version: str
    feature_version: str
    config_fingerprint: str
    code_commit: str | None
    close_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat() if self.started_at else None
        data["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        return data


class EvidenceCampaignService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: Callable[[], Any] = SessionLocal,
    ) -> None:
        self.settings = settings or get_settings()
        self._session_factory = session_factory

    def _new_campaign_id(self, fingerprint: str, now: datetime) -> str:
        seed = f"{fingerprint}:{now.isoformat()}"
        return "camp-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    def get_or_create_active_campaign(
        self, *, now: datetime | None = None
    ) -> CampaignProvenance:
        now = now or datetime.now(timezone.utc)
        fingerprint = campaign_config_fingerprint(self.settings)
        with self._session_factory() as session:
            active = session.execute(
                select(EvidenceCampaignORM)
                .where(EvidenceCampaignORM.status == "active")
                .order_by(EvidenceCampaignORM.started_at.desc())
            ).scalars().first()

            if active is not None and active.config_fingerprint == fingerprint:
                return self._provenance(active)

            if active is not None:
                # Fingerprint changed: close the stale campaign, open a fresh one so
                # results collected under different assumptions never mix.
                active.status = "closed"
                active.ended_at = now
                active.close_reason = "config_change"

            campaign = EvidenceCampaignORM(
                campaign_id=self._new_campaign_id(fingerprint, now),
                started_at=now,
                ended_at=None,
                status="active",
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                feature_version=FEATURE_VERSION,
                config_fingerprint=fingerprint,
                code_commit=code_commit(),
                close_reason=None,
                notes_json=None,
            )
            session.add(campaign)
            session.commit()
            return self._provenance(campaign)

    @staticmethod
    def _provenance(campaign: EvidenceCampaignORM) -> CampaignProvenance:
        return CampaignProvenance(
            campaign_id=campaign.campaign_id,
            strategy_version=campaign.strategy_version,
            feature_version=campaign.feature_version,
            config_fingerprint=campaign.config_fingerprint,
            code_commit=campaign.code_commit,
        )

    def get_active_campaign(self) -> CampaignSummary | None:
        with self._session_factory() as session:
            active = session.execute(
                select(EvidenceCampaignORM)
                .where(EvidenceCampaignORM.status == "active")
                .order_by(EvidenceCampaignORM.started_at.desc())
            ).scalars().first()
            return self._summary(active) if active else None

    def list_campaigns(self, *, limit: int = 50) -> list[CampaignSummary]:
        with self._session_factory() as session:
            rows = session.execute(
                select(EvidenceCampaignORM)
                .order_by(EvidenceCampaignORM.started_at.desc())
                .limit(limit)
            ).scalars().all()
            return [self._summary(row) for row in rows]

    @staticmethod
    def _summary(campaign: EvidenceCampaignORM) -> CampaignSummary:
        return CampaignSummary(
            campaign_id=campaign.campaign_id,
            started_at=campaign.started_at,
            ended_at=campaign.ended_at,
            status=campaign.status,
            strategy_id=campaign.strategy_id,
            strategy_version=campaign.strategy_version,
            feature_version=campaign.feature_version,
            config_fingerprint=campaign.config_fingerprint,
            code_commit=campaign.code_commit,
            close_reason=campaign.close_reason,
        )
