import unittest

from app.core.confidence import compute_confidence_overlay
from app.provider_models import (
    BinanceMicrostructureSnapshot,
    BreadthSnapshot,
    DeribitPositioningSnapshot,
    FREDMacroSnapshot,
)
from app.schemas import OptionsFlowSnapshot


class ConfidenceOverlayTests(unittest.TestCase):
    def test_crypto_overlay_adds_review_flag_when_crowding_is_extreme(self) -> None:
        overlay = compute_confidence_overlay(
            asset_type="crypto",
            decision_signal="BUY",
            base_confidence=70.0,
            market_status="bullish",
            sentiment_score=0.0,
            catalyst_score=0.0,
            options_snapshot=OptionsFlowSnapshot(summary="n/a"),
            provider_status="ok",
            binance_snapshot=BinanceMicrostructureSnapshot(
                source="binance",
                available=True,
                aggressor_pressure=0.2,
                book_imbalance=0.15,
                spread_bps=4.0,
            ),
            deribit_snapshot=DeribitPositioningSnapshot(
                source="deribit",
                available=True,
                crowding_score=-0.8,
            ),
        )

        self.assertIn("crypto_crowding_extreme", overlay.review_flags)
        self.assertLess(overlay.adjusted_confidence, 70.0)

    def test_breadth_and_macro_can_support_confidence_without_changing_direction(self) -> None:
        overlay = compute_confidence_overlay(
            asset_type="stock",
            decision_signal="BUY",
            base_confidence=64.0,
            market_status="bullish",
            sentiment_score=0.3,
            catalyst_score=0.4,
            options_snapshot=OptionsFlowSnapshot(summary="supportive", bullish_score=8.0, bearish_score=2.0),
            provider_status="ok",
            fred_snapshot=FREDMacroSnapshot(source="fred", available=True, regime="risk_on"),
            breadth_snapshot=BreadthSnapshot(
                source="internal_breadth",
                available=True,
                buy_balance=68.0,
                sell_balance=22.0,
            ),
        )

        self.assertGreater(overlay.adjusted_confidence, 64.0)
        self.assertIn("internal_breadth_support", overlay.reasons)


if __name__ == "__main__":
    unittest.main()
