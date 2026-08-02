from __future__ import annotations

import unittest

from app.core.evidence_contract import (
    EVIDENCE_TRACK_KEYS,
    LIVE_FORWARD,
    REAL_MONEY_PILOT,
    evidence_track_manifest,
    track_for_sample_source,
    track_for_walk_forward_track,
)


class EvidenceContractTests(unittest.TestCase):
    def test_manifest_lists_all_six_tracks_in_order(self) -> None:
        manifest = evidence_track_manifest()
        self.assertEqual([t["key"] for t in manifest], list(EVIDENCE_TRACK_KEYS))
        self.assertEqual(len(manifest), 6)
        for track in manifest:
            self.assertTrue(track["label"])
            self.assertTrue(track["description"])
            self.assertIn("is_forward", track)
            self.assertIn("counts_toward_real_money", track)

    def test_only_forward_untouched_tracks_count_toward_real_money(self) -> None:
        counting = {
            t["key"] for t in evidence_track_manifest() if t["counts_toward_real_money"]
        }
        # Only live-forward and the future real-money pilot may graduate a pilot.
        self.assertEqual(counting, {LIVE_FORWARD, REAL_MONEY_PILOT})

    def test_sample_source_mapping(self) -> None:
        self.assertEqual(track_for_sample_source("historical"), "walk_forward_research")
        self.assertEqual(track_for_sample_source("backfilled_replay"), "historical_replay")
        self.assertEqual(track_for_sample_source("live_paper_forward"), LIVE_FORWARD)
        # out_of_sample is a held-out subset of live-forward evidence.
        self.assertEqual(track_for_sample_source("out_of_sample"), LIVE_FORWARD)
        self.assertIsNone(track_for_sample_source("nonsense"))
        self.assertIsNone(track_for_sample_source(None))

    def test_walk_forward_track_mapping(self) -> None:
        self.assertEqual(track_for_walk_forward_track("research"), "walk_forward_research")
        # Validation is the tuning-side segment; same contract track as research.
        self.assertEqual(track_for_walk_forward_track("validation"), "walk_forward_research")
        self.assertEqual(track_for_walk_forward_track("holdout"), "walk_forward_holdout")
        self.assertIsNone(track_for_walk_forward_track("unknown"))


if __name__ == "__main__":
    unittest.main()
