"""Host adapter around the brain: registry, snapshots, champion switch, promotion."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.brain.config import HybridPolicyConfig, RulerConfig, WeeklyPolicyConfig
from app.brain.contracts import BrainDecision, MarketSnapshot, SymbolSnapshot
from app.brain.evaluation.promotion import PromotionReport, build_promotion_report
from app.brain.policies import HYBRID_POLICY_ID, WEEKLY_POLICY_ID, HybridLegacyPolicy, WeeklyProbabilityPolicy
from app.brain.registry import PolicyRegistry
from app.config import Settings, get_settings
from app.schemas import (
    PolicyPromotionCheck,
    PolicyPromotionReport,
    ScanResult,
    WeeklyPatternPrediction,
)
from app.services.repository import ScanRepository
from app.services.learned_inputs import LearnedInputBundle, LearnedInputService
from app.services.walk_forward_repository import WalkForwardRepository


class BrainRuntime:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repository: ScanRepository | None = None,
        walk_forward_repository: WalkForwardRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or ScanRepository()
        self.walk_forward_repository = walk_forward_repository or WalkForwardRepository()
        self.learned_inputs_service = LearnedInputService(
            settings=self.settings,
            repository=self.repository,
            walk_forward_repository=self.walk_forward_repository,
        )
        self.learned_inputs: LearnedInputBundle | None = None
        self.weekly_config = WeeklyPolicyConfig.from_settings(self.settings)
        self.hybrid_config = HybridPolicyConfig.from_settings(self.settings)
        self.ruler_config = RulerConfig.from_settings(self.settings)
        self.hybrid = HybridLegacyPolicy(config=self.hybrid_config)
        self.weekly = WeeklyProbabilityPolicy(config=self.weekly_config)
        self.registry = PolicyRegistry()
        self.registry.register(self.hybrid)
        self.registry.register(self.weekly)

    def requested_champion_id(self) -> str:
        raw = str(getattr(self.settings, "brain_champion_policy_id", HYBRID_POLICY_ID) or HYBRID_POLICY_ID)
        return raw.strip() or HYBRID_POLICY_ID

    def refresh_weekly_inputs(self, bundle: LearnedInputBundle | None = None) -> LearnedInputBundle:
        """Reload learned inputs for the weekly policy (the policy itself does no I/O).

        Reliability maps come from the latest walk-forward run; repository-accrued
        per-pattern stats (replay/live/holdout tracks) feed the evidence verdict.
        Only the bullish patterns can reach a stats lookup, so only those load.
        """
        bundle = bundle or self.learned_inputs_service.load_for_serving()
        self.learned_inputs = bundle
        self.hybrid = HybridLegacyPolicy(
            config=self.hybrid_config,
            learned_artifacts_fingerprint=bundle.fingerprint,
        )
        self.weekly = WeeklyProbabilityPolicy(
            config=self.weekly_config,
            reliability_maps=bundle.reliability_maps,
            extra_stats=bundle.extra_stats,
            learned_artifact_reference=bundle.reference,
        )
        self.registry = PolicyRegistry()
        self.registry.register(self.hybrid)
        self.registry.register(self.weekly)
        return bundle

    def build_snapshot(
        self,
        *,
        as_of: datetime,
        results: Iterable[ScanResult],
        daily_bars_by_symbol: dict[str, list[dict[str, Any]]],
        stock_market_bars: list[dict[str, Any]] | None = None,
        crypto_market_bars: list[dict[str, Any]] | None = None,
    ) -> MarketSnapshot:
        symbols: list[SymbolSnapshot] = []
        for row in results:
            weekly = getattr(row, "weekly_prediction", None)
            exit_window = getattr(row, "exit_window", None)
            session = {
                "decision_signal": row.decision_signal,
                "price": row.price,
                "calibrated_confidence": getattr(row, "calibrated_confidence", None),
                "upside_probability_pct": getattr(row, "upside_probability_pct", None),
                "score": row.score,
                "gate_passed": row.gate_passed,
                "weekly_directional_bias": getattr(weekly, "directional_bias", None) if weekly else None,
                "pattern_name": getattr(weekly, "pattern_name", None) if weekly else None,
                "evidence_basis": getattr(weekly, "evidence_basis", None) if weekly else None,
                "historical_hit_rate_pct": getattr(weekly, "historical_hit_rate_pct", None) if weekly else None,
                "historical_avg_return_pct": getattr(weekly, "avg_forward_1w_return_pct", None) if weekly else None,
                "calibration_source": getattr(row, "calibration_source", None),
                "target_price": getattr(exit_window, "estimated_exit_price", None) if exit_window else None,
                "stop_price": getattr(exit_window, "invalidation_level", None) if exit_window else None,
                "horizon_days": int(getattr(self.settings, "weekly_forward_days", 7)),
            }
            bars = daily_bars_by_symbol.get(row.ticker) or []
            symbols.append(
                SymbolSnapshot(
                    symbol=row.ticker,
                    asset_type=row.asset_type,  # type: ignore[arg-type]
                    daily_bars=bars,
                    session=session,
                    data_quality=getattr(weekly, "data_quality", None) or getattr(row, "data_quality", "ok") or "ok",
                    daily_bars_stale=bool(getattr(weekly, "daily_bars_stale", False)) if weekly else False,
                    daily_bars_source=getattr(weekly, "daily_bars_source", "store") if weekly else "store",
                )
            )
        benchmarks = {}
        if stock_market_bars:
            benchmarks["SPY"] = stock_market_bars
        if crypto_market_bars:
            benchmarks["BTC/USD"] = crypto_market_bars
        return MarketSnapshot(as_of=as_of, symbols=tuple(symbols), benchmark_daily_bars=benchmarks)

    def decide_all(self, snapshot: MarketSnapshot) -> dict[str, list[BrainDecision]]:
        return {policy.policy_id: policy.decide_all(snapshot) for policy in self.registry.all_policies()}

    def promotion_report(self) -> PromotionReport:
        """Standing report: current production hybrid vs the weekly challenger.

        The report is always framed as hybrid_legacy (incumbent) versus
        weekly_probability (replayable candidate), regardless of which champion
        is requested in settings; ``effective_champion_id`` reads this report to
        decide whether a requested weekly champion may actually take effect.
        """
        if self.learned_inputs is None:
            self.refresh_weekly_inputs()
        wf_summary = self.walk_forward_repository.get_latest_applicable_run_summary(
            policy_id=self.weekly.policy_id,
            policy_version=self.weekly.policy_version,
            decision_fingerprint=self.weekly.fingerprint(),
            learned_artifacts_fingerprint=self.learned_inputs.fingerprint,
        )
        wf_passed = bool(wf_summary and wf_summary.pilot_verdict.ready)
        pairs = self.repository.list_paired_policy_outcomes(
            champion_policy_id=HYBRID_POLICY_ID,
            champion_policy_version=self.hybrid.policy_version,
            champion_decision_fingerprint=self.hybrid.fingerprint(),
            champion_learned_artifacts_fingerprint=self.learned_inputs.fingerprint,
            challenger_policy_id=WEEKLY_POLICY_ID,
            challenger_policy_version=self.weekly.policy_version,
            challenger_decision_fingerprint=self.weekly.fingerprint(),
            challenger_learned_artifacts_fingerprint=self.learned_inputs.fingerprint,
        )
        return build_promotion_report(
            champion_policy_id=HYBRID_POLICY_ID,
            challenger_policy_id=WEEKLY_POLICY_ID,
            challenger_replayable=True,
            champion_decision_fingerprint=self.hybrid.fingerprint(),
            challenger_decision_fingerprint=self.weekly.fingerprint(),
            ruler_config_payload=self.ruler_config.payload(),
            walk_forward_holdout_passed=wf_passed,
            return_pairs=pairs.get("returns", []),
            brier_pairs=pairs.get("brier", []),
            min_pairs=int(self.ruler_config.promotion_min_pairs),
            diagnostics={"pair_exclusion_counts": pairs.get("exclusions", {})},
        )

    def promotion_report_response(self) -> PolicyPromotionReport:
        """Promotion report shaped for the Proof API, including the champion
        actually in effect versus the one requested in settings."""
        report = self.promotion_report()
        return PolicyPromotionReport(
            champion_policy_id=report.champion_policy_id,
            challenger_policy_id=report.challenger_policy_id,
            challenger_replayable=report.challenger_replayable,
            ruler_version=report.ruler_version,
            ruler_fingerprint=report.ruler_fingerprint,
            champion_decision_fingerprint=report.champion_decision_fingerprint,
            challenger_decision_fingerprint=report.challenger_decision_fingerprint,
            gates_cleared=report.gates_cleared,
            walk_forward_holdout_passed=report.walk_forward_holdout_passed,
            summary=report.summary,
            checks=[
                PolicyPromotionCheck(name=check.name, passed=check.passed, detail=check.detail)
                for check in report.checks
            ],
            paired_returns_total=report.paired_returns.n_pairs_total,
            paired_returns_informative=report.paired_returns.n_pairs_informative,
            paired_returns_both_abstained=report.paired_returns.n_both_abstained,
            paired_returns_resolution_clusters=report.paired_returns.n_resolution_clusters,
            paired_returns_cluster_metadata_complete=(
                report.paired_returns.resolution_cluster_metadata_complete
            ),
            paired_returns_superior=report.paired_returns.challenger_superior,
            pair_exclusion_counts=report.diagnostics.get("pair_exclusion_counts", {}),
            effective_champion_policy_id=self.effective_champion_id(report=report),
            requested_champion_policy_id=self.requested_champion_id(),
        )

    def effective_champion_id(self, report: PromotionReport | None = None) -> str:
        """Apply a requested champion only when promotion gates clear.

        ``hybrid_legacy`` is always allowed (safe fallback / current production).
        Any other requested champion must clear the promotion report first.
        """
        requested = self.requested_champion_id()
        if requested == HYBRID_POLICY_ID:
            return HYBRID_POLICY_ID
        try:
            self.registry.get(requested)
        except KeyError:
            return HYBRID_POLICY_ID
        resolved = report if report is not None else self.promotion_report()
        if resolved.gates_cleared and resolved.challenger_policy_id == requested:
            return requested
        return HYBRID_POLICY_ID

    def apply_champion(
        self,
        results: list[ScanResult],
        decisions: list[BrainDecision],
    ) -> list[ScanResult]:
        by_symbol = {decision.symbol: decision for decision in decisions}
        updated: list[ScanResult] = []
        for row in results:
            decision = by_symbol.get(row.ticker)
            if decision is None:
                updated.append(row)
                continue
            weekly = row.weekly_prediction
            if decision.action == "BUY" and decision.exit_plan is not None:
                weekly = WeeklyPatternPrediction(
                    pattern_name=decision.pattern_name or (weekly.pattern_name if weekly else "weekly_probability"),
                    directional_bias="bullish",
                    range_low=float(decision.exit_plan.stop_price or row.price),
                    range_high=float(decision.exit_plan.target_price or row.price),
                    upside_probability_pct=decision.p_up_calibrated,
                    historical_hit_rate_pct=decision.evidence_basis.historical_hit_rate_pct,
                    avg_forward_1w_return_pct=decision.evidence_basis.historical_avg_return_pct,
                    sample_size=int(
                        (decision.evidence_basis.sample_sizes or {}).get("historical")
                        or (decision.diagnostics or {}).get("sample_size")
                        or 0
                    ),
                    data_quality=str((decision.diagnostics or {}).get("data_quality") or "ok"),  # type: ignore[arg-type]
                    evidence_basis=decision.evidence_basis.basis,  # type: ignore[arg-type]
                    methodology=decision.probability_methodology or "pattern_recognition",
                )
                updated.append(
                    row.model_copy(
                        update={
                            "decision_signal": "BUY",
                            "calibrated_confidence": decision.p_up_calibrated or 0.0,
                            "confidence_score": decision.p_up_calibrated or 0.0,
                            "upside_probability_pct": decision.p_up_calibrated,
                            "weekly_prediction": weekly,
                            "is_buy_candidate": True,
                            "gate_passed": True,
                            "gate_reason": None,
                            "calibration_source": "weekly_probability",
                        }
                    )
                )
            else:
                reason = ",".join(decision.reasons) if decision.reasons else "weekly_abstain"
                updated.append(
                    row.model_copy(
                        update={
                            "decision_signal": "HOLD",
                            "is_buy_candidate": False,
                            "gate_passed": False,
                            "gate_reason": reason,
                            "upside_probability_pct": None,
                            "calibration_source": "weekly_probability",
                        }
                    )
                )
        return updated
