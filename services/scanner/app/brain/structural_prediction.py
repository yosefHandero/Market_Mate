from __future__ import annotations

from dataclasses import dataclass

from app.schemas import DecisionSignal, PricePrediction

_VOLATILITY_BANDS: dict[str, tuple[float, float]] = {
    "low": (0.01, 0.02),
    "normal": (0.01, 0.02),
    "elevated": (0.015, 0.03),
    "high": (0.02, 0.04),
    "extreme": (0.025, 0.05),
}

_HORIZON_LABELS = {
    "15m": "15 minutes",
    "1h": "1 hour",
    "1d": "1 day",
    "1w": "1 week",
}


def _stop_target_pcts(volatility_regime: str) -> tuple[float, float]:
    return _VOLATILITY_BANDS.get((volatility_regime or "normal").strip().lower(), (0.01, 0.02))


def build_structural_prediction(
    *,
    price: float,
    decision_signal: DecisionSignal,
    volatility_regime: str,
    horizon: str,
    asset_type: str = "stock",
    atr_pct: float | None = None,
    atr_target_mult: float = 2.5,
    atr_stop_mult: float = 1.5,
) -> PricePrediction:
    entry = max(0.01, float(price))
    stop_pct, target_pct = _stop_target_pcts(volatility_regime)
    if atr_pct is not None and atr_pct > 0:
        # Size stop/target from realized volatility (ATR) rather than fixed regime
        # bands, so ranges adapt to each symbol's actual movement.
        atr_fraction = float(atr_pct) / 100.0
        stop_pct = max(0.005, atr_fraction * float(atr_stop_mult))
        target_pct = max(0.005, atr_fraction * float(atr_target_mult))
    horizon_key = (horizon or "1h").strip().lower()
    horizon_label = _HORIZON_LABELS.get(horizon_key, horizon_key)

    if decision_signal == "BUY":
        stop = round(entry * (1 - stop_pct), 2)
        target = round(entry * (1 + target_pct), 2)
        range_low, range_high = stop, target
        invalidation = f"Invalidate if price closes below ${stop:.2f} (structural stop)."
    elif decision_signal == "SELL":
        stop = round(entry * (1 + stop_pct), 2)
        target = round(entry * (1 - target_pct), 2)
        range_low, range_high = target, stop
        invalidation = f"Invalidate if price closes above ${stop:.2f} (structural stop)."
    else:
        band = round(entry * stop_pct, 2)
        range_low = round(max(0.01, entry - band), 2)
        range_high = round(entry + band, 2)
        invalidation = "No directional thesis; range is observation-only."

    asset_note = "crypto" if asset_type == "crypto" else "stock"
    return PricePrediction(
        range_low=range_low,
        range_high=range_high,
        horizon=horizon_key,
        horizon_label=horizon_label,
        invalidation=invalidation,
        methodology="structural_stop_target",
        disclaimer=(
            f"Structural {asset_note} range from stop/target levels aligned with paper sizing. "
            "Not a guarantee or price target."
        ),
    )


@dataclass(frozen=True)
class PredictionAccuracyVerdict:
    outcome: str
    in_range: bool | None


def evaluate_prediction_accuracy(
    *,
    decision_signal: DecisionSignal,
    range_low: float,
    range_high: float,
    price_at_horizon: float | None,
) -> PredictionAccuracyVerdict:
    if price_at_horizon is None:
        return PredictionAccuracyVerdict(outcome="missed", in_range=None)
    low = min(range_low, range_high)
    high = max(range_low, range_high)
    if low <= price_at_horizon <= high:
        return PredictionAccuracyVerdict(outcome="in_range", in_range=True)
    if price_at_horizon < low:
        return PredictionAccuracyVerdict(outcome="below_range", in_range=False)
    return PredictionAccuracyVerdict(outcome="above_range", in_range=False)


@dataclass(frozen=True)
class PriceBar:
    high: float
    low: float


@dataclass(frozen=True)
class ExitWindowOutcome:
    exit_window_status: str
    exit_hit: bool
    invalidation_hit: bool
    protected_return_pct: float | None
    hold_return_pct: float | None
    exit_window_helped: bool | None
    # True when the resolving bar touched BOTH the exit target and the stop within
    # a single (daily) bar, so the outcome relied on the conservative "assume stop
    # first" tie-break rather than an unambiguous single-level touch. Measurement
    # only; it does not change which outcome wins.
    exit_conflict: bool = False


def _return_pct(entry: float, exit_price: float) -> float:
    return round(((exit_price - entry) / entry) * 100.0, 4)


def _bar_high(bar: PriceBar | dict) -> float:
    if isinstance(bar, PriceBar):
        return bar.high
    return float(bar.get("h") or bar.get("high") or 0.0)


def _bar_low(bar: PriceBar | dict) -> float:
    if isinstance(bar, PriceBar):
        return bar.low
    return float(bar.get("l") or bar.get("low") or 0.0)


def _buy_bar_touches_exit(bar: PriceBar | dict, exit_price: float) -> bool:
    return _bar_high(bar) >= exit_price


def _buy_bar_touches_invalidation(bar: PriceBar | dict, invalidation_level: float) -> bool:
    return _bar_low(bar) <= invalidation_level


def _resolve_buy_bar_conflict(
    bar: PriceBar | dict,
    *,
    exit_price: float,
    invalidation_level: float,
    finer_bars: list[PriceBar | dict] | None,
) -> str:
    """Return 'exit', 'invalidation', or 'none' for a bar where both levels may touch."""
    if not (_buy_bar_touches_exit(bar, exit_price) and _buy_bar_touches_invalidation(bar, invalidation_level)):
        if _buy_bar_touches_exit(bar, exit_price):
            return "exit"
        if _buy_bar_touches_invalidation(bar, invalidation_level):
            return "invalidation"
        return "none"
    if finer_bars:
        for sub_bar in finer_bars:
            touches_exit = _buy_bar_touches_exit(sub_bar, exit_price)
            touches_inv = _buy_bar_touches_invalidation(sub_bar, invalidation_level)
            if touches_exit and touches_inv:
                return "invalidation"
            if touches_inv:
                return "invalidation"
            if touches_exit:
                return "exit"
        return "invalidation"
    return "invalidation"


