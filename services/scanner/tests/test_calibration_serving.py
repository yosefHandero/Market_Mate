from __future__ import annotations

import unittest

from app.core.calibration import (
    ReliabilityBin,
    apply_reliability_map,
    build_reliability_map,
    reliability_map_from_payload,
    reliability_map_to_payload,
)


class CalibrationServingTests(unittest.TestCase):
    def test_payload_round_trip_preserves_bins(self) -> None:
        pairs = [(72.0, True)] * 6 + [(74.0, False)] * 4
        reliability_map = build_reliability_map(pairs)
        self.assertTrue(reliability_map)
        restored = reliability_map_from_payload(reliability_map_to_payload(reliability_map))
        self.assertEqual(restored, reliability_map)

    def test_apply_snaps_probability_to_realized_rate(self) -> None:
        # 6 of 10 predictions in the 70-79 band actually went up -> realized 60%.
        pairs = [(72.0, True)] * 6 + [(74.0, False)] * 4
        reliability_map = build_reliability_map(pairs)
        restored = reliability_map_from_payload(reliability_map_to_payload(reliability_map))
        self.assertEqual(apply_reliability_map(restored, 75.0), 60.0)

    def test_min_count_filter_drops_thin_bins(self) -> None:
        payload = [
            {"low": 60.0, "high": 70.0, "realized_rate_pct": 40.0, "count": 3},
            {"low": 70.0, "high": 80.0, "realized_rate_pct": 65.0, "count": 25},
        ]
        served = reliability_map_from_payload(payload, min_count=10)
        self.assertEqual(len(served), 1)
        self.assertEqual(served[0], ReliabilityBin(low=70.0, high=80.0, realized_rate_pct=65.0, count=25))
        # A probability landing in the dropped thin bin is served unchanged.
        self.assertEqual(apply_reliability_map(served, 65.0), 65.0)

    def test_empty_or_malformed_payload_is_safe(self) -> None:
        self.assertEqual(reliability_map_from_payload(None), [])
        self.assertEqual(reliability_map_from_payload([]), [])
        self.assertEqual(reliability_map_from_payload([{"low": 1.0}]), [])


if __name__ == "__main__":
    unittest.main()
