# 95+ fake-money loop: evidence window and promotion gates

This note supports the **dry-run paper loop only** (no live execution, automation remains `execution_enabled=false`).

## Severity-1 incidents (fail the 95+ claim)

- Duplicate dry-run `place` for the same deterministic `intent_key` (or duplicate audit for the same `idempotency_key` when the intent should have been terminal).
- Budget bypass: hourly, daily, per-symbol window, or per-cycle caps exceeded without a block.
- Circuit breaker stuck **open** for more than two hours while automation is enabled and the scanner is healthy (operator must verify DB row `paper_loop_breaker` and logs).
- Silent retry beyond `paper_loop_retry_max_attempts` (intent should be `failed_terminal`).

## 7-day staging window (default calendar days)

1. Mirror production scheduler settings (`scan_interval_seconds`, automation phase, allowlist size policy).
2. Daily (~15 minutes): `GET /automation/status` (budget, breaker, recent intents), row counts by `automation_intents.status`, spot-check new `execution_audits` dry-run rows vs intents.
3. Weekly: export or note requests made vs avoided, dedupe hits, blocked reasons, max hourly usage %, `candidates_considered` vs `candidates_reached_execution_call` (filter rate).

## Promotion gates (all must pass)

- **Shadow**: no `place`; stable intent volume; no duplicate intent keys; filter-rate baseline tracked via metrics.
- **Limited dry-run**: automated tests for retry cap, breaker, CAS claim, recovery audit reuse; staging clean run per rollout table in the product roadmap.
- **Broad dry-run**: same caps review; no severity-1 incidents in the prior stage.

Rollout remains **single process** + **one** aggregated `/automation/status` read path; no new infrastructure.
