from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.schemas import ReplayRequest
from app.services.replay import ReplayService


async def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Backfill weekly pattern evidence for calibration.")
    parser.add_argument(
        "--days",
        type=int,
        default=730,
        help="Lookback window in calendar days for weekly replay backfill.",
    )
    args = parser.parse_args()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(args.days, 30))
    symbols = settings.watchlist_items + settings.crypto_watchlist_items
    service = ReplayService()
    response = await service.replay_and_persist(
        ReplayRequest(
            symbols=symbols,
            start=start,
            end=end,
            interval_minutes=7 * 24 * 60,
            warmup_bars=max(settings.weekly_daily_lookback_bars_min // 4, 60),
            replay_mode="weekly",
            sample_source="backfilled_replay",
            persist_outcomes=True,
            apply_friction=True,
        )
    )
    print(
        f"weekly_backfill_complete snapshots={response.summary.total_snapshots} "
        f"actionable={response.summary.actionable_signals} win_rate={response.summary.win_rate}"
    )


if __name__ == "__main__":
    asyncio.run(main())
