from __future__ import annotations

import httpx

from app.config import get_settings
from app.http_client import request_json


class SECClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.headers = {
            "User-Agent": self.settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        }
        self._client = httpx.AsyncClient(
            timeout=self.settings.provider_timeout_seconds,
            headers=self.headers,
        )

    async def has_recent_material_filing(self, ticker: str) -> bool:
        return (await self.get_recent_catalyst_score(ticker)) > 0

    async def get_recent_catalyst_score(self, ticker: str) -> float:
        """
        Simple first-pass catalyst score.
        The SEC JSON APIs are company/CIK-based, so for the MVP we use sec submissions tickers mapping fallback.
        Direction is intentionally neutral here; filings raise event risk but do not imply bullishness.
        """
        try:
            mapping = await request_json(
                self._client,
                method="GET",
                url="https://www.sec.gov/files/company_tickers.json",
            )
        except Exception:
            return 0.0

        cik = None
        for row in mapping.values():
            if str(row.get("ticker", "")).upper() == ticker.upper():
                cik = str(row.get("cik_str", "")).zfill(10)
                break
        if not cik:
            return 0.0

        try:
            payload = await request_json(
                self._client,
                method="GET",
                url=f"https://data.sec.gov/submissions/CIK{cik}.json",
            )
        except Exception:
            return 0.0

        recent_forms = payload.get("filings", {}).get("recent", {}).get("form", [])[:8]
        if not recent_forms:
            return 0.0

        weights = {
            "8-K": 0.55,
            "6-K": 0.45,
            "10-Q": 0.35,
            "10-K": 0.4,
            "S-3": 0.2,
            "424B5": 0.15,
        }
        best = max((weights.get(form, 0.0) for form in recent_forms), default=0.0)
        return round(best, 4)
