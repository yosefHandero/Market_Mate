import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import Base
from app.models.scan import EvidenceCampaignORM
from app.services.evidence_campaign import (
    EvidenceCampaignService,
    campaign_config_fingerprint,
)


class EvidenceCampaignServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = Path(self._temp_dir.name) / "scanner.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        Base.metadata.create_all(self.engine)
        # Dispose the engine before the temp dir is removed so Windows releases the
        # SQLite file handle (addCleanup is LIFO, so this runs before cleanup()).
        self.addCleanup(self.engine.dispose)
        self.settings = get_settings().model_copy(deep=True)

    def _service(self) -> EvidenceCampaignService:
        return EvidenceCampaignService(
            settings=self.settings, session_factory=self.SessionLocal
        )

    def _campaign_count(self) -> int:
        with self.SessionLocal() as session:
            return len(session.execute(select(EvidenceCampaignORM)).scalars().all())

    def test_creates_single_active_campaign_and_reuses_it(self) -> None:
        service = self._service()
        first = service.get_or_create_active_campaign()
        second = service.get_or_create_active_campaign()

        self.assertEqual(first.campaign_id, second.campaign_id)
        self.assertEqual(self._campaign_count(), 1)
        self.assertTrue(first.config_fingerprint)
        self.assertTrue(first.campaign_id.startswith("camp-"))

    def test_evidence_relevant_change_rotates_campaign(self) -> None:
        service = self._service()
        first = service.get_or_create_active_campaign()

        # Mutate an evidence-relevant setting -> fingerprint changes -> rotation.
        self.settings.signal_buy_threshold = self.settings.signal_buy_threshold + 5.0
        rotated = self._service().get_or_create_active_campaign()

        self.assertNotEqual(first.campaign_id, rotated.campaign_id)
        self.assertNotEqual(first.config_fingerprint, rotated.config_fingerprint)
        self.assertEqual(self._campaign_count(), 2)

        with self.SessionLocal() as session:
            rows = session.execute(select(EvidenceCampaignORM)).scalars().all()
            statuses = {row.campaign_id: (row.status, row.close_reason) for row in rows}
        self.assertEqual(statuses[first.campaign_id], ("closed", "config_change"))
        self.assertEqual(statuses[rotated.campaign_id][0], "active")

    def test_fingerprint_is_stable_for_same_settings(self) -> None:
        self.assertEqual(
            campaign_config_fingerprint(self.settings),
            campaign_config_fingerprint(self.settings.model_copy(deep=True)),
        )


if __name__ == "__main__":
    unittest.main()
