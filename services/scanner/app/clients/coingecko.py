from __future__ import annotations

import httpx

from app.config import get_settings
from app.http_client import request_json
from app.provider_resilience import AsyncProviderGuard

SYMBOL_TO_COINGECKO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "LTC": "litecoin",
    "UNI": "uniswap",
    "SHIB": "shiba-inu",
    "BCH": "bitcoin-cash",
    "AAVE": "aave",
    "POL": "matic-network",
    "PEPE": "pepe",
    "FIL": "filecoin",
    "GRT": "the-graph",
    "RENDER": "render-token",
    "BONK": "bonk",
}


class CoinGeckoClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("coingecko", pace_seconds=1.0)

    def _symbol_to_id(self, symbol: str) -> str | None:
        base_symbol = symbol.split("/", 1)[0].upper()
        return SYMBOL_TO_COINGECKO_ID.get(base_symbol)

    async def get_market_context(self, symbols: list[str]) -> dict[str, dict]:
        ids_by_symbol = {
            symbol: self._symbol_to_id(symbol)
            for symbol in symbols
        }
        valid_pairs = {symbol: coin_id for symbol, coin_id in ids_by_symbol.items() if coin_id}
        if not valid_pairs:
            return {}

        headers = {}
        if self.settings.coingecko_api_key:
            headers["x-cg-demo-api-key"] = self.settings.coingecko_api_key

        params = {
            "vs_currency": "usd",
            "ids": ",".join(sorted(set(valid_pairs.values()))),
            "price_change_percentage": "24h",
        }

        cache_key = ("coins_markets", tuple(sorted(valid_pairs)), tuple(sorted(set(valid_pairs.values()))))
        try:
            payload = await self._guard.cached_call(
                key=cache_key,
                ttl_seconds=self.settings.coingecko_cache_seconds,
                stale_ttl_seconds=max(self.settings.coingecko_cache_seconds * 5, 600),
                fetcher=lambda: self._fetch_market_context(params=params, headers=headers),
            )
        except Exception:
            return {}

        by_id = {item.get("id"): item for item in payload if item.get("id")}
        output: dict[str, dict] = {}
        for symbol, coin_id in valid_pairs.items():
            row = by_id.get(coin_id)
            if not row:
                continue
            output[symbol] = {
                "market_cap_rank": int(row.get("market_cap_rank") or 0) or None,
                "price_change_pct_24h": float(row.get("price_change_percentage_24h_in_currency") or 0.0),
                "market_cap_change_pct_24h": float(row.get("market_cap_change_percentage_24h") or 0.0),
            }
        return output

    async def _fetch_market_context(self, *, params: dict[str, str], headers: dict[str, str]) -> list[dict]:
        await self._guard.throttle()
        payload = await request_json(
            self._client,
            method="GET",
            url=f"{self.settings.coingecko_base_url}/coins/markets",
            params=params,
            headers=headers,
            provider="coingecko",
            on_backoff=self._guard.register_backoff,
        )
        return payload if isinstance(payload, list) else []
