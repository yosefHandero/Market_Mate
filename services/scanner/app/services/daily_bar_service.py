from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.clients.alpaca import AlpacaClient
from app.clients.polygon import PolygonClient
from app.config import Settings, get_settings
from app.core.weekly_bar_utils import parse_bar_timestamp, sorted_bars

logger = logging.getLogger(__name__)


class DailyBarService:
    def __init__(
        self,
        *,
        alpaca: AlpacaClient | None = None,
        polygon: PolygonClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.alpaca = alpaca or AlpacaClient()
        self.polygon = polygon or PolygonClient()

    def _cache_path(self, symbol: str, asset_type: str) -> Path:
        safe_symbol = symbol.replace("/", "_").upper()
        return self.settings.cache_dir_path / "daily_bars" / asset_type / f"{safe_symbol}.json"

    def _read_cache(self, path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception:
            logger.warning("daily_bar_cache_read_failed", extra={"path": str(path)}, exc_info=True)
            return None
        return payload if isinstance(payload, dict) else None

    def _cache_fresh(self, payload: dict[str, Any]) -> bool:
        fetched_at = payload.get("fetched_at")
        if not fetched_at:
            return False
        try:
            parsed = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        age_seconds = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
        return age_seconds <= max(self.settings.weekly_daily_bar_cache_ttl_seconds, 60)

    def _write_cache(self, path: Path, *, symbol: str, asset_type: str, bars: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "symbol": symbol.upper(),
            "asset_type": asset_type,
            "timeframe": "1Day",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "bars": bars,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _trim_bars(self, bars: list[dict[str, Any]], *, max_bars: int) -> list[dict[str, Any]]:
        ordered = sorted_bars(bars)
        if len(ordered) <= max_bars:
            return ordered
        return ordered[-max_bars:]

    async def _fetch_alpaca_daily(
        self,
        symbol: str,
        *,
        asset_type: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        if asset_type == "crypto":
            return await self.alpaca.get_historical_crypto_bars(
                symbol,
                start=start,
                end=end,
                timeframe="1Day",
                limit=limit,
            )
        return await self.alpaca.get_historical_stock_bars(
            symbol,
            start=start,
            end=end,
            timeframe="1Day",
            limit=limit,
        )

    async def _fetch_polygon_daily(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        return await self.polygon.get_historical_bars(
            symbol,
            start=start,
            end=end,
            timeframe="1Day",
            limit=limit,
        )

    async def get_daily_bars(
        self,
        symbol: str,
        *,
        asset_type: str | None = None,
        force_refresh: bool = False,
    ) -> tuple[list[dict[str, Any]], str]:
        normalized_symbol = symbol.upper()
        resolved_asset_type = asset_type or ("crypto" if "/" in normalized_symbol else "stock")
        cache_path = self._cache_path(normalized_symbol, resolved_asset_type)
        if not force_refresh:
            cached = self._read_cache(cache_path)
            if cached and self._cache_fresh(cached):
                bars = list(cached.get("bars") or [])
                return self._trim_bars(bars, max_bars=self.settings.weekly_daily_lookback_bars_max), "cache"

        end = datetime.now(timezone.utc)
        lookback_calendar_days = int(self.settings.weekly_daily_lookback_bars_max * 1.6)
        start = end - timedelta(days=max(lookback_calendar_days, 365))
        limit = min(max(self.settings.weekly_daily_lookback_bars_max, 500), 5000)
        source = "alpaca"
        bars: list[dict[str, Any]] = []
        try:
            bars = await self._fetch_alpaca_daily(
                normalized_symbol,
                asset_type=resolved_asset_type,
                start=start,
                end=end,
                limit=limit,
            )
        except Exception as alpaca_error:
            if resolved_asset_type != "stock" or not self.settings.polygon_api_key:
                raise alpaca_error
            bars = await self._fetch_polygon_daily(
                normalized_symbol,
                start=start,
                end=end,
                limit=limit,
            )
            source = "polygon"

        trimmed = self._trim_bars(bars, max_bars=self.settings.weekly_daily_lookback_bars_max)
        if trimmed:
            self._write_cache(
                cache_path,
                symbol=normalized_symbol,
                asset_type=resolved_asset_type,
                bars=trimmed,
            )
        return trimmed, source

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
