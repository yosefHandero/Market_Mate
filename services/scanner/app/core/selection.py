from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.brain.gates import buy_candidate_rank_score
from app.core.ranking import display_sort_key
from app.core.paper_action import paper_action_checks
from app.core.readiness import compute_trade_readiness
from app.schemas import ScanResult

AssetType = str


@dataclass(frozen=True)
class TopPickSelection:
    stocks: tuple[ScanResult, ...]
    crypto: tuple[ScanResult, ...]
    selection_ranks: dict[str, int]


def _sort_key_for_selection(
    row: ScanResult,
    *,
    settings: Settings,
) -> tuple[float, float, tuple[int, int, float, str]]:
    readiness = compute_trade_readiness(row)
    return (
        -buy_candidate_rank_score(row, settings=settings),
        -readiness.score,
        display_sort_key(
            row,
            settings=settings,
            resolve_signal=lambda item: item.decision_signal,
            scan_result=row,
        ),
    )


def _is_selectable_buy_candidate(row: ScanResult) -> bool:
    """Shortlist only BUYs the existing Decision paper-action checks allow."""
    return all(check.passed for check in paper_action_checks(row))


def select_top_picks(
    results: list[ScanResult],
    *,
    settings: Settings,
    limit: int = 3,
) -> TopPickSelection:
    selection_ranks: dict[str, int] = {}
    stocks: list[ScanResult] = []
    crypto: list[ScanResult] = []

    for asset_type, bucket in (("stock", stocks), ("crypto", crypto)):
        candidates = [
            row
            for row in results
            if row.asset_type == asset_type and _is_selectable_buy_candidate(row)
        ]
        ranked = sorted(
            candidates,
            key=lambda row: _sort_key_for_selection(row, settings=settings),
        )
        for index, row in enumerate(ranked[:limit]):
            selection_ranks[row.ticker] = index + 1
            bucket.append(row)

    return TopPickSelection(
        stocks=tuple(stocks),
        crypto=tuple(crypto),
        selection_ranks=selection_ranks,
    )


def apply_top_pick_selection(
    results: list[ScanResult],
    *,
    settings: Settings,
    limit: int = 3,
) -> list[ScanResult]:
    selection = select_top_picks(results, settings=settings, limit=limit)
    enriched: list[ScanResult] = []

    for row in results:
        readiness = compute_trade_readiness(row)
        recommended_action = readiness.action
        selection_rank = selection.selection_ranks.get(row.ticker)
        enriched.append(
            row.model_copy(
                update={
                    "readiness_score": readiness.score,
                    "readiness_band": readiness.band,
                    "readiness_hard_stop": readiness.hard_stop,
                    "readiness_reason": readiness.reason,
                    "recommended_action": recommended_action,
                    "selection_rank": selection_rank,
                    "is_top_pick": selection_rank is not None,
                }
            )
        )

    return enriched
