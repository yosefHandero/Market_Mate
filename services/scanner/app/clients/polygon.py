from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.http_client import request_json
from app.provider_resilience import AsyncProviderGuard

_TIMEFRAME_TO_POLYGON = {
    "1Min": (1, "minute"),
    "5Min": (5, "minute"),
    "1Hour": (1, "hour"),
    "1Day": (1, "day"),
}


class PolygonClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("polygon", pace_seconds=0.15)

    def _require_credentials(self) -> None:
        if not self.settings.polygon_api_key:
            raise RuntimeError("Missing Polygon API key")

    @staticmethod
    def _parse_timeframe(timeframe: str) -> tuple[int, str]:
        return _TIMEFRAME_TO_POLYGON.get(timeframe, (5, "minute"))

    @staticmethod
    def _polygon_ticker(symbol: str) -> str:
        return symbol.strip().upper()

    @staticmethod
    def _polygon_crypto_ticker(symbol: str) -> str:
        cleaned = symbol.strip().upper().replace("-", "/")
        if "/" in cleaned:
            base, quote = cleaned.split("/", 1)
        else:
            base, quote = cleaned, "USD"
        return f"X:{base}{quote}"

    @staticmethod
    def _rows_to_alpaca_bars(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in results:
            timestamp_ms = row.get("t")
            if timestamp_ms is None:
                continue
            parsed = datetime.fromtimestamp(float(timestamp_ms) / 1000.0, tz=timezone.utc)
            rows.append(
                {
                    "t": parsed.isoformat(),
                    "o": row.get("o"),
                    "h": row.get("h"),
                    "l": row.get("l"),
                    "c": row.get("c"),
                    "v": row.get("v"),
                }
            )
        return rows

    async def _fetch_symbol_bars(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        multiplier, timespan = self._parse_timeframe(timeframe)
        ticker = self._polygon_ticker(symbol)
        from_ms = int(start.timestamp() * 1000)
        to_ms = int(end.timestamp() * 1000)
        await self._guard.throttle()
        payload = await request_json(
            self._client,
            method="GET",
            url=(
                f"{self.settings.polygon_base_url}/v2/aggs/ticker/{ticker}/range/"
                f"{multiplier}/{timespan}/{from_ms}/{to_ms}"
            ),
            params={
                "adjusted": "true",
                "sort": "asc",
                "limit": limit,
                "apiKey": self.settings.polygon_api_key,
            },
            provider="polygon",
            on_backoff=self._guard.register_backoff,
        )
        if payload.get("status") not in {None, "OK", "ok"} and not payload.get("results"):
            message = payload.get("error") or payload.get("message") or "unexpected Polygon response"
            raise RuntimeError(f"Polygon returned no bars for {symbol}: {message}")
        return self._rows_to_alpaca_bars(list(payload.get("results") or []))

    async def get_latest_bars(
        self,
        symbols: list[str],
        timeframe: str = "5Min",
        *,
        bar_builder: Callable[[dict[str, Any]], dict[str, dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        self._require_credentials()
        if not symbols:
            return {}

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=3)
        limit = 1000

        async def fetch_one(symbol: str) -> tuple[str, list[dict[str, Any]]]:
            rows = await self._fetch_symbol_bars(
                symbol=symbol,
                start=start,
                end=end,
                timeframe=timeframe,
                limit=limit,
            )
            return symbol.upper(), rows

        pairs = await asyncio.gather(*(fetch_one(symbol) for symbol in symbols))
        alpaca_payload = {
            "bars": {symbol: rows for symbol, rows in pairs if rows},
        }
        return bar_builder(alpaca_payload)

    async def get_historical_bars(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "1Day",
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        self._require_credentials()
        return await self._fetch_symbol_bars(
            symbol=symbol,
            start=start,
            end=end,
            timeframe=timeframe,
            limit=limit,
        )

    async def get_historical_crypto_bars(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "1Day",
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        self._require_credentials()
        return await self._fetch_symbol_bars(
            symbol=self._polygon_crypto_ticker(symbol),
            start=start,
            end=end,
            timeframe=timeframe,
            limit=limit,
        )
