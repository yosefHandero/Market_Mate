from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_bar_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        if value > 1_000_000_000_000:
            return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc)
        return datetime.fromtimestamp(value, tz=timezone.utc)
    raise RuntimeError(f"Unsupported bar timestamp format: {value!r}")


def bars_as_of(bars: list[dict[str, Any]], as_of: datetime) -> list[dict[str, Any]]:
    comparable = as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    filtered: list[dict[str, Any]] = []
    for bar in bars:
        timestamp = bar.get("t")
        if timestamp is None:
            continue
        parsed = parse_bar_timestamp(timestamp)
        if parsed <= comparable:
            filtered.append(bar)
    return filtered


def close_price(bar: dict[str, Any]) -> float:
    return float(bar.get("c", 0) or 0)


def sorted_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(bars, key=lambda row: parse_bar_timestamp(row.get("t")))


def forward_close_after(
    bars: list[dict[str, Any]],
    *,
    as_of: datetime,
    forward_days: int = 7,
    tolerance_days: int = 3,
) -> float | None:
    comparable = as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    target = comparable.timestamp() + forward_days * 86400
    tolerance = tolerance_days * 86400
    candidates: list[tuple[float, float]] = []
    for bar in sorted_bars(bars):
        parsed = parse_bar_timestamp(bar.get("t"))
        delta = parsed.timestamp() - target
        if delta >= -tolerance:
            price = close_price(bar)
            if price > 0:
                candidates.append((abs(delta), price))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]
