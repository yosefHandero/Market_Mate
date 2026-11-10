"""Inspect the actual one-hour BUY evidence gate using query-only production capture.

Does not start application services, call providers, resolve rows, or repair data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def read_worker_console(pid):
    """Read one existing Windows console buffer without sending any input."""
    if pid is None:
        return {"inspected":False}
    import ctypes
    from ctypes import wintypes
    class Coord(ctypes.Structure):
        _fields_ = [("x",ctypes.c_short),("y",ctypes.c_short)]
    class Rect(ctypes.Structure):
        _fields_ = [("left",ctypes.c_short),("top",ctypes.c_short),("right",ctypes.c_short),("bottom",ctypes.c_short)]
    class Info(ctypes.Structure):
        _fields_ = [("size",Coord),("cursor",Coord),("attr",ctypes.c_ushort),("window",Rect),("maxsize",Coord)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.FreeConsole()
    attached = bool(kernel.AttachConsole(pid))
    if not attached:
        return {"inspected":True,"attached":False,"windows_error":ctypes.get_last_error()}
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW("CONOUT$",0x80000000,3,None,3,0,None)
    try:
        info = Info()
        if not kernel.GetConsoleScreenBufferInfo(handle,ctypes.byref(info)):
            return {"inspected":True,"attached":True,"windows_error":ctypes.get_last_error()}
        size = info.size.x * info.size.y
        buffer = ctypes.create_unicode_buffer(size)
        count = wintypes.DWORD()
        kernel.ReadConsoleOutputCharacterW(handle,buffer,size,Coord(0,0),ctypes.byref(count))
        raw, cursor, events = buffer.value,0,[]
        decoder = json.JSONDecoder()
        while True:
            cursor = raw.find('{"timestamp"',cursor)
            if cursor < 0:
                break
            try:
                event,length = decoder.raw_decode(raw[cursor:])
            except ValueError:
                cursor += 1
                continue
            cursor += length
            if "Outcome signal " in event.get("message",""):
                events.append({key:event.get(key) for key in ("timestamp","message","event","ticker","code")})
        return {"inspected":True,"attached":True,"pid":pid,"signal_outcome_events":events,"success_logging_limit":"Resolver does not log successful per-row horizon HTTP responses; no matching event proves neither failure nor success."}
    finally:
        kernel.CloseHandle(handle)
        kernel.FreeConsole()


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--worker-pid",type=int,help="Read one existing worker console buffer; sends no console input")
    args = parser.parse_args()
    from app.config import get_settings
    settings = get_settings()
    database = Path(settings.database_url.removeprefix("sqlite:///"))
    database = (root / database).resolve() if not database.is_absolute() else database.resolve()
    attempts = []
    def no_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
            attempts.append(event)
            raise AssertionError("Network forbidden in signal BUY read-only inspection")
    sys.addaudithook(no_network)
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    get_settings.cache_clear()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.services.repository as repository_module

    captured_at = datetime.now(timezone.utc)
    observed = utc(args.observed_at) if args.observed_at else captured_at
    source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    memory = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        source.execute("PRAGMA query_only=ON")
        source.backup(memory)
        source_changes = source.total_changes
    finally:
        source.close()
    memory.row_factory = sqlite3.Row
    memory.execute("PRAGMA query_only=ON")
    engine = create_engine("sqlite://", creator=lambda: memory, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with patch.object(repository_module, "engine", engine), patch.object(repository_module, "SessionLocal", sessions):
            repo = repository_module.ScanRepository()
            repo.settings = settings
            start, end = repo.trust_window_bounds_for(observed_at=observed, horizon=settings.trade_gate_horizon)
            raw = [dict(row) for row in memory.execute("SELECT * FROM signal_outcomes WHERE generated_at>=? AND generated_at<? ORDER BY generated_at,id", (start.isoformat(sep=" "), end.isoformat(sep=" ")))]
            buys = [row for row in raw if row["signal"] == "BUY"]
            batch = repo.list_due_signal_outcome_evaluations(observed_at=observed, limit=8, exclude_ids=set())
            all_raw = [dict(row) for row in memory.execute("SELECT id,ticker,asset_type,signal,generated_at,entry_price,price_after_15m,price_after_1h,price_after_1d,price_after_1w,status_15m,status_1h,status_1d,status_1w FROM signal_outcomes")]
            due_rows = [row for row in all_raw if row["entry_price"] > 0 and any(row[f"price_after_{h}"] is None and row[f"status_{h}"] == "pending" and utc(row["generated_at"]) + delta <= observed for h,delta in repo._OUTCOME_HORIZONS.items())]
            due_rows.sort(key=lambda row: (int(utc(row["generated_at"]) < utc(start)), int(row["signal"] not in ("BUY", "SELL")), utc(row["generated_at"]), row["id"]))
            rank = {row["id"]: index+1 for index,row in enumerate(due_rows)}
            selected_ids = {item.outcome_id for item in batch}
            assets = {}
            for asset in ("stock", "crypto"):
                rows = [row for row in buys if row["asset_type"] == asset]
                served = [row for row in rows if (row["sample_source"] or "live_paper_forward") not in ("out_of_sample", "live_holdout")]
                counts = Counter(all_saved_buy_rows=len(rows), excluded_holdout=len(rows)-len(served), served_buy_rows=len(served))
                for row in served:
                    due = utc(row["generated_at"]) + timedelta(hours=1) <= observed
                    if not due:
                        counts["not_yet_due"] += 1
                    elif row["status_1h"] == "pending" and row["price_after_1h"] is None:
                        counts["due_pending"] += 1
                    if row["price_after_1h"] is not None and row["entry_price"] > 0:
                        counts["price_resolved_counted_by_gate"] += 1
                    if row["status_1h"] == "missed":
                        counts["missed"] += 1
                    if row["entry_price"] <= 0:
                        counts["unusable_entry_no_return"] += 1
                for key in ("not_yet_due", "due_pending", "price_resolved_counted_by_gate", "missed", "unusable_entry_no_return"):
                    counts.setdefault(key, 0)
                gates = {}
                for band in ("0-59", "60-69", "70-79", "80-89", "90-100"):
                    gate = repo.evaluate_signal_gate(asset_type=asset, signal="BUY", score_band=band, horizon=settings.trade_gate_horizon, observed_at=observed)
                    gates[band] = {**asdict(gate), "checks": [check.model_dump() for check in gate.checks]}
                compatible = [row for row in served if row["entry_price"] > 0 and row["price_after_1h"] is None and row["status_1h"] == "pending" and utc(row["generated_at"]) + timedelta(hours=1) <= observed]
                def trace(row):
                    if row is None:
                        return None
                    return {**row, "horizon_target_at_utc": utc(row["generated_at"]) + timedelta(hours=1), "normal_worker_queue_position_without_private_deferrals": rank.get(row["id"]), "selected_in_projected_next_batch": row["id"] in selected_ids}
                def lifecycle_counts(items):
                    return {
                        "rows":len(items),
                        "not_yet_due":sum(utc(row["generated_at"])+timedelta(hours=1)>observed for row in items),
                        "due_pending":sum(utc(row["generated_at"])+timedelta(hours=1)<=observed and row["status_1h"]=="pending" and row["price_after_1h"] is None for row in items),
                        "price_resolved":sum(row["price_after_1h"] is not None and row["entry_price"]>0 for row in items),
                        "missed":sum(row["status_1h"]=="missed" for row in items),
                        "status_counts":dict(Counter(row["status_1h"] for row in items)),
                    }
                resolved = [row for row in served if row["price_after_1h"] is not None and row["entry_price"]>0]
                assets[asset] = {"counts":dict(counts), "actual_gate_by_score_band":gates,
                                 "lifecycle_all_saved":lifecycle_counts(rows),
                                 "lifecycle_holdout_excluded":lifecycle_counts([row for row in rows if row not in served]),
                                 "newest_compatible_due_buy":trace(compatible[-1] if compatible else None),
                                 "oldest_compatible_due_buy":trace(compatible[0] if compatible else None),
                                 "all_compatible_due_buys_newest_first":[trace(row) for row in reversed(compatible)],
                                 "served_buy_rows_newest_first":[trace(row) for row in reversed(served)],
                                 "most_recent_price_resolved_served_buy":trace(resolved[-1] if resolved else None),
                                 "requested_ticker_rows":{ticker:[trace(row) for row in reversed(rows) if row["ticker"]==ticker][:2] for ticker in ("AMZN","MCD")},
                                 "source_counts":dict(Counter(row["sample_source"] for row in rows)),
                                 "status_counts_served":dict(Counter(row["status_1h"] for row in served))}
            latest = memory.execute("SELECT run_id,created_at FROM scan_runs ORDER BY created_at DESC LIMIT 1").fetchone()
            saved_checks = [dict(row) for row in memory.execute("SELECT run_id,ticker,asset_type,created_at,score,decision_signal,gate_passed,gate_reason,gate_checks_json FROM scan_results WHERE run_id=? AND (decision_signal='BUY' OR ticker IN ('AMZN','MCD'))", (latest["run_id"],))] if latest else []
            output = {"observed_at_utc":observed,"captured_at_utc":captured_at,"database":str(database),"production_access":"mode=ro/query_only production backup to query-only memory","production_changes":source_changes,"network_attempts":attempts,
                      "gate_horizon":settings.trade_gate_horizon,"window_start_inclusive_utc":utc(start),"window_end_exclusive_utc":utc(end),
                      "thresholds":{"stock_min_count":settings.trade_gate_min_evaluated_count,"crypto_buy_min_count":max(settings.trade_gate_min_evaluated_count,settings.trade_gate_crypto_buy_min_evaluated_count),"min_win_rate_pct":settings.trade_gate_min_win_rate,"min_avg_return_pct":settings.trade_gate_min_avg_return},
                      "filters":"asset type/direction, generated_at in [start,end), holdout-family excluded; gate derives return from non-NULL horizon price and positive entry, independently of status/stored return; no campaign/policy/ticker/gate_passed/evaluated_at filter",
                      "assets":assets,"latest_saved_scan":dict(latest) if latest else None,"latest_saved_checks":saved_checks,
                      "projected_worker_batch_limit_rows":8,"projected_worker_batch_horizon_evaluations":[asdict(item) for item in batch],"worker_due_row_count":len(due_rows),"private_worker_deferrals":"unknown; projection assumes none",
                      "resolver_contract":{"dispatch":"SchedulerService.run_forever -> refresh_due_signal_outcomes, same shared scan lease; inline scan also refreshes existing signal outcomes","horizon_price":"AlpacaClient.get_price_on_or_after_timestamp or crypto counterpart; first 5Min bar timestamp >= generated_at+1h; max_search_minutes=4320; no latest-price substitution","persistence":"ScanRepository.apply_signal_outcome_evaluations saves price_after_1h, price-derived return, resolved status and supplied actual evaluation time","positive_response_observability":"Successful horizon response not separately logged and resolved schema stores no actual selected-bar timestamp; persisted price and evaluation time are observable, exact HTTP response/bar cannot be reconstructed without captured bars"},
                      "existing_worker_console":read_worker_console(args.worker_pid)}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, indent=2, default=str)+"\n",encoding="utf-8")
            print(json.dumps({"observed_at_utc":observed,"start":utc(start),"assets":{a:{"counts":x["counts"],"gate":{key:x["actual_gate_by_score_band"]["0-59"][key] for key in ("signal_count","signal_win_rate","signal_avg_return")},"newest":x["newest_compatible_due_buy"]["id"] if x["newest_compatible_due_buy"] else None} for a,x in assets.items()},"batch":[(x.outcome_id,x.ticker,x.horizon) for x in batch],"output":str(args.output)},default=str,indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
