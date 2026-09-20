from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import inspect, select

from app.brain.calibration import (
    ReliabilityBin,
    reliability_map_from_payload,
)
from app.brain.identity import learned_artifact_identity
from app.brain.policies.weekly import weekly_learned_artifacts_payload
from app.brain.weekly_backtest import PatternBacktestStats
from app.brain.weekly_patterns import BULLISH_PATTERN_NAMES
from app.config import Settings, get_settings
from app.db import SessionLocal, engine
from app.models.scan import EvidenceCampaignORM
from app.services.repository import ScanRepository
from app.services.walk_forward_repository import WalkForwardRepository


@dataclass(frozen=True)
class LearnedInputBundle:
    reliability_maps: dict[str, list[ReliabilityBin]]
    extra_stats: dict[tuple[str, str, str], PatternBacktestStats]
    identity: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        return str(self.identity["content_hash"])

    @property
    def reference(self) -> dict[str, Any]:
        reference = self.identity.get("reference")
        return reference if isinstance(reference, dict) else {}

    def identity_json(self) -> str:
        return json.dumps(self.identity, sort_keys=True, default=str)

    def stats_by_source(
        self,
        *,
        pattern_name: str,
        asset_type: str,
        sources: tuple[str, ...],
    ) -> dict[str, PatternBacktestStats]:
        result: dict[str, PatternBacktestStats] = {}
        for source in sources:
            stats = self.extra_stats.get((pattern_name, asset_type, source))
            if stats is not None:
                result[source] = stats
        return result


