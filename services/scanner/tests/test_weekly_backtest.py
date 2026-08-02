import unittest
from datetime import datetime, timedelta, timezone

from app.core.weekly_backtest import summarize_pattern_stats, walk_forward_pattern_samples
from app.core.weekly_patterns import detect_weekly_pattern


def _bars(closes: list[float]) -> list[dict]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "t": (start + timedelta(days=index)).isoformat(),
            "o": close,
            "h": close * 1.01,
            "l": close * 0.99,
            "c": close,
            "v": 1000,
        }
        for index, close in enumerate(closes)
    ]


class WeeklyBacktestTests(unittest.TestCase):
    def test_walk_forward_produces_historical_samples(self) -> None:
        closes = [100 + (index * 0.3) for index in range(400)]
        samples = walk_forward_pattern_samples(_bars(closes), warmup_bars=60, step_days=7)
        self.assertGreater(len(samples), 10)
        self.assertTrue(all(sample.sample_source == "historical" for sample in samples))

    def test_summarize_pattern_stats(self) -> None:
        closes = [100 + (index * 0.3) for index in range(400)]
        samples = walk_forward_pattern_samples(_bars(closes), warmup_bars=60, step_days=7)
        pattern_name = samples[0].pattern_name
        stats = summarize_pattern_stats(samples, pattern_name=pattern_name)
        self.assertGreater(stats.sample_size, 0)
        self.assertIsNotNone(stats.hit_rate_pct)
        self.assertIsNotNone(stats.avg_forward_return_pct)

    def test_walk_forward_does_not_use_future_outcomes_in_detection(self) -> None:
        closes = [100 + index for index in range(120)]
        bars = _bars(closes)
        first_sample = walk_forward_pattern_samples(bars, warmup_bars=60, step_days=7)[0]
        redetected = detect_weekly_pattern(bars, as_of=first_sample.as_of)
        self.assertEqual(first_sample.pattern_name, redetected.pattern_name)


if __name__ == "__main__":
    unittest.main()
