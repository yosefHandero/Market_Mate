from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import httpx

from app.config import get_settings


class AlpacaClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.timeout = self.settings.provider_timeout_seconds
        self.headers = {
            "APCA-API-KEY-ID": self.settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": self.settings.alpaca_api_secret,
        }
        self._async_client = httpx.AsyncClient(timeout=self.timeout)

    def _require_credentials(self) -> None:
        if not self.settings.alpaca_api_key or not self.settings.alpaca_api_secret:
            raise RuntimeError("Missing Alpaca API credentials")

    def _parse_bar_timestamp(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, (int, float)):
            if value > 1_000_000_000_000:
                return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc)
            return datetime.fromtimestamp(value, tz=timezone.utc)
        raise RuntimeError(f"Unsupported bar timestamp format: {value!r}")

    def _build_bars_by_symbol(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        bars_by_symbol: dict[str, dict[str, Any]] = {}
        for symbol, rows in payload.get("bars", {}).items():
            if not rows:
                continue
            parsed_rows = [
                {
                    **row,
                    "_timestamp": self._parse_bar_timestamp(row.get("t")),
                }
                for row in rows
            ]
            latest = rows[-1]
            latest_date = parsed_rows[-1]["_timestamp"].date()
            current_session = [row for row in parsed_rows if row["_timestamp"].date() == latest_date]
            prior_sessions: dict[Any, list[dict[str, Any]]] = {}
            for row in parsed_rows:
                session_date = row["_timestamp"].date()
                if session_date == latest_date:
                    continue
                prior_sessions.setdefault(session_date, []).append(row)

            session_open = float(current_session[0].get("o", 0) or latest.get("o", 0) or 0)
            session_high = max(float(row.get("h", 0) or 0) for row in current_session)
            session_low = min(float(row.get("l", 0) or 0) for row in current_session)
            session_cumulative_volume = sum(float(row.get("v", 0) or 0) for row in current_session)
            bar_index = max(len(current_session) - 1, 0)
            prior_cumulative_samples = []
            for rows_for_day in prior_sessions.values():
                if len(rows_for_day) > bar_index:
                    prior_cumulative_samples.append(
                        sum(float(row.get("v", 0) or 0) for row in rows_for_day[: bar_index + 1])
                    )

            reference_cumulative_volume = (
                sum(prior_cumulative_samples) / len(prior_cumulative_samples)
                if prior_cumulative_samples
                else (
                    sum(float(r.get("v", 0) or 0) for r in rows[:-1] or rows)
                    / max(len(rows[:-1] or rows), 1)
                )
            )
            lookback_rows = parsed_rows[-21:-1] or parsed_rows[:-1] or parsed_rows
            rolling_high = max(float(r.get("h", 0) or 0) for r in lookback_rows)
            rolling_low = min(float(r.get("l", 0) or 0) for r in lookback_rows)
            previous_close = float(
                next(
                    (
                        row.get("c")
                        for row in reversed(parsed_rows[:-len(current_session)] or parsed_rows[:-1])
                        if row.get("c") is not None
                    ),
                    latest.get("o", 0),
                )
                or 0
            )
            vwap_numerator = sum(
                float(row.get("c", 0) or 0) * float(row.get("v", 0) or 0)
                for row in current_session
            )
            vwap_denominator = sum(float(row.get("v", 0) or 0) for row in current_session) or 1
            bars_by_symbol[symbol] = {
                "latest_price": float(latest.get("c", 0)),
                "latest_volume": session_cumulative_volume,
                "average_volume": reference_cumulative_volume or 1,
                "day_open": session_open,
                "session_open": session_open,
                "session_high": session_high,
                "session_low": session_low,
                "rolling_high": rolling_high,
                "rolling_low": rolling_low,
                "previous_close": previous_close,
                "vwap": vwap_numerator / vwap_denominator,
                "session_bar_index": bar_index,
                "bars": rows,
            }
        return bars_by_symbol

    async def get_latest_bars(self, symbols: list[str], timeframe: str = "5Min") -> dict[str, dict[str, Any]]:
        self._require_credentials()

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=3)
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 1000,
            "adjustment": "raw",
            "feed": "iex",
            "sort": "asc",
        }

        url = f"{self.settings.alpaca_market_data_url}/v2/stocks/bars"
        response = await self._async_client.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        payload = response.json()

        return self._build_bars_by_symbol(payload)

    async def get_latest_crypto_bars(
        self,
        symbols: list[str],
        timeframe: str = "5Min",
    ) -> dict[str, dict[str, Any]]:
        self._require_credentials()
        if not symbols:
            return {}

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=3)
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 1000,
            "sort": "asc",
        }
        url = f"{self.settings.alpaca_market_data_url}/v1beta3/crypto/us/bars"
        response = await self._async_client.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        payload = response.json()
        return self._build_bars_by_symbol(payload)

    async def get_latest_price(self, symbol: str) -> float:
        bars = await self.get_latest_bars([symbol], timeframe="1Min")
        item = bars.get(symbol)
        if not item:
            raise RuntimeError(f"No price data returned for {symbol}")
        return float(item["latest_price"])

    async def get_latest_crypto_price(self, symbol: str) -> float:
        bars = await self.get_latest_crypto_bars([symbol], timeframe="1Min")
        item = bars.get(symbol)
        if not item:
            raise RuntimeError(f"No crypto price data returned for {symbol}")
        return float(item["latest_price"])

    async def get_price_near_timestamp(
        self,
        symbol: str,
        target_time: datetime,
        *,
        tolerance_minutes: int = 15,
        timeframe: str = "1Min",
    ) -> float | None:
        self._require_credentials()

        target = (
            target_time.astimezone(timezone.utc)
            if target_time.tzinfo is not None
            else target_time.replace(tzinfo=timezone.utc)
        )
        start = target - timedelta(minutes=tolerance_minutes)
        end = target + timedelta(minutes=tolerance_minutes)
        params = {
            "symbols": symbol.upper(),
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 500,
            "adjustment": "raw",
            "feed": "iex",
            "sort": "asc",
        }

        url = f"{self.settings.alpaca_market_data_url}/v2/stocks/bars"
        response = await self._async_client.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        payload = response.json()

        rows = payload.get("bars", {}).get(symbol.upper(), [])
        if not rows:
            return None

        closest = min(
            rows,
            key=lambda row: abs(
                (self._parse_bar_timestamp(row.get("t")) - target).total_seconds()
            ),
        )
        return float(closest.get("c", 0)) or None

    async def get_price_on_or_after_timestamp(
        self,
        symbol: str,
        target_time: datetime,
        *,
        max_search_minutes: int,
        timeframe: str = "1Min",
    ) -> float | None:
        self._require_credentials()

        target = (
            target_time.astimezone(timezone.utc)
            if target_time.tzinfo is not None
            else target_time.replace(tzinfo=timezone.utc)
        )
        end = target + timedelta(minutes=max_search_minutes)
        params = {
            "symbols": symbol.upper(),
            "timeframe": timeframe,
            "start": target.isoformat(),
            "end": end.isoformat(),
            "limit": 5000,
            "adjustment": "raw",
            "feed": "iex",
            "sort": "asc",
        }

        url = f"{self.settings.alpaca_market_data_url}/v2/stocks/bars"
        response = await self._async_client.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        payload = response.json()

        rows = payload.get("bars", {}).get(symbol.upper(), [])
        if not rows:
            return None

        for row in rows:
            row_time = self._parse_bar_timestamp(row.get("t"))
            if row_time >= target:
                return float(row.get("c", 0)) or None
        return None

    async def get_crypto_price_on_or_after_timestamp(
        self,
        symbol: str,
        target_time: datetime,
        *,
        max_search_minutes: int,
        timeframe: str = "1Min",
    ) -> float | None:
        self._require_credentials()
        target = (
            target_time.astimezone(timezone.utc)
            if target_time.tzinfo is not None
            else target_time.replace(tzinfo=timezone.utc)
        )
        end = target + timedelta(minutes=max_search_minutes)
        params = {
            "symbols": symbol.upper(),
            "timeframe": timeframe,
            "start": target.isoformat(),
            "end": end.isoformat(),
            "limit": 5000,
            "sort": "asc",
        }

        url = f"{self.settings.alpaca_market_data_url}/v1beta3/crypto/us/bars"
        response = await self._async_client.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        payload = response.json()

        rows = payload.get("bars", {}).get(symbol.upper(), [])
        if not rows:
            return None

        for row in rows:
            row_time = self._parse_bar_timestamp(row.get("t"))
            if row_time >= target:
                return float(row.get("c", 0)) or None
        return None

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "market",
        time_in_force: str | None = None,
        limit_price: float | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self._require_credentials()
        payload: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": order_type,
            "qty": round(qty, 6),
            "time_in_force": time_in_force or self.settings.execution_default_time_in_force,
        }
        if order_type == "limit":
            if limit_price is None:
                raise RuntimeError("limit_price is required for limit orders")
            payload["limit_price"] = round(limit_price, 4)
        if idempotency_key:
            payload["client_order_id"] = idempotency_key[:48]

        response = await self._async_client.post(
            f"{self.settings.alpaca_base_url}/v2/orders",
            json=payload,
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()
