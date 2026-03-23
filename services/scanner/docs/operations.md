# Scanner Operations

## Process Model

- Run API process with `uvicorn app.main:app`.
- Run scheduler worker separately with `python -m app.worker`.
- Run migrations before either process starts: `python -m alembic upgrade head`.

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
- `GET /readyz`: database and schema readiness.

## Trading Kill Switch

- Set `EXECUTION_ENABLED=false` to disable order submission.
- Keep `ALLOW_LIVE_TRADING=false` unless a live rollout is explicitly approved.
- Revoke or rotate `ADMIN_API_TOKEN` if operator credentials are compromised.

## Migrations

- Create new revision: `python -m alembic revision -m "describe change"`.
- Apply latest migration: `python -m alembic upgrade head`.
- Production rollouts should apply migrations before restarting API/worker processes.
