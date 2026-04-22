# Scanner Operations

## Process Model

- Run API process with `uvicorn app.main:app`.
- Run scheduler worker separately with `python -m app.worker`.
- Run migrations before either process starts: `.venv/Scripts/alembic.exe upgrade head`.
- Keep `TRUST_RECENT_WINDOW_DAYS` explicit in the environment so scan-time gates, order-time eligibility, and recent validation use the same evidence basis.
- Treat [`docs/trust-model.md`](trust-model.md) as the operational contract for what the scanner is and is not claiming.
- Treat [`docs/product-thesis.md`](product-thesis.md), [`docs/evidence-protocol.md`](evidence-protocol.md), and [`docs/paper-trading-operations.md`](paper-trading-operations.md) as the current execution focus for product scope, evidence standards, and paper-trading discipline.

## Deployment Checklist

- Set `APP_ENV=production`.
- Use Postgres in `DATABASE_URL`.
- Set `ADMIN_API_TOKEN`.
- Set `PUBLIC_READ_ACCESS_ENABLED=false` if the read API should be private.
- Keep `ALPACA_BASE_URL` on paper trading unless `ALLOW_LIVE_TRADING=true` is intentional.
- Start both API and worker.

## Health Checks

- `GET /livez`: process liveness.
- `GET /startupz`: startup dependencies.
- `GET /readyz`: database, schema, **at least one completed full scan**, and scan freshness. With no scans yet, `ready=false` and `scan_fresh=false`.
- `readyz` reports `last_scan_at`, `last_scan_age_minutes`, `max_stale_minutes`, `scan_fresh`, scheduler state, trust-window counts, threshold evidence status, and pending due outcome counts.
- If the latest scan is older than `HEALTH_MAX_STALE_MINUTES`, `readyz` is not ready so stale paper-trading evidence is visible to operators.
- When `REQUIRE_READYZ_FOR_EXECUTION=true` (default), `POST /orders/preview` and `POST /orders/place` return **503** with `not_ready` if readiness is false (same rules as `readyz`), except successful **idempotent reuse** of an existing submitted/dry-run/blocked audit for the same key and body hash.
- A trustworthy paper-trading session should show `scan_fresh=true` and should not leave `trust_threshold_evidence_status=provisional` indefinitely without a clear data-sparsity explanation.

## Trading Kill Switch

- Set `EXECUTION_ENABLED=false` to disable order submission.
- Keep `ALLOW_LIVE_TRADING=false` unless a live rollout is explicitly approved.
- Live rollout remains capped even when explicitly approved. Small size is intentional until replay, validation, and provider reliability are materially stronger.
- Revoke or rotate `ADMIN_API_TOKEN` if operator credentials are compromised.

## Paper Trading Evidence Loop

- Use `POST /orders/preview` first to inspect the trade gate, warnings, and estimated notional.
- Use `POST /orders/place` with `dry_run=true` to create a non-broker paper audit trail while keeping execution disabled.
- Inspect recent order evidence with `GET /orders/audits`.
- Inspect ledger state with `GET /paper/ledger` and `GET /paper/ledger/summary`.
- Recent audits now carry `signal_outcome_id`, `trade_gate_horizon`, `evidence_basis`, and trust-window timestamps so blocked previews can be traced back to the exact evidence basis that allowed or blocked them.
- Compare operator behavior against signal evidence with `GET /signals/validation/execution-alignment`.
- A trustworthy paper-trading loop should leave a visible chain of:
  - latest signal and gate decision
  - preview or place audit record
  - later outcome evaluation
  - alignment metrics for taken, skipped, and blocked cohorts
- Paper support should treat `execution_eligibility=review` as manual-review only, not as permission to auto-submit.

## Signal Outcome Performance Report

- Use `GET /signals/outcomes/performance-report` to inspect stored signal expectancy without any frontend dependency.
- The route is admin-only and accepts `Authorization: Bearer <token>` or `X-API-Key: <token>` using the same admin token rules as the rest of the scanner admin API.
- Required query params:
  - `start`: inclusive lower bound on `signal_outcomes.generated_at`
  - `end`: exclusive upper bound on `signal_outcomes.generated_at`
  - Optional `asset_type=stock|crypto`
- Example:

```text
GET /signals/outcomes/performance-report?start=2026-03-01T00:00:00Z&end=2026-03-08T00:00:00Z&asset_type=stock
Authorization: Bearer <ADMIN_API_TOKEN>
```

- `by_signal_and_gate` answers the main ops question directly with buckets such as `BUY:passed`, `BUY:blocked`, `SELL:passed`, and `SELL:blocked`.
- Each slice includes `metrics_15m`, `metrics_1h`, and `metrics_1d` with counts, win/loss splits, mean and median return, and expectancy.
- Returns are directional. `SELL` outcomes are already sign-flipped in storage, so a positive return still means the signal direction was correct.
- `meets_min_sample` and `insufficient_sample` help avoid over-reading thin samples for any horizon.
- `baseline.passes_baseline` summarizes whether gated `BUY` and gated `SELL` cohorts both clear the configured minimum sample count and minimum mean return on the configured primary validation horizon.

