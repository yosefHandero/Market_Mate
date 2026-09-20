from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.brain.candidate_quality import buy_candidate_reject_reason, rsi, sma, volume_confirmed
from app.brain.weekly_backtest import PatternBacktestStats

LAST_DAY = datetime(2026, 1, 1, tzinfo=timezone.utc)


def rising_bars(
    *,
    count: int = 120,
    start: float = 100.0,
    drift: float = 0.5,
    recent_volume: int = 1000,
    baseline_volume: int = 1000,
    recent_window: int = 20,
) -> list[dict]:
    bars: list[dict] = []
    for offset in reversed(range(count)):
        day = LAST_DAY - timedelta(days=offset)
        index = count - 1 - offset
        close = start + drift * index
        volume = recent_volume if index >= count - recent_window else baseline_volume
        bars.append(
            {
                "t": day.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                "o": round(close - 0.2, 4),
                "h": round(close + 0.6, 4),
                "l": round(close - 0.6, 4),
                "c": round(close, 4),
                "v": volume,
            }
        )
    return bars


def closes_of(bars: list[dict]) -> list[float]:
    return [float(bar["c"]) for bar in bars]


def base_settings(**overrides) -> SimpleNamespace:
    values = dict(
        proof_rsi_overbought=101.0,
        proof_min_pattern_samples=3,
        proof_min_pattern_edge_pct=0.0,
        proof_require_buy_hold_baseline=False,
        proof_volume_lookback_days=20,
        proof_min_volume_median_ratio=0.5,
        weekly_forward_days=7,
        weekly_forward_tolerance_days=3,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


GOOD_STATS = PatternBacktestStats(
    pattern_name="p", sample_size=10, hit_rate_pct=60.0, avg_forward_return_pct=1.5
)


class BuyCandidateRejectReasonTests(unittest.TestCase):
    def _call(self, *, bars, closes, entry_price, settings, stats):
        return buy_candidate_reject_reason(
            bars=bars,
            closes=closes,
            entry_price=entry_price,
            as_of=LAST_DAY,
            settings=settings,
            stats=stats,
            warmup_bars=60,
            step_days=7,
        )

    def test_accepts_clean_bullish_candidate(self) -> None:
        bars = rising_bars()
        closes = closes_of(bars)
        self.assertIsNone(
            self._call(
                bars=bars, closes=closes, entry_price=closes[-1], settings=base_settings(), stats=GOOD_STATS
            )
        )

    def test_below_sma50_rejected(self) -> None:
        bars = rising_bars()
        closes = closes_of(bars)
        below = sma(closes, 50) - 5.0
        self.assertEqual(
            self._call(bars=bars, closes=closes, entry_price=below, settings=base_settings(), stats=GOOD_STATS),
            "below_sma50",
        )

    def test_rsi_overbought_rejected(self) -> None:
        bars = rising_bars()
        closes = closes_of(bars)
        # Monotonic rise makes RSI saturate at 100.
        self.assertEqual(rsi(closes, 14), 100.0)
        self.assertEqual(
            self._call(
                bars=bars,
                closes=closes,
                entry_price=closes[-1],
                settings=base_settings(proof_rsi_overbought=70.0),
                stats=GOOD_STATS,
            ),
            "rsi_overbought",
        )

    def test_insufficient_samples_rejected(self) -> None:
        bars = rising_bars()
        closes = closes_of(bars)
        thin = PatternBacktestStats(pattern_name="p", sample_size=1, hit_rate_pct=90.0, avg_forward_return_pct=2.0)
        self.assertEqual(
            self._call(bars=bars, closes=closes, entry_price=closes[-1], settings=base_settings(), stats=thin),
            "insufficient_pattern_samples",
        )

    def test_pattern_edge_below_min_rejected(self) -> None:
        bars = rising_bars()
        closes = closes_of(bars)
        weak = PatternBacktestStats(pattern_name="p", sample_size=10, hit_rate_pct=45.0, avg_forward_return_pct=1.0)
        self.assertEqual(
            self._call(
                bars=bars,
                closes=closes,
                entry_price=closes[-1],
                settings=base_settings(proof_min_pattern_edge_pct=2.0),
                stats=weak,
            ),
            "pattern_edge_below_min",
        )

    def test_nonpositive_expectancy_rejected(self) -> None:
        bars = rising_bars()
        closes = closes_of(bars)
        flat = PatternBacktestStats(pattern_name="p", sample_size=10, hit_rate_pct=60.0, avg_forward_return_pct=0.0)
        self.assertEqual(
            self._call(bars=bars, closes=closes, entry_price=closes[-1], settings=base_settings(), stats=flat),
            "nonpositive_expectancy",
        )

    def test_no_edge_vs_buy_hold_rejected(self) -> None:
        bars = rising_bars()
        closes = closes_of(bars)
        tiny = PatternBacktestStats(pattern_name="p", sample_size=10, hit_rate_pct=60.0, avg_forward_return_pct=0.001)
        self.assertEqual(
            self._call(
                bars=bars,
                closes=closes,
                entry_price=closes[-1],
                settings=base_settings(proof_require_buy_hold_baseline=True),
                stats=tiny,
            ),
            "no_edge_vs_buy_hold",
        )

    def test_volume_not_confirmed_rejected(self) -> None:
        bars = rising_bars(recent_volume=100, baseline_volume=1000)
        closes = closes_of(bars)
        self.assertFalse(
            volume_confirmed(bars, LAST_DAY, lookback_days=20, min_median_ratio=0.5)
        )
        self.assertEqual(
            self._call(bars=bars, closes=closes, entry_price=closes[-1], settings=base_settings(), stats=GOOD_STATS),
            "volume_not_confirmed",
        )


if __name__ == "__main__":
    unittest.main()
