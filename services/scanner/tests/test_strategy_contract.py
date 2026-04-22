import unittest

from app.core.strategy_contract import (
    build_strategy_evaluation_metadata,
    determine_execution_eligibility,
    get_current_strategy_contract,
)


class StrategyContractTests(unittest.TestCase):
    def test_current_contract_exposes_explicit_signal_meaning(self) -> None:
        contract = get_current_strategy_contract()

        self.assertEqual(contract.strategy_id, "scanner-directional")
        self.assertEqual(contract.strategy_version, "v4.1-integrated")
        self.assertEqual(contract.primary_holding_horizon, "1h")
        self.assertIn("HOLD means abstain", contract.hold_definition.operational_meaning)
        self.assertIn("binance", contract.supportive_provider_inputs)

    def test_execution_eligibility_blocks_on_critical_provider_state(self) -> None:
        eligibility = determine_execution_eligibility(
            signal="BUY",
            gate_passed=True,
            provider_status="critical",
            evidence_quality="moderate",
        )

        self.assertEqual(eligibility, "blocked")

    def test_strategy_metadata_separates_confidence_from_evidence_quality(self) -> None:
        metadata = build_strategy_evaluation_metadata(
            signal="BUY",
            gate_passed=True,
            calibration_source="score_band",
            data_quality="ok",
            provider_status="ok",
            provider_warnings=[],
        )

        self.assertEqual(metadata.confidence_label, "calibrated_confidence")
        self.assertEqual(metadata.execution_eligibility, "eligible")
        self.assertEqual(metadata.evidence_quality, "high")


if __name__ == "__main__":
    unittest.main()
