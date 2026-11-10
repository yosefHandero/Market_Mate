"""Bounded, as-of evidence for the one-hour paper BUY gate."""

from datetime import datetime, timedelta, timezone
import json
import math

from sqlalchemy import desc, inspect, select

from app.brain.policies.hybrid import HYBRID_POLICY_ID, HYBRID_POLICY_VERSION
from app.config import Settings
from app.core.scoring import SCORING_VERSION
from app.models.scan import PredictionSnapshotORM, SignalOutcomeORM, StrategyReplayRunORM


MAX_AGE = timedelta(days=90)
HORIZON = timedelta(hours=1)
EXIT_TOLERANCE = timedelta(days=3)
REPLAY_RECIPE = "hourly-buy-v1-alpaca-5min-core"


def replay_thresholds(settings: Settings, asset_type: str) -> dict[str, float]:
    prefix = "signal_crypto_" if asset_type == "crypto" else "signal_"
    return {
        "buy_threshold": getattr(settings, prefix + "buy_threshold"),
        "sell_threshold": getattr(settings, prefix + "sell_threshold"),
        "signal_margin": getattr(settings, prefix + "margin"),
    }


def replay_identity(settings: Settings) -> dict:
    return {
        "recipe": REPLAY_RECIPE,
        "strategy_variant": settings.scanner_strategy_variant or "layered-v4",
        "scoring_version": SCORING_VERSION,
        "stock": replay_thresholds(settings, "stock"),
        "crypto": replay_thresholds(settings, "crypto"),
    }


def _completed_rows(session, *, asset_type: str, variant: str, start: datetime, stop: datetime, as_of: datetime):
    outcome = SignalOutcomeORM
    snapshot = PredictionSnapshotORM
    # A prediction snapshot proves the source policy, not the evaluation horizon.
    # The one-hour price and resolution come from the separate signal outcome.
    production = (
        select(snapshot.id)
        .where(
            snapshot.run_id == outcome.run_id,
            snapshot.ticker == outcome.ticker,
            snapshot.generated_at == outcome.generated_at,
            snapshot.asset_type == outcome.asset_type,
            snapshot.signal == "BUY",
            snapshot.sample_source == "live_paper_forward",
            snapshot.decision_role == "production",
            snapshot.policy_id == HYBRID_POLICY_ID,
            snapshot.policy_version == HYBRID_POLICY_VERSION,
        )
        .exists()
    )
    query = select(outcome).where(
        outcome.asset_type == asset_type,
        outcome.signal == "BUY",
        outcome.strategy_variant == variant,
        outcome.scoring_version == SCORING_VERSION,
        outcome.sample_source == "live_paper_forward",
        outcome.generated_at >= start,
        outcome.generated_at < stop,
        outcome.status_1h == "resolved",
        outcome.evaluated_at_1h <= as_of,
        outcome.entry_price > 0,
        outcome.price_after_1h > 0,
        production,
    ).order_by(desc(outcome.generated_at), desc(outcome.id))
    return (
        row for row in session.scalars(query)
        if row.generated_at + HORIZON <= row.evaluated_at_1h
        and math.isfinite(row.entry_price) and math.isfinite(row.price_after_1h)
        and math.isfinite(row.raw_score) and bool(row.ticker.strip())
    )


