"""Frozen wrap of the current hybrid (intraday score + overlay + weekly gate).

Not replayable from daily bars: it needs session features the host extracts
from 5-minute bars and live provider context. The host fills
``SymbolSnapshot.session`` after running the existing analyze path; this
policy only maps those precomputed fields onto a ``BrainDecision`` so the
ruler can compare it to replayable challengers on the same scans.

SELL/HOLD session signals become ABSTAIN (BUY-only product).
"""

from __future__ import annotations

from typing import Any

from app.brain.config import HybridPolicyConfig
from app.brain.contracts import BrainDecision, EvidenceBasis, ExitPlan, MarketSnapshot, SymbolSnapshot
from app.brain.identity import decision_fingerprint

HYBRID_POLICY_ID = "hybrid_legacy"
HYBRID_POLICY_VERSION = "hybrid-v4.2"


class HybridLegacyPolicy:
    policy_id = HYBRID_POLICY_ID
    policy_version = HYBRID_POLICY_VERSION
    replayable = False

    def __init__(
        self,
        *,
        config: HybridPolicyConfig | None = None,
        learned_artifacts_fingerprint: str | None = None,
    ) -> None:
        self.config = config or HybridPolicyConfig()
        self.learned_artifacts_fingerprint = learned_artifacts_fingerprint

    def config_payload(self) -> dict[str, Any]:
        payload = self.config.payload()
        payload["scoring_version"] = "v4.2-budget-normalized"
        return payload

    def fingerprint(self) -> str:
        learned_artifacts = None
        if self.learned_artifacts_fingerprint:
            learned_artifacts = {
                "session_weekly_inputs": self.learned_artifacts_fingerprint,
            }
        return decision_fingerprint(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            config_payload=self.config_payload(),
            learned_artifacts=learned_artifacts,
        )

    def decide_all(self, snapshot: MarketSnapshot) -> list[BrainDecision]:
        return [self._decide_symbol(symbol, snapshot) for symbol in snapshot.symbols]

    def _decide_symbol(self, symbol: SymbolSnapshot, snapshot: MarketSnapshot) -> BrainDecision:
        session = symbol.session or {}
        signal = str(session.get("decision_signal") or "").upper()
        price = float(session.get("price") or 0.0)
        p_up = session.get("calibrated_confidence")
        if p_up is None:
            p_up = session.get("upside_probability_pct")
        ev = session.get("expected_value_pct")
        weekly_bias = session.get("weekly_directional_bias")
        if signal != "BUY" and not (
            weekly_bias == "bullish" and session.get("upside_probability_pct") is not None
        ):
            reason = "insufficient_session_features" if not session else "not_buy_signal"
            return BrainDecision(
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                decision_fingerprint=self.fingerprint(),
                symbol=symbol.symbol,
                asset_type=symbol.asset_type,
                as_of=snapshot.as_of,
                action="ABSTAIN",
                reasons=(reason,),
                pattern_name=session.get("pattern_name"),
                diagnostics={"session_signal": signal or None},
            )

        exit_plan = None
        if price > 0 and (session.get("target_price") or session.get("stop_price")):
            exit_plan = ExitPlan(
                entry_price=price,
                target_price=session.get("target_price"),
                stop_price=session.get("stop_price"),
                horizon_days=int(session.get("horizon_days") or 7),
            )
        try:
            p_up_value = float(p_up) if p_up is not None else None
        except (TypeError, ValueError):
            p_up_value = None
        try:
            ev_value = float(ev) if ev is not None else None
        except (TypeError, ValueError):
            ev_value = None
        return BrainDecision(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            decision_fingerprint=self.fingerprint(),
            symbol=symbol.symbol,
            asset_type=symbol.asset_type,
            as_of=snapshot.as_of,
            action="BUY",
            p_up_calibrated=p_up_value,
            expected_value_pct=ev_value,
            exit_plan=exit_plan,
            evidence_basis=EvidenceBasis(
                basis=str(session.get("evidence_basis") or "insufficient"),
                historical_hit_rate_pct=session.get("historical_hit_rate_pct"),
                historical_avg_return_pct=session.get("historical_avg_return_pct"),
            ),
            reasons=(),
            pattern_name=session.get("pattern_name"),
            probability_methodology=str(session.get("calibration_source") or "hybrid_overlay"),
            diagnostics={
                "session_signal": "BUY",
                "raw_score": session.get("score"),
                "gate_passed": session.get("gate_passed"),
            },
        )
