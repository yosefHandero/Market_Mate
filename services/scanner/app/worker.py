from __future__ import annotations

import asyncio

from app.dependencies import scheduler_service
from app.logging_utils import configure_logging


async def main() -> None:
    configure_logging()
    await scheduler_service.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
