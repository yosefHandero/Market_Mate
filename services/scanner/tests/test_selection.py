import unittest
from datetime import datetime, timezone

from app.config import Settings
from app.core.selection import apply_top_pick_selection, select_top_picks
from app.schemas import ScanResult


def _result(
    *,
    ticker: str,
    asset_type: str = "stock",
    score: float,
    decision_signal: str = "BUY",
    gate_passed: bool = True,
    provider_status: str = "ok",
    execution_eligibility: str = "eligible",
    evidence_quality: str = "high",
    recommended_action: str = "dry_run",
    bar_age_minutes: float = 5.0,
) -> ScanResult:
    return ScanResult(
        ticker=ticker,
        asset_type=asset_type,
        score=score,
        raw_score=score,
        calibrated_confidence=score,
        evidence_quality=evidence_quality,
        execution_eligibility=execution_eligibility,
        decision_signal=decision_signal,
        recommended_action=recommended_action,
        explanation="fixture",
        price=100.0,
        price_change_pct=1.0,
        relative_volume=1.0,
        sentiment_score=0.1,
        filing_flag=False,
        breakout_flag=True,
        market_status="bullish",
        sector_strength_score=0.5,
        gate_passed=gate_passed,
        provider_status=provider_status,
        bar_age_minutes=bar_age_minutes,
        created_at=datetime.now(timezone.utc),
    )


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(health_max_stale_minutes=30)

    def test_selects_top_three_per_asset_type_by_readiness(self) -> None:
        results = [
            _result(ticker="NVDA", score=90.0),
            _result(ticker="AMD", score=70.0, evidence_quality="moderate", recommended_action="dry_run"),
            _result(ticker="INTC", score=60.0, evidence_quality="low", recommended_action="preview"),
            _result(ticker="IBM", score=50.0, gate_passed=False, recommended_action="blocked"),
            _result(ticker="BTC/USD", asset_type="crypto", score=88.0),
            _result(ticker="ETH/USD", asset_type="crypto", score=75.0),
            _result(ticker="SOL/USD", asset_type="crypto", score=65.0),
            _result(ticker="DOGE/USD", asset_type="crypto", score=40.0, gate_passed=False),
        ]
        selection = select_top_picks(results, settings=self.settings, limit=3)
        self.assertEqual([row.ticker for row in selection.stocks], ["NVDA", "AMD", "INTC"])
        self.assertEqual([row.ticker for row in selection.crypto], ["BTC/USD", "ETH/USD", "SOL/USD"])

    def test_apply_top_pick_selection_sets_persisted_fields(self) -> None:
        results = [
            _result(ticker="NVDA", score=90.0),
            _result(ticker="AMD", score=70.0),
            _result(ticker="BTC/USD", asset_type="crypto", score=88.0),
        ]
        enriched = apply_top_pick_selection(results, settings=self.settings, limit=3)
        nvda = next(row for row in enriched if row.ticker == "NVDA")
        self.assertTrue(nvda.is_top_pick)
        self.assertEqual(nvda.selection_rank, 1)
        self.assertGreater(nvda.readiness_score, 0)
        self.assertEqual(nvda.readiness_band, "high")

    def test_excludes_hold_and_sell_from_top_picks(self) -> None:
        results = [
            _result(ticker="NVDA", score=90.0, decision_signal="BUY"),
            _result(ticker="AMD", score=95.0, decision_signal="SELL"),
            _result(ticker="INTC", score=94.0, decision_signal="HOLD"),
        ]
        selection = select_top_picks(results, settings=self.settings, limit=5)
        picked = [row.ticker for row in selection.stocks]
        self.assertIn("NVDA", picked)
        self.assertNotIn("AMD", picked)
        self.assertNotIn("INTC", picked)

    def test_respects_configurable_limit_up_to_five(self) -> None:
        results = [
            _result(ticker=f"T{i}", score=90.0 - i)
            for i in range(8)
        ]
        selection = select_top_picks(results, settings=self.settings, limit=5)
        self.assertEqual(len(selection.stocks), 5)

    def test_effective_top_pick_limit_clamped_between_three_and_five(self) -> None:
        self.assertEqual(Settings(top_pick_limit=1).effective_top_pick_limit, 3)
        self.assertEqual(Settings(top_pick_limit=4).effective_top_pick_limit, 4)
        self.assertEqual(Settings(top_pick_limit=9).effective_top_pick_limit, 5)

    def test_hard_stopped_row_excluded(self) -> None:
        results = [
            _result(ticker="NVDA", score=90.0),
            _result(
                ticker="AMD",
                score=99.0,
                provider_status="critical",
                bar_age_minutes=6000.0,
            ),
        ]
        selection = select_top_picks(results, settings=self.settings, limit=5)
        picked = [row.ticker for row in selection.stocks]
        self.assertIn("NVDA", picked)
        self.assertNotIn("AMD", picked)


if __name__ == "__main__":
    unittest.main()
