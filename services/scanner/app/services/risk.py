from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_settings
from app.core.freshness import is_stale_signal
from app.core.strategy_contract import build_strategy_evaluation_metadata
from app.schemas import DecisionSignal, GateCheck, OrderSide, TradeEligibility
from app.services.repository import ScanRepository


class RiskService:
    def __init__(self, scan_repository: ScanRepository | None = None) -> None:
        self.settings = get_settings()
        self.repo = scan_repository or ScanRepository()

    def _required_signal_for_side(self, side: OrderSide) -> DecisionSignal:
        return "BUY" if side == "buy" else "SELL"

    def _asset_type_for_symbol(self, symbol: str) -> str:
        return "crypto" if "/" in symbol else "stock"

    def _bucket_metrics(self, *, bucket, horizon: str) -> tuple[int | None, float | None, float | None]:
        if bucket is None:
            return None, None, None

        if horizon == "15m":
            return bucket.evaluated_15m_count, bucket.win_rate_15m, bucket.avg_return_15m
        if horizon == "1d":
            return bucket.evaluated_1d_count, bucket.win_rate_1d, bucket.avg_return_1d
        return bucket.evaluated_1h_count, bucket.win_rate_1h, bucket.avg_return_1h

    def _portfolio_checks(self, *, ticker: str, asset_type: str, notional_estimate: float) -> tuple[list[GateCheck], str | None]:
        if not self.settings.portfolio_risk_enabled:
            return (
                [
                    GateCheck(
                        name="portfolio_risk_enabled",
                        passed=False,
                        detail="Portfolio risk disabled by configuration.",
                    )
                ],
                "Portfolio risk is disabled by configuration; trading support is blocked (fail-closed).",
            )

        snapshot = self.repo.get_portfolio_guardrail_snapshot()
        symbol_notional = float(snapshot["symbol_notional"].get(ticker, 0.0))
        asset_type_notional = float(snapshot["asset_type_notional"].get(asset_type, 0.0))
        daily_notional_after_order = round(float(snapshot["daily_notional"]) + notional_estimate, 2)
        symbol_notional_after_order = round(symbol_notional + notional_estimate, 2)
        asset_type_notional_after_order = round(asset_type_notional + notional_estimate, 2)

        checks = [
            GateCheck(
                name="portfolio_daily_notional",
                passed=daily_notional_after_order <= self.settings.portfolio_max_daily_notional,
                detail=f"${daily_notional_after_order:.2f} vs max ${self.settings.portfolio_max_daily_notional:.2f}",
            ),
            GateCheck(
                name="portfolio_symbol_concentration",
                passed=symbol_notional_after_order <= self.settings.portfolio_max_symbol_notional,
                detail=f"${symbol_notional_after_order:.2f} vs max ${self.settings.portfolio_max_symbol_notional:.2f}",
            ),
            GateCheck(
                name="portfolio_asset_type_concentration",
                passed=asset_type_notional_after_order <= self.settings.portfolio_max_asset_type_notional,
                detail=f"${asset_type_notional_after_order:.2f} vs max ${self.settings.portfolio_max_asset_type_notional:.2f}",
            ),
            GateCheck(
                name="portfolio_daily_loss_limit",
                passed=(
                    snapshot["weighted_daily_return_pct"] is None
                    or float(snapshot["weighted_daily_return_pct"]) >= self.settings.portfolio_daily_loss_limit_pct
                ),
                detail=(
                    "no resolved trade outcomes for the day"
                    if snapshot["weighted_daily_return_pct"] is None
                    else (
                        f"{float(snapshot['weighted_daily_return_pct']):.4f}% vs min "
                        f"{self.settings.portfolio_daily_loss_limit_pct:.4f}%"
                    )
                ),
            ),
            GateCheck(
                name="portfolio_loss_streak",
                passed=int(snapshot["loss_streak"]) < self.settings.portfolio_max_loss_streak,
                detail=f"{int(snapshot['loss_streak'])} vs max {self.settings.portfolio_max_loss_streak - 1}",
            ),
            GateCheck(
                name="portfolio_drawdown_kill_switch",
                passed=float(snapshot["max_drawdown_pct"]) < self.settings.portfolio_max_drawdown_pct,
                detail=f"{float(snapshot['max_drawdown_pct']):.4f}% vs max {self.settings.portfolio_max_drawdown_pct:.4f}%",
            ),
        ]
        first_failed = next((check for check in checks if not check.passed), None)
        summary = None
        if first_failed is not None:
            summary = f"Blocked by {first_failed.name}: {first_failed.detail}."
        return checks, summary

    def evaluate_trade(
        self,
        *,
        ticker: str,
        side: OrderSide,
        qty: float,
        latest_price: float,
    ) -> TradeEligibility:
        symbol = ticker.upper()
        asset_type = self._asset_type_for_symbol(symbol)
        required_signal = self._required_signal_for_side(side)
        notional_estimate = round(latest_price * qty, 2)
        horizon = self.settings.trade_gate_horizon
        gate_checks: list[GateCheck] = []
        now = datetime.now(timezone.utc)

        if not self.settings.trade_gate_enabled:
            return TradeEligibility(
                ticker=symbol,
                asset_type=asset_type,
                requested_side=side,
                required_signal=required_signal,
                horizon=horizon,
                allowed=False,
                reason="Trade gate is disabled by configuration; order support is blocked (fail-closed).",
                notional_estimate=notional_estimate,
                qty=qty,
                execution_eligibility="blocked",
                gate_checks=[
                    GateCheck(
                        name="trade_gate_enabled",
                        passed=False,
                        detail="Trade gate disabled by configuration.",
                    )
                ],
            )

        if qty > self.settings.trade_gate_max_qty:
            return TradeEligibility(
                ticker=symbol,
                asset_type=asset_type,
                requested_side=side,
                required_signal=required_signal,
                horizon=horizon,
                allowed=False,
                reason=f"Order qty {qty} exceeds max qty {self.settings.trade_gate_max_qty}.",
                notional_estimate=notional_estimate,
                qty=qty,
                gate_checks=[GateCheck(name="max_qty", passed=False, detail=f"{qty} > {self.settings.trade_gate_max_qty}")],
            )

        if notional_estimate > self.settings.trade_gate_max_notional:
            return TradeEligibility(
                ticker=symbol,
                asset_type=asset_type,
                requested_side=side,
                required_signal=required_signal,
                horizon=horizon,
                allowed=False,
                reason=(
                    f"Order notional ${notional_estimate:.2f} exceeds max notional "
                    f"${self.settings.trade_gate_max_notional:.2f}."
                ),
                notional_estimate=notional_estimate,
                qty=qty,
                gate_checks=[
                    GateCheck(
                        name="max_notional",
                        passed=False,
                        detail=f"${notional_estimate:.2f} > ${self.settings.trade_gate_max_notional:.2f}",
                    )
                ],
            )

        latest_context = self.repo.get_latest_signal_context(symbol)
        if latest_context is None:
            return TradeEligibility(
                ticker=symbol,
                asset_type=asset_type,
                requested_side=side,
                required_signal=required_signal,
                horizon=horizon,
                allowed=False,
                reason="No current decision signal is available for this ticker.",
                notional_estimate=notional_estimate,
                qty=qty,
                gate_checks=[GateCheck(name="latest_signal", passed=False, detail="No latest signal context found.")],
            )

        confidence_bucket = self.repo.confidence_bucket_for(latest_context.calibrated_confidence)
        raw_score_bucket = self.repo.confidence_bucket_for(latest_context.raw_score)
        evidence_gate = self.repo.evaluate_signal_gate(
            asset_type=asset_type,
            signal=latest_context.signal,
            score_band=latest_context.score_band,
            horizon=horizon,
            observed_at=latest_context.signal_generated_at,
        )

        signal_generated_at = latest_context.signal_generated_at
        if signal_generated_at.tzinfo is None:
            signal_generated_at = signal_generated_at.replace(tzinfo=timezone.utc)
        signal_age_minutes = round(
            (now - signal_generated_at).total_seconds() / 60,
            2,
        )
        latest_run_at = self.repo.get_latest_run_timestamp()
        latest_scan_age_minutes = None
        latest_scan_fresh = None
        if latest_run_at is not None:
            comparable_latest_run_at = latest_run_at
            if comparable_latest_run_at.tzinfo is None:
                comparable_latest_run_at = comparable_latest_run_at.replace(tzinfo=timezone.utc)
            latest_scan_age_minutes = round((now - comparable_latest_run_at).total_seconds() / 60, 2)
            latest_scan_fresh = latest_scan_age_minutes <= self.settings.health_max_stale_minutes
        gate_consistent_with_signal = evidence_gate.passed == latest_context.gate_passed
        strategy_metadata = build_strategy_evaluation_metadata(
            signal=latest_context.signal,
            gate_passed=latest_context.gate_passed,
            calibration_source=latest_context.calibration_source,
            data_quality=getattr(latest_context, "data_quality", "ok") or "ok",
            provider_status=getattr(latest_context, "provider_status", "ok") or "ok",
            provider_warnings=getattr(latest_context, "provider_warnings", []),
        )
        review_flags = list(
            (((getattr(latest_context, "layer_details", {}) or {}).get("execution") or {}).get("review_flags") or [])
        )
        execution_eligibility = strategy_metadata.execution_eligibility
        evidence_quality_reasons = list(strategy_metadata.evidence_quality_reasons)
        if review_flags and execution_eligibility == "eligible":
            execution_eligibility = "review"
            evidence_quality_reasons.append(
                "Execution review flags are active: " + ", ".join(sorted(review_flags)) + "."
            )

        eligibility = TradeEligibility(
            ticker=symbol,
            asset_type=asset_type,
            strategy_variant=getattr(latest_context, "strategy_variant", "layered-v4") or "layered-v4",
            requested_side=side,
            required_signal=required_signal,
            signal_outcome_id=latest_context.signal_outcome_id,
            signal_run_id=latest_context.run_id,
            signal_generated_at=latest_context.signal_generated_at,
            latest_signal=latest_context.signal,
            confidence=latest_context.calibrated_confidence,
            calibration_source=latest_context.calibration_source,
            raw_score=latest_context.raw_score,
            confidence_label=strategy_metadata.confidence_label,
            evidence_quality=strategy_metadata.evidence_quality,
            evidence_quality_score=strategy_metadata.evidence_quality_score,
            evidence_quality_reasons=evidence_quality_reasons,
            execution_eligibility=execution_eligibility,
            strategy_id=strategy_metadata.strategy_id,
            strategy_version=strategy_metadata.strategy_version,
            strategy_primary_horizon=strategy_metadata.primary_holding_horizon,
            strategy_entry_assumption=strategy_metadata.entry_assumption,
            strategy_exit_assumption=strategy_metadata.exit_assumption,
            signal_age_minutes=signal_age_minutes,
            confidence_bucket=confidence_bucket,
            raw_score_bucket=raw_score_bucket,
            score_band=latest_context.score_band,
            horizon=horizon,
            gate_evaluation_mode=latest_context.gate_evaluation_mode,
            evidence_basis=evidence_gate.evidence_basis,
            trust_window_start=evidence_gate.trust_window_start,
            trust_window_end=evidence_gate.trust_window_end,
            latest_scan_age_minutes=latest_scan_age_minutes,
            latest_scan_fresh=latest_scan_fresh,
            stored_gate_passed=latest_context.gate_passed,
            stored_gate_reason=latest_context.gate_reason,
            gate_consistent_with_signal=gate_consistent_with_signal,
            allowed=False,
            reason="Trade gate evaluation not completed.",
            notional_estimate=notional_estimate,
            qty=qty,
            signal_evaluated_count=evidence_gate.signal_count,
            signal_win_rate=evidence_gate.signal_win_rate,
            signal_avg_return=evidence_gate.signal_avg_return,
            score_band_evaluated_count=evidence_gate.score_band_count,
            score_band_win_rate=evidence_gate.score_band_win_rate,
            score_band_avg_return=evidence_gate.score_band_avg_return,
            gate_checks=gate_checks,
        )

        gate_checks.append(
            GateCheck(
                name="required_signal",
                passed=latest_context.signal == required_signal,
                detail=f"latest={latest_context.signal} required={required_signal}",
            )
        )
        if latest_context.signal != required_signal:
            eligibility.reason = (
                f"Latest decision for {symbol} is {latest_context.signal}, "
                f"which does not support a {side.upper()} order."
            )
            return eligibility

        scan_fresh = latest_scan_fresh is True
        gate_checks.append(
            GateCheck(
                name="latest_scan_freshness",
                passed=scan_fresh,
                detail=(
                    "no recent scan timestamp available"
                    if latest_scan_age_minutes is None
                    else f"{latest_scan_age_minutes:.2f} minute(s) old vs max {self.settings.health_max_stale_minutes}"
                ),
            )
        )
        if not scan_fresh:
            eligibility.reason = (
                f"Scanner state is not fresh enough for paper-trading support on {symbol}. "
                f"Latest full scan age is "
                f"{'unknown' if latest_scan_age_minutes is None else f'{latest_scan_age_minutes:.2f} minutes'}."
            )
            return eligibility

        max_signal_age = self.settings.stale_signal_max_age_minutes
        stale_signal, signal_age_minutes = is_stale_signal(
            observed_at=now,
            signal_created_at=signal_generated_at,
            stale_after_minutes=max_signal_age,
        )
        gate_checks.append(
            GateCheck(
                name="signal_freshness",
                passed=not stale_signal,
                detail=f"{signal_age_minutes:.2f} minute(s) old vs max {max_signal_age}",
            )
        )
        if stale_signal:
            eligibility.reason = (
                f"Latest signal for {symbol} is stale at {signal_age_minutes:.2f} minutes old; "
                f"max allowed age is {max_signal_age} minutes."
            )
            return eligibility

        gate_checks.append(
            GateCheck(
                name="signal_enabled",
                passed=latest_context.signal in self.settings.trade_gate_allowed_signal_items,
                detail=f"allowed={','.join(self.settings.trade_gate_allowed_signal_items)}",
            )
        )
        if latest_context.signal not in self.settings.trade_gate_allowed_signal_items:
            eligibility.reason = (
                f"Signal {latest_context.signal} is not enabled for trading by configuration."
            )
            return eligibility

        gate_checks.extend(evidence_gate.checks)
        gate_checks.append(
            GateCheck(
                name="signal_gate_consistency",
                passed=gate_consistent_with_signal,
                detail=(
                    f"stored_scan_gate={latest_context.gate_passed} "
                    f"locked_window_gate={evidence_gate.passed}"
                ),
            )
        )
        if not gate_consistent_with_signal:
            eligibility.reason = (
                f"Stored scan gate for {symbol} does not match the locked trust-window re-evaluation. "
                f"stored={latest_context.gate_passed} locked={evidence_gate.passed}."
            )
            return eligibility
        if not latest_context.gate_passed:
            eligibility.reason = latest_context.gate_reason
            return eligibility

        portfolio_checks, portfolio_summary = self._portfolio_checks(
            ticker=symbol,
            asset_type=asset_type,
            notional_estimate=notional_estimate,
        )
        eligibility.portfolio_checks = portfolio_checks
        eligibility.portfolio_summary = portfolio_summary
        if portfolio_summary is not None:
            eligibility.reason = portfolio_summary
            eligibility.execution_eligibility = "blocked"
            return eligibility

        eligibility.allowed = True
        eligibility.reason = latest_context.gate_reason or evidence_gate.reason
        if eligibility.execution_eligibility not in {"review", "not_applicable"}:
            eligibility.execution_eligibility = "eligible"
        return eligibility
