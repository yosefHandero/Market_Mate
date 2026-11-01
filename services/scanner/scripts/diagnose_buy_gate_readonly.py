"""Recompute stock BUY evidence on a query-only in-memory production capture.

No application startup, repairs, scans, queue processing or provider requests.
The only production connection is SQLite mode=ro plus PRAGMA query_only=ON.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch


def main() -> None:
    scanner_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(scanner_root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observed-at", help="UTC timestamp for the fixed evidence window; defaults to capture time")
    args = parser.parse_args()
    from app.config import get_settings

    settings = get_settings()
    if not settings.database_url.startswith("sqlite:///"):
        raise SystemExit("This inspection requires the configured local SQLite database.")
    database_path = Path(settings.database_url.removeprefix("sqlite:///"))
    if not database_path.is_absolute():
        database_path = scanner_root / database_path
    database_path = database_path.resolve()
    source_uri = database_path.as_uri() + "?mode=ro"

    def forbid_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
            raise AssertionError("Network forbidden during read-only gate inspection")

    sys.addaudithook(forbid_network)
    # Prevent app.db's import-time engine from opening the configured file.
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    get_settings.cache_clear()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.services.repository as repository_module

    captured_at = datetime.now(timezone.utc)
    observed_at = datetime.fromisoformat(args.observed_at.replace("Z", "+00:00")) if args.observed_at else captured_at
    if observed_at.tzinfo is None:
        raise SystemExit("--observed-at must include a timezone offset")
    observed_at = observed_at.astimezone(timezone.utc)
    source = sqlite3.connect(source_uri, uri=True)
    snapshot = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        source.execute("PRAGMA query_only=ON")
        source.backup(snapshot)
        source_changes = source.total_changes
    finally:
        source.close()
    snapshot.execute("PRAGMA query_only=ON")
    captured_engine = create_engine("sqlite://", creator=lambda: snapshot, poolclass=StaticPool)
    captured_sessions = sessionmaker(bind=captured_engine, expire_on_commit=False)
    try:
        with patch.object(repository_module, "engine", captured_engine), patch.object(repository_module, "SessionLocal", captured_sessions):
            repo = repository_module.ScanRepository()
            repo.settings = settings
            horizon = settings.trade_gate_horizon
            start, end = repo.trust_window_bounds_for(observed_at=observed_at, horizon=horizon)
            bands = {}
            for band in ("0-59", "60-69", "70-79", "80-89", "90-100"):
                gate = repo.evaluate_signal_gate(asset_type="stock", signal="BUY", score_band=band, horizon=horizon, observed_at=observed_at)
                bands[band] = {**asdict(gate), "checks": [check.model_dump() for check in gate.checks]}
            rows = repo._load_signal_outcome_rows(asset_type="stock", generated_at_start=start, generated_at_end=end)
            buy_rows = [row for row in rows if row.signal == "BUY"]
            returns = [repo._return_for_horizon(row, horizon) for row in buy_rows]
            measured = [value for value in returns if value is not None]
            latest_run = snapshot.execute("SELECT run_id, created_at FROM scan_runs ORDER BY created_at DESC LIMIT 1").fetchone()
            latest_buy_checks = []
            if latest_run:
                for row in snapshot.execute("SELECT ticker, score, gate_passed, gate_reason, gate_checks_json FROM scan_results WHERE run_id=? AND asset_type='stock' AND decision_signal='BUY'", (latest_run[0],)):
                    latest_buy_checks.append(dict(zip(("ticker", "raw_score", "saved_gate_passed", "saved_gate_reason", "saved_gate_checks_json"), row)))
            table_times = {}
            for table, generated, evaluated in (("scan_runs", "created_at", None), ("signal_outcomes", "generated_at", "evaluated_at_1h"), ("prediction_snapshots", "generated_at", "evaluated_at"), ("paper_positions", "opened_at", "closed_at")):
                columns = {row[1] for row in snapshot.execute(f"PRAGMA table_info({table})")}
                expressions = ["COUNT(*)", f"MIN({generated})", f"MAX({generated})"]
                if evaluated and evaluated in columns:
                    expressions += [f"MAX({evaluated})"]
                values = snapshot.execute(f"SELECT {', '.join(expressions)} FROM {table}").fetchone()
                table_times[table] = dict(zip(("count", "min_generated_at", "max_generated_at", "max_evaluated_at"), values))
            prediction_counts = dict(snapshot.execute("SELECT status, COUNT(*) FROM prediction_snapshots GROUP BY status").fetchall())
            in_window_count = snapshot.execute("SELECT COUNT(*) FROM signal_outcomes WHERE asset_type='stock' AND signal='BUY' AND generated_at>=? AND generated_at<?", (start.isoformat(sep=" "), end.isoformat(sep=" "))).fetchone()[0]
            sql_returns = snapshot.execute(
                f"SELECT ROUND((price_after_{horizon}-entry_price)/entry_price*100,4) FROM signal_outcomes WHERE asset_type='stock' AND signal='BUY' AND generated_at>=? AND generated_at<? AND COALESCE(sample_source,'live_paper_forward') NOT IN ('out_of_sample','live_holdout') AND entry_price>0 AND price_after_{horizon} IS NOT NULL",
                (start.isoformat(sep=" "), end.isoformat(sep=" ")),
            ).fetchall()
            output = {
                "observed_at_utc": observed_at.isoformat(), "captured_at_utc": captured_at.isoformat(), "database": str(database_path),
                "capture": "SQLite mode=ro, query_only=ON backup to query-only :memory:",
                "source_total_changes": source_changes, "network_requests": 0,
                "configured_horizon": horizon, "window_start_inclusive_utc": start.isoformat(), "window_end_exclusive_utc": end.isoformat(),
                "thresholds": {"sample_count_min": settings.trade_gate_min_evaluated_count, "win_rate_min_pct": settings.trade_gate_min_win_rate, "avg_return_min_pct": settings.trade_gate_min_avg_return, "win_return_strictly_above_pct": settings.validation_win_threshold_pct},
                "filters": "asset_type=stock, signal=BUY, generated_at in [start,end); exclude out_of_sample/live_holdout (NULL source treated live_paper_forward); return derived from non-NULL horizon price and positive entry, rounded4dp; no status, gate_passed, campaign, policy, ticker, or evaluated_at filter",
                "stock_buy_rows_before_holdout_filter": in_window_count,
                "stock_buy_rows_after_filters": len(buy_rows), "evaluated_count": len(measured), "wins": sum(repo._is_validation_win(value) for value in measured),
                "served_stock_buy_horizon_status_counts": dict(Counter(getattr(row, f"status_{horizon}") for row in buy_rows)),
                "independent_sql_evaluated_count": len(sql_returns),
                "per_score_band_actual_gate": bands, "latest_saved_scan": latest_run,
                "latest_saved_stock_buy_checks_historical": latest_buy_checks,
                "table_count_min_generated_max_generated_max_evaluated": table_times,
                "prediction_snapshot_status_counts_separate_context": prediction_counts,
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, indent=2, default=str) + "\n", encoding="utf-8")
            first = next(iter(bands.values()))
            print(json.dumps({"artifact": str(args.output.resolve()), "observed_at": output["observed_at_utc"], "horizon": horizon, "start": start, "end": end, "count": first["signal_count"], "win_rate": first["signal_win_rate"], "avg_return": first["signal_avg_return"], "latest_scan": latest_run, "source_changes": source_changes, "network_requests": 0}, default=str, indent=2))
    finally:
        captured_engine.dispose()


if __name__ == "__main__":
    main()
