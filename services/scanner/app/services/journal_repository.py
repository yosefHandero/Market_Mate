from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select

from app.db import SessionLocal
from app.models.journal import JournalEntryORM
from app.schemas import (
    JournalAnalyticsBucket,
    JournalAnalyticsResponse,
    JournalEntryCreateRequest,
    JournalEntryResponse,
    JournalEntryUpdateRequest,
)
from collections import defaultdict

class JournalRepository:
    def create_entry(self, payload: JournalEntryCreateRequest) -> JournalEntryResponse:
        with SessionLocal() as session:
            row = JournalEntryORM(
                ticker=payload.ticker.upper(),
                run_id=payload.run_id,
                decision=payload.decision,
                entry_price=payload.entry_price,
                exit_price=payload.exit_price,
                pnl_pct=payload.pnl_pct,
                signal_label=payload.signal_label,
                score=payload.score,
                news_source=payload.news_source,
                notes=payload.notes,
                override_reason=payload.override_reason,
                action_state=payload.action_state or payload.decision,
                created_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._map(row)

    def list_entries(self, limit: int = 50) -> list[JournalEntryResponse]:
        with SessionLocal() as session:
            rows = session.execute(
                select(JournalEntryORM)
                .order_by(desc(JournalEntryORM.created_at))
                .limit(limit)
            ).scalars().all()
            return [self._map(row) for row in rows]

    def _map(self, row: JournalEntryORM) -> JournalEntryResponse:
        return JournalEntryResponse(
            id=row.id,
            ticker=row.ticker,
            run_id=row.run_id,
            decision=row.decision,
            entry_price=row.entry_price,
            exit_price=row.exit_price,
            pnl_pct=row.pnl_pct,
            signal_label=row.signal_label,
            score=row.score,
            news_source=row.news_source,
            notes=row.notes,
            override_reason=getattr(row, "override_reason", None),
            action_state=getattr(row, "action_state", None),
            created_at=row.created_at
        )
    def update_entry(self, entry_id: int, payload: JournalEntryUpdateRequest) -> JournalEntryResponse | None:
        with SessionLocal() as session:
            row = session.get(JournalEntryORM, entry_id)
            if not row:
                return None

            provided_fields = payload.model_fields_set

            if "decision" in provided_fields:
                row.decision = payload.decision
            if "entry_price" in provided_fields:
                row.entry_price = payload.entry_price
            if "exit_price" in provided_fields:
                row.exit_price = payload.exit_price

            if "pnl_pct" in provided_fields:
                row.pnl_pct = payload.pnl_pct

            if "notes" in provided_fields:
                row.notes = payload.notes
            if "override_reason" in provided_fields:
                row.override_reason = payload.override_reason
            if "action_state" in provided_fields:
                row.action_state = payload.action_state

            session.commit()
            session.refresh(row)
            return self._map(row)
    def get_analytics(self) -> JournalAnalyticsResponse:
        with SessionLocal() as session:
            rows = session.execute(
                select(JournalEntryORM).order_by(desc(JournalEntryORM.created_at))
            ).scalars().all()

            total_entries = len(rows)
            took_count = sum(1 for row in rows if row.decision == "took")
            skipped_count = sum(1 for row in rows if row.decision == "skipped")
            watching_count = sum(1 for row in rows if row.decision == "watching")

            open_trades = sum(
                1
                for row in rows
                if row.decision == "took" and row.exit_price is None
            )
            closed_trades = sum(
                1
                for row in rows
                if row.decision == "took" and row.exit_price is not None
            )

            overall_closed = [
                row for row in rows
                if row.decision == "took" and row.pnl_pct is not None
            ]

            win_rate = self._calculate_win_rate(overall_closed)
            avg_pnl_pct = self._calculate_avg_pnl(overall_closed)

            return JournalAnalyticsResponse(
                total_entries=total_entries,
                took_count=took_count,
                skipped_count=skipped_count,
                watching_count=watching_count,
                open_trades=open_trades,
                closed_trades=closed_trades,
                win_rate=win_rate,
                avg_pnl_pct=avg_pnl_pct,
                by_signal_label=self._build_group_buckets(
                    rows,
                    key_fn=lambda row: row.signal_label or "unknown",
                ),
                by_news_source=self._build_group_buckets(
                    rows,
                    key_fn=lambda row: row.news_source or "unknown",
                ),
                by_ticker=self._build_group_buckets(
                    rows,
                    key_fn=lambda row: row.ticker or "unknown",
                ),
            )

    def _build_group_buckets(
            self,
            rows: list[JournalEntryORM],
            key_fn,
        ) -> list[JournalAnalyticsBucket]:
            grouped: dict[str, list[JournalEntryORM]] = defaultdict(list)

            for row in rows:
                grouped[key_fn(row)].append(row)

            buckets: list[JournalAnalyticsBucket] = []

            for key, group_rows in grouped.items():
                closed = [
                    row
                    for row in group_rows
                    if row.decision == "took" and row.pnl_pct is not None
                ]
                open_count = sum(
                    1
                    for row in group_rows
                    if row.decision == "took" and row.exit_price is None
                )
                closed_count = sum(
                    1
                    for row in group_rows
                    if row.decision == "took" and row.exit_price is not None
                )

                buckets.append(
                    JournalAnalyticsBucket(
                        key=key,
                        total=len(group_rows),
                        open_count=open_count,
                        closed_count=closed_count,
                        win_rate=self._calculate_win_rate(closed),
                        avg_pnl_pct=self._calculate_avg_pnl(closed),
                    )
                )

            return sorted(
                buckets,
                key=lambda bucket: (
                    -bucket.total,
                    bucket.key,
                ),
            )

    def _calculate_win_rate(self, rows: list[JournalEntryORM]) -> float | None:
            if not rows:
                return None

            wins = sum(1 for row in rows if (row.pnl_pct or 0) > 0)
            return (wins / len(rows)) * 100

    def _calculate_avg_pnl(self, rows: list[JournalEntryORM]) -> float | None:
        if not rows:
            return None

        return sum((row.pnl_pct or 0) for row in rows) / len(rows)

