from __future__ import annotations

import json
from collections.abc import Sequence

import websockets


class CoinbaseAdvancedTradeWebSocketClient:
    def __init__(
        self,
        *,
        url: str,
        channel: str,
        product_ids: Sequence[str],
    ) -> None:
        self.url = url
        self.channel = channel
        self.product_ids = [item.strip().upper() for item in product_ids if item.strip()]

    def connect(self):
        return websockets.connect(
            self.url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
            max_queue=1000,
        )

    def build_subscribe_message(self) -> str:
        return json.dumps(
            {
                "type": "subscribe",
                "product_ids": self.product_ids,
                "channel": self.channel,
            }
        )

    async def subscribe(self, websocket) -> None:
        await websocket.send(self.build_subscribe_message())
