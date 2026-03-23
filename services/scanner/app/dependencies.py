from __future__ import annotations

from app.services.execution import ExecutionService
from app.services.journal_repository import JournalRepository
from app.services.repository import ScanRepository
from app.services.risk import RiskService
from app.services.scheduler import SchedulerService
from app.services.scanner import ScannerService

scanner_service = ScannerService()
execution_service = ExecutionService()
journal_repository = JournalRepository()
risk_service = RiskService()
scan_repository = ScanRepository()
scheduler_service = SchedulerService(scanner_service=scanner_service)


def get_scanner_service() -> ScannerService:
    return scanner_service


def get_execution_service() -> ExecutionService:
    return execution_service


def get_journal_repository() -> JournalRepository:
    return journal_repository


def get_risk_service() -> RiskService:
    return risk_service


def get_scan_repository() -> ScanRepository:
    return scan_repository


def get_scheduler_service() -> SchedulerService:
    return scheduler_service
