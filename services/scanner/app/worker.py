from __future__ import annotations

import asyncio
from contextlib import suppress

from app.dependencies import coinbase_market_data_service, scheduler_service
from app.logging_utils import configure_logging


async def main() -> None:
    configure_logging()
    market_data_task = None
    if coinbase_market_data_service.enabled:
        market_data_task = asyncio.create_task(
            coinbase_market_data_service.run_forever(),
            name="coinbase-advanced-trade-ws-worker",
        )
    try:
        await scheduler_service.run_forever()
    finally:
        if market_data_task is not None:
            coinbase_market_data_service.stop()
            market_data_task.cancel()
            with suppress(asyncio.CancelledError):
                await market_data_task


if __name__ == "__main__":
    asyncio.run(main())
