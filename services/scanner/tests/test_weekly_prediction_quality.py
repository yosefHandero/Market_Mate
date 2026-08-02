from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.core.calibration import ReliabilityBin
from app.core.weekly_backtest import PatternBacktestStats
from app.services.weekly_prediction_service import WeeklyPredictionService

LAST_DAY = datetime(2026, 1, 1, tzinfo=timezone.utc)


def rising_bars(count: int = 160, start: float = 100.0, drift: float = 0.5) -> list[dict]:
    bars: list[dict] = []
    for offset in reversed(range(count)):
        day = LAST_DAY - timedelta(days=offset)
        index = count - 1 - offset
        close = start + drift * index
        bars.append(
            {
                "t": day.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                "o": round(close - 0.2, 4),
                "h": round(close + 0.6, 4),
                "l": round(close - 0.6, 4),
                "c": round(close, 4),
                "v": 1000,
            }
        )
    return bars


class FakeDailyBars:
    def assess_data_quality(self, bars, *, asset_type=None, as_of=None) -> str:
        return "ok"

    def is_daily_bars_stale(self, bars, *, asset_type=None, as_of=None) -> bool:
        return False

    async def get_daily_bars(self, symbol, *, asset_type=None, force_refresh=False):
        return [], "none"


class FakeScanRepo:
    def get_weekly_pattern_stats(self, *, pattern_name, asset_type, sample_source, signal=None):
        return PatternBacktestStats(
            pattern_name=pattern_name, sample_size=0, hit_rate_pct=None, avg_forward_return_pct=None
        )

    def _friction_bps_for_asset_type(self, asset_type: str) -> float:
        return 10.0


class FakeWalkForwardRepo:
    def __init__(self, reliability_map: list[ReliabilityBin] | None = None) -> None:
        self._map = reliability_map or []

    def get_latest_reliability_map(self, asset_type: str, *, min_count: int = 0) -> list[ReliabilityBin]:
        return list(self._map)


def live_settings(**overrides) -> Settings:
    base = dict(
        weekly_primary_horizon_enabled=True,
        weekly_daily_lookback_bars_min=60,
        weekly_daily_lookback_bars_preferred=120,
        proof_rsi_overbought=101.0,
        proof_min_pattern_edge_pct=0.0,
        proof_require_buy_hold_baseline=False,
        proof_min_pattern_samples=3,
        proof_step_days=14,
        proof_momentum_lookback_days=20,
        weekly_forward_days=7,
        weekly_forward_tolerance_days=3,
        calibration_min_score_band_samples=1,
    )
    base.update(overrides)
    return Settings(**base)


def build(service: WeeklyPredictionService, bars: list[dict]):
    return asyncio.run(
        service.build_weekly_prediction(
            symbol="AAA", asset_type="stock", as_of=LAST_DAY, daily_bars=bars
        )
    )


def build_with_market(
    service: WeeklyPredictionService, bars: list[dict], market_bars: list[dict]
):
    return asyncio.run(
        service.build_weekly_prediction(
            symbol="AAA",
            asset_type="stock",
            as_of=LAST_DAY,
            daily_bars=bars,
            market_daily_bars=market_bars,
        )
    )


def make_service(settings: Settings, wf_repo: FakeWalkForwardRepo | None = None) -> WeeklyPredictionService:
    return WeeklyPredictionService(
        daily_bars=FakeDailyBars(),
        repository=FakeScanRepo(),
        walk_forward_repository=wf_repo or FakeWalkForwardRepo(),
        settings=settings,
    )


class WeeklyPredictionQualityTests(unittest.TestCase):
    def test_clean_bullish_candidate_is_served(self) -> None:
        service = make_service(live_settings())
        prediction = build(service, rising_bars())
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.directional_bias, "bullish")
        self.assertIsNotNone(prediction.upside_probability_pct)
        self.assertEqual(prediction.methodology, "pattern_recognition")

    def test_rejected_when_filter_fails(self) -> None:
        service = make_service(live_settings(proof_min_pattern_samples=999))
        self.assertIsNone(build(service, rising_bars()))

    def test_filter_flag_off_keeps_prediction(self) -> None:
        service = make_service(
            live_settings(proof_min_pattern_samples=999, weekly_apply_proof_candidate_filters=False)
        )
        self.assertIsNotNone(build(service, rising_bars()))

    def test_calibration_map_is_applied(self) -> None:
        wf_repo = FakeWalkForwardRepo(
            [ReliabilityBin(low=0.0, high=100.0, realized_rate_pct=61.0, count=50)]
        )
        service = make_service(live_settings(), wf_repo=wf_repo)
        prediction = build(service, rising_bars())
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.upside_probability_pct, 61.0)
        self.assertEqual(prediction.methodology, "pattern_recognition_calibrated")

    def test_calibration_disabled_serves_raw(self) -> None:
        wf_repo = FakeWalkForwardRepo(
            [ReliabilityBin(low=0.0, high=100.0, realized_rate_pct=61.0, count=50)]
        )
        service = make_service(live_settings(weekly_apply_calibration_map=False), wf_repo=wf_repo)
        prediction = build(service, rising_bars())
        self.assertIsNotNone(prediction)
        self.assertNotEqual(prediction.upside_probability_pct, 61.0)
        self.assertEqual(prediction.methodology, "pattern_recognition")

    def test_expected_value_gate_rejects(self) -> None:
        service = make_service(live_settings(proof_min_expected_value_pct=999.0))
        self.assertIsNone(build(service, rising_bars()))

    def test_relative_strength_parity_tilts_probability(self) -> None:
        # When a benchmark daily series is supplied (as the scanner now does), the
        # live path applies the same relative-strength tilt the proof engine uses.
        service = make_service(live_settings())
        symbol_bars = rising_bars(drift=0.5)
        weak_benchmark = rising_bars(drift=0.0)  # symbol outperforms -> positive RS
        strong_benchmark = rising_bars(drift=1.5)  # symbol lags -> negative RS
        outperforming = build_with_market(service, symbol_bars, weak_benchmark)
        lagging = build_with_market(service, symbol_bars, strong_benchmark)
        self.assertIsNotNone(outperforming)
        self.assertIsNotNone(lagging)
        self.assertGreater(
            outperforming.upside_probability_pct, lagging.upside_probability_pct
        )


if __name__ == "__main__":
    unittest.main()
