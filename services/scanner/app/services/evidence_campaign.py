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
_FINGERPRINT_SETTING_KEYS = (
    "watchlist",
    "crypto_watchlist",
    "trade_gate_enabled",
    "trade_gate_horizon",
    "trade_gate_min_evaluated_count",
    "trade_gate_min_win_rate",
    "trade_gate_min_avg_return",
    "trade_gate_crypto_buy_min_evaluated_count",
    "trade_gate_allowed_signals",
    "signal_buy_threshold",
    "signal_sell_threshold",
    "signal_margin",
    "signal_crypto_buy_threshold",
    "signal_crypto_sell_threshold",
    "signal_crypto_margin",
    "weekly_forward_days",
    "weekly_primary_horizon_enabled",
    "stock_slippage_bps",
    "stock_spread_bps",
    "stock_fee_bps",
    "crypto_slippage_bps",
    "crypto_spread_bps",
    "crypto_fee_bps",
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
