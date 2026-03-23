from __future__ import annotations

import httpx

from app.config import get_settings
from app.http_client import request_json

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
}


class CoinGeckoClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)

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

        try:
            payload = await request_json(
                self._client,
                method="GET",
                url=f"{self.settings.coingecko_base_url}/coins/markets",
                params=params,
                headers=headers,
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
