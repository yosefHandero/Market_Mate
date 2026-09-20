"""Promotion report: the only way a challenger may become champion.

Gates (all required, no calendar shortcut):
1. If the challenger is replayable, its latest walk-forward holdout verdict
   must pass (``walk_forward_holdout_passed``).
2. Live shadow vs champion paired comparison on identical scan opportunities
   must have enough informative pairs and a resolution-week clustered 95% CI
   on the after-friction return difference entirely above zero.
3. Paired Brier comparison (stored as negated Brier so higher is better) must
   not find the challenger significantly worse under the same clustered
   inference discipline.

Paper-only reduces deployment risk, not evidentiary uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.brain.evaluation.paired import PairedComparisonResult, PairedOutcome, compare_paired
from app.brain.identity import RULER_VERSION, ruler_fingerprint


@dataclass(frozen=True)
class PromotionCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PromotionReport:
    champion_policy_id: str
    challenger_policy_id: str
    challenger_replayable: bool
    ruler_version: str
    ruler_fingerprint: str
    champion_decision_fingerprint: str
    challenger_decision_fingerprint: str
    walk_forward_holdout_passed: bool
    paired_returns: PairedComparisonResult
    paired_brier: PairedComparisonResult | None
    checks: tuple[PromotionCheck, ...]
    gates_cleared: bool
    summary: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "champion_policy_id": self.champion_policy_id,
            "challenger_policy_id": self.challenger_policy_id,
            "challenger_replayable": self.challenger_replayable,
            "ruler_version": self.ruler_version,
            "ruler_fingerprint": self.ruler_fingerprint,
            "champion_decision_fingerprint": self.champion_decision_fingerprint,
            "challenger_decision_fingerprint": self.challenger_decision_fingerprint,
            "walk_forward_holdout_passed": self.walk_forward_holdout_passed,
            "paired_returns": self.paired_returns.__dict__,
            "paired_brier": self.paired_brier.__dict__ if self.paired_brier is not None else None,
            "checks": [check.__dict__ for check in self.checks],
            "gates_cleared": self.gates_cleared,
            "summary": self.summary,
            "diagnostics": self.diagnostics,
        }


def build_promotion_report(
    *,
    champion_policy_id: str,
    challenger_policy_id: str,
    challenger_replayable: bool,
    champion_decision_fingerprint: str,
    challenger_decision_fingerprint: str,
    ruler_config_payload: dict[str, Any],
    walk_forward_holdout_passed: bool,
    return_pairs: list[PairedOutcome],
    brier_pairs: list[PairedOutcome] | None = None,
    min_pairs: int = 40,
    diagnostics: dict[str, Any] | None = None,
) -> PromotionReport:
    paired_returns = compare_paired(return_pairs, min_pairs=min_pairs)
    paired_brier = (
        compare_paired(brier_pairs, min_pairs=min_pairs) if brier_pairs is not None else None
    )
    wf_ok = (not challenger_replayable) or walk_forward_holdout_passed
    calibration_ok = paired_brier is None or not paired_brier.challenger_inferior
    checks = (
        PromotionCheck(
            name="walk_forward_holdout",
            passed=wf_ok,
            detail=(
                "Walk-forward holdout verdict passed."
                if walk_forward_holdout_passed
                else (
                    "Challenger is not replayable; walk-forward holdout is not required."
                    if not challenger_replayable
                    else "Walk-forward holdout verdict has not passed."
                )
            ),
        ),
        PromotionCheck(
            name="paired_live_shadow_returns",
            passed=paired_returns.challenger_superior,
            detail=paired_returns.summary,
        ),
        PromotionCheck(
            name="paired_calibration_not_worse",
            passed=calibration_ok,
            detail=(
                paired_brier.summary
                if paired_brier is not None
                else "No paired Brier sample; calibration gate deferred."
            ),
        ),
    )
    gates_cleared = all(check.passed for check in checks)
    if gates_cleared:
        summary = (
            f"Challenger {challenger_policy_id} clears promotion gates versus "
            f"champion {champion_policy_id}."
        )
    else:
        failed = [check.name for check in checks if not check.passed]
        summary = (
            f"Challenger {challenger_policy_id} does not clear promotion gates "
            f"({', '.join(failed)})."
        )
    return PromotionReport(
        champion_policy_id=champion_policy_id,
        challenger_policy_id=challenger_policy_id,
        challenger_replayable=challenger_replayable,
        ruler_version=RULER_VERSION,
        ruler_fingerprint=ruler_fingerprint(config_payload=ruler_config_payload),
        champion_decision_fingerprint=champion_decision_fingerprint,
        challenger_decision_fingerprint=challenger_decision_fingerprint,
        walk_forward_holdout_passed=walk_forward_holdout_passed,
        paired_returns=paired_returns,
        paired_brier=paired_brier,
        checks=checks,
        gates_cleared=gates_cleared,
        summary=summary,
        diagnostics=diagnostics or {},
    )
