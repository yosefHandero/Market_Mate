from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO

import httpx

from app.config import get_settings
from app.provider_models import FREDMacroSnapshot
from app.provider_resilience import AsyncProviderGuard


class FREDClient:
    _SERIES = ("VIXCLS", "BAMLH0A0HYM2", "T10Y2Y")

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("fred", pace_seconds=0.2)

    async def get_macro_snapshot(self) -> FREDMacroSnapshot:
        try:
            return await self._guard.cached_call(
                key=("fred_macro_snapshot",),
                ttl_seconds=self.settings.fred_cache_seconds,
                stale_ttl_seconds=max(self.settings.fred_cache_seconds * 4, 14400),
                fetcher=self._fetch_macro_snapshot,
            )
        except Exception as exc:
            return FREDMacroSnapshot(
                source="fred",
                available=False,
                warnings=(f"fred_unavailable:{type(exc).__name__}",),
            )

    async def _fetch_macro_snapshot(self) -> FREDMacroSnapshot:
        series_values: dict[str, float] = {}
        warnings: list[str] = []
        await self._guard.throttle()
        for series_id in self._SERIES:
            response = await self._client.get(
                self.settings.fred_csv_url,
                params={"id": series_id},
            )
            response.raise_for_status()
            value = self._latest_csv_value(response.text)
            if value is None:
                warnings.append(f"fred_missing:{series_id}")
                continue
            series_values[series_id] = value

        vix = series_values.get("VIXCLS")
        high_yield = series_values.get("BAMLH0A0HYM2")
        curve = series_values.get("T10Y2Y")
        risk_off_score = 0.0
        supportive_flags: list[str] = []
        warning_flags: list[str] = []
        if vix is not None and vix >= 25:
            risk_off_score += 0.5
            warning_flags.append("vix_elevated")
        elif vix is not None and vix <= 18:
            supportive_flags.append("vix_calm")
        if high_yield is not None and high_yield >= 4.5:
            risk_off_score += 0.3
            warning_flags.append("credit_spreads_wide")
        elif high_yield is not None and high_yield <= 3.5:
            supportive_flags.append("credit_spreads_tight")
        if curve is not None and curve < 0:
            risk_off_score += 0.2
            warning_flags.append("yield_curve_inverted")
        elif curve is not None and curve > 0.5:
            supportive_flags.append("yield_curve_positive")

        regime = "neutral"
        if risk_off_score >= 0.6:
            regime = "risk_off"
        elif risk_off_score <= 0.1 and supportive_flags:
            regime = "risk_on"

        return FREDMacroSnapshot(
            source="fred",
            available=bool(series_values),
            stale=False,
            as_of=datetime.now(timezone.utc),
            warnings=tuple(warnings),
            regime=regime,
            vix_close=vix,
            high_yield_spread=high_yield,
            yield_curve_10y_2y=curve,
            risk_off_score=round(risk_off_score, 4),
            supportive_flags=tuple(supportive_flags),
            warning_flags=tuple(warning_flags),
        )

    def _latest_csv_value(self, csv_text: str) -> float | None:
        reader = csv.DictReader(StringIO(csv_text))
        latest_value: float | None = None
        for row in reader:
            raw_value = str(row.get("VALUE") or ".").strip()
            if raw_value == ".":
                continue
            try:
                latest_value = float(raw_value)
            except ValueError:
                continue
        return latest_value

