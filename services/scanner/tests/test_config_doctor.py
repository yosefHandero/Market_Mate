import tempfile
import unittest
from pathlib import Path

from app.config_doctor import diagnose_env_file


class ConfigDoctorTests(unittest.TestCase):
    def test_detects_duplicate_and_blank_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "ALPACA_API_KEY=\nALPACA_API_KEY=abc123\nUNUSED_KEY=1\n",
                encoding="utf-8",
            )
            report = diagnose_env_file(env_path)
            self.assertIn("ALPACA_API_KEY", report.duplicate_keys)
            statuses = {item.key: item.status for item in report.keys}
            self.assertIn("duplicate", statuses["ALPACA_API_KEY"])

    def test_duplicate_present_and_blank_is_likely_misconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "ALPACA_API_KEY=\nALPACA_API_KEY=real-value\n",
                encoding="utf-8",
            )
            report = diagnose_env_file(env_path)
            self.assertIn("ALPACA_API_KEY", report.likely_misconfigured)

    def test_polygon_key_is_not_marked_unused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("POLYGON_API_KEY=present-value\n", encoding="utf-8")
            report = diagnose_env_file(env_path)
            self.assertNotIn("POLYGON_API_KEY", report.unused_keys)

    def test_uppercase_settings_keys_are_not_marked_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "ALLOW_LIVE_TRADING=false\n"
                "EXECUTION_ENABLED=false\n"
                "PUBLIC_READ_ACCESS_ENABLED=true\n",
                encoding="utf-8",
            )
            report = diagnose_env_file(env_path)
            statuses = {item.key: item.status for item in report.keys}
            self.assertNotIn("unknown_to_scanner", statuses["ALLOW_LIVE_TRADING"])
            self.assertNotIn("unknown_to_scanner", statuses["EXECUTION_ENABLED"])
            self.assertNotIn("unknown_to_scanner", statuses["PUBLIC_READ_ACCESS_ENABLED"])

    def test_legacy_news_threshold_is_marked_unused_not_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("NEWS_CHECK_SCORE_THRESHOLD=70\n", encoding="utf-8")
            report = diagnose_env_file(env_path)
            statuses = {item.key: item.status for item in report.keys}
            self.assertIn("NEWS_CHECK_SCORE_THRESHOLD", report.unused_keys)
            self.assertIn("unused", statuses["NEWS_CHECK_SCORE_THRESHOLD"])
            self.assertNotIn("unknown_to_scanner", statuses["NEWS_CHECK_SCORE_THRESHOLD"])

    def test_removed_live_rollout_caps_are_marked_unused_not_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "LIVE_TRADING_MAX_NOTIONAL=100\nLIVE_TRADING_MAX_QTY=1\n",
                encoding="utf-8",
            )
            report = diagnose_env_file(env_path)
            statuses = {item.key: item.status for item in report.keys}
            self.assertIn("LIVE_TRADING_MAX_NOTIONAL", report.unused_keys)
            self.assertIn("LIVE_TRADING_MAX_QTY", report.unused_keys)
            self.assertIn("unused", statuses["LIVE_TRADING_MAX_NOTIONAL"])
            self.assertIn("unused", statuses["LIVE_TRADING_MAX_QTY"])
            self.assertNotIn("unknown_to_scanner", statuses["LIVE_TRADING_MAX_NOTIONAL"])
            self.assertNotIn("unknown_to_scanner", statuses["LIVE_TRADING_MAX_QTY"])


if __name__ == "__main__":
    unittest.main()