def evaluate_exit_window_outcome(
    *,
    entry_price: float,
    estimated_exit_price: float | None,
    invalidation_level: float | None,
    price_at_horizon: float | None,
    decision_signal: DecisionSignal,
    bars: list[PriceBar | dict],
    friction_pct: float = 0.0,
) -> ExitWindowOutcome:
    entry = max(0.01, float(entry_price))
    if price_at_horizon is None:
        return ExitWindowOutcome(
            exit_window_status="missed",
            exit_hit=False,
            invalidation_hit=False,
            protected_return_pct=None,
            hold_return_pct=None,
            exit_window_helped=None,
        )
    hold_return = _return_pct(entry, float(price_at_horizon))
    if decision_signal != "BUY" or estimated_exit_price is None:
        protected = hold_return
        return ExitWindowOutcome(
            exit_window_status="resolved",
            exit_hit=False,
            invalidation_hit=False,
            protected_return_pct=protected,
            hold_return_pct=hold_return,
            exit_window_helped=(protected - friction_pct) >= (hold_return - friction_pct),
        )
    exit_price = float(estimated_exit_price)
    stop = float(invalidation_level) if invalidation_level is not None else None
    exit_hit = False
    invalidation_hit = False
    exit_conflict = False
    protected = hold_return
    for bar in bars:
        if stop is not None:
            both_touched = _buy_bar_touches_exit(bar, exit_price) and _buy_bar_touches_invalidation(bar, stop)
            conflict = _resolve_buy_bar_conflict(bar, exit_price=exit_price, invalidation_level=stop, finer_bars=None)
            if conflict == "invalidation":
                invalidation_hit = True
                exit_conflict = both_touched
                protected = _return_pct(entry, stop)
                break
            if conflict == "exit":
                exit_hit = True
                exit_conflict = both_touched
                protected = _return_pct(entry, exit_price)
                break
        elif _buy_bar_touches_exit(bar, exit_price):
            exit_hit = True
            protected = _return_pct(entry, exit_price)
            break
    protected_after_friction = round(protected - friction_pct, 4)
    hold_after_friction = round(hold_return - friction_pct, 4)
    return ExitWindowOutcome(
        exit_window_status="resolved",
        exit_hit=exit_hit,
        invalidation_hit=invalidation_hit,
        protected_return_pct=protected,
        hold_return_pct=hold_return,
        exit_window_helped=protected_after_friction >= hold_after_friction,
        exit_conflict=exit_conflict,
    )


def evaluate_exit_window_outcome_with_disambiguation(
    *,
    entry_price: float,
    estimated_exit_price: float | None,
    invalidation_level: float | None,
    price_at_horizon: float | None,
    decision_signal: DecisionSignal,
    bars: list[PriceBar | dict],
    finer_bars_by_index: dict[int, list[PriceBar | dict]] | None = None,
    friction_pct: float = 0.0,
) -> ExitWindowOutcome:
    entry = max(0.01, float(entry_price))
    if price_at_horizon is None:
        return ExitWindowOutcome(
            exit_window_status="missed",
            exit_hit=False,
            invalidation_hit=False,
            protected_return_pct=None,
            hold_return_pct=None,
            exit_window_helped=None,
        )
    hold_return = _return_pct(entry, float(price_at_horizon))
    if decision_signal != "BUY" or estimated_exit_price is None:
        protected = hold_return
        protected_after_friction = round(protected - friction_pct, 4)
        hold_after_friction = round(hold_return - friction_pct, 4)
        return ExitWindowOutcome(
            exit_window_status="resolved",
            exit_hit=False,
            invalidation_hit=False,
            protected_return_pct=protected,
            hold_return_pct=hold_return,
            exit_window_helped=protected_after_friction >= hold_after_friction,
        )
    exit_price = float(estimated_exit_price)
    stop = float(invalidation_level) if invalidation_level is not None else None
    exit_hit = False
    invalidation_hit = False
    exit_conflict = False
    protected = hold_return
    finer = finer_bars_by_index or {}
    for index, bar in enumerate(bars):
        if stop is not None:
            both_touched = _buy_bar_touches_exit(bar, exit_price) and _buy_bar_touches_invalidation(bar, stop)
            conflict = _resolve_buy_bar_conflict(
                bar,
                exit_price=exit_price,
                invalidation_level=stop,
                finer_bars=finer.get(index),
            )
            if conflict == "invalidation":
                invalidation_hit = True
                exit_conflict = both_touched
                protected = _return_pct(entry, stop)
                break
            if conflict == "exit":
                exit_hit = True
                exit_conflict = both_touched
                protected = _return_pct(entry, exit_price)
                break
        elif _buy_bar_touches_exit(bar, exit_price):
            exit_hit = True
            protected = _return_pct(entry, exit_price)
            break
    protected_after_friction = round(protected - friction_pct, 4)
    hold_after_friction = round(hold_return - friction_pct, 4)
    return ExitWindowOutcome(
        exit_window_status="resolved",
        exit_hit=exit_hit,
        invalidation_hit=invalidation_hit,
        protected_return_pct=protected,
        hold_return_pct=hold_return,
        exit_window_helped=protected_after_friction >= hold_after_friction,
        exit_conflict=exit_conflict,
    )
