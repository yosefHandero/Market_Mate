from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.crypto_symbols import to_binance_symbol
from app.http_client import request_json
from app.provider_models import BinanceMicrostructureSnapshot
from app.provider_resilience import AsyncProviderGuard


class BinanceClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("binance", pace_seconds=0.1)

    async def get_microstructure_batch(
        self,
        symbols: list[str],
    ) -> dict[str, BinanceMicrostructureSnapshot]:
        results = await asyncio.gather(*(self.get_microstructure(symbol) for symbol in symbols))
        return {symbol: snapshot for symbol, snapshot in results}

    async def get_microstructure(self, symbol: str) -> tuple[str, BinanceMicrostructureSnapshot]:
        normalized_symbol = symbol.upper()
        exchange_symbol = to_binance_symbol(normalized_symbol)
        try:
            snapshot = await self._guard.cached_call(
                key=("binance_microstructure", exchange_symbol),
                ttl_seconds=self.settings.binance_cache_seconds,
                stale_ttl_seconds=max(self.settings.binance_cache_seconds * 4, 15),
                fetcher=lambda: self._fetch_microstructure(normalized_symbol, exchange_symbol),
            )
        except Exception as exc:
            return normalized_symbol, BinanceMicrostructureSnapshot(
                source="binance",
                available=False,
                warnings=(f"binance_unavailable:{type(exc).__name__}",),
            )
        return normalized_symbol, snapshot

    async def _fetch_microstructure(
        self,
        symbol: str,
        exchange_symbol: str,
    ) -> BinanceMicrostructureSnapshot:
        await self._guard.throttle()
        book_ticker, depth, trades = await asyncio.gather(
            request_json(
                self._client,
                method="GET",
                url=f"{self.settings.binance_base_url}/api/v3/ticker/bookTicker",
                params={"symbol": exchange_symbol},
                provider="binance",
                on_backoff=self._guard.register_backoff,
            ),
            request_json(
                self._client,
                method="GET",
                url=f"{self.settings.binance_base_url}/api/v3/depth",
                params={"symbol": exchange_symbol, "limit": 20},
                provider="binance",
                on_backoff=self._guard.register_backoff,
            ),
            request_json(
                self._client,
                method="GET",
                url=f"{self.settings.binance_base_url}/api/v3/trades",
                params={"symbol": exchange_symbol, "limit": 40},
                provider="binance",
                on_backoff=self._guard.register_backoff,
            ),
        )

        best_bid = float(book_ticker.get("bidPrice") or 0.0)
        best_ask = float(book_ticker.get("askPrice") or 0.0)
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0.0
        spread_bps = ((best_ask - best_bid) / mid) * 10000 if mid else None

        bids = depth.get("bids") or []
        asks = depth.get("asks") or []
        bid_size = sum(float(level[1]) for level in bids[:10] if len(level) >= 2)
        ask_size = sum(float(level[1]) for level in asks[:10] if len(level) >= 2)
        denom = bid_size + ask_size
        book_imbalance = ((bid_size - ask_size) / denom) if denom else 0.0

        buy_volume = sum(float(row.get("qty") or 0.0) for row in trades if not bool(row.get("isBuyerMaker")))
        sell_volume = sum(float(row.get("qty") or 0.0) for row in trades if bool(row.get("isBuyerMaker")))
        trade_denom = buy_volume + sell_volume
        aggressor_pressure = ((buy_volume - sell_volume) / trade_denom) if trade_denom else 0.0

        warnings: list[str] = []
        if spread_bps is not None and spread_bps >= 12:
            warnings.append("binance_spread_wide")
        if abs(book_imbalance) < 0.03:
            warnings.append("binance_book_balanced")

        return BinanceMicrostructureSnapshot(
            source="binance",
            available=True,
            stale=False,
            as_of=datetime.now(timezone.utc),
            warnings=tuple(warnings),
            best_bid=round(best_bid, 8) if best_bid else None,
            best_ask=round(best_ask, 8) if best_ask else None,
            spread_bps=round(spread_bps, 4) if spread_bps is not None else None,
            book_imbalance=round(book_imbalance, 4),
            aggressor_pressure=round(aggressor_pressure, 4),
        )

