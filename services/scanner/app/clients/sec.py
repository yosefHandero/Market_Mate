from __future__ import annotations

import httpx
from datetime import datetime, timezone

from app.config import get_settings
from app.http_client import request_json
from app.provider_models import SECCatalystSnapshot, SECRecentFiling
from app.provider_resilience import AsyncProviderGuard


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
        self._guard = AsyncProviderGuard("sec", pace_seconds=0.25)

    async def has_recent_material_filing(self, ticker: str) -> bool:
        return (await self.get_recent_catalyst_score(ticker)) > 0

    async def get_company_snapshot(self, ticker: str) -> SECCatalystSnapshot:
        normalized = ticker.upper()
        warnings: list[str] = []
        try:
            mapping = await self._get_company_mapping()
        except Exception as exc:
            return SECCatalystSnapshot(
                source="sec",
                available=False,
                warnings=(f"sec_company_mapping_unavailable:{type(exc).__name__}",),
            )

        cik = self._resolve_cik(mapping, normalized)
        if not cik:
            return SECCatalystSnapshot(
                source="sec",
                available=False,
                warnings=("sec_cik_not_found",),
            )

        submissions = None
        company_facts = None
        try:
            submissions = await self._get_submissions(cik)
        except Exception as exc:
            warnings.append(f"sec_submissions_unavailable:{type(exc).__name__}")
        try:
            company_facts = await self._get_company_facts(cik)
        except Exception as exc:
            warnings.append(f"sec_company_facts_unavailable:{type(exc).__name__}")

        recent_forms, filing_quality_score, recent_event_flags = self._analyze_recent_forms(submissions)
        company_facts_score, fundamental_flags = self._analyze_company_facts(company_facts)
        catalyst_score = round(min(1.0, filing_quality_score + company_facts_score), 4)

        return SECCatalystSnapshot(
            source="sec",
            available=submissions is not None or company_facts is not None,
            stale=False,
            as_of=datetime.now(timezone.utc),
            warnings=tuple(warnings),
            cik=cik,
            catalyst_score=catalyst_score,
            filing_quality_score=round(filing_quality_score, 4),
            company_facts_score=round(company_facts_score, 4),
            recent_forms=tuple(recent_forms),
            recent_event_flags=tuple(recent_event_flags),
            fundamental_flags=tuple(fundamental_flags),
        )

    async def _get_company_mapping(self) -> dict:
        await self._guard.throttle()
        return await self._guard.cached_call(
            key=("company_tickers",),
            ttl_seconds=self.settings.sec_company_tickers_cache_seconds,
            stale_ttl_seconds=max(self.settings.sec_company_tickers_cache_seconds * 4, 3600),
            fetcher=lambda: request_json(
                self._client,
                method="GET",
                url="https://www.sec.gov/files/company_tickers.json",
                provider="sec",
                on_backoff=self._guard.register_backoff,
            ),
        )

    async def _get_submissions(self, cik: str) -> dict:
        await self._guard.throttle()
        return await self._guard.cached_call(
            key=("submissions", cik),
            ttl_seconds=self.settings.sec_filings_cache_seconds,
            stale_ttl_seconds=max(self.settings.sec_filings_cache_seconds * 4, 1800),
            fetcher=lambda: request_json(
                self._client,
                method="GET",
                url=f"https://data.sec.gov/submissions/CIK{cik}.json",
                provider="sec",
                on_backoff=self._guard.register_backoff,
            ),
        )

    async def _get_company_facts(self, cik: str) -> dict:
        await self._guard.throttle()
        return await self._guard.cached_call(
            key=("company_facts", cik),
            ttl_seconds=self.settings.sec_company_facts_cache_seconds,
            stale_ttl_seconds=max(self.settings.sec_company_facts_cache_seconds * 4, 7200),
            fetcher=lambda: request_json(
                self._client,
                method="GET",
                url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                provider="sec",
                on_backoff=self._guard.register_backoff,
            ),
        )

    async def get_recent_catalyst_score(self, ticker: str) -> float:
        snapshot = await self.get_company_snapshot(ticker)
        return snapshot.catalyst_score if snapshot.available else 0.0

    def _resolve_cik(self, mapping: dict, ticker: str) -> str | None:
        for row in mapping.values():
            if str(row.get("ticker", "")).upper() == ticker:
                return str(row.get("cik_str", "")).zfill(10)
        return None

    def _analyze_recent_forms(
        self,
        payload: dict | None,
    ) -> tuple[list[SECRecentFiling], float, list[str]]:
        if not payload:
            return [], 0.0, []
        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form") or []
        filed_dates = recent.get("filingDate") or []
        accession_numbers = recent.get("accessionNumber") or []
        primary_documents = recent.get("primaryDocument") or []
        weights = {
            "8-K": 0.45,
            "6-K": 0.35,
            "10-Q": 0.22,
            "10-K": 0.26,
            "S-3": 0.12,
            "424B5": 0.08,
            "13D": 0.28,
            "13G": 0.18,
            "4": 0.12,
        }
        recent_forms: list[SECRecentFiling] = []
        recent_event_flags: list[str] = []
        filing_quality_score = 0.0
        for index, form in enumerate(forms[:10]):
            normalized_form = str(form).upper()
            recent_forms.append(
                SECRecentFiling(
                    form=normalized_form,
                    filed_at=filed_dates[index] if index < len(filed_dates) else None,
                    accession_number=accession_numbers[index] if index < len(accession_numbers) else None,
                    primary_document=primary_documents[index] if index < len(primary_documents) else None,
                )
            )
            filing_quality_score = max(filing_quality_score, weights.get(normalized_form, 0.0))
            if normalized_form in {"8-K", "6-K"}:
                recent_event_flags.append("current_report_recent")
            if normalized_form in {"10-Q", "10-K"}:
                recent_event_flags.append("financial_update_recent")
            if normalized_form in {"13D", "13G", "4"}:
                recent_event_flags.append("ownership_hook_recent")
        return recent_forms, filing_quality_score, list(dict.fromkeys(recent_event_flags))

    def _analyze_company_facts(
        self,
        payload: dict | None,
    ) -> tuple[float, list[str]]:
        if not payload:
            return 0.0, []
        us_gaap = payload.get("facts", {}).get("us-gaap", {})
        revenue_score, revenue_flags = self._latest_fact_trend_score(
            us_gaap,
            keys=("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"),
            direction="up",
            label="revenue",
        )
        earnings_score, earnings_flags = self._latest_fact_trend_score(
            us_gaap,
            keys=("NetIncomeLoss",),
            direction="up",
            label="net_income",
        )
        return round(min(0.25, revenue_score + earnings_score), 4), revenue_flags + earnings_flags

    def _latest_fact_trend_score(
        self,
        facts: dict,
        *,
        keys: tuple[str, ...],
        direction: str,
        label: str,
    ) -> tuple[float, list[str]]:
        for key in keys:
            fact = facts.get(key) or {}
            units = fact.get("units") or {}
            usd_rows = units.get("USD") or []
            numeric_rows: list[float] = []
            for row in usd_rows:
                if row.get("form") not in {"10-Q", "10-K"}:
                    continue
                value = row.get("val")
                try:
                    numeric_rows.append(float(value))
                except (TypeError, ValueError):
                    continue
            if len(numeric_rows) >= 2:
                latest = numeric_rows[-1]
                prior = numeric_rows[-2]
                if prior == 0:
                    return 0.0, []
                change = (latest - prior) / abs(prior)
                if direction == "up" and change >= 0.05:
                    return 0.12, [f"{label}_trend_positive"]
                if direction == "up" and change <= -0.05:
                    return -0.05, [f"{label}_trend_negative"]
        return 0.0, []
