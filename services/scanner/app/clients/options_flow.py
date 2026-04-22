from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import math

import httpx
import yfinance as yf
from yahooquery import Ticker

from app.config import get_settings
from app.http_client import parse_json_response
from app.provider_resilience import AsyncProviderGuard
from app.schemas import OptionsFlowSnapshot


@dataclass
class _ContractSignal:
    volume: int
    open_interest: int

    @property
    def volume_oi_ratio(self) -> float:
        return self.volume / max(self.open_interest, 1)


class OptionsFlowClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._guard = AsyncProviderGuard("options_flow", pace_seconds=0.5)

    async def get_flow_snapshot(self, ticker: str) -> OptionsFlowSnapshot:
        normalized = ticker.upper()
        return await self._guard.cached_call(
            key=("options_flow", normalized),
            ttl_seconds=self.settings.options_flow_cache_seconds,
            stale_ttl_seconds=max(self.settings.options_flow_cache_seconds * 3, 900),
            fetcher=lambda: asyncio.to_thread(self._get_flow_snapshot_sync, normalized),
        )

    def _get_flow_snapshot_sync(self, ticker: str) -> OptionsFlowSnapshot:
        errors: list[str] = []

        try:
            if self.settings.marketdata_api_token:
                return self._get_marketdata_snapshot_sync(ticker)
        except Exception as exc:
            errors.append(f"MarketData.app failed: {exc}")

        try:
            return self._get_yahooquery_snapshot_sync(ticker)
        except Exception as exc:
            errors.append(f"yahooquery failed: {exc}")

        try:
            return self._get_yfinance_snapshot_sync(ticker)
        except Exception as exc:
            errors.append(f"yfinance failed: {exc}")
            return OptionsFlowSnapshot(summary="Options flow unavailable: " + "; ".join(errors))

    def _get_marketdata_snapshot_sync(self, ticker: str) -> OptionsFlowSnapshot:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.settings.marketdata_api_token}",
        }
        url = f"https://api.marketdata.app/v1/options/chain/{ticker.upper()}/"
        with httpx.Client(timeout=self.settings.provider_timeout_seconds, headers=headers) as client:
            response = client.get(url)
            payload = parse_json_response(response, provider="marketdata.app", url=url)

        if payload.get("s") != "ok":
            raise RuntimeError(payload.get("errmsg") or payload.get("error") or "unexpected MarketData.app response")

        expirations = payload.get("expiration") or []
        sides = payload.get("side") or []
        volumes = payload.get("volume") or []
        open_interest = payload.get("openInterest") or []

        if not expirations or not sides:
            return OptionsFlowSnapshot(summary="No listed options for this symbol.")

        first_expiry = min(expirations)
        expiry = datetime.fromtimestamp(first_expiry, tz=timezone.utc).date().isoformat()
        calls: list[dict] = []
        puts: list[dict] = []

        for idx, expiry_value in enumerate(expirations):
            if expiry_value != first_expiry:
                continue
            row = {
                "volume": self._coerce_number(volumes[idx] if idx < len(volumes) else 0),
                "openInterest": self._coerce_number(open_interest[idx] if idx < len(open_interest) else 0),
            }
            side = str(sides[idx]).lower() if idx < len(sides) else ""
            if side == "call":
                calls.append(row)
            elif side == "put":
                puts.append(row)

        return self._build_snapshot(expiry=expiry, calls=calls, puts=puts)

    def _get_yahooquery_snapshot_sync(self, ticker: str) -> OptionsFlowSnapshot:
        chain = Ticker(ticker).option_chain
        if chain is None or getattr(chain, "empty", True):
            return OptionsFlowSnapshot(summary="No listed options for this symbol.")

        normalized = chain.reset_index().fillna(0)
        expiries = normalized["expiration"]
        if expiries.empty:
            return OptionsFlowSnapshot(summary="No listed options for this symbol.")

        first_expiry = expiries.min()
        expiry = first_expiry.date().isoformat() if hasattr(first_expiry, "date") else str(first_expiry)
        nearest_rows = normalized[normalized["expiration"] == first_expiry]
        calls = nearest_rows[nearest_rows["optionType"].isin(["call", "calls"])].to_dict("records")
        puts = nearest_rows[nearest_rows["optionType"].isin(["put", "puts"])].to_dict("records")
        return self._build_snapshot(expiry=expiry, calls=calls, puts=puts)

    def _get_yfinance_snapshot_sync(self, ticker: str) -> OptionsFlowSnapshot:
        yf_ticker = yf.Ticker(ticker)
        expiries = list(yf_ticker.options or [])
        if not expiries:
            return OptionsFlowSnapshot(summary="No listed options for this symbol.")

        expiry = expiries[0]
        chain = yf_ticker.option_chain(expiry)
        calls = chain.calls.fillna(0).to_dict("records")
        puts = chain.puts.fillna(0).to_dict("records")
        return self._build_snapshot(expiry=expiry, calls=calls, puts=puts)

    def _build_snapshot(
        self,
        *,
        expiry: str,
        calls: list[dict],
        puts: list[dict],
    ) -> OptionsFlowSnapshot:
        call_volume = sum(self._coerce_int(row.get("volume", 0)) for row in calls)
        put_volume = sum(self._coerce_int(row.get("volume", 0)) for row in puts)
        call_oi = sum(self._coerce_int(row.get("openInterest", 0)) for row in calls)
        put_oi = sum(self._coerce_int(row.get("openInterest", 0)) for row in puts)

        call_unusual_count = 0
        put_unusual_count = 0
        for row in calls:
            signal = _ContractSignal(
                self._coerce_int(row.get("volume", 0)),
                self._coerce_int(row.get("openInterest", 0)),
            )
            if signal.volume >= 100 and signal.volume_oi_ratio >= 2:
                call_unusual_count += 1
        for row in puts:
            signal = _ContractSignal(
                self._coerce_int(row.get("volume", 0)),
                self._coerce_int(row.get("openInterest", 0)),
            )
            if signal.volume >= 100 and signal.volume_oi_ratio >= 2:
                put_unusual_count += 1
        unusual_contract_count = call_unusual_count + put_unusual_count

        put_call_ratio = round(put_volume / max(call_volume, 1), 2)
        total_volume = max(call_volume + put_volume, 1)
        directional_score = (call_volume - put_volume) / total_volume if total_volume > 0 else 0.0
        call_pressure = call_volume / total_volume
        put_pressure = put_volume / total_volume
        bullish_unusual_bonus = min(call_unusual_count / 4, 1.0)
        bearish_unusual_bonus = min(put_unusual_count / 4, 1.0)
        bullish_score = round(
            max(0.0, min(1.0, (call_pressure * 0.7) + (max(directional_score, 0) * 0.15) + (bullish_unusual_bonus * 0.15))) * 10,
            2,
        )
        bearish_score = round(
            max(0.0, min(1.0, (put_pressure * 0.7) + (max(-directional_score, 0) * 0.15) + (bearish_unusual_bonus * 0.15))) * 10,
            2,
        )

        if call_volume == 0 and put_volume == 0:
            summary = f"Options listed for {expiry}, but no meaningful volume yet."
        elif put_call_ratio <= 0.7:
            summary = f"bullish options flow on {expiry} with calls leading puts {call_volume:,} to {put_volume:,}"
        elif put_call_ratio >= 1.3:
            summary = f"bearish options flow on {expiry} with puts leading calls {put_volume:,} to {call_volume:,}"
        else:
            summary = f"mixed options flow on {expiry}; call/put volume is balanced"

        if unusual_contract_count:
            summary += f" and {unusual_contract_count} contract(s) show unusual volume vs open interest"

        return OptionsFlowSnapshot(
            expiry=expiry,
            call_volume=call_volume,
            put_volume=put_volume,
            call_open_interest=call_oi,
            put_open_interest=put_oi,
            put_call_volume_ratio=put_call_ratio,
            unusual_contract_count=unusual_contract_count,
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            summary=summary + ".",
        )

    def _coerce_number(self, value: object) -> float:
        if value is None:
            return 0.0
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return 0.0
        return number

    def _coerce_int(self, value: object) -> int:
        return int(self._coerce_number(value))
