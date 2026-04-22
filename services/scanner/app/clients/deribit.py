from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.crypto_symbols import to_deribit_currency
from app.http_client import request_json
from app.provider_models import DeribitPositioningSnapshot
from app.provider_resilience import AsyncProviderGuard


class DeribitClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("deribit", pace_seconds=0.15)

    async def get_positioning_batch(
        self,
        symbols: list[str],
    ) -> dict[str, DeribitPositioningSnapshot]:
        results = await asyncio.gather(*(self.get_positioning(symbol) for symbol in symbols))
        return {symbol: snapshot for symbol, snapshot in results}

    async def get_positioning(self, symbol: str) -> tuple[str, DeribitPositioningSnapshot]:
        normalized_symbol = symbol.upper()
        currency = to_deribit_currency(normalized_symbol)
        try:
            snapshot = await self._guard.cached_call(
                key=("deribit_positioning", currency),
                ttl_seconds=self.settings.deribit_cache_seconds,
                stale_ttl_seconds=max(self.settings.deribit_cache_seconds * 4, 90),
                fetcher=lambda: self._fetch_positioning(normalized_symbol, currency),
            )
        except Exception as exc:
            return normalized_symbol, DeribitPositioningSnapshot(
                source="deribit",
                available=False,
                warnings=(f"deribit_unavailable:{type(exc).__name__}",),
            )
        return normalized_symbol, snapshot

    async def _fetch_positioning(self, symbol: str, currency: str) -> DeribitPositioningSnapshot:
        await self._guard.throttle()
        futures_payload, options_payload = await asyncio.gather(
            request_json(
                self._client,
                method="GET",
                url=f"{self.settings.deribit_base_url}/get_book_summary_by_currency",
                params={"currency": currency, "kind": "future"},
                provider="deribit",
                on_backoff=self._guard.register_backoff,
            ),
            request_json(
                self._client,
                method="GET",
                url=f"{self.settings.deribit_base_url}/get_book_summary_by_currency",
                params={"currency": currency, "kind": "option"},
                provider="deribit",
                on_backoff=self._guard.register_backoff,
            ),
        )

        futures = futures_payload.get("result") or []
        options = options_payload.get("result") or []
        perp = next(
            (row for row in futures if "PERPETUAL" in str(row.get("instrument_name", "")).upper()),
            None,
        )
        underlying = float((perp or {}).get("underlying_price") or 0.0)
        mark_price = float((perp or {}).get("mark_price") or 0.0)
        perp_premium_pct = (((mark_price - underlying) / underlying) * 100) if underlying and mark_price else 0.0
        total_open_interest_usd = 0.0
        for row in futures:
            open_interest = float(row.get("open_interest") or 0.0)
            reference_price = float(row.get("underlying_price") or row.get("mark_price") or 0.0)
            total_open_interest_usd += open_interest * reference_price

        call_oi = 0.0
        put_oi = 0.0
        call_iv_total = 0.0
        put_iv_total = 0.0
        call_iv_count = 0
        put_iv_count = 0
        for row in options:
            instrument_name = str(row.get("instrument_name", "")).upper()
            open_interest = float(row.get("open_interest") or 0.0)
            mark_iv = float(row.get("mark_iv") or 0.0)
            if "-C" in instrument_name:
                call_oi += open_interest
                if mark_iv > 0:
                    call_iv_total += mark_iv
                    call_iv_count += 1
            elif "-P" in instrument_name:
                put_oi += open_interest
                if mark_iv > 0:
                    put_iv_total += mark_iv
                    put_iv_count += 1

        put_call_ratio = put_oi / max(call_oi, 1.0)
        avg_call_iv = call_iv_total / call_iv_count if call_iv_count else 0.0
        avg_put_iv = put_iv_total / put_iv_count if put_iv_count else 0.0
        options_skew_bias = ((avg_put_iv - avg_call_iv) / max(avg_call_iv, 1.0)) if avg_call_iv else 0.0
        crowding_score = max(min((perp_premium_pct / 3.0) - ((put_call_ratio - 1.0) * 0.35), 1.0), -1.0)

        warnings: list[str] = []
        if abs(crowding_score) >= 0.55:
            warnings.append("deribit_crowding_extreme")
        if total_open_interest_usd <= 0:
            warnings.append("deribit_open_interest_unavailable")

        return DeribitPositioningSnapshot(
            source="deribit",
            available=True,
            stale=False,
            as_of=datetime.now(timezone.utc),
            warnings=tuple(warnings),
            perp_premium_pct=round(perp_premium_pct, 4),
            funding_bias=round(perp_premium_pct, 4),
            open_interest_usd=round(total_open_interest_usd, 2),
            put_call_open_interest_ratio=round(put_call_ratio, 4),
            options_skew_bias=round(options_skew_bias, 4),
            crowding_score=round(crowding_score, 4),
        )

