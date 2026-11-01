"""Disposable real-service HTTP fixture for the release browser walkthrough.

Only quotes and prior evidence are fixtures. Reuses the real hybrid scorer,
gate, selection, risk, execution, saved positions, due closure and ledger.
No application startup/worker is run and all non-loopback networking is blocked.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
temporary = tempfile.TemporaryDirectory(prefix="market-mate-release-ui-")
tempfile.tempdir = temporary.name
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(temporary.name) / 'default.db').as_posix()}"
os.environ["CACHE_DIR"] = str(Path(temporary.name) / "cache")
os.environ["EXECUTION_ENABLED"] = "false"
os.environ["ALLOW_LIVE_TRADING"] = "false"
violations = []


def guard(event, args):
    if event == "sqlite3.connect" and str(args[0]) != ":memory:":
        if not Path(args[0]).resolve().is_relative_to(Path(temporary.name).resolve()):
            violations.append(event)
            raise AssertionError("Fixture blocked a non-temporary database")
    if event == "socket.connect" and args[1][0] not in {"127.0.0.1", "::1"}:
        violations.append(event)
        raise AssertionError("Fixture blocked external networking")
    if event in {"socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
        violations.append(event)
        raise AssertionError("Fixture blocked external networking")


sys.addaudithook(guard)
from sqlalchemy import select, update
from app.db import Base
from app.errors import AppError
from app.models.scan import ExecutionAuditORM, PaperPositionORM, ScanResultORM
from app.schemas import OrderPlaceRequest, OrderPreviewRequest
import app.services.execution as execution_module
import app.services.repository as repository_module
import app.services.risk as risk_module
import app.services.scanner as scanner_module
from tests.test_paper_contract import PaperContractAcceptanceTests, _clock_at

case = PaperContractAcceptanceTests()
case.setUp()
case.stack.enter_context(patch.object(repository_module, "engine", case.engine))
case._store_hybrid_buy()
if "--blocked" in sys.argv:
    with case.SessionLocal.begin() as session:
        session.execute(update(ScanResultORM).values(provider_status="critical", readiness_hard_stop=True))
now = case.fill_at
requests = []
last_place_request = None
last_preview = None


def encode(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def clocks():
    stack = ExitStack()
    for module in (execution_module, repository_module, scanner_module, risk_module):
        stack.enter_context(patch.object(module, "datetime", _clock_at(now)))
    return stack


def state():
    with case.SessionLocal() as session:
        counts = {"positions": len(session.scalars(select(PaperPositionORM)).all()),
                  "audits": len(session.scalars(select(ExecutionAuditORM)).all())}
    return {"now": now, "initial_fill_at": case.fill_at, "settings_horizon": case.settings.trade_gate_horizon,
            "positions": case.repo.list_paper_positions(observed_at=now),
            "summary": case.repo.get_paper_ledger_summary(observed_at=now),
            "counts": counts, "violations": violations, "requests": requests,
            "last_place_request": last_place_request}


class Handler(BaseHTTPRequestHandler):
    def dispatch(self, payload):
        global now, last_place_request, last_preview
        path = self.path.split("?", 1)[0]
        if path != "/fixture/state":
            requests.append({"method": self.command, "path": path, "payload": payload})
        with clocks():
            if path == "/scan/latest":
                return case.repo.get_latest_run()
            if path == "/dashboard/decisions/latest":
                return case.repo.get_latest_decisions()
            if path == "/orders/preview":
                case.execution.alpaca.get_latest_price.return_value = 100.0
                last_preview = asyncio.run(case.execution.preview(OrderPreviewRequest.model_validate(payload)))
                return last_preview
            if path == "/orders/place":
                last_place_request = payload
                case.execution.alpaca.get_latest_price.return_value = 101.0
                return asyncio.run(case.execution.place(OrderPlaceRequest.model_validate(payload)))
            if path == "/orders/audits":
                return case.repo.list_execution_audits(limit=50)
            if path == "/paper/ledger":
                return case.repo.list_paper_positions(observed_at=now)
            if path == "/paper/ledger/summary":
                return case.repo.get_paper_ledger_summary(observed_at=now)
            if path == "/proof/summary":
                return {"generated_at": now, "ledger": case.repo.get_paper_ledger_summary(observed_at=now),
                        "loop_metrics": {"recent_dry_runs": int(bool(last_place_request)), "recent_previewed": int(bool(last_preview)), "recent_blocked": 0, "total_audits": len(case.repo.list_execution_audits())},
                        "live_forward": case.repo.get_live_forward_progress(now=now),
                        "prediction_accuracy": case.repo.get_prediction_accuracy_summary(),
                        "confidence_performance": case.repo.get_confidence_performance(),
                        "last_scan_at": case.scan_at, "scan_fresh": True,
                        "note": "Isolated real-service fixture. Gross paper P/L comes from actual simulated fills and closes; signal evidence is separate."}
            if path == "/fixture/state":
                return state()
            if path == "/fixture/control":
                action = payload["action"]
                if action == "missing_exit":
                    now = case.fill_at + timedelta(hours=1, minutes=5)
                    case.settings.trade_gate_horizon = "1d"
                    case.scanner.alpaca.get_latest_price.side_effect = RuntimeError("mock missing exit quote")
                    closed = case._close_at(now)
                elif action == "close_late":
                    now = case.fill_at + timedelta(hours=1, minutes=10)
                    case.scanner.alpaca.get_latest_price.side_effect = None
                    case.scanner.alpaca.get_latest_price.return_value = 104.0
                    closed = case._close_at(now)
                elif action == "duplicate_close":
                    closed = case._close_at(now)
                elif action == "block_buy":
                    now = case.fill_at
                    case.settings.trade_gate_horizon = "1h"
                    with case.SessionLocal.begin() as session:
                        session.execute(update(ScanResultORM).values(provider_status="critical", readiness_hard_stop=True))
                    closed = None
                else:
                    raise ValueError("Unknown fixture action")
                return {"closed": closed, **state()}
        raise LookupError(path)

    def handle_request(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length)) if length else None
            data = self.dispatch(payload)
            status = 200
        except AppError as exc:
            data, status = {"detail": exc.message, "code": exc.code}, exc.status_code
        except Exception as exc:
            import traceback
            traceback.print_exc()
            data, status = {"detail": str(exc)}, 500
        raw = json.dumps(data, default=encode).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = handle_request
    do_POST = handle_request


try:
    print(f"REAL fixture backend: http://127.0.0.1:8018; database {temporary.name}; quotes mocked", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8018), Handler).serve_forever()
finally:
    case.doCleanups()
    temporary.cleanup()
