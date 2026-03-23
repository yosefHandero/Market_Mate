from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_settings
from app.schemas import DecisionSignal, GateCheck, OrderSide, TradeEligibility
from app.services.repository import ScanRepository


class RiskService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.repo = ScanRepository()

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

        if not self.settings.trade_gate_enabled:
            return TradeEligibility(
                ticker=symbol,
                asset_type=asset_type,
                requested_side=side,
                required_signal=required_signal,
                horizon=horizon,
                allowed=True,
                reason="Trade gate disabled by configuration.",
                notional_estimate=notional_estimate,
                qty=qty,
                gate_checks=[GateCheck(name="trade_gate_enabled", passed=True, detail="Trade gate disabled by configuration.")],
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
        summary = self.repo.get_signal_outcome_summary(asset_type=asset_type)
        signal_bucket = next(
            (bucket for bucket in summary.by_signal if bucket.key == latest_context.signal),
            None,
        )
        score_band_bucket = next(
            (
                bucket
                for bucket in summary.by_signal_score_bucket
                if bucket.key == f"{latest_context.signal}:{latest_context.score_band}"
            ),
            None,
        )
        signal_count, signal_win_rate, signal_avg_return = self._bucket_metrics(
            bucket=signal_bucket,
            horizon=horizon,
        )
        score_band_count, score_band_win_rate, score_band_avg_return = self._bucket_metrics(
            bucket=score_band_bucket,
            horizon=horizon,
        )

        signal_generated_at = latest_context.signal_generated_at
        if signal_generated_at.tzinfo is None:
            signal_generated_at = signal_generated_at.replace(tzinfo=timezone.utc)
        signal_age_minutes = round(
            (datetime.now(timezone.utc) - signal_generated_at).total_seconds() / 60,
            2,
        )

        eligibility = TradeEligibility(
            ticker=symbol,
            asset_type=asset_type,
            requested_side=side,
            required_signal=required_signal,
            signal_run_id=latest_context.run_id,
            signal_generated_at=latest_context.signal_generated_at,
            latest_signal=latest_context.signal,
            confidence=latest_context.calibrated_confidence,
            calibration_source=latest_context.calibration_source,
            raw_score=latest_context.raw_score,
            signal_age_minutes=signal_age_minutes,
            confidence_bucket=confidence_bucket,
            raw_score_bucket=raw_score_bucket,
            score_band=latest_context.score_band,
            horizon=horizon,
            allowed=False,
            reason="Trade gate evaluation not completed.",
            notional_estimate=notional_estimate,
            qty=qty,
            signal_evaluated_count=signal_count,
            signal_win_rate=signal_win_rate,
            signal_avg_return=signal_avg_return,
            score_band_evaluated_count=score_band_count,
            score_band_win_rate=score_band_win_rate,
            score_band_avg_return=score_band_avg_return,
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

        max_signal_age = self.settings.signal_max_age_minutes
        gate_checks.append(
            GateCheck(
                name="signal_freshness",
                passed=signal_age_minutes <= max_signal_age,
                detail=f"{signal_age_minutes:.2f} minute(s) old vs max {max_signal_age}",
            )
        )
        if signal_age_minutes > max_signal_age:
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

        min_count = self.settings.trade_gate_min_evaluated_count
        gate_checks.append(
            GateCheck(
                name="sample_size",
                passed=(signal_count or 0) >= min_count,
                detail=f"{signal_count or 0} vs min {min_count} {horizon} outcomes",
            )
        )
        if (signal_count or 0) < min_count:
            eligibility.reason = (
                f"{asset_type} signal bucket {latest_context.signal} has only {signal_count or 0} "
                f"evaluated {horizon} outcomes; need at least {min_count}."
            )
            return eligibility

        min_win_rate = self.settings.trade_gate_min_win_rate
        gate_checks.append(
            GateCheck(
                name="win_rate",
                passed=(signal_win_rate or 0) >= min_win_rate,
                detail=f"{signal_win_rate or 0:.2f}% vs min {min_win_rate:.2f}%",
            )
        )
        if (signal_win_rate or 0) < min_win_rate:
            eligibility.reason = (
                f"{asset_type} signal bucket {latest_context.signal} win rate {signal_win_rate or 0:.2f}% "
                f"is below minimum {min_win_rate:.2f}%."
            )
            return eligibility

        min_avg_return = self.settings.trade_gate_min_avg_return
        gate_checks.append(
            GateCheck(
                name="avg_return",
                passed=(signal_avg_return or 0) >= min_avg_return,
                detail=f"{signal_avg_return or 0:.4f}% vs min {min_avg_return:.4f}%",
            )
        )
        if (signal_avg_return or 0) < min_avg_return:
            eligibility.reason = (
                f"{asset_type} signal bucket {latest_context.signal} average {horizon} return "
                f"{signal_avg_return or 0:.4f}% is below minimum {min_avg_return:.4f}%."
            )
            return eligibility

        if (score_band_count or 0) >= min_count:
            gate_checks.append(
                GateCheck(
                    name="score_band_win_rate",
                    passed=(score_band_win_rate or 0) >= min_win_rate,
                    detail=f"{score_band_win_rate or 0:.2f}% vs min {min_win_rate:.2f}%",
                )
            )
            if (score_band_win_rate or 0) < min_win_rate:
                eligibility.reason = (
                    f"Score band {latest_context.score_band} win rate {score_band_win_rate or 0:.2f}% "
                    f"is below minimum {min_win_rate:.2f}%."
                )
                return eligibility

            gate_checks.append(
                GateCheck(
                    name="score_band_avg_return",
                    passed=(score_band_avg_return or 0) >= min_avg_return,
                    detail=f"{score_band_avg_return or 0:.4f}% vs min {min_avg_return:.4f}%",
                )
            )
            if (score_band_avg_return or 0) < min_avg_return:
                eligibility.reason = (
                    f"Score band {latest_context.score_band} average {horizon} return "
                    f"{score_band_avg_return or 0:.4f}% is below minimum {min_avg_return:.4f}%."
                )
                return eligibility

        eligibility.allowed = True
        if (score_band_count or 0) >= min_count:
            eligibility.reason = (
                f"Trade passes {asset_type} signal validation, score-band validation, and risk gates."
            )
        else:
            eligibility.reason = (
                f"Trade passes {asset_type} signal-level validation and risk gates. "
                f"Score-band bucket {latest_context.score_band} is still maturing with {score_band_count or 0} evaluated outcomes."
            )
        return eligibility
