from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.brain.weekly_bar_utils import parse_bar_timestamp, sorted_bars
from app.clients.alpaca import AlpacaClient
from app.clients.polygon import PolygonClient
from app.config import Settings, get_settings
from app.services.historical_bar_store import HistoricalBarStore

logger = logging.getLogger(__name__)


class DailyBarService:
    """Live access to the single point-in-time daily-bar spine.

    Serves bars from :class:`HistoricalBarStore` - the same store replay and
    the walk-forward proof engine read - so live decisions, replay backfill,
    and historical proof all see identical history: split-adjusted stocks,
    Polygon-deepened crypto, and auditable in-place bar revisions. There is no
    separate JSON file cache anymore; the store is the cache. A per-process
    TTL memo bounds how often the provider tail-refresh runs per symbol.
    """

    def __init__(
        self,
        *,
        alpaca: AlpacaClient | None = None,
        polygon: PolygonClient | None = None,
        settings: Settings | None = None,
        bar_store: HistoricalBarStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.bar_store = bar_store or HistoricalBarStore(
            alpaca=alpaca, polygon=polygon, settings=self.settings
        )
        self._tail_checked_at: dict[tuple[str, str], datetime] = {}

    def _refresh_due(self, key: tuple[str, str], now: datetime) -> bool:
        checked = self._tail_checked_at.get(key)
        if checked is None:
            return True
        ttl_seconds = max(int(self.settings.weekly_daily_bar_cache_ttl_seconds), 60)
        return (now - checked).total_seconds() > ttl_seconds

    def _trim_bars(self, bars: list[dict[str, Any]], *, max_bars: int) -> list[dict[str, Any]]:
        ordered = sorted_bars(bars)
        if len(ordered) <= max_bars:
            return ordered
        return ordered[-max_bars:]

    async def get_daily_bars(
        self,
        symbol: str,
        *,
        asset_type: str | None = None,
        force_refresh: bool = False,
    ) -> tuple[list[dict[str, Any]], str]:
        normalized_symbol = symbol.upper()
        resolved_asset_type = HistoricalBarStore.resolve_asset_type(normalized_symbol, asset_type)
        key = (normalized_symbol, resolved_asset_type)
        now = datetime.now(timezone.utc)

        if force_refresh or self._refresh_due(key, now):
            bars = await self.bar_store.ensure_recent_tail(
                normalized_symbol, asset_type=resolved_asset_type
            )
            self._tail_checked_at[key] = now
            source = "store_refreshed"
        else:
            bars = self.bar_store.load_bars(normalized_symbol, asset_type=resolved_asset_type)
            source = "store"

        return (
            self._trim_bars(bars, max_bars=self.settings.weekly_daily_lookback_bars_max),
            source,
        )

    def _max_age_days(self, asset_type: str | None) -> int:
        if (asset_type or "stock") == "crypto":
            return max(int(self.settings.weekly_daily_bar_max_age_days_crypto), 1)
        return max(int(self.settings.weekly_daily_bar_max_age_days_stock), 1)

    def latest_bar_age_days(
        self,
        bars: list[dict[str, Any]],
        *,
        as_of: datetime | None = None,
    ) -> float | None:
        try:
            latest = self.latest_bar_as_of(bars)
        except Exception:
            return None
        if latest is None:
            return None
        reference = as_of or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        return max((reference - latest).total_seconds() / 86400.0, 0.0)

    def is_daily_bars_stale(
        self,
        bars: list[dict[str, Any]],
        *,
        asset_type: str | None = None,
        as_of: datetime | None = None,
    ) -> bool:
        age_days = self.latest_bar_age_days(bars, as_of=as_of)
        if age_days is None:
            return True
        return age_days > self._max_age_days(asset_type)

    def assess_data_quality(
        self,
        bars: list[dict[str, Any]],
        *,
        asset_type: str | None = None,
        as_of: datetime | None = None,
    ) -> str:
        count = len(bars)
        if count >= self.settings.weekly_daily_lookback_bars_preferred:
            count_quality = "ok"
        elif count >= self.settings.weekly_daily_lookback_bars_min:
            count_quality = "low"
        else:
            count_quality = "degraded"
        if self.is_daily_bars_stale(bars, asset_type=asset_type, as_of=as_of):
            return "degraded" if count_quality == "degraded" else "low"
        return count_quality

    def latest_bar_as_of(self, bars: list[dict[str, Any]]) -> datetime | None:
        if not bars:
            return None
        return parse_bar_timestamp(sorted_bars(bars)[-1].get("t"))
