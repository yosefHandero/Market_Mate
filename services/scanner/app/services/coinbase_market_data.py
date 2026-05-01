from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.clients.coinbase_advanced_trade_ws import CoinbaseAdvancedTradeWebSocketClient
from app.config import get_settings

logger = logging.getLogger(__name__)


class CoinbaseMarketDataService:
    def __init__(
        self,
        *,
        client: CoinbaseAdvancedTradeWebSocketClient | None = None,
    ) -> None:
        self.settings = get_settings()
        self.client = client or CoinbaseAdvancedTradeWebSocketClient(
            url=self.settings.coinbase_ws_url,
            channel=self.settings.coinbase_ws_channel,
            product_ids=self.settings.coinbase_ws_product_items,
        )
        self._stop_event = asyncio.Event()
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._channel_handlers = {
            "ticker": self._handle_ticker_message,
        }

    @property
    def enabled(self) -> bool:
        return self.settings.coinbase_ws_enabled and bool(self.client.product_ids)

    @property
    def snapshot_file_path(self) -> Path:
        return self.settings.cache_dir_path / "coinbase_advanced_trade_ticker.json"

    def stop(self) -> None:
        self._stop_event.set()

    def reset_for_testing(self) -> None:
        self._snapshots = {}
        self._stop_event = asyncio.Event()

    def list_snapshots(self) -> list[dict[str, Any]]:
        snapshots = self._load_snapshots()
        return [snapshots[key] for key in sorted(snapshots)]

    def get_latest_price(self, symbol: str) -> float | None:
        snapshot = self.get_snapshot_for_symbol(symbol)
        if snapshot is None:
            return None
        return float(snapshot["price"])

    def get_snapshot_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        product_id = self.product_id_for_symbol(symbol)
        snapshot = self._load_snapshots().get(product_id)
        if not snapshot:
            return None
        received_at = self._parse_timestamp(snapshot.get("received_at"))
        if received_at is None:
            return None
        age = datetime.now(timezone.utc) - received_at
        if age > timedelta(seconds=max(self.settings.coinbase_ws_snapshot_stale_seconds, 1)):
            return None
        return snapshot

    def apply_crypto_price_overrides(self, crypto_bars: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if not crypto_bars:
            return crypto_bars

        updated = dict(crypto_bars)
        for symbol, item in crypto_bars.items():
            snapshot = self.get_snapshot_for_symbol(symbol)
            if snapshot is None:
                continue

            refreshed = dict(item)
            refreshed["latest_price"] = float(snapshot["price"])
            refreshed["coinbase_price_received_at"] = snapshot["received_at"]
            refreshed["coinbase_product_id"] = snapshot["product_id"]
            updated[symbol] = refreshed

        return updated

    async def run_forever(self) -> None:
        if not self.enabled:
            logger.info(
                "coinbase websocket disabled",
                extra={"event": "coinbase_ws_disabled"},
            )
            return

        reconnect_delay = max(self.settings.coinbase_ws_reconnect_base_seconds, 0.1)
        while not self._stop_event.is_set():
            try:
                logger.info(
                    "connecting to coinbase advanced trade websocket",
                    extra={
                        "event": "coinbase_ws_connecting",
                        "url": self.client.url,
                        "channel": self.client.channel,
                        "product_ids": self.client.product_ids,
                    },
                )
                async with self.client.connect() as websocket:
                    await self.client.subscribe(websocket)
                    logger.info(
                        "subscribed to coinbase advanced trade websocket",
                        extra={
                            "event": "coinbase_ws_subscribed",
                            "channel": self.client.channel,
                            "product_ids": self.client.product_ids,
                        },
                    )
                    reconnect_delay = max(self.settings.coinbase_ws_reconnect_base_seconds, 0.1)
                    while not self._stop_event.is_set():
                        raw_message = await websocket.recv()
                        self.handle_message(raw_message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "coinbase websocket disconnected; reconnecting",
                    extra={
                        "event": "coinbase_ws_reconnecting",
                        "reconnect_delay_seconds": reconnect_delay,
                    },
                    exc_info=exc,
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(
                    reconnect_delay * 2,
                    max(self.settings.coinbase_ws_reconnect_max_seconds, reconnect_delay),
                )

    def handle_message(self, raw_message: str | bytes | dict[str, Any]) -> None:
        payload = self._coerce_payload(raw_message)
        if payload is None:
            return

        if self.settings.coinbase_ws_log_messages:
            logger.info(
                "coinbase websocket message received",
                extra={
                    "event": "coinbase_ws_message",
                    "channel": payload.get("channel"),
                    "type": payload.get("type"),
                    "sequence_num": payload.get("sequence_num"),
                    "product_ids": self._message_product_ids(payload),
                    "payload": payload,
                },
            )

        handler = self._channel_handlers.get(str(payload.get("channel") or "").lower())
        if handler is not None:
            handler(payload)

    def _handle_ticker_message(self, payload: dict[str, Any]) -> None:
        received_at = datetime.now(timezone.utc)
        sequence_num = payload.get("sequence_num")

        for event in payload.get("events", []):
            for ticker in event.get("tickers", []):
                product_id = str(ticker.get("product_id") or "").upper()
                price = self._parse_price(ticker.get("price"))
                if not product_id or price is None:
                    continue
                current = self._snapshots.get(product_id)
                if current is not None:
                    current_sequence = current.get("sequence_num")
                    if (
                        isinstance(sequence_num, int)
                        and isinstance(current_sequence, int)
                        and sequence_num < current_sequence
                    ):
                        continue
                snapshot = {
                    "symbol": self.symbol_for_product_id(product_id),
                    "product_id": product_id,
                    "price": price,
                    "received_at": received_at.isoformat(),
                    "channel": payload.get("channel"),
                    "event_type": event.get("type"),
                    "sequence_num": sequence_num,
                    "source": "coinbase_advanced_trade_ws",
                }
                self._snapshots[product_id] = snapshot

        if self._snapshots:
            self._persist_snapshots()

    def _load_snapshots(self) -> dict[str, dict[str, Any]]:
        if self._snapshots:
            return self._snapshots

        try:
            raw = json.loads(self.snapshot_file_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._snapshots
        except Exception as exc:
            logger.warning(
                "unable to load coinbase snapshot cache",
                extra={"event": "coinbase_ws_snapshot_load_failed"},
                exc_info=exc,
            )
            return self._snapshots

        snapshots: dict[str, dict[str, Any]] = {}
        for item in raw.get("prices", []):
            product_id = str(item.get("product_id") or "").upper()
            if product_id:
                snapshots[product_id] = item
        self._snapshots = snapshots
        return self._snapshots

    def _persist_snapshots(self) -> None:
        self.snapshot_file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"prices": [self._snapshots[key] for key in sorted(self._snapshots)]}
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.snapshot_file_path.parent,
                prefix=f"{self.snapshot_file_path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                json.dump(payload, tmp_file, indent=2, sort_keys=True)
            tmp_path.replace(self.snapshot_file_path)
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    logger.warning(
                        "unable to remove coinbase snapshot temp file",
                        extra={"event": "coinbase_ws_snapshot_temp_cleanup_failed"},
                        exc_info=True,
                    )

    def _coerce_payload(self, raw_message: str | bytes | dict[str, Any]) -> dict[str, Any] | None:
        if isinstance(raw_message, dict):
            return raw_message
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8")
        try:
            payload = json.loads(raw_message)
        except Exception:
            logger.warning(
                "received non-json coinbase websocket message",
                extra={"event": "coinbase_ws_invalid_message"},
            )
            return None
        return payload if isinstance(payload, dict) else None

    def _message_product_ids(self, payload: dict[str, Any]) -> list[str]:
        event_product_ids: list[str] = []
        for event in payload.get("events", []):
            for ticker in event.get("tickers", []):
                product_id = str(ticker.get("product_id") or "").upper()
                if product_id:
                    event_product_ids.append(product_id)
        return event_product_ids or list(payload.get("product_ids") or [])

    def _parse_timestamp(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                return None
        return None

    def _parse_price(self, value: Any) -> float | None:
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None

    def product_id_for_symbol(self, symbol: str) -> str:
        return symbol.strip().upper().replace("/", "-")

    def symbol_for_product_id(self, product_id: str) -> str:
        return product_id.strip().upper().replace("-", "/")
