from __future__ import annotations

from app.clients.telegram import TelegramClient
from app.config import get_settings
from app.schemas import ScanRun


class AlertService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.telegram = TelegramClient()

    async def dispatch_for_run(self, run: ScanRun) -> int:
        sent = 0
        threshold = self.settings.alert_score_threshold
        for result in run.results:
            if result.decision_signal == "HOLD" or result.score < threshold or not getattr(result, "gate_passed", False):
                continue
            ok = await self.telegram.send_message(
                self._format_message(result, run.market_status)
            )
            if ok:
                result.alert_sent = True
                sent += 1
        run.alerts_sent = sent
        return sent

    def _format_message(self, result, market_status: str) -> str:
        options_bias = "Bullish" if result.options_flow_bullish else "Bearish"
        signal_label = result.signal_label.upper()
        decision_signal = result.decision_signal.upper()
        news_status = result.news_source.capitalize()

        lines = [
            f"🚨 *{result.ticker}* | Score *{result.score:.1f}*",
            f"Decision: *{decision_signal}*",
            f"Signal quality: *{signal_label}*",
            f"Buy/Sell thesis: *{result.buy_score:.1f} / {result.sell_score:.1f}*",
            f"Price: `${result.price:.2f}` ({result.price_change_pct:+.2f}%)",
            f"RelVol: *{result.relative_volume:.2f}x*",
            f"Options: *{options_bias}*",
            f"P/C: *{result.options_call_put_ratio:.2f}*",
            f"News: *{news_status}*",
            f"Market: *{market_status.capitalize()}*",
            f"Why: {self._short_reason(result)}",
        ]

        if result.news_cache_label:
            lines.append(f"News note: {result.news_cache_label}")
        if getattr(result, "gate_reason", None):
            lines.append(f"Gate: {result.gate_reason}")

        return "\n".join(lines)

    def _short_reason(self, result) -> str:
        reasons = []

        if result.decision_signal == "BUY":
            reasons.append("bullish thesis confirmed")
        elif result.decision_signal == "SELL":
            reasons.append("bearish thesis confirmed")

        if result.signal_label == "strong":
            reasons.append("high-conviction setup")
        elif result.signal_label == "watch":
            reasons.append("watchlist-quality setup")

        if result.relative_volume >= 3:
            reasons.append("strong volume")
        elif result.relative_volume >= 1.5:
            reasons.append("above-normal volume")

        if result.price_change_pct >= 4:
            reasons.append("strong price move")
        elif result.price_change_pct >= 1.5:
            reasons.append("good price momentum")
        elif result.price_change_pct <= -2:
            reasons.append("active downside move")

        if result.options_flow_bullish:
            reasons.append("bullish options flow")
        elif result.options_call_put_ratio >= 1.2:
            reasons.append("put-heavy options flow")

        if result.breakout_flag:
            reasons.append("breakout")
        elif result.decision_signal == "SELL" and result.price_change_pct < 0:
            reasons.append("downside structure")

        if result.filing_flag:
            reasons.append("recent filing")

        if result.news_source == "cache":
            reasons.append("cached news confirmation")
        elif result.news_source.startswith("marketaux+finnhub") or result.news_source == "marketaux":
            reasons.append("fresh news check")

        if not reasons:
            return "setup is active but mixed"

        return " + ".join(reasons[:3])
