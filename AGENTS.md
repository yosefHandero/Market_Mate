# Agent conventions — Market Mate Scanner

## What this repo is

Local, personal, **paper-only** dry-run decision-support app. BUY-only Decision page + Proof page. No broker order submission exists or may be enabled.

Two outcomes must stay separate:

1. **Application completion** — code, ops, and verification (Phases 2–5).
2. **Real-money pilot confidence** — untouched live-forward evidence after completion. Never equate completion with readiness.

## Layout

- `apps/web` — Next.js 15 Decision (`/`) and Proof (`/proof`) UI
- `services/scanner` — FastAPI scanner API, worker, walk-forward, campaigns
- `scripts/windows` — wake-and-scan Task Scheduler tasks, backup, health checks

## Hard rules

- Never add live broker submission (`/v2/orders`, `submit_order`, trading API base URL).
- `EXECUTION_ENABLED` / `ALLOW_LIVE_TRADING` must stay false; Settings rejects truthy values.
- Orders are dry-run only (`mode: "dry_run"`, `dry_run: true`).
- Do not mix evidence tracks. Use the shared contract in `app/core/evidence_contract.py`.
- A strategy/config fingerprint change must open a new evidence campaign.
- Prefer additive Alembic migrations; never destructive schema rewrites for personal DB compatibility.
- Earlier phases: targeted tests only. Broad verification belongs in Phase 5.

## Commands

```bash
# Backend
cd services/scanner
pip install -r requirements.txt
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8005
python -m app.worker
python -m unittest discover -s tests

# Frontend
npm --prefix apps/web run dev
npm --prefix apps/web test
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

## Evidence tracks (canonical)

`walk_forward_research` · `walk_forward_holdout` · `historical_replay` · `paper_execution` · `live_forward` · `real_money_pilot`

Only `live_forward` (and a future `real_money_pilot`) count toward a manual pilot decision.
