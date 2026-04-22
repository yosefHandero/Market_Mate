from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ProviderSnapshotBase:
    source: str
    available: bool = False
    stale: bool = False
    as_of: datetime | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class BinanceMicrostructureSnapshot(ProviderSnapshotBase):
    best_bid: float | None = None
    best_ask: float | None = None
    spread_bps: float | None = None
    book_imbalance: float | None = None
    aggressor_pressure: float | None = None


@dataclass(frozen=True)
class DeribitPositioningSnapshot(ProviderSnapshotBase):
    perp_premium_pct: float | None = None
    funding_bias: float | None = None
    open_interest_usd: float | None = None
    put_call_open_interest_ratio: float | None = None
    options_skew_bias: float | None = None
    crowding_score: float | None = None


@dataclass(frozen=True)
class SECRecentFiling:
    form: str
    filed_at: str | None = None
    accession_number: str | None = None
    primary_document: str | None = None


@dataclass(frozen=True)
class SECCatalystSnapshot(ProviderSnapshotBase):
    cik: str | None = None
    catalyst_score: float = 0.0
    filing_quality_score: float = 0.0
    company_facts_score: float = 0.0
    recent_forms: tuple[SECRecentFiling, ...] = ()
    recent_event_flags: tuple[str, ...] = ()
    fundamental_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FREDMacroSnapshot(ProviderSnapshotBase):
    regime: str = "neutral"
    vix_close: float | None = None
    high_yield_spread: float | None = None
    yield_curve_10y_2y: float | None = None
    risk_off_score: float = 0.0
    supportive_flags: tuple[str, ...] = ()
    warning_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class BreadthSnapshot(ProviderSnapshotBase):
    universe: str = "all"
    percent_above_vwap: float | None = None
    percent_intraday_high: float | None = None
    percent_intraday_low: float | None = None
    buy_balance: float | None = None
    sell_balance: float | None = None
    participation_score: float = 0.0


@dataclass(frozen=True)
class DefiLlamaSnapshot(ProviderSnapshotBase):
    stablecoin_growth_pct_7d: float | None = None
    total_tvl_change_pct_7d: float | None = None
    positive_chain_breadth_pct: float | None = None
    supportive_score: float = 0.0

