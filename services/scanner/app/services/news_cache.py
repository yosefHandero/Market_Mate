from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from app.config import get_settings


class NewsCacheService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.cache_dir_path.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.settings.cache_dir_path / "news_cache.json"

    def _load(self) -> dict:
        if not self.cache_file.exists():
            return {}
        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        self.cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get(self, ticker: str) -> tuple[float | None, str | None]:
        data = self._load()
        item = data.get(ticker)
        if not item:
            return None, None

        checked_at = datetime.fromisoformat(item["checked_at"])
        age = datetime.now(timezone.utc) - checked_at
        if age > timedelta(minutes=self.settings.news_cache_minutes):
            return None, None

        age_minutes = int(age.total_seconds() // 60)
        label = f"Cached news from {age_minutes} minute(s) ago"
        return float(item["sentiment_score"]), label

    def set(self, ticker: str, sentiment_score: float) -> None:
        data = self._load()
        data[ticker] = {
            "sentiment_score": sentiment_score,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save(data)