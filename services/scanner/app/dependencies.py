from __future__ import annotations

from app.services.automation import AutomationService
from app.services.automation_repository import AutomationRepository
from app.services.coinbase_market_data import CoinbaseMarketDataService
from app.services.execution import ExecutionService
from app.services.journal_repository import JournalRepository
from app.services.promotion import PromotionService
from app.services.replay import ReplayService
from app.services.repository import ScanRepository
from app.services.risk import RiskService
from app.services.scheduler import SchedulerService
from app.services.scanner import ScannerService

coinbase_market_data_service = CoinbaseMarketDataService()
scanner_service = ScannerService(market_data_service=coinbase_market_data_service)
journal_repository = JournalRepository()
scan_repository = ScanRepository()
risk_service = RiskService(scan_repository=scan_repository)
execution_service = ExecutionService(scan_repository=scan_repository)
automation_repository = AutomationRepository()
automation_service = AutomationService(
    repository=automation_repository,
    execution_service=execution_service,
)
scanner_service.automation_service = automation_service
replay_service = ReplayService()
scheduler_service = SchedulerService(scanner_service=scanner_service)
promotion_service = PromotionService(scan_repository=scan_repository)


def get_scanner_service() -> ScannerService:
    return scanner_service


def get_coinbase_market_data_service() -> CoinbaseMarketDataService:
    return coinbase_market_data_service


def get_execution_service() -> ExecutionService:
    return execution_service


def get_journal_repository() -> JournalRepository:
    return journal_repository


def get_risk_service() -> RiskService:
    return risk_service


def get_scan_repository() -> ScanRepository:
    return scan_repository


def get_replay_service() -> ReplayService:
    return replay_service


def get_scheduler_service() -> SchedulerService:
    return scheduler_service


def get_automation_service() -> AutomationService:
    return automation_service


def get_promotion_service() -> PromotionService:
    return promotion_service
