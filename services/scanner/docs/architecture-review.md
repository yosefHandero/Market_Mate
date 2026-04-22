# Scanner Architecture Review

## Baseline Summary

The scanner currently operates as a single orchestrated pipeline centered on `app/services/scanner.py`.
`ScannerService.run_scan()` fetches bars and context, `_analyze_ticker_impl()` builds per-symbol features, `app/core/signals.py` and `app/core/scoring.py` produce the raw directional result, `app/services/repository.py` calibrates and gates the result using recent outcome evidence, and `app/core/strategy_contract.py` translates that into evidence quality and execution eligibility.

The pipeline is functional, but it still mixes several concerns that should be easier to reason about independently:

- raw direction
- confidence calibration
- evidence quality
- provider health
- execution support

## Current End-To-End Flow

1. `ScannerService.run_scan()` fetches stock bars, crypto bars, fear/greed, and CoinGecko context.
2. Crypto bars are optionally price-overridden by `CoinbaseMarketDataService`.
3. `ScannerService._compute_market_status()` and `_crypto_market_status()` derive regime context.
4. `_analyze_ticker_impl()` computes per-symbol features such as price change, relative volume, VWAP context, volatility regime, relative strength, SEC/options inputs for stocks, and optional directional news.
5. `compute_signal_and_explanation()` computes the raw directional decision.
6. `_gate_signal()` applies recent-window calibration and evidence gating from `ScanRepository`.
7. `build_strategy_evaluation_metadata()` produces evidence quality and execution eligibility labels.
8. `ScanRepository.save_run()` persists `scan_runs`, `scan_results`, and actionable `signal_outcomes`.
9. `RiskService.evaluate_trade()` and `ExecutionService.preview()` reuse the stored signal context and trade gate at order time.

## Current Provider Roles

### Primary

- `alpaca`: primary bars, reference price, execution broker, outcome resolution

### Supportive

- `coinbase_advanced_trade_ws`: crypto spot-price freshness overlay
- `coingecko`: crypto market-cap and 24h context
- `fear_greed`: broad crypto sentiment backdrop
- `marketaux`: directional news sentiment helper
- `finnhub`: directional news sentiment helper
- `sec`: stock catalyst/event helper
- `options_flow`: stock supportive positioning/context helper

### Current Weaknesses By Provider Layer

- provider outputs are not normalized into a shared contract
- missing data is represented inconsistently (`0.0`, `None`, `{}`, warning strings)
- freshness, fallback, and degraded-mode semantics are not exposed consistently
- supportive providers sometimes affect raw score directly when they would be safer as confidence or evidence modifiers

## Current Scoring Path

`compute_directional_scores()` currently blends:

- relative volume
- price momentum
- breakout/breakdown
- VWAP context
- close-to-high / close-to-low
- relative strength
- news sentiment
- market status
- options-flow skew
- neutral catalyst score
- context bias
- a confirmation count that overlaps several of the inputs above

This creates understandable outputs, but the current rule set likely double counts correlated intraday behavior and makes it harder to explain exactly why a signal became stronger.

## Current Trust / Policy Path

- `raw_score`: directional heuristic output
- `calibrated_confidence`: recent-window-adjusted ranking score
- `gate_passed`: minimum recent evidence check
- `evidence_quality`: trust label derived from gate, calibration maturity, data quality, and provider health
- `execution_eligibility`: policy label derived from signal, gate, evidence, and provider state

The trust model is already moving in the right direction, but evidence quality still inherits some gate and calibration penalties that are conceptually separate from data trustworthiness.

## Observability Already Present

- free-text `explanation`
- `gate_passed`, `gate_reason`, `gate_checks`
- `calibrated_confidence`, `calibration_source`
- `provider_status`, `provider_warnings`
- `evidence_quality`, `evidence_quality_score`, `evidence_quality_reasons`
- execution audit trail with trade-gate metadata
- replay and validation endpoints

## Current Test Baseline

The current test suite already covers several strong foundations:

- repository calibration and gate logic
- scanner run hardening and provider health
- strategy contract behavior
- replay no-lookahead basics
- risk and execution pathways
- provider-resilience caching and backoff
- Coinbase market-data overlay
- DB schema patching

Key gaps before the architecture pass:

- no first-class tests for feature flags or shadow-mode comparisons
- limited replay coverage for secondary-provider influence
- no baseline provider-contract normalization tests
- limited end-to-end comparison between live and alternate scoring variants

## Target Refactor Direction

The upgraded scanner should preserve explainability while assigning each feature exactly one primary role:

- directional score
- confidence calibration
- evidence quality
- execution eligibility
- risk / human review
- provider health / degraded mode

Provider additions should be selective and orthogonal:

- Binance: crypto timing and evidence quality
- Deribit: crypto crowding and confidence moderation
- SEC: stock catalyst quality and evidence support
- FRED: macro regime filter
- internal breadth: cross-sectional confirmation
- DefiLlama: supportive crypto macro breadth only after earlier phases stabilize

## Baseline Reference

Use this document together with `docs/baseline-architecture.json` as the before-state reference for the phased upgrade.
