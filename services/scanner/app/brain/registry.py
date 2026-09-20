"""Policy registry: exactly one champion, any number of shadow challengers.

The champion drives production surfaces and the paper loop. Challengers run in
shadow on the same scans, are measured by the same ruler, and never touch
production output or automation. Champion selection is host configuration
(``BRAIN_CHAMPION_POLICY_ID``); switching champions is a decision-identity
change and rotates the production prediction campaign.
"""

from __future__ import annotations

from app.brain.contracts import DecisionPolicy


class PolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, DecisionPolicy] = {}

    def register(self, policy: DecisionPolicy) -> None:
        if policy.policy_id in self._policies:
            raise ValueError(f"Policy already registered: {policy.policy_id}")
        self._policies[policy.policy_id] = policy

    def get(self, policy_id: str) -> DecisionPolicy:
        try:
            return self._policies[policy_id]
        except KeyError:
            raise KeyError(
                f"Unknown policy '{policy_id}'. Registered: {sorted(self._policies)}"
            ) from None

    def champion(self, champion_policy_id: str) -> DecisionPolicy:
        return self.get(champion_policy_id)

    def challengers(self, champion_policy_id: str) -> list[DecisionPolicy]:
        return [
            policy
            for policy_id, policy in sorted(self._policies.items())
            if policy_id != champion_policy_id
        ]

    def all_policies(self) -> list[DecisionPolicy]:
        return [policy for _pid, policy in sorted(self._policies.items())]
