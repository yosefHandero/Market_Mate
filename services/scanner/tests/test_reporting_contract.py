"""Reporting reads preserve stored identity and count only the named campaign."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import Base
from app.models.scan import EvidenceCampaignORM, PredictionSnapshotORM
from app.services.evidence_campaign import EvidenceCampaignService
from app.services.repository import ScanRepository
import app.services.repository as repository_module
from tests.test_brain_promotion import _runtime, _superior_pairs


class ReportingContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = create_engine(f"sqlite:///{(Path(self.directory.name) / 'reporting.db').as_posix()}")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.settings = Settings(_env_file=None)
        self.repo = ScanRepository()
        self.repo.settings = self.settings
        for name, value in (("SessionLocal", self.sessions), ("engine", self.engine)):
            item = patch.object(repository_module, name, value)
            item.start()
            self.addCleanup(item.stop)
        self.now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
        self.campaign = EvidenceCampaignService(settings=self.settings, session_factory=self.sessions).get_or_create_active_campaign(
            now=self.now,
            effective_policy_id="hybrid_legacy",
            effective_policy_version="hybrid-v4.2",
            effective_decision_fingerprint="saved-fingerprint",
            learned_artifacts_fingerprint="saved-artifact",
            learned_artifacts_json='{"preserved": [1, 2, 3]}',
        )

    def add_prediction(self, name, *, due, campaign=None, role="production", selection="selected", status="pending", asset="stock"):
        with self.sessions() as session:
            session.add(PredictionSnapshotORM(
                run_id=name, ticker=name, asset_type=asset, signal="BUY", entry_price=100,
                range_low=90, range_high=110, generated_at=self.now,
                campaign_id=campaign or self.campaign.campaign_id, decision_role=role,
                status=status, selection_status=selection, resolve_due_at=due,
            ))
            session.commit()

    def test_due_counts_use_recorded_times_and_exclude_other_campaigns_shadow_and_rejections(self):
        self.add_prediction("due", due=self.now - timedelta(seconds=1))
        self.add_prediction("exact", due=self.now, asset="crypto", selection="accepted_outside_top_n")
        self.add_prediction("later", due=self.now + timedelta(days=1))
        self.add_prediction("unknown", due=None)
        self.add_prediction("old", due=self.now, campaign="closed-campaign")
        self.add_prediction("shadow", due=self.now, role="shadow")
        self.add_prediction("rejected", due=self.now, selection="rejected", status="rejected_no_outcome")
        progress = self.repo.get_live_forward_progress(now=self.now)
        self.assertEqual(progress.pending_count, 4)
        self.assertEqual(progress.pending_due_count, 2)
        self.assertEqual(progress.pending_due_unknown_count, 1)
        self.assertEqual(progress.selected_count, 3)
        self.assertEqual(progress.accepted_outside_top_n_count, 1)
        self.assertEqual(progress.rejected_count, 1)
        self.assertEqual([row.pending_due for row in progress.by_asset], [1, 1])
        self.assertEqual(progress.saved_policy_version, "hybrid-v4.2")
        self.assertEqual(progress.saved_decision_fingerprint, "saved-fingerprint")
        self.assertIsNone(progress.runtime_policy_version)
        with self.sessions() as session:
            saved = session.execute(select(EvidenceCampaignORM)).scalar_one()
            self.assertEqual(saved.learned_artifacts_json, '{"preserved": [1, 2, 3]}')
            self.assertEqual(saved.learned_artifacts_fingerprint, "saved-artifact")

    def test_zero_due_is_distinct_from_pending_outcomes(self):
        self.add_prediction("later", due=self.now + timedelta(days=3))
        progress = self.repo.get_live_forward_progress(now=self.now)
        self.assertEqual(progress.pending_count, 1)
        self.assertEqual(progress.pending_due_count, 0)
        self.assertEqual(progress.pending_due_unknown_count, 0)

    def test_proof_preserves_saved_identity_and_labels_runtime_mismatch(self):
        import app.api.public as public_module

        runtime = _runtime(requested="hybrid_legacy", wf_ready=False, pairs={"returns": [], "brier": []})
        walk_forward = SimpleNamespace(get_latest_run_summary=lambda: None)
        with patch.object(public_module, "BrainRuntime", return_value=runtime):
            response = asyncio.run(public_module.get_proof_summary(scan_repository=self.repo, walk_forward_repository=walk_forward))
        progress = response.live_forward
        self.assertEqual(progress.saved_policy_id, "hybrid_legacy")
        self.assertEqual(progress.saved_policy_version, "hybrid-v4.2")
        self.assertEqual(progress.saved_decision_fingerprint, "saved-fingerprint")
        self.assertEqual(progress.runtime_policy_version, runtime.hybrid.policy_version)
        self.assertEqual(progress.runtime_decision_fingerprint, runtime.hybrid.fingerprint())
        self.assertFalse(progress.identity_matches_saved_campaign)
        with self.sessions() as session:
            self.assertEqual(len(session.execute(select(EvidenceCampaignORM)).scalars().all()), 1)

    def test_calibration_counts_are_independent_of_nonzero_returns_and_preserve_gate(self):
        runtime = _runtime(requested="hybrid_legacy", wf_ready=True, pairs={"returns": _superior_pairs(), "brier": []})
        before = runtime.promotion_report()
        response = runtime.promotion_report_response()
        self.assertGreater(response.paired_returns_informative, 0)
        self.assertEqual(response.calibration_eligible_pair_count, 0)
        self.assertEqual(response.calibration_min_pairs, before.paired_brier.min_pairs_required)
        self.assertEqual(response.gates_cleared, before.gates_cleared)
        self.assertEqual([(c.name, c.passed) for c in response.checks], [(c.name, c.passed) for c in before.checks])

    def test_matching_and_unknown_campaign_identity_are_distinct(self):
        import app.api.public as public_module

        runtime = _runtime(requested="hybrid_legacy", wf_ready=False, pairs={"returns": [], "brier": []})
        with self.sessions() as session:
            campaign = session.execute(select(EvidenceCampaignORM)).scalar_one()
            campaign.effective_policy_version = runtime.hybrid.policy_version
            campaign.effective_decision_fingerprint = runtime.hybrid.fingerprint()
            session.commit()
        walk_forward = SimpleNamespace(get_latest_run_summary=lambda: None)
        with patch.object(public_module, "BrainRuntime", return_value=runtime):
            matched = asyncio.run(public_module.get_proof_summary(scan_repository=self.repo, walk_forward_repository=walk_forward))
            self.assertTrue(matched.live_forward.identity_matches_saved_campaign)
            with self.sessions() as session:
                campaign = session.execute(select(EvidenceCampaignORM)).scalar_one()
                campaign.effective_decision_fingerprint = None
                session.commit()
            unknown = asyncio.run(public_module.get_proof_summary(scan_repository=self.repo, walk_forward_repository=walk_forward))
            self.assertIsNone(unknown.live_forward.identity_matches_saved_campaign)
            self.assertIsNone(unknown.live_forward.saved_decision_fingerprint)
            self.assertEqual(unknown.live_forward.runtime_decision_fingerprint, runtime.hybrid.fingerprint())


if __name__ == "__main__":
    unittest.main()
