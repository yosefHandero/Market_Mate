import unittest

from app.brain.evaluation.paired import PairedOutcome, compare_paired, t_critical_95


def _pairs(diffs: list[float], *, week_size: int = 5) -> list[PairedOutcome]:
    return [
        PairedOutcome(
            key=f"scan-{i}",
            champion_return_pct=0.0,
            challenger_return_pct=d,
            resolution_week=f"2024-W{(i // week_size) + 1:02d}",
        )
        for i, d in enumerate(diffs)
    ]


class PairedComparisonTests(unittest.TestCase):
    def test_both_abstained_pairs_are_excluded_from_inference(self) -> None:
        pairs = [
            PairedOutcome(key="a", champion_return_pct=None, challenger_return_pct=None),
            PairedOutcome(key="b", champion_return_pct=1.0, challenger_return_pct=2.0),
            PairedOutcome(key="c", champion_return_pct=None, challenger_return_pct=None),
        ]
        result = compare_paired(pairs, min_pairs=1)
        self.assertEqual(result.n_pairs_total, 3)
        self.assertEqual(result.n_pairs_informative, 1)
        self.assertEqual(result.n_both_abstained, 2)
        self.assertEqual(result.mean_diff_pct, 1.0)

    def test_abstention_counts_as_zero_return(self) -> None:
        pairs = [
            PairedOutcome(key="a", champion_return_pct=2.0, challenger_return_pct=None),
        ]
        result = compare_paired(pairs, min_pairs=1)
        self.assertEqual(result.mean_diff_pct, -2.0)
        self.assertEqual(result.n_disagreements, 1)

    def test_missing_resolution_week_is_reported_and_fails_closed(self) -> None:
        result = compare_paired(
            [
                PairedOutcome(
                    key=f"scan-{i}",
                    champion_return_pct=0.0,
                    challenger_return_pct=1.0,
                )
                for i in range(40)
            ],
            min_pairs=40,
        )
        self.assertTrue(result.sufficient_pairs)
        self.assertFalse(result.sufficient_resolution_clusters)
        self.assertEqual(result.n_resolution_clusters, 0)
        self.assertEqual(result.n_missing_resolution_week, 40)
        self.assertFalse(result.resolution_cluster_metadata_complete)
        self.assertFalse(result.challenger_superior)

    def test_insufficient_pairs_never_supports_promotion(self) -> None:
        result = compare_paired(_pairs([5.0] * 10), min_pairs=40)
        self.assertFalse(result.sufficient_pairs)
        self.assertFalse(result.challenger_superior)
        self.assertIn("need 40", result.summary)

    def test_clear_edge_with_enough_pairs_is_superior(self) -> None:
        diffs = [1.0, 1.2, 0.8, 1.1, 0.9] * 10  # 50 pairs, tight positive spread
        result = compare_paired(_pairs(diffs), min_pairs=40)
        self.assertTrue(result.sufficient_pairs)
        self.assertTrue(result.challenger_superior)
        self.assertFalse(result.challenger_inferior)
        self.assertIsNotNone(result.diff_ci95_low_pct)
        self.assertGreater(result.diff_ci95_low_pct, 0.0)
        self.assertEqual(result.n_resolution_clusters, 10)

    def test_noisy_point_estimate_alone_is_not_enough(self) -> None:
        # Positive mean but the spread is so wide the CI straddles zero:
        # a point-estimate rule would promote; the interval rule must not.
        diffs = ([30.0, -29.0] * 25)[:50]
        result = compare_paired(_pairs(diffs), min_pairs=40)
        self.assertTrue(result.sufficient_pairs)
        self.assertGreater(result.mean_diff_pct, 0.0)
        self.assertFalse(result.challenger_superior)
        self.assertIn("Inconclusive", result.summary)

    def test_clearly_worse_challenger_is_inferior(self) -> None:
        diffs = [-1.0, -1.2, -0.8, -1.1, -0.9] * 10
        result = compare_paired(_pairs(diffs), min_pairs=40)
        self.assertTrue(result.challenger_inferior)
        self.assertFalse(result.challenger_superior)

    def test_same_week_duplicates_cannot_create_promotion(self) -> None:
        pairs = [
            PairedOutcome(
                key=f"scan-{i}",
                champion_return_pct=0.0,
                challenger_return_pct=1.0,
                resolution_week="2024-W01",
            )
            for i in range(80)
        ]
        result = compare_paired(pairs, min_pairs=40)
        self.assertTrue(result.sufficient_pairs)
        self.assertFalse(result.sufficient_resolution_clusters)
        self.assertEqual(result.n_resolution_clusters, 1)
        self.assertIsNone(result.diff_ci95_low_pct)
        self.assertFalse(result.challenger_superior)

    def test_duplicating_week_clusters_does_not_shrink_clustered_interval(self) -> None:
        base_pairs = [
            PairedOutcome(
                key="week-1",
                champion_return_pct=0.0,
                challenger_return_pct=2.0,
                resolution_week="2024-W01",
            ),
            PairedOutcome(
                key="week-2",
                champion_return_pct=0.0,
                challenger_return_pct=2.0,
                resolution_week="2024-W02",
            ),
            PairedOutcome(
                key="week-3",
                champion_return_pct=0.0,
                challenger_return_pct=-1.0,
                resolution_week="2024-W03",
            ),
        ]
        duplicated_pairs = [
            PairedOutcome(
                key=f"{pair.key}-{copy}",
                champion_return_pct=pair.champion_return_pct,
                challenger_return_pct=pair.challenger_return_pct,
                resolution_week=pair.resolution_week,
            )
            for pair in base_pairs
            for copy in range(20)
        ]
        base_result = compare_paired(base_pairs, min_pairs=3)
        duplicated_result = compare_paired(duplicated_pairs, min_pairs=40)
        self.assertEqual(base_result.n_resolution_clusters, 3)
        self.assertEqual(duplicated_result.n_resolution_clusters, 3)
        self.assertEqual(duplicated_result.n_pairs_informative, 60)
        self.assertEqual(base_result.diff_ci95_low_pct, duplicated_result.diff_ci95_low_pct)
        self.assertEqual(base_result.diff_ci95_high_pct, duplicated_result.diff_ci95_high_pct)
        self.assertGreater(duplicated_result.mean_diff_pct, 0.0)
        self.assertFalse(duplicated_result.challenger_superior)

    def test_t_critical_values_are_monotone_toward_normal(self) -> None:
        self.assertGreater(t_critical_95(1), t_critical_95(5))
        self.assertGreater(t_critical_95(5), t_critical_95(30))
        self.assertGreaterEqual(t_critical_95(30), t_critical_95(61))
        self.assertEqual(t_critical_95(1000), 1.96)


if __name__ == "__main__":
    unittest.main()
