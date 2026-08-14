import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.db_integrity import record_hash_for_snapshot
from app.services.evidence_campaign import CampaignProvenance
from app.services.repository import ScanRepository


class SnapshotProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = ScanRepository()
        self.campaign = CampaignProvenance(
            campaign_id="camp-abc123",
            strategy_version="v-test",
            feature_version="feat-test",
            config_fingerprint="fp-test",
            code_commit="commit-test",
        )
        self.generated_at = datetime(2026, 7, 1, tzinfo=timezone.utc)

    def _base_kwargs(self, asset_type: str = "stock") -> dict:
        return {
            "run_id": "run-1",
            "ticker": "AAPL",
            "asset_type": asset_type,
            "signal": "BUY",
            "entry_price": 100.0,
            "range_low": 95.0,
            "range_high": 110.0,
            "horizon": "1w",
            "generated_at": self.generated_at,
        }

    def test_stamps_full_provenance_and_record_hash(self) -> None:
        kwargs = self._base_kwargs()
        result = SimpleNamespace(
            asset_type="stock",
            created_at=self.generated_at,
            selection_rank=1,
            is_top_pick=True,
            bar_as_of=self.generated_at,
        )
        self.repo._apply_snapshot_provenance(
            kwargs,
            result=result,
            campaign=self.campaign,
            selection_status="selected",
            rejection_reason=None,
        )

        self.assertEqual(kwargs["campaign_id"], "camp-abc123")
        self.assertEqual(kwargs["config_fingerprint"], "fp-test")
        self.assertEqual(kwargs["feature_version"], "feat-test")
        self.assertEqual(kwargs["provider_source"], "alpaca")
        self.assertEqual(kwargs["selection_status"], "selected")
        self.assertEqual(kwargs["candidate_rank"], 1)
        self.assertIsNone(kwargs["rejection_reason"])
        self.assertFalse(kwargs["resolved_late"])
        self.assertGreater(kwargs["resolve_due_at"], self.generated_at)
        self.assertGreater(kwargs["expected_friction_bps"], 0.0)
        # record_hash matches an independent recomputation over the immutable core.
        self.assertEqual(kwargs["record_hash"], record_hash_for_snapshot(kwargs))

    def test_crypto_falls_back_to_coinbase_when_no_price_source(self) -> None:
        # When the scan did not report a concrete price_source, crypto still
        # defaults to the coinbase label (backward-compatible fallback).
        kwargs = self._base_kwargs(asset_type="crypto")
        result = SimpleNamespace(
            asset_type="crypto",
            created_at=self.generated_at,
            selection_rank=None,
            is_top_pick=False,
            bar_as_of=None,
        )
        self.repo._apply_snapshot_provenance(
            kwargs,
            result=result,
            campaign=self.campaign,
            selection_status="accepted_outside_top_n",
            rejection_reason=None,
        )
        self.assertEqual(kwargs["provider_source"], "coinbase")
        self.assertEqual(kwargs["selection_status"], "accepted_outside_top_n")
        self.assertEqual(
            kwargs["expected_friction_bps"], self.repo._expected_friction_bps("crypto")
        )

    def test_provider_source_records_actual_price_source(self) -> None:
        # A crypto scan whose bars actually came from Alpaca must be stamped
        # "alpaca", not the old hardcoded "coinbase"; the real source wins.
        kwargs = self._base_kwargs(asset_type="crypto")
        result = SimpleNamespace(
            asset_type="crypto",
            created_at=self.generated_at,
            selection_rank=2,
            is_top_pick=False,
            bar_as_of=None,
            price_source="alpaca",
        )
        self.repo._apply_snapshot_provenance(
            kwargs,
            result=result,
            campaign=self.campaign,
            selection_status="accepted_outside_top_n",
            rejection_reason=None,
        )
        self.assertEqual(kwargs["provider_source"], "alpaca")

        ws_kwargs = self._base_kwargs(asset_type="crypto")
        ws_result = SimpleNamespace(
            asset_type="crypto",
            created_at=self.generated_at,
            selection_rank=1,
            is_top_pick=True,
            bar_as_of=None,
            price_source="coinbase_ws",
        )
        self.repo._apply_snapshot_provenance(
            ws_kwargs,
            result=ws_result,
            campaign=self.campaign,
            selection_status="selected",
            rejection_reason=None,
        )
        self.assertEqual(ws_kwargs["provider_source"], "coinbase_ws")

    def test_record_hash_changes_when_core_field_changes(self) -> None:
        base = self._base_kwargs()
        base.update(
            {
                "campaign_id": "camp-abc123",
                "config_fingerprint": "fp-test",
                "strategy_version": "v-test",
                "feature_version": "feat-test",
                "candidate_rank": 1,
                "selection_status": "selected",
                "rejection_reason": None,
            }
        )
        original = record_hash_for_snapshot(base)
        tampered = dict(base)
        tampered["entry_price"] = 101.0
        self.assertNotEqual(original, record_hash_for_snapshot(tampered))

    def test_record_hash_treats_naive_generated_at_as_utc(self) -> None:
        from datetime import timezone

        base = self._base_kwargs()
        aware = dict(base)
        aware["generated_at"] = base["generated_at"].replace(tzinfo=timezone.utc)
        naive = dict(base)
        naive["generated_at"] = base["generated_at"].replace(tzinfo=None)
        self.assertEqual(record_hash_for_snapshot(aware), record_hash_for_snapshot(naive))


if __name__ == "__main__":
    unittest.main()