class LearnedInputService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repository: ScanRepository | None = None,
        walk_forward_repository: WalkForwardRepository | None = None,
        session_factory: Callable[[], Any] = SessionLocal,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or ScanRepository()
        self.walk_forward_repository = walk_forward_repository or WalkForwardRepository()
        self._session_factory = session_factory

    def load_for_serving(self) -> LearnedInputBundle:
        pinned = self.load_active_campaign_pin()
        if pinned is not None:
            return pinned
        return self.load_current()

    def load_current(self) -> LearnedInputBundle:
        reliability_maps: dict[str, list[ReliabilityBin]] = {}
        min_count = int(self.settings.calibration_min_score_band_samples)
        wf_run = self.walk_forward_repository.get_latest_run()
        metrics = _load_json(getattr(wf_run, "metrics_json", None))
        raw_maps = metrics.get("reliability_maps") if isinstance(metrics, dict) else None
        raw_maps = raw_maps if isinstance(raw_maps, dict) else {}
        for asset_type in ("stock", "crypto"):
            reliability_maps[asset_type] = reliability_map_from_payload(
                raw_maps.get(asset_type),
                min_count=min_count,
            )

        extra: dict[tuple[str, str, str], PatternBacktestStats] = {}
        for pattern_name in BULLISH_PATTERN_NAMES:
            for asset_type in ("stock", "crypto"):
                for source in (
                    "historical",
                    "backfilled_replay",
                    "live_paper_forward",
                    # Repository compatibility maps this stored spelling to the
                    # complete holdout family: legacy out_of_sample plus current
                    # live_holdout rows. Loading live_holdout again would double
                    # count the same family in the frozen artifact.
                    "out_of_sample",
                ):
                    stats = self.repository.get_weekly_pattern_stats(
                        pattern_name=pattern_name,
                        asset_type=asset_type,
                        sample_source=source,  # type: ignore[arg-type]
                    )
                    if stats is not None and stats.sample_size > 0:
                        extra[(pattern_name, asset_type, source)] = stats

        return self._bundle_from_content(
            reliability_maps=reliability_maps,
            extra_stats=extra,
            reference={
                "reliability_maps": {
                    "table": "walk_forward_runs",
                    "run_id": getattr(wf_run, "run_id", None),
                    "config_fingerprint": getattr(wf_run, "config_fingerprint", None),
                    "engine_version": getattr(wf_run, "engine_version", None),
                    "metrics_json_path": "reliability_maps",
                    "min_count": min_count,
                },
                "pattern_stats": {
                    "table": "signal_outcomes",
                    "patterns": sorted(BULLISH_PATTERN_NAMES),
                    "asset_types": ["stock", "crypto"],
                    "sample_sources": [
                        "historical",
                        "backfilled_replay",
                        "live_paper_forward",
                        "out_of_sample",
                    ],
                    "aggregation": "sample_size, validation-win hit_rate_pct, avg_return_after_1w",
                    "validation_win_threshold_pct": self.settings.validation_win_threshold_pct,
                },
            },
        )

    def load_active_campaign_pin(self) -> LearnedInputBundle | None:
        try:
            inspector = inspect(engine)
            if not inspector.has_table("evidence_campaigns"):
                return None
            columns = {column["name"] for column in inspector.get_columns("evidence_campaigns")}
            if "learned_artifacts_json" not in columns:
                return None
        except Exception:
            return None

        with self._session_factory() as session:
            campaign = session.execute(
                select(EvidenceCampaignORM)
                .where(EvidenceCampaignORM.status == "active")
                .order_by(EvidenceCampaignORM.started_at.desc())
            ).scalars().first()
            if campaign is None:
                return None
            raw = getattr(campaign, "learned_artifacts_json", None)
            expected_fingerprint = getattr(campaign, "learned_artifacts_fingerprint", None)
        if not raw:
            return None
        try:
            identity = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("active campaign learned-artifact pin is not valid JSON") from exc
        bundle = self._bundle_from_identity(identity)
        if expected_fingerprint and bundle.fingerprint != expected_fingerprint:
            raise RuntimeError("active campaign learned-artifact fingerprint does not match its pin")
        return bundle

    def _bundle_from_content(
        self,
        *,
        reliability_maps: dict[str, list[ReliabilityBin]],
        extra_stats: dict[tuple[str, str, str], PatternBacktestStats],
        reference: dict[str, Any],
    ) -> LearnedInputBundle:
        identity = learned_artifact_identity(
            artifact_type="weekly_probability_inputs",
            content_payload=weekly_learned_artifacts_payload(
                reliability_maps=reliability_maps,
                extra_stats=extra_stats,
            ),
            reference_payload=reference,
        )
        return LearnedInputBundle(
            reliability_maps=reliability_maps,
            extra_stats=extra_stats,
            identity=identity,
        )

    def _bundle_from_identity(self, identity: dict[str, Any]) -> LearnedInputBundle:
        if not isinstance(identity, dict):
            raise RuntimeError("active campaign learned-artifact pin has the wrong shape")
        content = identity.get("content")
        if not isinstance(content, dict):
            raise RuntimeError("active campaign learned-artifact pin has no content")
        reliability_maps: dict[str, list[ReliabilityBin]] = {}
        raw_maps = content.get("reliability_maps")
        if isinstance(raw_maps, dict):
            for asset_type, payload in raw_maps.items():
                reliability_maps[str(asset_type)] = reliability_map_from_payload(
                    payload if isinstance(payload, list) else None,
                    min_count=0,
                )
        extra_stats: dict[tuple[str, str, str], PatternBacktestStats] = {}
        raw_stats = content.get("pattern_stats")
        if isinstance(raw_stats, list):
            for item in raw_stats:
                if not isinstance(item, dict):
                    continue
                try:
                    pattern_name = str(item["pattern_name"])
                    asset_type = str(item["asset_type"])
                    sample_source = str(item["sample_source"])
                    extra_stats[(pattern_name, asset_type, sample_source)] = PatternBacktestStats(
                        pattern_name=str(item.get("stats_pattern_name") or pattern_name),
                        sample_size=int(item.get("sample_size") or 0),
                        hit_rate_pct=(
                            None
                            if item.get("hit_rate_pct") is None
                            else float(item["hit_rate_pct"])
                        ),
                        avg_forward_return_pct=(
                            None
                            if item.get("avg_forward_return_pct") is None
                            else float(item["avg_forward_return_pct"])
                        ),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
        rebuilt = learned_artifact_identity(
            artifact_type=str(identity.get("artifact_type") or "weekly_probability_inputs"),
            content_payload=content,
            reference_payload=identity.get("reference") if isinstance(identity.get("reference"), dict) else {},
        )
        if identity.get("content_hash") and rebuilt["content_hash"] != identity["content_hash"]:
            raise RuntimeError("active campaign learned-artifact pin content hash is invalid")
        return LearnedInputBundle(
            reliability_maps=reliability_maps,
            extra_stats=extra_stats,
            identity=rebuilt,
        )


def _load_json(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}
