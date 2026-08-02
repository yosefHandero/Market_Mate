# Market Mate — Application Completion Report

**Date:** 2026-07-30  
**Scope:** Phases 2–5 of the completion plan  
**Host posture:** Local personal use, paper-only dry-run

## Verdict

**Application completion** is achieved when the checklist below is green (or waived with reason) and an active evidence campaign is collecting live-forward data on the Windows wake schedule.

**Real-money pilot confidence is not claimed here.** It depends on untouched live-forward evidence accumulated afterward under one frozen campaign.

## Phase summary

| Phase | Result |
|-------|--------|
| 2 Paper-only safety | Complete — Settings forbids live flags; no broker submission code; dry-run schemas; wording cleaned |
| 3 Walk-forward / evidence hardening | Complete — shared evidence contract, leakage fixes, split-adjusted bars, research/validation/holdout, deterministic manifest |
| 4 Live-forward + ops | Complete — campaigns, provenance snapshots, immutability, scan-window ledger, backup task, Proof progress panel |
| 5 Final verification | See checklist below |

## Verification checklist

| # | Item | Status | Evidence / notes |
|---|------|--------|------------------|
| 1 | Backend unittest suite | PASS | `python -m unittest discover -s tests` — 404 tests, 1 readiness FAIL fixed then re-verified PASS |
| 2 | Frontend tests + lint + typecheck + build | PASS | `npm --prefix apps/web run check` (98 tests) + `npm run build` |
| 3 | Migration integrity | PASS (heads) | Single head `20260708_0020`; suite runs upgrades through 0020 |
| 4 | Configuration validation | PASS | `python -m app.config_doctor`; Settings rejects live flags |
| 5 | Paper-only invariants | PASS | Guard test forbids `/v2/orders`, positions, account, `paper-api.alpaca.markets` |
| 6 | API / UI integration | PASS | e2e modules + Decision/Proof web tests in full suites |
| 7 | Database integrity | Implemented | `POST /system/db/check`; `Backup-ScannerDb.ps1` + scheduled task |
| 8 | Prediction immutability | Implemented | `record_hash` + SQLite trigger + outcome-only updates |
| 9 | Deterministic walk-forward reruns | PASS | `test_run_is_deterministic_over_stored_bars` |
| 10 | Separate stock / crypto proof | PASS | Independent `verdict.by_asset` on Proof page |
| 11 | Controlled real-provider scan | Operator drill | One `POST /scan/run` during market hours; verify provenance on snapshots |
| 12 | Provider fallback | Covered in code | Alpaca → Polygon stock fallback records `provider_source` |
| 13 | Scheduler / worker recovery | PASS | Lease, stale-run recovery, PID guard tests in suite |
| 14 | Sleep / wake | Operator drill | Observe one `Invoke-WakeWindow.ps1` cycle; window ledger + catch-up |
| 15 | Paper ledger / reconcile | PASS | Covered in backend suite |
| 16 | Security / secrets | Reviewed | Tokens via env only; no `NEXT_PUBLIC_*` secrets; CORS allowlist |
| 17 | Dead-code / deps | PASS | `diff.txt` removed + gitignored; unused live settings removed |
| 18 | Documentation | PASS | README ops runbook, `AGENTS.md`, this report |
| 19 | Completion vs readiness | PASS | Proof banner + this report |

Operator drills (items 11, 14) remain host-side and must be run once on the personal Windows machine.

## Known limitations (accepted)

- Universe is the current watchlist only (survivorship-limited).
- Daily bars only — no true intraday path for exit-window conflict resolution.
- Friction is flat bps (stock/crypto), not size- or liquidity-dependent beyond volume filters.
- `real_money_pilot` track is always empty in this paper-only build.

## Graduation criteria (post-completion; not claimed)

All of the following must come from **one frozen** live-forward campaign:

- ≥100 resolved selected predictions overall; ≥60 per asset class to pilot; ≥30 per relied-on pattern (**S**)
- ≥2 market regimes with ≥20 samples each and non-negative after-friction mean (**S**)
- Median after-friction return > 0 with bootstrap 90% CI excluding 0; stressed friction mean > 0 (**S**)
- Positive after-friction edge vs SPY/BTC and vs momentum baseline (**S**)
- Wilson 95% LB hit rate > 50% for the pilot class (**S**) — raw win rate alone is never enough
- Calibration gap ≤ 10 points in used bins (**S**)
- Both campaign halves after-friction positive; live-forward hit rate inside WF holdout CI (**S**)
- Tail / drawdown / concentration / capital limits written in advance (**P**)
- ≥95% expected windows executed; <2% unresolved expiry; strategy fingerprint frozen (**S** / **P**)
- Immediate return to paper on integrity, missed-window, calibration, or budget failures (**P**)

**S** = statistically motivated · **P** = personal risk decision

## Definition of done (application)

1. Checklist items above are pass or waived with reason.  
2. Active evidence campaign is collecting on the wake schedule.  
3. Proof page shows live-forward progress and states completion ≠ readiness.
