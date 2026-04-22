# Market Mate Scanner Evidence Protocol

## Purpose

This protocol defines the minimum evidence standard required before:

- expanding strategy scope
- promoting supportive providers into the main scoring path
- making larger paper-trading claims
- increasing live-trading exposure
- packaging the system as a paid product

Use this together with:

- `docs/trust-model.md`
- `docs/operations.md`
- the current evidence pack export

## Locked Research Loop

Every evaluation cycle must freeze these fields for the full window:

- tradable universe
- asset type focus
- strategy version
- primary holding horizon
- trade-gate thresholds
- friction assumptions
- benchmark set

Do not compare results across windows if any of the above changed mid-window.

## Core Benchmarks

Every strategy review must compare the current strategy against at least:

1. a simpler baseline directional model
2. a core-data-only version with supportive providers removed
3. the currently deployed strategy version

If a change does not beat a simpler baseline after friction, it does not earn production influence.

## Validation Windows

Use three explicit windows for every serious review:

1. training window: used to understand and calibrate the strategy
2. tuning window: used to compare threshold candidates and variants
3. holdout window: untouched future data used only for evaluation

Recent-window evidence remains the operational default for trust and thresholds.
Full-history pooling is for exploration only.

## Minimum Proof Standard

Before calling the strategy research-complete for its current loop, target:

- at least 300 evaluated signals in the primary loop
- at least 100 evaluated passed `BUY` signals on the primary horizon
- at least 100 evaluated passed `SELL` signals on the primary horizon
- positive expectancy after friction in the holdout window
- no obvious single-regime dependence
- no large divergence between fresh, operationally eligible setups and the broader dataset

If any of the above are not true, the system stays in evidence-building mode.

## Promotion Rules

### Promote a provider into the main scoring path only if

- it has been tested in shadow or compare mode first
- it improves holdout expectancy or false-positive control
- its benefit survives realistic friction assumptions
- its failure mode is operationally acceptable

### Promote a strategy variant only if

- it beats the deployed version on the holdout window
- it does not reduce explainability materially
- it does not create a worse provider-dependency profile
- it improves the actual action cohorts, not only total-sample averages

### Promote live automation only if

- the paper loop is stable for multiple weeks
- readiness and freshness remain healthy during target trading hours
- thresholds are not stuck in `provisional`
- recent evidence remains positive after friction
- live rollout stays inside explicit size caps and kill-switch rules

## Anti-Self-Deception Rules

- Replay is for research support, not final proof.
- Do not tune and judge on the same untouched window.
- Do not celebrate full-history averages without checking recent windows.
- Do not blend crypto and stocks into one headline result.
- Do not treat raw score improvements as evidence unless action cohorts improve.
- Do not expand scope because a new provider tells a better story.

## Weekly Review Outputs

Each weekly review should answer:

1. Did the latest holdout or recent window remain positive after friction?
2. Did passed `BUY` and passed `SELL` cohorts remain sufficiently sampled?
3. Did any provider improve or degrade without measurable effect on edge?
4. Did operator behavior improve or dilute results?
5. Is the current loop strong enough to keep, narrow, or pause?
