import unittest
from datetime import datetime, timezone

from app.config import Settings
from app.brain.gates import buy_candidate_rank_score, is_buy_candidate, row_is_buy_candidate
from app.core.ranking import actionability_sort_tier, display_sort_key
from app.schemas import ScanResult, WeeklyPatternPrediction


def _buy_row(
    *,
    ticker: str,
    upside: float | None,
    confidence: float,
    sample_size: int,
    provenance: str,
    data_quality: str = "ok",
) -> ScanResult:
    weekly = WeeklyPatternPrediction(
        pattern_name="breakout_20d_high",
        directional_bias="bullish",
        range_low=97.0,
        range_high=110.0,
        upside_probability_pct=upside,
        sample_size=sample_size,
        evidence_basis=provenance,
        data_quality=data_quality,
    )
    return ScanResult(
        ticker=ticker,
        score=confidence,
        raw_score=confidence,
        calibrated_confidence=confidence,
        confidence_score=confidence,
        upside_probability_pct=upside,
        evidence_provenance=provenance,
        weekly_prediction=weekly,
        decision_signal="BUY",
        explanation="fixture",
        price=100.0,
        price_change_pct=1.0,
        relative_volume=1.0,
        sentiment_score=0.1,
        filing_flag=False,
        breakout_flag=True,
        market_status="bullish",
        sector_strength_score=0.5,
        gate_passed=True,
        provider_status="ok",
        execution_eligibility="eligible",
        bar_age_minutes=5.0,
        data_quality=data_quality,
        created_at=datetime.now(timezone.utc),
    )


class RankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(health_max_stale_minutes=30)

    def test_critical_provider_ranks_below_clean_actionable(self) -> None:
        clean = ScanResult(
            ticker="NVDA",
            score=80,
            explanation="clean",
            price=100,
            price_change_pct=2,
            relative_volume=1.5,
            sentiment_score=0.2,
            filing_flag=False,
            breakout_flag=True,
            market_status="bullish",
            sector_strength_score=1,
            decision_signal="BUY",
            gate_passed=True,
            provider_status="ok",
            execution_eligibility="eligible",
            bar_age_minutes=5,
            created_at=datetime.now(timezone.utc),
        )
        critical = clean.model_copy(
            update={
                "ticker": "AMD",
                "score": 90,
                "provider_status": "critical",
                "execution_eligibility": "blocked",
            }
        )
        self.assertLess(
            actionability_sort_tier(
                clean,
                settings=self.settings,
                resolve_signal=lambda row: row.decision_signal,
                scan_result=clean,
            ),
            actionability_sort_tier(
                critical,
                settings=self.settings,
                resolve_signal=lambda row: row.decision_signal,
                scan_result=critical,
            ),
        )
        self.assertLess(
            display_sort_key(
                clean,
                settings=self.settings,
                resolve_signal=lambda row: row.decision_signal,
                scan_result=clean,
            ),
            display_sort_key(
                critical,
                settings=self.settings,
                resolve_signal=lambda row: row.decision_signal,
                scan_result=critical,
            ),
        )

    def test_higher_upside_ranks_higher(self) -> None:
        strong = _buy_row(ticker="A", upside=80.0, confidence=60.0, sample_size=50, provenance="historical_only")
        weak = _buy_row(ticker="B", upside=55.0, confidence=60.0, sample_size=50, provenance="historical_only")
        self.assertGreater(
            buy_candidate_rank_score(strong, settings=self.settings),
            buy_candidate_rank_score(weak, settings=self.settings),
        )

    def test_live_forward_provenance_outranks_historical(self) -> None:
        live = _buy_row(ticker="A", upside=70.0, confidence=60.0, sample_size=50, provenance="live_forward_proven")
        hist = _buy_row(ticker="B", upside=70.0, confidence=60.0, sample_size=50, provenance="historical_only")
        self.assertGreater(
            buy_candidate_rank_score(live, settings=self.settings),
            buy_candidate_rank_score(hist, settings=self.settings),
        )

    def test_larger_sample_size_ranks_higher(self) -> None:
        thick = _buy_row(ticker="A", upside=70.0, confidence=60.0, sample_size=200, provenance="historical_only")
        thin = _buy_row(ticker="B", upside=70.0, confidence=60.0, sample_size=2, provenance="historical_only")
        self.assertGreater(
            buy_candidate_rank_score(thick, settings=self.settings),
            buy_candidate_rank_score(thin, settings=self.settings),
        )

    def test_is_buy_candidate_excludes_sell(self) -> None:
        self.assertFalse(
            is_buy_candidate(decision_signal="SELL", weekly_directional_bias="bullish", upside_probability_pct=80.0)
        )
        self.assertTrue(
            is_buy_candidate(decision_signal="BUY", weekly_directional_bias="neutral", upside_probability_pct=None)
        )
        self.assertTrue(
            is_buy_candidate(decision_signal="HOLD", weekly_directional_bias="bullish", upside_probability_pct=60.0)
        )
        self.assertFalse(
            is_buy_candidate(decision_signal="HOLD", weekly_directional_bias="neutral", upside_probability_pct=None)
        )

    def test_row_is_buy_candidate(self) -> None:
        self.assertTrue(row_is_buy_candidate(_buy_row(ticker="A", upside=70.0, confidence=60.0, sample_size=50, provenance="historical_only")))


if __name__ == "__main__":
    unittest.main()
