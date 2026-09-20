# The Decision Brain

This package is the complete decision-making core of the scanner: decision
policies (champion + challengers), the shared math they use, and the ruler
that judges every policy's evidence. It is deliberately isolated so decision
quality work and application/UI work cannot contaminate each other.

## Boundary

- The brain contains **pure functions over passed-in data**. No network, no
  database, no filesystem, no clock reads that affect decisions (`as_of` is an
  input).
- Allowed imports: stdlib, `app.brain.*`, `app.schemas` (pure typed
  contracts), `app.config` (settings values; the brain never mutates or
  reloads them).
- Forbidden imports: `app.services`, `app.api`, `app.models`, `app.clients`,
  `app.db`, `app.core` (host shell), SQLAlchemy, FastAPI, HTTP clients.
  Enforced by `tests/test_brain_boundary.py`.
- The host shell adapts providers/ORM rows into brain inputs
  (`contracts.MarketSnapshot`) and persists brain outputs
  (`contracts.BrainDecision`). Presentation (labels, sort order for display,
  freshness badges) and operations (kill switches, breakers, readiness) stay
  in the host.

## Champion / challenger model

- Exactly one **champion** policy drives production surfaces (Decision page,
  alerts, paper loop). Any number of **challenger** policies run in shadow on
  the same scans: their decisions are persisted (`decision_role="shadow"`),
  resolved by the same outcome pipeline, and judged by the same ruler, but
  never touch production output or automation.
- The production rule: the champion may only consume inputs whose contribution
  has been validated by the ruler. Unvalidated data (news sentiment, options
  flow, macro context, ...) is challenger material until it earns its way in
  through walk-forward + live shadow evidence.
- Promotion is strict and evidence-only: a challenger replaces the champion
  only when the promotion report clears (walk-forward holdout gates plus a
  paired live-shadow comparison with uncertainty accounted for). There is no
  calendar shortcut and no "paper-only" relaxation: paper-only reduces
  deployment risk, not evidentiary uncertainty.

## Two identities (never conflate them)

- **Decision identity** — `identity.decision_fingerprint(policy_id,
  policy_version, config_payload)`. Covers everything that can affect
  *produced decisions*. Stamped on predictions; a change rotates that
  policy's prediction campaign so incompatible predictions never mix.
- **Ruler identity** — `identity.RULER_VERSION` + `RulerConfig` payload.
  Covers *how stored evidence is judged*. Stamped on evaluation outputs
  (walk-forward runs, promotion reports, proof summaries). Ruler changes
  never rotate prediction campaigns: raw outcomes are canonical and
  re-judging them is reinterpretation, not a new brain.
- Classification rule: if a constant flows into decision production it is
  decision identity; if it only judges stored evidence it is ruler identity.
  If a change affects both, it rotates campaigns (decision side wins).

## How to change the brain

1. Decision-affecting change (policy logic, pattern definitions, probability
   construction, decision-side config): bump the policy's `policy_version`
   (or `FEATURE_VERSION` for pattern semantics) and expect a campaign
   rotation. Hardcoded constants inside brain modules are part of decision
   identity through these versions; if you change one, you must bump.
2. Judging-affecting change (metrics, win definitions, benchmarks, verdict or
   promotion gates): bump `RULER_VERSION`. Do not rotate campaigns.
3. New data source or model: add it as a challenger policy (or challenger
   config of an existing policy), let it accrue shadow + walk-forward
   evidence, and promote through the ruler.
4. Never add live broker submission anywhere, including here. BUY/ABSTAIN
   decisions are decision-support output only.

## Layout

- `contracts.py` — `MarketSnapshot` / `SymbolSnapshot` inputs,
  `BrainDecision` output, `DecisionPolicy` protocol.
- `registry.py` — policy registry (one champion, N challengers).
- `identity.py` — decision fingerprint + ruler version/fingerprint.
- `config.py` — frozen decision-side policy configs and ruler config, built
  from `Settings` by the host at the edge.
- `weekly_patterns.py`, `weekly_backtest.py`, `weekly_bar_utils.py`,
  `candidate_quality.py`, `probability.py`, `calibration.py`, `gates.py`,
  `structural_prediction.py`, `weekly_evidence.py` — decision math shared by
  policies.
- `evaluation/` — the ruler's pure math (metric statistics, paired
  comparison, promotion gates). Judges evidence; never feeds decisions.
- `policies/` — concrete `DecisionPolicy` implementations.
