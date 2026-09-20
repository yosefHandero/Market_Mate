"""Brain contracts: inputs, decisions, and the DecisionPolicy interface.

These types are the only surface the host shell may depend on (besides the
public functions re-exported from the package root and the evaluation
entrypoints). Policies receive the whole universe snapshot at once so
cross-sectional or regime-conditional policies fit without contract changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

DecisionAction = Literal["BUY", "ABSTAIN"]
DecisionRole = Literal["production", "shadow"]


@dataclass(frozen=True)
class SymbolSnapshot:
    """Point-in-time market data for one symbol.

    ``daily_bars`` are Alpaca-shaped dicts (t/o/h/l/c/v) with no bar after
    ``MarketSnapshot.as_of``. ``session`` optionally carries intraday-derived
    features computed by the host (relative volume, breakout flags, VWAP
    state, ...). ``context`` optionally carries provider context snapshots
    (news sentiment, options flow, macro, microstructure, ...). Policies may
    only rely on fields they have earned through the ruler; unvalidated
    context is challenger material.
    """

    symbol: str
    asset_type: Literal["stock", "crypto"]
    daily_bars: list[dict] = field(default_factory=list)
    session: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    data_quality: str = "ok"
    daily_bars_stale: bool = False
    daily_bars_source: str = "unknown"


@dataclass(frozen=True)
class MarketSnapshot:
    """The full point-in-time universe a policy decides over."""

    as_of: datetime
    symbols: tuple[SymbolSnapshot, ...] = ()
    # Benchmark daily bars keyed by benchmark symbol (e.g. "SPY", "BTC/USD").
    benchmark_daily_bars: dict[str, list[dict]] = field(default_factory=dict)
    universe_source: str = "current_watchlist"

    def get(self, symbol: str) -> SymbolSnapshot | None:
        for snapshot in self.symbols:
            if snapshot.symbol == symbol:
                return snapshot
        return None


@dataclass(frozen=True)
class ExitPlan:
    entry_price: float
    target_price: float | None
    stop_price: float | None
    horizon_days: int


@dataclass(frozen=True)
class EvidenceBasis:
    """Which evidence supported a decision and how much of it there was."""

    basis: str = "insufficient"  # live_forward_proven | mixed | historical_only | insufficient
    sample_sizes: dict[str, int] = field(default_factory=dict)
    historical_hit_rate_pct: float | None = None
    historical_avg_return_pct: float | None = None


@dataclass(frozen=True)
class BrainDecision:
    """One policy's decision for one symbol at one point in time.

    ``p_up_calibrated`` is the only confidence number: the calibrated
    probability (percent) that price is higher after the horizon. ABSTAIN
    decisions carry machine-readable ``reasons`` explaining why no BUY was
    produced. ``diagnostics`` is free-form, display/debug only, and must never
    feed back into decision logic.
    """

    policy_id: str
    policy_version: str
    decision_fingerprint: str
    symbol: str
    asset_type: Literal["stock", "crypto"]
    as_of: datetime
    action: DecisionAction
    p_up_calibrated: float | None = None
    expected_value_pct: float | None = None
    exit_plan: ExitPlan | None = None
    evidence_basis: EvidenceBasis = field(default_factory=EvidenceBasis)
    reasons: tuple[str, ...] = ()
    pattern_name: str | None = None
    probability_methodology: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DecisionPolicy(Protocol):
    """A versioned decision policy the brain can run as champion or challenger.

    ``replayable`` declares whether the policy can be honestly evaluated by
    the walk-forward engine from stored daily bars alone. Policies that need
    live-only inputs (intraday session features, live provider context) are
    not replayable and can only be judged through live shadow evidence.
    """

    policy_id: str
    policy_version: str
    replayable: bool

    def config_payload(self) -> dict[str, Any]:
        """Full decision-relevant config for fingerprinting."""
        ...

    def fingerprint(self) -> str:
        """Decision fingerprint for this policy + config."""
        ...

    def decide_all(self, snapshot: MarketSnapshot) -> list[BrainDecision]:
        """Decide over the whole universe snapshot. BUY or ABSTAIN per symbol."""
        ...
