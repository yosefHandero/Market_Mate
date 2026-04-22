from __future__ import annotations


def market_symbol_base(symbol: str) -> str:
    return symbol.split("/", 1)[0].replace("-", "").upper()


def market_symbol_quote(symbol: str) -> str:
    if "/" in symbol:
        return symbol.split("/", 1)[1].replace("-", "").upper()
    return "USD"


def to_binance_symbol(symbol: str) -> str:
    base = market_symbol_base(symbol)
    quote = market_symbol_quote(symbol)
    normalized_quote = "USDT" if quote == "USD" else quote
    return f"{base}{normalized_quote}"


def to_deribit_currency(symbol: str) -> str:
    return market_symbol_base(symbol)

