"""Capture scan-time coverage without changing candidate evaluation."""

from app.schemas import AssetType, ScanAssetCoverage, ScanMissingSymbol, ScanResult


def build_scan_coverage(
    *,
    asset_type: AssetType,
    expected_symbols: list[str],
    market_data: dict,
    provider_error: Exception | None,
    results: list[ScanResult],
) -> ScanAssetCoverage:
    returned = {row.ticker for row in results if row.asset_type == asset_type}
    missing = []
    for ticker in expected_symbols:
        if ticker in returned:
            continue
        if asset_type == "stock" and ticker in {"SPY", "QQQ"}:
            reason = "benchmark_only"
            detail = "Used as a market benchmark; not analyzed as a candidate."
        elif provider_error is not None:
            reason = "provider_unavailable"
            status = getattr(provider_error, "status_code", None)
            suffix = f", HTTP {status}" if status is not None else ""
            # Persist the failure category, not potentially sensitive request URLs.
            detail = f"Market data provider unavailable ({type(provider_error).__name__}{suffix})."
        elif not market_data.get(ticker):
            reason = "market_data_missing"
            detail = "No usable market data returned for this symbol."
        else:
            reason = "analysis_skipped"
            detail = "Market data was returned, but no analysis result was produced."
        missing.append(ScanMissingSymbol(ticker=ticker, reason=reason, detail=detail))
    returned_symbols = [ticker for ticker in expected_symbols if ticker in returned]
    status = (
        "not_requested" if not expected_symbols else
        "complete" if not missing else
        "partial" if returned_symbols else
        "unavailable"
    )
    return ScanAssetCoverage(
        asset_type=asset_type,
        expected_symbols=expected_symbols,
        returned_symbols=returned_symbols,
        missing_symbols=missing,
        status=status,
    )
