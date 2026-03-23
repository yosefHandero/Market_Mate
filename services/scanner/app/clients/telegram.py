from __future__ import annotations

import httpx

from app.config import get_settings
from app.http_client import request_json


class TelegramClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.telegram_alerts_enabled
            and self.settings.telegram_bot_token
            and self.settings.telegram_chat_id
        )

    async def send_message(self, text: str) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        data = await request_json(
            self._client,
            method="POST",
            url=url,
            json=payload,
        )
        return bool(data.get("ok"))
