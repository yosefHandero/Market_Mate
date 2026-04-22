# Scanner Trust Model

## Purpose

Market Mate Scanner is a trading scanner and decision-support system. It is not allowed to imply certainty that the evidence does not support.
The active product thesis and execution scope now live alongside this document in [`docs/product-thesis.md`](product-thesis.md) and [`docs/evidence-protocol.md`](evidence-protocol.md).

The scanner now separates four concepts that were previously easy to blur together:

- `raw_score`: heuristic directional score from the strategy engine
- `calibrated_confidence`: recent-evidence-adjusted score for operational ranking (not a probability of profit, win, or future return)
- `evidence_quality`: how trustworthy the available inputs and supporting evidence are
- `execution_eligibility`: whether the system is willing to support action after gates and safeguards

## Strategy Contract

Current strategy contract:

- `strategy_id`: `scanner-directional`
- `strategy_version`: `v3.0-explicit`
- Primary holding horizon: `1h`
- Entry assumption: enter on the next available trade after the scan snapshot
- Exit assumption: evaluate direction over fixed 15m, 1h, and 1d forward windows

Signal meanings:

- `BUY`: directional long thesis with evidence that points to upside over the validation horizon
- `SELL`: directional short thesis with evidence that points to downside over the validation horizon
- `HOLD`: abstain because no directional edge is strong enough to justify action

## What Evidence Quality Means

`evidence_quality` is not a price target or a probability. It is a trust label based on:

- recent evidence gate outcome
- calibration maturity
- market-data quality
- provider health

Levels:

- `high`: gate passed, inputs look healthy, and confidence has mature support
- `moderate`: usable but not especially clean
- `low`: action may still be research-worthy, but evidence is thin or partially degraded
- `degraded`: critical provider or data-quality problems mean the setup should not be trusted operationally

## What Execution Eligibility Means

Execution support is intentionally stricter than signal generation:

- `eligible`: evidence gate passed and no critical trust blockers are active
- `review`: setup may be interesting, but operator review is required because evidence/provider quality is not clean
- `blocked`: trade gate, provider state, or portfolio guardrails block the trade
- `not_applicable`: HOLD signal

## Portfolio Guardrails

Portfolio controls are derived conservatively from the system's own execution audit trail and resolved signal outcomes.

Current explicit checks include:

- daily deployed notional cap
- per-symbol notional concentration cap
- per-asset-type concentration cap
- daily weighted return limit
- consecutive loss-streak cooldown
- drawdown-based kill switch

These are useful safeguards, but they are not a substitute for full broker-native position accounting yet.

## Replay And Validation

The replay foundation is historical-bar based and avoids lookahead during signal generation by only using bars available at each replay timestamp.

Important limitations:

- replay currently uses core market bars only
- historical reconstruction of news, options flow, and filing context is not complete yet
- friction is modeled conservatively, but still remains an approximation

## Mode Readiness

Research only:

- strategy exploration
- raw score inspection
- replay experiments
- threshold comparison

Paper-trading support:

- scan freshness is healthy
- evidence gates are active
- provider state is not critical
- portfolio guardrails are not tripped
- execution remains paper or dry-run only

Not ready for normal live trading:

- any mode that lacks mature out-of-sample evidence
- any mode with provisional thresholds
- any mode with degraded critical provider inputs
- any rollout larger than the conservative live caps

Tiny live trading is still an exception path, not a default operating mode.
