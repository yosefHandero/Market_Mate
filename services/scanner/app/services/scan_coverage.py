"""Capture scan-time coverage without changing candidate evaluation."""

from app.schemas import AssetType, ScanAssetCoverage, ScanMissingSymbol, ScanResult


def build_scan_coverage(
    *,
    asset_type: AssetType,
    expected_symbols: list[str],
    market_data: dict,
    provider_error: Exception | None,
    results: list[ScanResult],
    attempts_by_symbol: dict[str, dict] | None = None,
    benchmark_blocker: str | None = None,
    blocked_inputs: dict[str, dict] | None = None,
) -> ScanAssetCoverage:
    returned = {row.ticker for row in results if row.asset_type == asset_type}
    missing = []
    for ticker in expected_symbols:
        if ticker in returned:
            continue
        required_input = None
        blocked = (blocked_inputs or {}).get(ticker, {})
        news = blocked.get("directional_news")
        if asset_type == "stock" and ticker in {"SPY", "QQQ"} and market_data.get(ticker):
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
            if blocked.get("volume_reference"):
                required_input = "volume_reference"
                detail = "No positive reference volume could be calculated from the provider's OHLCV history. Check recent trading activity and feed coverage."
            elif news is not None:
                required_input = "directional_news"
                checks = []
                for check in news["providers"]:
                    status = check["status"].replace("_", " ")
                    http_status = check.get("http_status")
                    checks.append(f"{check['provider']} {status}" + (f" HTTP {http_status}" if http_status else ""))
                detail = f"Triggered directional news unavailable ({', '.join(checks)})."
            elif benchmark_blocker:
                required_input = "benchmark"
                detail = benchmark_blocker
            else:
                detail = "Market data was returned, but no analysis result was produced."
        attempts = (attempts_by_symbol or {}).get(ticker)
        if attempts and (reason in {"market_data_missing", "provider_unavailable"} or required_input == "volume_reference"):
            labels = (("primary", "Alpaca IEX"), ("fallback", "Alpaca SIP"), ("polygon", "Polygon"))
            checks = []
            for key, label in labels:
                state = attempts.get(f"{key}_status")
                if state:
                    status = attempts.get(f"{key}_http_status")
                    checks.append(f"{label}: {state.replace('_', ' ')}" + (f" (HTTP {status})" if status else ""))
            if checks:
                detail += " " + ", ".join(checks) + "."
        missing.append(ScanMissingSymbol(
            ticker=ticker, reason=reason, detail=detail, required_input=required_input, directional_news=news,
        ))
    returned_symbols = [ticker for ticker in expected_symbols if ticker in returned]
    status = (
        "not_requested" if not expected_symbols else
        "complete" if all(item.reason == "benchmark_only" for item in missing) else
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
