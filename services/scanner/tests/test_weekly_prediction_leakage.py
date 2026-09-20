from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.brain.weekly_backtest import PatternBacktestStats
from app.services.weekly_prediction_service import WeeklyPredictionService


def _rising_bars(*, count: int, last_day: datetime, drift: float = 0.4) -> list[dict]:
    bars: list[dict] = []
    for offset in reversed(range(count)):
        day = last_day - timedelta(days=offset)
        idx = count - 1 - offset
        close = 100.0 + drift * idx
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


class WalkForwardStatsLeakageTests(unittest.TestCase):
    def setUp(self) -> None:
        # Avoid touching the DB: the helpers under test are pure.
        self.service = WeeklyPredictionService.__new__(WeeklyPredictionService)
        self.service.settings = Settings(
            weekly_daily_lookback_bars_min=60,
            weekly_forward_days=7,
            weekly_forward_tolerance_days=3,
            weekly_hold_return_tolerance_pct=0.0,
        )

    def test_future_bars_cannot_change_served_walkforward_stats(self) -> None:
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        full = _rising_bars(count=400, last_day=last_day)
        as_of = datetime(2025, 7, 1, tzinfo=timezone.utc)
        truncated = [b for b in full if datetime.fromisoformat(b["t"]) <= as_of]

        with_future = self.service._stats_from_walkforward(
            full, pattern_name="range_neutral", as_of=as_of
        )
        without_future = self.service._stats_from_walkforward(
            truncated, pattern_name="range_neutral", as_of=as_of
        )
        self.assertEqual(with_future.sample_size, without_future.sample_size)
        self.assertEqual(with_future.hit_rate_pct, without_future.hit_rate_pct)
        self.assertEqual(
            with_future.avg_forward_return_pct, without_future.avg_forward_return_pct
        )


class ServedBlendLeakageTests(unittest.TestCase):
    def _stats(self, source: str, *, n: int, hit: float) -> PatternBacktestStats:
        return PatternBacktestStats(
            pattern_name=source, sample_size=n, hit_rate_pct=hit, avg_forward_return_pct=1.0
        )

    def test_out_of_sample_and_live_forward_never_enter_served_blend(self) -> None:
        fallback = self._stats("walkforward", n=5, hit=55.0)
        repo_stats = {
            "historical": self._stats("historical", n=40, hit=60.0),
            "backfilled_replay": self._stats("backfilled_replay", n=30, hit=58.0),
            # These must be ignored by the served blend.
            "live_paper_forward": self._stats("live_paper_forward", n=100, hit=90.0),
            "out_of_sample": self._stats("out_of_sample", n=100, hit=10.0),
        }
        blended = WeeklyPredictionService._served_blend(repo_stats, fallback=fallback)
        # Backfilled replay is a calibration source and wins over historical; the
        # leaky live/oos rows are never selected regardless of their sample size.
        self.assertEqual(blended.pattern_name, "backfilled_replay")
        self.assertNotIn(blended.pattern_name, {"live_paper_forward", "out_of_sample"})

    def test_blend_falls_back_to_historical_then_walkforward(self) -> None:
        fallback = self._stats("walkforward", n=5, hit=55.0)
        only_leaky = {
            "live_paper_forward": self._stats("live_paper_forward", n=100, hit=90.0),
            "out_of_sample": self._stats("out_of_sample", n=100, hit=10.0),
        }
        blended = WeeklyPredictionService._served_blend(only_leaky, fallback=fallback)
        # With no calibration source present, the walk-forward fallback is served,
        # never the leaky live/oos stats.
        self.assertEqual(blended.pattern_name, "walkforward")


if __name__ == "__main__":
    unittest.main()
