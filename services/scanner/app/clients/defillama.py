from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.http_client import request_json
from app.provider_models import DefiLlamaSnapshot
from app.provider_resilience import AsyncProviderGuard


class DefiLlamaClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("defillama", pace_seconds=0.25)

    async def get_macro_snapshot(self) -> DefiLlamaSnapshot:
        try:
            return await self._guard.cached_call(
                key=("defillama_macro_snapshot",),
                ttl_seconds=self.settings.defillama_cache_seconds,
                stale_ttl_seconds=max(self.settings.defillama_cache_seconds * 4, 3600),
                fetcher=self._fetch_macro_snapshot,
            )
        except Exception as exc:
            return DefiLlamaSnapshot(
                source="defillama",
                available=False,
                warnings=(f"defillama_unavailable:{type(exc).__name__}",),
            )

    async def _fetch_macro_snapshot(self) -> DefiLlamaSnapshot:
        await self._guard.throttle()
        chains_payload, stablecoins_payload = await self._fetch_payloads()

        chains = chains_payload if isinstance(chains_payload, list) else []
        positive_chains = 0
        negative_chains = 0
        tvl_change_sum = 0.0
        tvl_change_count = 0
        for row in chains[:50]:
            change_7d = row.get("change_7d")
            if change_7d is None:
                continue
            try:
                change = float(change_7d)
            except (TypeError, ValueError):
                continue
            tvl_change_sum += change
            tvl_change_count += 1
            if change > 0:
                positive_chains += 1
            elif change < 0:
                negative_chains += 1

        positive_chain_breadth = (
            (positive_chains / max(positive_chains + negative_chains, 1)) * 100
            if (positive_chains + negative_chains) > 0
            else None
        )
        total_tvl_change_pct_7d = (tvl_change_sum / tvl_change_count) if tvl_change_count else None

        stablecoin_growth_pct_7d = None
        warnings: list[str] = []
        if isinstance(stablecoins_payload, dict):
            current_total = float(stablecoins_payload.get("totalCirculatingUSD") or 0.0)
            total_1w_ago = float(stablecoins_payload.get("totalCirculatingUSDPrevWeek") or 0.0)
            if current_total > 0 and total_1w_ago > 0:
                stablecoin_growth_pct_7d = ((current_total - total_1w_ago) / total_1w_ago) * 100
            else:
                warnings.append("defillama_stablecoin_growth_unavailable")
        else:
            warnings.append("defillama_stablecoin_payload_unavailable")

        supportive_score = 0.0
        if stablecoin_growth_pct_7d is not None:
            supportive_score += max(min(stablecoin_growth_pct_7d / 8.0, 0.5), -0.5)
        if total_tvl_change_pct_7d is not None:
            supportive_score += max(min(total_tvl_change_pct_7d / 12.0, 0.35), -0.35)
        if positive_chain_breadth is not None:
            supportive_score += max(min((positive_chain_breadth - 50.0) / 100.0, 0.25), -0.25)

        return DefiLlamaSnapshot(
            source="defillama",
            available=bool(chains),
            stale=False,
            as_of=datetime.now(timezone.utc),
            warnings=tuple(warnings),
            stablecoin_growth_pct_7d=round(stablecoin_growth_pct_7d, 4) if stablecoin_growth_pct_7d is not None else None,
            total_tvl_change_pct_7d=round(total_tvl_change_pct_7d, 4) if total_tvl_change_pct_7d is not None else None,
            positive_chain_breadth_pct=round(positive_chain_breadth, 4) if positive_chain_breadth is not None else None,
            supportive_score=round(supportive_score, 4),
        )

    async def _fetch_payloads(self) -> tuple[object, object]:
        chains_task = request_json(
            self._client,
            method="GET",
            url=f"{self.settings.defillama_base_url}/v2/chains",
            provider="defillama",
            on_backoff=self._guard.register_backoff,
        )
        stablecoins_task = request_json(
            self._client,
            method="GET",
            url=self.settings.defillama_stablecoins_url,
            provider="defillama",
            on_backoff=self._guard.register_backoff,
        )
        return await asyncio.gather(chains_task, stablecoins_task)

