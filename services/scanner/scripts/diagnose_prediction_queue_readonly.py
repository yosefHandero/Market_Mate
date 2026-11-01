"""Inspect due prediction progress without starting workers or contacting providers.

Production SQLite is opened mode=ro/query_only and copied to query-only memory.
Run again after normal worker operation and compare the resulting JSON artifacts.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from unittest.mock import patch


def utc(value):
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def worker_inventory():
    command = "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -match '(app.worker|uvicorn)' } | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=20, check=True)
        records = json.loads(result.stdout) if result.stdout.strip() else []
        return {"processes": records if isinstance(records, list) else [records], "query_ok": True, "queried_at_utc": datetime.now(timezone.utc)}
    except Exception as exc:
        return {"query_ok": False, "error_type": type(exc).__name__}


def main():
    scanner_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(scanner_root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observed-at", help="Fixed UTC window time; defaults to current capture time")
    args = parser.parse_args()
    from app.config import get_settings
    settings = get_settings()
    if not settings.database_url.startswith("sqlite:///"):
        raise SystemExit("Inspection requires the configured local SQLite database")
    database = Path(settings.database_url.removeprefix("sqlite:///"))
    database = (scanner_root / database).resolve() if not database.is_absolute() else database.resolve()
    attempts = []

    def forbid_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
            attempts.append(event)
            raise AssertionError("Network forbidden in read-only prediction diagnosis")

    sys.addaudithook(forbid_network)
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    get_settings.cache_clear()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.services.repository as repository_module

    captured_at = datetime.now(timezone.utc)
    observed_at = utc(args.observed_at) if args.observed_at else captured_at
    snapshot = sqlite3.connect(":memory:", check_same_thread=False)
    source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        source.execute("PRAGMA query_only=ON")
        source.backup(snapshot)
        source_changes = source.total_changes
    finally:
        source.close()
    snapshot.row_factory = sqlite3.Row
    snapshot.execute("PRAGMA query_only=ON")
    engine = create_engine("sqlite://", creator=lambda: snapshot, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with patch.object(repository_module, "engine", engine), patch.object(repository_module, "SessionLocal", sessions):
            repo = repository_module.ScanRepository()
            repo.settings = settings
            active = snapshot.execute("SELECT campaign_id,started_at,status,effective_policy_id,effective_policy_version FROM evidence_campaigns WHERE status='active' ORDER BY started_at DESC LIMIT 1").fetchone()
            campaign = active["campaign_id"] if active else None
            columns = "id,ticker,campaign_id,decision_role,policy_id,policy_version,decision_fingerprint,horizon,generated_at,status,price_at_horizon,evaluated_at,resolve_due_at,resolved_late,exit_window_status,estimated_exit_price,invalidation_level"
            rows = [dict(row) for row in snapshot.execute(f"SELECT {columns} FROM prediction_snapshots")]
            totals = defaultdict(Counter)
            eligible = []
            for row in rows:
                row["effective_horizon"] = (row["horizon"] or "1h").strip().lower()
                delta = repo._OUTCOME_HORIZONS.get(row["effective_horizon"])
                row["resolver_target_at"] = utc(row["generated_at"]) + delta if delta else None
                row["resolver_eligible"] = row["status"] == "pending" and delta is not None and row["resolver_target_at"] <= observed_at
                row["overdue"] = row["status"] == "pending" and row["resolve_due_at"] is not None and utc(row["resolve_due_at"]) < observed_at
                group = "current_campaign" if row["campaign_id"] == campaign and campaign else "older_or_unassigned"
                role = row["decision_role"] or "legacy_or_unknown"
                keys = ("all", group, f"{group}:{role}")
                for key in keys:
                    counts = totals[key]
                    counts["total"] += 1
                    counts[row["status"]] += 1
                    if row["status"] == "pending":
                        counts["eligible"] += int(row["resolver_eligible"])
                        counts["not_yet_due"] += int(delta is not None and not row["resolver_eligible"])
                        counts["unknown_horizon_pending"] += int(delta is None)
                        counts["overdue"] += int(row["overdue"])
                        counts["unknown_overdue_deadline_pending"] += int(row["resolve_due_at"] is None)
                    if row["status"] == "resolved":
                        counts["resolved_with_price"] += int(row["price_at_horizon"] is not None)
                        counts["resolved_without_price"] += int(row["price_at_horizon"] is None)
                if row["resolver_eligible"]:
                    eligible.append(row)
            eligible.sort(key=lambda row: (utc(row["generated_at"]), row["id"]))
            by_id = {row["id"]: row for row in rows}
            batch = repo.list_due_prediction_evaluations(observed_at=observed_at, limit=8, exclude_ids=set())
            selected_ids = [item.snapshot_id for item in batch]
            traces = {"production": None, "shadow": None}
            for role in ("production", "shadow"):
                for position, row in enumerate(eligible, start=1):
                    if row["campaign_id"] == campaign and row["decision_role"] == role:
                        traces[role] = {**row, "oldest_first_eligible_queue_position": position, "selected_in_actual_next_batch": row["id"] in selected_ids, "provider_response": "unknown unless an existing exact-id log states an exception; no live provider probe"}
                        break
            logs = []
            events = []
            for path in sorted((scanner_root / "var" / "run").glob("*worker*.log")):
                with path.open(encoding="utf-8", errors="replace") as log:
                    for line_number, line in enumerate(log, 1):
                        try:
                            event = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        if "timestamp" in event:
                            events.append({key: event.get(key) for key in ("timestamp", "level", "event", "message", "ticker", "stage", "snapshot_id")} | {"path": str(path.relative_to(scanner_root)), "line": line_number})
                logs.append({"path": str(path.relative_to(scanner_root)), "last_write_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)})
            events.sort(key=lambda event: event["timestamp"])
            for trace in traces.values():
                if trace is None:
                    continue
                matches = [event for event in events if re.search(rf"Outcome prediction {trace['id']}\b", event.get("message") or "")]
                trace["exact_id_log_matches"] = matches[-3:]
                if matches:
                    trace["provider_response"] = "Historical exact-id provider exception logged; horizon versus exit-path stage unknown because the existing event does not name the stage"
            prediction_events = [event for event in events if re.search(r"Outcome prediction \d+\b", event.get("message") or "")]
            completions = sorted((row for row in rows if row["evaluated_at"]), key=lambda row: (utc(row["evaluated_at"]), row["id"]), reverse=True)
            schema_tables = {row[0] for row in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            scheduler = [dict(row) for row in snapshot.execute("SELECT scheduler_key,enabled,worker_heartbeat_at,last_run_started_at,last_run_finished_at,last_error FROM scheduler_state")] if "scheduler_state" in schema_tables else []
            count_names = ("total", "pending", "not_yet_due", "eligible", "overdue", "resolved", "resolved_with_price", "resolved_without_price", "missed", "rejected_no_outcome", "unknown_horizon_pending", "unknown_overdue_deadline_pending")
            counts = {key: {name: value[name] for name in count_names} for key, value in totals.items()}
            output = {
                "observed_at_utc": observed_at, "captured_at_utc": captured_at,
                "database": str(database), "production_access": "SQLite mode=ro, query_only=ON backup to query-only memory", "production_changes": source_changes, "forbidden_network_attempts": attempts,
                "active_campaign": dict(active) if active else None,
                "count_semantics": "eligible=pending generated_at+stored normalized horizon<=observation; overdue=pending resolve_due_at<observation, overlaps eligible; resolved_with_price excludes missed/rejected and null prices",
                "counts": counts,
                "next_batch_limit": 8, "process_local_deferred_ids": "unavailable; next batch assumes none, matching a fresh worker", "actual_next_batch": [{**asdict(item), "campaign_id": by_id[item.snapshot_id]["campaign_id"], "decision_role": by_id[item.snapshot_id]["decision_role"]} for item in batch],
                "selector_source_sha256": hashlib.sha256(inspect.getsource(repo.list_due_prediction_evaluations).encode()).hexdigest(),
                "oldest_first_next_batch_ids": [row["id"] for row in eligible[:8]],
                "current_campaign_due_traces": traces, "latest_stored_completions": completions[:12],
                "completions_utc_date_counts": dict(Counter(str(row["evaluated_at"])[:10] for row in completions)),
                "worker_process_inventory": worker_inventory(), "scheduler_state": scheduler,
                "worker_log_files": logs, "latest_worker_event": events[-1] if events else None,
                "latest_prediction_specific_worker_event": prediction_events[-1] if prediction_events else None,
                "operational_note": "No worker started/restarted; no scans or provider requests; existing generic provider errors do not distinguish horizon from exit lookup failures",
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, indent=2, default=str) + "\n", encoding="utf-8")
            print(json.dumps({key: output[key] for key in ("observed_at_utc", "active_campaign", "counts", "oldest_first_next_batch_ids", "worker_process_inventory", "scheduler_state", "latest_worker_event", "latest_prediction_specific_worker_event")}, indent=2, default=str))
            print("Actual batch:", selected_ids)
            print("Current traces:", [(key, row["id"], row["oldest_first_eligible_queue_position"], row["selected_in_actual_next_batch"]) if row else (key, "no eligible row") for key, row in traces.items()])
            print("Artifact:", args.output.resolve())
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
