from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.services.walk_forward_proof import WalkForwardProofService


async def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Run the historical walk-forward proof engine (daily-bar weekly-pattern layer)."
    )
    parser.add_argument(
        "--years",
        type=int,
        default=settings.proof_effective_years,
        help="Years of historical daily data to replay (clamped to configured min/max).",
    )
    parser.add_argument(
        "--step-days",
        type=int,
        default=settings.proof_step_days,
        help="Replay cadence in calendar days (7 = weekly, 1 = daily).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=settings.proof_effective_top_n_per_asset,
        help="Top candidates per asset class per replay date (3-5).",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-fetch daily history from providers even if cached.",
    )
    parser.add_argument(
        "--stock-only",
        action="store_true",
        help="Replay only the stock watchlist and skip crypto providers.",
    )
    parser.add_argument(
        "--crypto-only",
        action="store_true",
        help="Replay only the crypto watchlist (independent crypto proof run).",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "Wipe and refetch each symbol's stored daily history before running. "
            "Use after the split-adjustment fix so older raw-adjusted stock bars are "
            "replaced by uniformly split-adjusted bars. The daily-bar store is a "
            "refetchable cache, so this is non-destructive to evidence."
        ),
    )
    args = parser.parse_args()

    if args.stock_only and args.crypto_only:
        parser.error("--stock-only and --crypto-only are mutually exclusive.")

    if args.stock_only:
        symbols = settings.watchlist_items
    elif args.crypto_only:
        symbols = settings.crypto_watchlist_items
    else:
        symbols = None

    service = WalkForwardProofService()

    if args.rebuild:
        rebuild_symbols = symbols or (
            settings.watchlist_items + settings.crypto_watchlist_items
        )
        rebuild_symbols = [s for s in rebuild_symbols if s.upper() not in {"SPY", "QQQ"}]
        print(f"rebuilding daily history for {len(rebuild_symbols)} symbols...")
        for symbol in rebuild_symbols:
            cover = await service.bar_store.rebuild_history(symbol, years=args.years)
            print(f"  rebuilt {symbol}: {cover.bar_count} bars ({cover.source})")

    run_id, summary = await service.run(
        symbols=symbols,
        years=args.years,
        step_days=args.step_days,
        top_n_per_asset=args.top_n,
        force_refresh=args.force_refresh,
        persist=True,
    )
    verdict = summary.get("pilot_verdict", {})
    print(
        f"walk_forward_proof_complete run_id={run_id} "
        f"predictions={summary.get('prediction_count')} "
        f"resolved={summary.get('resolved_count')} "
        f"pilot_ready={verdict.get('ready')}"
    )
    for row in summary.get("by_asset_track", []):
        print(
            f"  {row['asset_type']}/{row['track']}: "
            f"n={row.get('resolved_count')} "
            f"upside_hit_rate={row.get('upside_hit_rate_pct')} "
            f"after_friction_stressed={row.get('avg_return_after_friction_stressed_pct')} "
            f"exit_helped={row.get('exit_window_helped_rate_pct')} "
            f"max_dd={row.get('max_drawdown_pct')}"
        )


if __name__ == "__main__":
    asyncio.run(main())
