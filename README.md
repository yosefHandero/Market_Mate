# Market Mate Scanner MVP

A personal stock-scanner dashboard that:
- scans a fixed watchlist every 5 minutes
- scores each ticker using price/volume/news/options-flow/SEC catalyst/market context
- stores scan history in SQLite for local development and supports Postgres for production
- exposes a FastAPI service for scans and order previews
- shows a Next.js dashboard with ranking, explanations, and recent history
- can push Telegram alerts and submit orders to Alpaca when you enable execution

## Stack
- Next.js 15 + TypeScript
- FastAPI + httpx + pydantic-settings
- SQLite for local development
- yfinance for lightweight options-chain flow heuristics

## What this MVP now includes
- **Options flow**: nearest-expiry options-chain snapshot, call/put volume ratio, unusual volume-vs-open-interest count, and a simple bullish flow score.
- **Telegram alerts**: sends any result above your score threshold to your bot chat.
- **Broker execution**: order preview and optional Alpaca order placement. Keep `EXECUTION_ENABLED=false` until you are confident.

## Important note on “options flow”
This project uses **yfinance options-chain data** to create a practical options-flow heuristic. It is useful for a personal scanner, but it is **not equivalent to a premium institutional flow feed** that includes exchange-level sweeps, blocks, or aggressor-side labeling.

## Project structure

```
market-mate-scanner/
  apps/web/            # Next.js dashboard
  services/scanner/    # FastAPI scanner service
  db/                  # local sqlite file created here
```

## Quick start

### 1) Scanner service

```bash
cd services/scanner
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
.venv/Scripts/python.exe -m alembic upgrade head   # Linux/macOS: .venv/bin/python -m alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### 1b) Scheduler worker

```bash
cd services/scanner
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m app.worker
```

### 2) Web app

```bash
cd apps/web
cp .env.local.example .env.local
npm install
npm run dev
```

Open:
- Scanner API docs: http://localhost:8000/docs
- Web app: http://localhost:3000

## Environment variables

### Scanner (`services/scanner/.env`)

```env
APP_ENV=development
DATABASE_URL=sqlite:///../../../db/market_mate.db
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
PUBLIC_READ_ACCESS_ENABLED=true
READ_API_TOKEN=
ADMIN_API_TOKEN=

ALPACA_API_KEY=your_key
ALPACA_API_SECRET=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_MARKET_DATA_URL=https://data.alpaca.markets
EXECUTION_ENABLED=false
ALLOW_LIVE_TRADING=false
EXECUTION_DEFAULT_TIME_IN_FORCE=day

MARKETAUX_API_TOKEN=
FINNHUB_API_KEY=your_finnhub_key
SEC_USER_AGENT=Your Name your@email.com

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_ALERTS_ENABLED=false
ALERT_SCORE_THRESHOLD=65

WATCHLIST=AAPL,MSFT,NVDA,AMD,META,AMZN,GOOGL,TSLA,PLTR,COIN,CRM,AVGO,SMCI,NFLX,SHOP,UBER,SNOW,PANW,INTC,ARM,SPY,QQQ
CRYPTO_WATCHLIST=BTC/USD,ETH/USD
SCAN_INTERVAL_SECONDS=300
SCHEDULER_ENABLED=false
```

### Web (`apps/web/.env.local`)

```env
NEXT_PUBLIC_SCANNER_API_BASE=http://localhost:8000
```

## Run a scan manually

```bash
curl -X POST http://localhost:8000/scan/run
```

## Start background scanning

Run the worker and then enable the scheduler via the admin API:

```bash
curl -X POST http://localhost:8000/scan/scheduler/start \
  -H "X-API-Key: your-admin-token"
```

## Preview an order

```bash
curl -X POST http://localhost:8000/orders/preview \
  -H "X-API-Key: your-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA","side":"buy","qty":1,"order_type":"market"}'
```

## Place a dry-run order

```bash
curl -X POST http://localhost:8000/orders/place \
  -H "X-API-Key: your-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA","side":"buy","qty":1,"order_type":"market","dry_run":true,"idempotency_key":"nvda-buy-demo-0001"}'
```

## Notes
- Keep Alpaca in **paper trading** while you validate the scanner. Production execution is guarded by `EXECUTION_ENABLED` and `ALLOW_LIVE_TRADING`.
- Telegram’s Bot API is HTTP based, so once you create a bot token and know your chat ID, alert delivery is straightforward.
- Coinbase’s Advanced Trade API exists for automated crypto orders, but this codebase is currently wired for **stock scanning and Alpaca order execution**, not Coinbase crypto execution.
- Production deployments should run migrations with Alembic before starting the API and worker processes.
- Sensitive routes are now admin-protected; use `ADMIN_API_TOKEN` with either `Authorization: Bearer ...` or `X-API-Key`.

## Next upgrades after this
- real options-flow provider (exchange-level feed)
- multi-broker support
- authenticated dashboard and order journal
- Telegram action buttons or Slack alerts
