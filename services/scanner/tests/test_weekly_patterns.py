import unittest
from datetime import datetime, timedelta, timezone

from app.core.weekly_bar_utils import bars_as_of, parse_bar_timestamp
from app.core.weekly_patterns import detect_weekly_pattern, project_weekly_range


def _bars(closes: list[float], start: datetime | None = None) -> list[dict]:
    start = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "t": (start + timedelta(days=index)).isoformat(),
                "o": close,
                "h": close * 1.01,
                "l": close * 0.99,
                "c": close,
                "v": 1000,
            }
        )
    return rows


class WeeklyPatternTests(unittest.TestCase):
    def test_detect_pattern_uses_only_bars_as_of(self) -> None:
        closes = [100 + index * 0.5 for index in range(80)]
        all_bars = _bars(closes)
        as_of = parse_bar_timestamp(all_bars[40]["t"])
        past_only = detect_weekly_pattern(all_bars, as_of=as_of)
        truncated = detect_weekly_pattern(bars_as_of(all_bars, as_of), as_of=as_of)
        self.assertIsNotNone(past_only)
        self.assertEqual(past_only.pattern_name, truncated.pattern_name)
        self.assertEqual(past_only.directional_bias, truncated.directional_bias)

    def test_future_bars_do_not_change_past_detection(self) -> None:
        closes = [100 + index for index in range(60)]
        base = _bars(closes)
        as_of = parse_bar_timestamp(base[-10]["t"])
        baseline = detect_weekly_pattern(base, as_of=as_of)
        extended = base + _bars([500.0] * 20, start=parse_bar_timestamp(base[-1]["t"]) + timedelta(days=1))
        with_future = detect_weekly_pattern(extended, as_of=as_of)
        self.assertEqual(baseline.pattern_name, with_future.pattern_name)
        self.assertEqual(baseline.directional_bias, with_future.directional_bias)

    def test_project_weekly_range_orders_low_high(self) -> None:
        pattern = detect_weekly_pattern(_bars([100 + index for index in range(70)]), as_of=datetime(2024, 3, 1, tzinfo=timezone.utc))
        self.assertIsNotNone(pattern)
        low, high = project_weekly_range(price=120.0, pattern=pattern, closes=[110.0, 115.0, 120.0])
        self.assertLess(low, high)


if __name__ == "__main__":
    unittest.main()