## Validation Windows And Thresholds

- `GET /signals/validation/summary`, `GET /signals/validation/threshold-sweep`, and `GET /signals/validation/execution-alignment` now accept optional `start` and `end` query params on `signal_outcomes.generated_at`.
- Validation summary also supports optional `regime` and `data_grade` filters.
- Execution alignment now supports `friction_scenario=base|stressed|worst`.
- Use explicit recent windows when judging trust. Full-history pooling is useful for exploration, but recent windows are the right default for paper-trading confidence decisions.
- Scan-time gating and trade-time eligibility now use the configured recent trust window by default instead of silently pooling full-history signal evidence.
- `by_signal_and_gate` is the quickest way to inspect `BUY:passed`, `BUY:blocked`, `SELL:passed`, and `SELL:blocked` maturity in a selected window.
- The threshold sweep now returns:
  - `candidates`: exploratory threshold combinations ranked from the selected window
  - `recommendation`: the current threshold recommendation
- When gated cohorts are too sparse, `recommendation.evidence_status` remains `provisional` and the API keeps the configured trade-gate thresholds as a fallback instead of pretending the data is mature enough to lock a new threshold set.
- Thresholds should only be treated as ready when the selected window has mature gated `BUY` and gated `SELL` evidence, not just a good-looking in-sample candidate list.
- Validation now also tracks friction-adjusted return views so raw expectancy is not mistaken for tradeable expectancy.

## Watchlist Sizing

- Default `WATCHLIST` carries ~49 US equities (47 scannable + SPY/QQQ benchmarks). Default `CRYPTO_WATCHLIST` carries 20 `BASE/USD` pairs verified against Alpaca's supported crypto assets.
- Expected per-scan metrics: `watchlist_size` ~69, `scan_count` ~67 when all bars are returned (SPY/QQQ excluded from scan rows).
- Alpaca bar fetching is batched (one stock request, one crypto request per scan); CoinGecko context is a single `coins/markets` call. Per-stock costs are SEC + options (2 calls) and conditional news checks. Crypto symbols skip SEC/options entirely.
- Scan duration scales roughly with total symbols divided by `SCAN_CONCURRENCY_LIMIT` (default 8). A ~69-symbol scan will take roughly 4-5x longer than the original ~14-symbol scan unless provider latency changes.
- If provider errors or scan latency increase after expanding the list, first try lowering `SCAN_CONCURRENCY_LIMIT` to reduce API fan-out, then trim low-priority symbols from the tail of each list.
- Coinbase WS (`COINBASE_WS_PRODUCTS`) defaults to `BTC-USD,ETH-USD`. Other crypto pairs still scan correctly via Alpaca; adding more Coinbase products is optional for fresher spot-price overlays.

## Stale Signal Contract

- `STALE_SIGNAL_MAX_AGE_MINUTES` is the canonical stale-signal threshold for both order-time risk checks and automation pre-execution checks.
- Rows may still appear in the UI after this threshold, but order-time support and automation should fail closed once the threshold is exceeded.
- Treat bar-age and row-level `freshness_flags` as the provenance record for what the row knew at scan time.

## Promotion And Reconciliation

- Use `GET /admin/paper/promotion-check` to inspect whether the current paper loop is clean enough to move from `shadow` to `limited`, or from `limited` to `broad`.
- Use `GET /admin/paper/reconcile` to detect ledger gaps between automation intents, execution audits, and paper positions.
- Promotion should remain blocked when reconciliation is dirty, duplicate/idempotency failures appear, or recent dry-run evidence is too thin.

## Replay Foundation

- Use `POST /strategy/replay` for a no-lookahead historical replay over market-bar snapshots.
- Replay is an admin route because it is expensive and meant for controlled validation work.
- Replay assumptions are intentionally conservative:
  - signal generation only sees bars available at each replay timestamp
  - friction can be applied to distinguish raw vs friction-adjusted outcomes
  - secondary providers are not yet fully reconstructed historically
- Replay is currently good enough for strategy comparison and leak detection, but not yet a final proof of live tradeability.

## Mode Boundaries

- Research only:
  - raw score exploration
  - replay experiments
  - threshold candidate inspection
- Paper-trading support:
  - fresh scans
  - recent evidence gates active
  - provider state not critical
  - portfolio guardrails passing
- Not ready for live trading by default:
  - provisional thresholds
  - degraded critical providers
  - larger-than-cap live orders

## Migrations

- Create new revision: `python -m alembic revision -m "describe change"`.
- Apply latest migration: `.venv/Scripts/alembic.exe upgrade head`.
- Production rollouts should apply migrations before restarting API/worker processes.

## Evidence Pack

- Export the current evidence pack with:

```text
.venv/Scripts/python.exe scripts/export_evidence_pack.py --base-url http://127.0.0.1:8005
```

- The command writes a timestamped folder under `services/scanner/var/evidence-pack/` containing:
  - DB integrity checks
  - current `readyz`
  - recent scan cadence
  - recent-window validation, threshold, performance, and execution-alignment outputs
  - recent audit samples
  - joined paper-loop samples
  - exit-bar verification
  - backend test output
