"""Canonical automation intent state machine (paper loop, dry-run only).

Terminal states end all execution paths. Non-terminal states must eventually
reach a terminal via success, gate block, budget block, retry cap, or operator-visible failure.

Allowed transitions (summary; enforced in AutomationService + AutomationRepository.claim_intent):

- pending -> claimed -> placing -> dry_run_complete | blocked_by_gate | failed_retryable | failed_terminal
- pending -> shadowed | blocked_by_* | circuit_open | stale_signal | no_* (terminal or pre-exec terminal)
- failed_retryable -> claimed -> ... (only if attempt_count < max_place_attempts)
- blocked_by_budget | circuit_open -> claimed -> ... (recovery) when next_retry due and budgets allow
- claimed | placing (stale claim) -> claimed -> placing -> ... (recovery)

Strict rule: never call place() when attempt_count >= max_place_attempts.
"""

from __future__ import annotations

# Terminal: no further automation execution for this intent without manual DB intervention.
AUTOMATION_INTENT_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "shadowed",
        "dry_run_complete",
        "blocked_by_gate",
        "failed_terminal",
        "stale_signal",
        "no_meaningful_delta",
        "no_open_position",
    }
)

# Recoverable / may transition toward another place() attempt (subject to caps and breaker).
AUTOMATION_INTENT_ACTIVE_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "claimed",
        "placing",
        "failed_retryable",
        "blocked_by_budget",
        "circuit_open",
    }
)


def is_terminal_status(status: str) -> bool:
    return status in AUTOMATION_INTENT_TERMINAL_STATUSES


def may_schedule_place_attempt(status: str, *, attempt_count: int, max_place_attempts: int) -> bool:
    if attempt_count >= max_place_attempts:
        return False
    if status in AUTOMATION_INTENT_TERMINAL_STATUSES:
        return False
    if status == "pending":
        return True
    if status in {"failed_retryable", "blocked_by_budget", "circuit_open"}:
        return True
    if status in {"claimed", "placing"}:
        return True  # stale claim recovery; claim_intent CAS enforces single winner
    return False
