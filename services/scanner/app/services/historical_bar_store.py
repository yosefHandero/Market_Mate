from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.clients.alpaca import AlpacaClient
from app.clients.polygon import PolygonClient
from app.config import Settings, get_settings
from app.brain.weekly_bar_utils import parse_bar_timestamp, sorted_bars
from app.db import SessionLocal
from app.models.scan import DailyBarHistoryORM

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BarCoverage:
    symbol: str
    asset_type: str
    bar_count: int
    first_date: str | None
    last_date: str | None
    years_available: float
    source: str
    sufficient: bool
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "bar_count": self.bar_count,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "years_available": round(self.years_available, 2),
            "source": self.source,
            "sufficient": self.sufficient,
            "note": self.note,
        }


class HistoricalBarStore:
    """Persistent, incremental daily-bar cache backing the walk-forward proof engine.

    Bars are stored append-only per (symbol, asset_type, bar_date) so repeated proof
    runs reuse cached history and provider rate limits do not block long-range proof.
    """

    def __init__(
        self,
        *,
        alpaca: AlpacaClient | None = None,
        polygon: PolygonClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._alpaca = alpaca
        self._polygon = polygon

    @property
    def alpaca(self) -> AlpacaClient:
        if self._alpaca is None:
            self._alpaca = AlpacaClient()
        return self._alpaca

    @property
    def polygon(self) -> PolygonClient:
        if self._polygon is None:
            self._polygon = PolygonClient()
        return self._polygon

    @staticmethod
    def resolve_asset_type(symbol: str, asset_type: str | None = None) -> str:
        return asset_type or ("crypto" if "/" in symbol else "stock")

    def load_bars(self, symbol: str, *, asset_type: str | None = None) -> list[dict[str, Any]]:
        normalized = symbol.upper()
        resolved = self.resolve_asset_type(normalized, asset_type)
        with SessionLocal() as session:
            rows = session.execute(
                select(DailyBarHistoryORM)
                .where(
                    DailyBarHistoryORM.symbol == normalized,
                    DailyBarHistoryORM.asset_type == resolved,
                )
                .order_by(DailyBarHistoryORM.bar_date.asc())
            ).scalars().all()
        return [
            {
                "t": row.bar_ts,
                "o": row.open,
                "h": row.high,
                "l": row.low,
                "c": row.close,
                "v": row.volume,
            }
            for row in rows
        ]

    def coverage(self, symbol: str, *, asset_type: str | None = None) -> BarCoverage:
        normalized = symbol.upper()
        resolved = self.resolve_asset_type(normalized, asset_type)
        bars = self.load_bars(normalized, asset_type=resolved)
        return self._coverage_from_bars(normalized, resolved, bars, source="cache")

    def _coverage_from_bars(
        self,
        symbol: str,
        asset_type: str,
        bars: list[dict[str, Any]],
        *,
        source: str,
    ) -> BarCoverage:
        ordered = sorted_bars(bars) if bars else []
        min_years = float(self.settings.proof_min_years)
        if not ordered:
            return BarCoverage(
                symbol=symbol,
                asset_type=asset_type,
                bar_count=0,
                first_date=None,
                last_date=None,
                years_available=0.0,
                source=source,
                sufficient=False,
                note="no history",
            )
        first_ts = parse_bar_timestamp(ordered[0].get("t"))
        last_ts = parse_bar_timestamp(ordered[-1].get("t"))
        years = max((last_ts - first_ts).days / 365.0, 0.0)
        return BarCoverage(
            symbol=symbol,
            asset_type=asset_type,
            bar_count=len(ordered),
            first_date=first_ts.date().isoformat(),
            last_date=last_ts.date().isoformat(),
            years_available=years,
            source=source,
            sufficient=years >= min_years and len(ordered) >= self.settings.weekly_daily_lookback_bars_min,
            note="" if years >= min_years else f"only {years:.1f}y available (min {min_years:.0f}y)",
        )

    async def _fetch_provider_bars(
        self,
        symbol: str,
        *,
        asset_type: str,
        start: datetime,
        end: datetime,
    ) -> tuple[list[dict[str, Any]], str]:
        chunk_days = max(int(self.settings.proof_fetch_chunk_days), 90)
        limit = min(max(self.settings.proof_daily_lookback_bars_max, 500), 5000)
        collected: dict[str, dict[str, Any]] = {}
        source = "alpaca"
        cursor = start
        while cursor < end:
            window_end = min(cursor + timedelta(days=chunk_days), end)
            try:
                if asset_type == "crypto":
                    rows = await self.alpaca.get_historical_crypto_bars(
                        symbol, start=cursor, end=window_end, timeframe="1Day", limit=limit
                    )
                else:
                    rows = await self.alpaca.get_historical_stock_bars(
                        symbol, start=cursor, end=window_end, timeframe="1Day", limit=limit
                    )
            except Exception as alpaca_error:
                rows = await self._polygon_fallback(
                    symbol, asset_type=asset_type, start=cursor, end=window_end, limit=limit
                )
                if rows is None:
                    raise alpaca_error
                source = "polygon"
            for row in rows:
                timestamp = row.get("t")
                if timestamp is None:
                    continue
                key = parse_bar_timestamp(timestamp).date().isoformat()
                collected[key] = row
            cursor = window_end

        # Crypto history from Alpaca is often shallow (and has no other primary
        # source). When Polygon is configured, merge its crypto aggregates to
        # deepen coverage rather than leaving the pair permanently underpowered.
        if asset_type == "crypto" and self.settings.polygon_api_key:
            deepened = await self._polygon_fallback(
                symbol, asset_type=asset_type, start=start, end=end, limit=limit
            )
            for row in deepened or []:
                timestamp = row.get("t")
                if timestamp is None:
                    continue
                key = parse_bar_timestamp(timestamp).date().isoformat()
                if key not in collected:
                    collected[key] = row
                    source = "alpaca+polygon" if source == "alpaca" else source
        return sorted_bars(list(collected.values())), source

    async def _polygon_fallback(
        self,
        symbol: str,
        *,
        asset_type: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[dict[str, Any]] | None:
        if not self.settings.polygon_api_key:
            return None
        try:
            if asset_type == "crypto":
                return await self.polygon.get_historical_crypto_bars(
                    symbol, start=start, end=end, timeframe="1Day", limit=limit
                )
            return await self.polygon.get_historical_bars(
                symbol, start=start, end=end, timeframe="1Day", limit=limit
            )
        except Exception:
            logger.warning(
                "polygon_fallback_failed",
                extra={"symbol": symbol, "asset_type": asset_type},
                exc_info=True,
            )
            return None

    @staticmethod
    def adjustment_policy_for(asset_type: str) -> str:
        # Stocks are fetched split-adjusted from both providers; crypto has no
        # corporate actions so no adjustment applies.
        return "none" if asset_type == "crypto" else "split"

    def _persist_bars(
        self,
        symbol: str,
        asset_type: str,
        bars: list[dict[str, Any]],
        *,
        source: str,
    ) -> tuple[int, int]:
        """Insert new bars and revise existing ones whose values drifted.

        First write is append-only. A later refetch that returns a different OHLCV
        for a stored bar_date updates the row in place, increments revision_count,
        and stamps revised_at so point-in-time revisions are auditable rather than
        silently first-write-wins.
        """
        if not bars:
            return 0, 0
        now = datetime.now(timezone.utc)
        policy = self.adjustment_policy_for(asset_type)
        inserted = 0
        revised = 0
        with SessionLocal() as session:
            existing_rows = {
                row.bar_date: row
                for row in session.execute(
                    select(DailyBarHistoryORM).where(
                        DailyBarHistoryORM.symbol == symbol,
                        DailyBarHistoryORM.asset_type == asset_type,
                    )
                ).scalars().all()
            }
            for bar in bars:
                timestamp = bar.get("t")
                if timestamp is None:
                    continue
                parsed = parse_bar_timestamp(timestamp)
                bar_date = parsed.date().isoformat()
                o = float(bar.get("o", 0) or 0)
                h = float(bar.get("h", 0) or 0)
                low = float(bar.get("l", 0) or 0)
                c = float(bar.get("c", 0) or 0)
                v = float(bar.get("v", 0) or 0)
                current = existing_rows.get(bar_date)
                if current is None:
                    session.add(
                        DailyBarHistoryORM(
                            symbol=symbol,
                            asset_type=asset_type,
                            bar_date=bar_date,
                            bar_ts=parsed.isoformat(),
                            open=o,
                            high=h,
                            low=low,
                            close=c,
                            volume=v,
                            source=source,
                            fetched_at=now,
                            adjustment_policy=policy,
                            revision_count=0,
                            revised_at=None,
                        )
                    )
                    inserted += 1
                    continue
                if self._bar_values_drifted(current, o=o, h=h, low=low, c=c, v=v):
                    current.open = o
                    current.high = h
                    current.low = low
                    current.close = c
                    current.volume = v
                    current.source = source
                    current.fetched_at = now
                    current.adjustment_policy = policy
                    current.revision_count = int(current.revision_count or 0) + 1
                    current.revised_at = now
                    revised += 1
                    logger.info(
                        "daily_bar_revised",
                        extra={
                            "event": "daily_bar_revised",
                            "symbol": symbol,
                            "asset_type": asset_type,
                            "bar_date": bar_date,
                            "revision_count": current.revision_count,
                        },
                    )
            session.commit()
        return inserted, revised

    @staticmethod
    def _bar_values_drifted(
        row: DailyBarHistoryORM, *, o: float, h: float, low: float, c: float, v: float
    ) -> bool:
        def changed(stored: float | None, fresh: float) -> bool:
            stored_val = float(stored or 0.0)
            if stored_val == 0.0 and fresh == 0.0:
                return False
            denom = max(abs(stored_val), 1e-9)
            return abs(stored_val - fresh) / denom > 1e-4

        return (
            changed(row.open, o)
            or changed(row.high, h)
            or changed(row.low, low)
            or changed(row.close, c)
            # Volume revisions are common and low-stakes; only track OHLC drift as
            # a corporate-action / correction signal, but refresh volume silently.
        )

    def quality_check(self, symbol: str, *, asset_type: str | None = None) -> list[str]:
        """Session-aware bar QC. Returns a list of human-readable issue strings.

        - Duplicate bar_dates (should be impossible given the unique constraint).
        - Zero/negative prices.
        - Stale tail (last bar older than the asset's freshness tolerance).
        - Session-aware gaps: weekday grid with holiday tolerance for stocks; a
          continuous daily grid for 24/7 crypto.
        """
        normalized = symbol.upper()
        resolved = self.resolve_asset_type(normalized, asset_type)
        bars = sorted_bars(self.load_bars(normalized, asset_type=resolved))
        issues: list[str] = []
        if not bars:
            return [f"{normalized}: no history"]

        seen_dates: set[str] = set()
        prev_date: datetime | None = None
        gap_count = 0
        for bar in bars:
            parsed = parse_bar_timestamp(bar.get("t"))
            date_key = parsed.date().isoformat()
            if date_key in seen_dates:
                issues.append(f"{normalized}: duplicate bar {date_key}")
            seen_dates.add(date_key)
            for field in ("o", "h", "l", "c"):
                if float(bar.get(field, 0) or 0) <= 0:
                    issues.append(f"{normalized}: non-positive {field} on {date_key}")
                    break
            if prev_date is not None:
                gap_days = (parsed.date() - prev_date.date()).days
                if resolved == "crypto":
                    if gap_days > 1:
                        gap_count += 1
                else:
                    # Stocks: expect the next trading day. Allow up to a long
                    # holiday weekend (<= 4 calendar days) before flagging.
                    if gap_days > 4:
                        gap_count += 1
            prev_date = parsed
        if gap_count:
            issues.append(f"{normalized}: {gap_count} session gap(s) beyond tolerance")

        last_ts = parse_bar_timestamp(bars[-1].get("t"))
        stale_days = (
            self.settings.weekly_daily_bar_max_age_days_crypto
            if resolved == "crypto"
            else self.settings.weekly_daily_bar_max_age_days_stock
        )
        age_days = (datetime.now(timezone.utc) - last_ts).days
        if age_days > max(int(stale_days) + 5, 7):
            issues.append(f"{normalized}: stale tail, last bar {age_days}d old")
        return issues

    async def rebuild_history(
        self, symbol: str, *, asset_type: str | None = None, years: int | None = None
    ) -> BarCoverage:
        """Wipe and refetch a symbol's stored history.

        Used after the split-adjustment fix so any older raw-adjusted stock rows
        are replaced by uniformly split-adjusted bars. The daily-bar store is a
        refetchable cache, so this is non-destructive to evidence.
        """
        normalized = symbol.upper()
        resolved = self.resolve_asset_type(normalized, asset_type)
        with SessionLocal() as session:
            session.query(DailyBarHistoryORM).filter(
                DailyBarHistoryORM.symbol == normalized,
                DailyBarHistoryORM.asset_type == resolved,
            ).delete(synchronize_session=False)
            session.commit()
        return await self.ensure_history(
            normalized, asset_type=resolved, years=years, force_refresh=True
        )

    async def ensure_recent_tail(
        self,
        symbol: str,
        *,
        asset_type: str | None = None,
        overlap_days: int = 5,
    ) -> list[dict[str, Any]]:
        """Incrementally extend a symbol's stored history through now.

        Fetches only the window from shortly before the last stored bar (the
        overlap catches late provider revisions) to the present and persists it
        into the point-in-time store. Falls back to a full ``ensure_history``
        when the symbol has no stored bars yet. Serves whatever the store holds
        when providers fail: stale data with honest staleness flags beats an
        empty universe.
        """
        normalized = symbol.upper()
        resolved = self.resolve_asset_type(normalized, asset_type)
        existing = self.coverage(normalized, asset_type=resolved)
        if existing.bar_count == 0 or existing.last_date is None:
            await self.ensure_history(normalized, asset_type=resolved)
            return self.load_bars(normalized, asset_type=resolved)

        end = datetime.now(timezone.utc)
        last = datetime.fromisoformat(existing.last_date).replace(tzinfo=timezone.utc)
        start = last - timedelta(days=max(int(overlap_days), 1))
        if start >= end:
            return self.load_bars(normalized, asset_type=resolved)
        try:
            bars, source = await self._fetch_provider_bars(
                normalized, asset_type=resolved, start=start, end=end
            )
        except Exception:
            logger.warning(
                "historical_bar_tail_fetch_failed",
                extra={"symbol": normalized, "asset_type": resolved},
                exc_info=True,
            )
            return self.load_bars(normalized, asset_type=resolved)
        self._persist_bars(normalized, resolved, bars, source=source)
        return self.load_bars(normalized, asset_type=resolved)

    async def ensure_history(
        self,
        symbol: str,
        *,
        asset_type: str | None = None,
        years: int | None = None,
        force_refresh: bool = False,
    ) -> BarCoverage:
        normalized = symbol.upper()
        resolved = self.resolve_asset_type(normalized, asset_type)
        target_years = int(years or self.settings.proof_effective_years)

        existing_coverage = self.coverage(normalized, asset_type=resolved)
        stale_days = self.settings.weekly_daily_bar_max_age_days_crypto if resolved == "crypto" else self.settings.weekly_daily_bar_max_age_days_stock
        recent_enough = False
        if existing_coverage.last_date:
            last = datetime.fromisoformat(existing_coverage.last_date).replace(tzinfo=timezone.utc)
            recent_enough = (datetime.now(timezone.utc) - last).days <= max(int(stale_days) + 3, 4)
        if (
            not force_refresh
            and existing_coverage.years_available >= target_years
            and recent_enough
        ):
            return existing_coverage

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=int(target_years * 365) + 45)
        try:
            bars, source = await self._fetch_provider_bars(
                normalized, asset_type=resolved, start=start, end=end
            )
        except Exception:
            logger.warning(
                "historical_bar_fetch_failed",
                extra={"symbol": normalized, "asset_type": resolved},
                exc_info=True,
            )
            return self._coverage_from_bars(
                normalized,
                resolved,
                self.load_bars(normalized, asset_type=resolved),
                source="cache",
            )
        self._persist_bars(normalized, resolved, bars, source=source)
        merged = self.load_bars(normalized, asset_type=resolved)
        return self._coverage_from_bars(normalized, resolved, merged, source=source)