def _utc_naive(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("replay timestamps must include an offset")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _replay_rows(session, *, settings: Settings, asset_type: str, start: datetime, as_of: datetime, holdout_source):
    if not inspect(session.connection()).has_table(StrategyReplayRunORM.__tablename__):
        return []
    allowed = set(settings.crypto_watchlist_items if asset_type == "crypto" else settings.watchlist_items)
    allowed.difference_update(("SPY", "QQQ"))
    # A replay of an assigned holdout ticker would defeat the ticker-level split.
    allowed = {ticker for ticker in allowed if holdout_source(ticker) == "live_paper_forward"}
    allowed.difference_update(session.scalars(select(SignalOutcomeORM.ticker).where(
        SignalOutcomeORM.asset_type == asset_type,
        SignalOutcomeORM.generated_at >= start,
        SignalOutcomeORM.generated_at < as_of,
        SignalOutcomeORM.sample_source.in_(("live_holdout", "out_of_sample")),
    )))
    identity = replay_identity(settings)
    query = select(StrategyReplayRunORM).where(
        StrategyReplayRunORM.created_at >= start,
        StrategyReplayRunORM.created_at <= as_of,
        StrategyReplayRunORM.request_json.contains(REPLAY_RECIPE),
    ).order_by(desc(StrategyReplayRunORM.created_at), StrategyReplayRunORM.replay_id)
    rows = []
    for replay in session.scalars(query):
        try:
            request = json.loads(replay.request_json)
            result = json.loads(replay.response_json)
            if (request.get("hourly_buy_evidence") != identity or request.get("replay_mode") != "intraday"
                or request.get("sample_source") != "backfilled_replay" or request.get("horizon") != "1h"
                or not request.get("persist_outcomes")):
                continue
            requested_start = _utc_naive(request["start"])
            requested_end = _utc_naive(request["end"])
            symbols = allowed.intersection(request["symbols"])
            replay_rows = result["rows"]
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if not isinstance(replay_rows, list):
            continue
        for row in replay_rows:
            try:
                if (row["symbol"] not in symbols or row["asset_type"] != asset_type or row["signal"] != "BUY"
                    or row["strategy_variant"] != identity["strategy_variant"] or row["horizon"] != "1h"
                    or row["provider_status"] != "ok"):
                    continue
                observed = _utc_naive(row["observed_at"])
                exit_at = _utc_naive(row["future_price_at"])
                entry, exit_price, score = (float(row[key]) for key in ("entry_price", "future_price", "raw_score"))
                if not (max(start, requested_start) <= observed < as_of
                        and observed + HORIZON <= exit_at <= min(observed + HORIZON + EXIT_TOLERANCE,
                                                               requested_end, replay.created_at, as_of)
                        and all(math.isfinite(value) for value in (entry, exit_price, score))
                        and entry > 0 and exit_price > 0 and 0 <= score <= 100):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(SignalOutcomeORM(
                ticker=row["symbol"], signal="BUY", raw_score=score, generated_at=observed,
                entry_price=entry, price_after_1h=exit_price, sample_source="backfilled_replay",
            ))
    return sorted(rows, key=lambda row: (row.generated_at, row.ticker), reverse=True)


def select_hourly_buy_evidence(
    session, *, settings: Settings, asset_type: str, recent_start: datetime, as_of: datetime,
    minimum: int, live_provenance_available: bool, holdout_source,
) -> dict[str, list[SignalOutcomeORM]]:
    """Choose observations by source, compatibility and recency before scoring any return."""
    sources: dict[str, list[SignalOutcomeORM]] = {
        "Recent completed": [], "Historical completed": [], "Historical replay": [],
    }
    oldest = as_of - MAX_AGE
    recent_start = max(recent_start, oldest)
    variant = settings.scanner_strategy_variant or "layered-v4"
    seen: set[tuple[str, datetime]] = set()

    def add(label, rows, *, stop_at_minimum=False):
        for row in rows:
            key = row.ticker.strip().upper(), row.generated_at
            if key in seen:
                continue
            seen.add(key)
            sources[label].append(row)
            if stop_at_minimum and len(seen) >= minimum:
                break

    if live_provenance_available:
        add("Recent completed", _completed_rows(
            session, asset_type=asset_type, variant=variant, start=recent_start, stop=as_of, as_of=as_of,
        ))
        if len(seen) < minimum and oldest < recent_start:
            add("Historical completed", _completed_rows(
                session, asset_type=asset_type, variant=variant, start=oldest, stop=recent_start, as_of=as_of,
            ), stop_at_minimum=True)
    if len(seen) < minimum:
        add("Historical replay", _replay_rows(
            session, settings=settings, asset_type=asset_type, start=oldest, as_of=as_of,
            holdout_source=holdout_source,
        ), stop_at_minimum=True)
    return sources
