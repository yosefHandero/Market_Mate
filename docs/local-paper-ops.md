# Local paper-only operations

This runbook is for **local, paper and dry-run use only**. **Real-money / live trading is disabled in this product path and is out of scope** for this document. Do not use this app to justify live trading.

Deeper product context: [`../services/scanner/docs/paper-trading-operations.md`](../services/scanner/docs/paper-trading-operations.md).

## Start the backend

From a terminal (Python env with `services/scanner` dependencies installed):

```bash
cd services/scanner
python -m uvicorn app.main:app --reload --port 8005
```

## Worker process

The scheduler has two separate local states:

- **Scheduler enabled** means the backend scheduler flag has been turned on with the scheduler API.
- **Worker running** means a local worker process is currently alive and polling for due scheduler work.

The web dashboard may show "scheduler enabled" while also warning that the worker is not running. That is expected when the scheduler has been enabled but no local worker terminal is active. The dashboard does **not** auto-launch the worker.

Start the worker from another terminal:

```bash
cd services/scanner
python -m app.worker
```

Helper scripts do the same local command without secrets:

```bash
services/scanner/scripts/run_worker_local.sh
services/scanner/scripts/run_worker_local.bat
```

After enabling the scheduler from the dashboard, `/readyz` should eventually report `scheduler_running=true` when the worker is alive. If it stays false, start or restart the worker process.

## Start the web dashboard

```bash
cd apps/web
npm run dev
```

Open **http://localhost:3000** (default Next.js port).

## Local environment (no secrets)

- Copy templates only; **never commit** `.env` or `.env.local` files, and do not paste token values into tickets or chat.
- Backend template: `services/scanner/.env.example` → create `services/scanner/.env` locally.
- Web template: `apps/web/.env.local.example` → create `apps/web/.env.local` locally.
- **Name mapping** (same secret, different variable name):
  - `READ_API_TOKEN` (scanner) ↔ `SCANNER_READ_API_TOKEN` (web)
  - `ADMIN_API_TOKEN` (scanner) ↔ `SCANNER_ADMIN_API_TOKEN` (web)
- `PUBLIC_READ_ACCESS_ENABLED` on the scanner controls whether read routes need a token; see root [`README.md`](../README.md) for behavior.

## Health checks

```bash
curl -s http://localhost:8005/health
curl -s http://localhost:8005/readyz
```

There is **no** `/healthz` route; use `/health` and `/readyz` only.

- `/readyz` encodes scan freshness and operating readiness; use it before treating the loop as “actionable.”

## Readiness (dashboard)

On the **Actions** dashboard, **Readiness** is the main “can I trust and act on this *right now*?” score (0–100%). It is **not** the same as raw calibrated confidence: confidence stays in the API and in deeper surfaces, but Readiness blends it with **recommended action**, **gates**, **provider status**, **freshness / bar age**, **evidence quality**, **risk-setup sanity** (entry/stop/target from the dry-run shape), **sample-size gate failures** when present, and **automation safety** (kill switch / circuit breaker) when the dashboard has that snapshot.

**How to read the buckets**

| Range | Meaning |
|-------|---------|
| 80–100 | High readiness — best case for considering preview/dry-run when the action allows it |
| 60–79 | Watch / preview band — still possible to preview when action is `preview` or `dry_run`, but extra caution |
| 30–59 | Low readiness — treat as low trust until issues clear |
| 0–29 | Not actionable — do not treat as a green light |

**Important:** A row can show a non-zero Readiness but still have **Preview** / **Place** disabled when `recommended_action` is not `preview` or `dry_run`. Readiness explains trust; the buttons still follow the backend’s action and dry-run rules.

## Run a fresh scan

1. With backend and web running, on the **Dashboard** use **Operator actions** to trigger a run (the UI calls `POST` via the web app’s scan proxy).
2. Or with your **admin** token (header `Authorization: Bearer <ADMIN_API_TOKEN>` or `X-API-Key`):

   ```bash
   curl -X POST http://localhost:8005/scan/run -H "X-API-Key: <your-admin-token>"
   ```

3. Confirm on the dashboard: **Latest scan** time updates, **Ranked results** / watchlist fields reflect the new run.

## Blocked / ignored rows (no trade)

When a row is not eligible for preview/place:

- **Preview** and **Place** stay disabled; the UI should **not** auto-call preview.
- Read the explanation panel: **gate / block reasons**, **provider status**, and **freshness** where the API exposes them.
- **Do not** loosen strategy gates or thresholds to “get a trade.” An empty or fully blocked set is **safe behavior**, not a product failure.

## No eligible ticker

- Note the top **block reasons** and **execution_eligibility** / trust labels for the ranked list.
- Wait for the next scan window (or your scheduled session); do not force eligibility.

## Preview and place (dry-run paper only)

1. Select an **eligible** row in the trading workspace.
2. Run **Preview** (dry-run path); note **execution audit id** in the response / UI.
3. Run **Place** with dry-run; the API **forces** `dry_run=true` on `/orders/place`. Expect a receipt-style response with `dry_run=true`, `execution_audit_id`, and **`ledger_id`** when the paper path records a position.

Backend guard (for your confidence): `POST /orders/place` returns **400** with code `dry_run_required` if `dry_run=false` and `mode` is not `dry_run` — live placement through this endpoint is rejected at the boundary.

## Verify ledger and summary

- On the **Dashboard**, the **Trading workspace** loads paper ledger rows and a summary (when the read API and tokens are configured).
- After a successful dry-run place, refresh or rely on the UI refresh path and confirm a new row and updated summary figures **without** expecting a broker fill.

## First-week operating routine (suggested)

| Practice | Suggestion |
|----------|------------|
| Scan windows | 1–2 focused sessions per day when markets match your plan |
| Paper orders | Cap at **2 dry-run paper placements per day** while learning the loop |
| Logging | Use [`local-smoke-log-template.md`](local-smoke-log-template.md); mark each setup **took** / **skipped** / **watching** |
| Review | End of week: re-read block reasons, audits, and ledger vs. your notes |

## Stop conditions (pause or go research-only)

- `/readyz` or freshness consistently bad during your trading window  
- Scheduler not running when you expect automation  
- Provider or trust degradation flags dominating results  
- You cannot reconcile audits ↔ ledger ↔ notes  

## Personal cheatsheet

```cmd
scripts\local-clean.bat
scripts\local-clean.bat --yes
scripts\backup-db.bat --dry-run
scripts\backup-db.bat
services\scanner\scripts\run_worker_local.bat
curl -s http://localhost:8005/readyz
```

## Reminder

**Real-money trading remains disabled** on this local paper path. This tool is for **decision support, dry-run execution rehearsal, and ledger/audit practice** — not for live order submission.
