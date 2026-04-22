# Paper Trading Operations

## Purpose

This document defines the minimum paper-trading operating standard for Market Mate Scanner.

Paper trading is considered trustworthy only when the operator can reconstruct:

1. what signal was shown
2. whether the trust gate allowed action
3. what the operator did
4. what outcome later resolved
5. whether the operator behavior aligned with the evidence

## Daily Start Checklist

Before using the dashboard for decisions, confirm:

- `readyz` is healthy
- `scan_fresh=true`
- scheduler is running if scheduled scans are expected
- threshold evidence is not silently stuck in `provisional`
- pending due outcome counts are not growing abnormally
- no critical provider degradation is active

If any of the above fails, use the product for research only and do not treat the paper loop as trustworthy for action support.

## Operator Action Standard

Every reviewed setup should end up in one of these states:

- `took`
- `skipped`
- `watching`

Until the journal schema grows richer, use note prefixes to capture nuance:

- `override:` when you took or skipped against the system recommendation
- `late:` when the action happened after the signal freshness window
- `stale:` when the underlying scan was no longer fresh
- `ops:` when the decision was affected by provider, scheduler, or readiness problems

This keeps operator-behavior evidence usable without changing the current journal contract yet.

## Paper Action Workflow

For any actionable symbol:

1. review the latest decision row
2. verify execution eligibility and trust warnings
3. use preview before any place flow
4. if using paper execution, prefer `dry_run=true` and keep the audit trail
5. create or update the matching journal entry
6. review the later outcome and alignment metrics

Do not treat `execution_eligibility=review` as permission for automation.

## Weekly Trust Review

Review these outputs once per week:

- evidence pack export
- validation summary over the recent trust window
- threshold sweep recommendation and warnings
- execution alignment cohorts
- recent audit samples
- journal analytics

The weekly review should explicitly check:

- passed `BUY` and `SELL` sample depth
- stale scans or scheduler failures
- blocked preview reasons
- operator overrides
- whether paper actions remain aligned with the intended strategy contract

## Hard Stops

Pause paper-trading claims and revert to research-only when:

- scans stop being fresh during target sessions
- critical provider state degrades
- threshold evidence remains immature without explanation
- audit chains become incomplete
- operator actions stop being recorded consistently
- recent holdout or recent-window expectancy turns materially negative after friction

## Current Limitation

The home-page paper simulation is still a quick decision aid, not the source of portfolio truth.
Use the audit trail, journal, and validation reports as the authoritative paper-evidence loop until a first-class paper portfolio ledger replaces the simulation shortcut.
