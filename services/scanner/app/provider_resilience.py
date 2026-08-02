from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

RATE_LIMIT_COOLDOWN_THRESHOLD = 3
RATE_LIMIT_COOLDOWN_SECONDS = 60.0


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float
    stale_until: float


class AsyncProviderGuard:
    def __init__(self, provider: str, *, pace_seconds: float = 0.0) -> None:
        self.provider = provider
        self.pace_seconds = max(float(pace_seconds), 0.0)
        self._cache: dict[Any, _CacheEntry] = {}
        self._inflight: dict[Any, asyncio.Task[Any]] = {}
        self._last_served_stale: dict[Any, bool] = {}
        self._cache_lock = asyncio.Lock()
        self._pace_lock = asyncio.Lock()
        self._next_allowed_at = 0.0
        self._consecutive_rate_limits = 0

    def last_served_stale_for(self, key: Any) -> bool:
        return bool(self._last_served_stale.get(key))

    async def throttle(self) -> None:
        if self.pace_seconds <= 0:
            return
        loop = asyncio.get_running_loop()
        async with self._pace_lock:
            now = loop.time()
            wait_seconds = max(self._next_allowed_at - now, 0.0)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._next_allowed_at = max(self._next_allowed_at, loop.time()) + self.pace_seconds

    async def register_backoff(
        self,
        delay_seconds: float | None,
        *,
        rate_limited: bool = False,
    ) -> None:
        delay = max(float(delay_seconds or 0.0), self.pace_seconds)
        if rate_limited:
            self._consecutive_rate_limits += 1
            if self._consecutive_rate_limits >= RATE_LIMIT_COOLDOWN_THRESHOLD:
                delay = max(delay, RATE_LIMIT_COOLDOWN_SECONDS)
                logger.warning(
                    "provider rate-limit cooldown engaged",
                    extra={
                        "event": "provider_rate_limit_cooldown",
                        "provider": self.provider,
                        "consecutive_rate_limits": self._consecutive_rate_limits,
                        "cooldown_seconds": RATE_LIMIT_COOLDOWN_SECONDS,
                    },
                )
        else:
            self._consecutive_rate_limits = 0
        if delay <= 0:
            return
        loop = asyncio.get_running_loop()
        async with self._pace_lock:
            self._next_allowed_at = max(self._next_allowed_at, loop.time() + delay)

    async def cached_call(
        self,
        *,
        key: Any,
        fetcher: Callable[[], Awaitable[Any]],
        ttl_seconds: float = 0.0,
        stale_ttl_seconds: float = 0.0,
    ) -> Any:
        cached = await self._get_cached(key)
        if cached is not None:
            return cached

        async with self._cache_lock:
            cached = self._get_cached_unlocked(key)
            if cached is not None:
                self._record_stale_served_unlocked(key, False)
                return cached
            inflight = self._inflight.get(key)
            if inflight is None:
                inflight = asyncio.create_task(
                    self._execute(
                        key=key,
                        fetcher=fetcher,
                        ttl_seconds=ttl_seconds,
                        stale_ttl_seconds=stale_ttl_seconds,
                    )
                )
                self._inflight[key] = inflight

        try:
            return await inflight
        finally:
            async with self._cache_lock:
                if self._inflight.get(key) is inflight:
                    self._inflight.pop(key, None)

    async def _execute(
        self,
        *,
        key: Any,
        fetcher: Callable[[], Awaitable[Any]],
        ttl_seconds: float,
        stale_ttl_seconds: float,
    ) -> Any:
        stale_entry = await self._get_entry(key)
        try:
            value = await fetcher()
        except Exception:
            if stale_entry is not None and stale_entry.stale_until > asyncio.get_running_loop().time():
                await self._record_stale_served(key, True)
                logger.warning(
                    "provider fallback stale cache served",
                    extra={
                        "event": "provider_fallback_stale_served",
                        "provider": self.provider,
                    },
                )
                return stale_entry.value
            raise

        if ttl_seconds > 0 or stale_ttl_seconds > 0:
            await self._store(
                key,
                value,
                ttl_seconds=max(float(ttl_seconds), 0.0),
                stale_ttl_seconds=max(float(stale_ttl_seconds), 0.0),
            )
        await self._record_stale_served(key, False)
        self._consecutive_rate_limits = 0
        return value

    async def _get_cached(self, key: Any) -> Any | None:
        async with self._cache_lock:
            cached = self._get_cached_unlocked(key)
            if cached is not None:
                self._record_stale_served_unlocked(key, False)
            return cached

    def _get_cached_unlocked(self, key: Any) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        now = asyncio.get_running_loop().time()
        if entry.expires_at > now:
            return entry.value
        if entry.stale_until <= now:
            self._cache.pop(key, None)
        return None

    async def _get_entry(self, key: Any) -> _CacheEntry | None:
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            now = asyncio.get_running_loop().time()
            if entry.stale_until <= now:
                self._cache.pop(key, None)
                return None
            return entry

    async def _store(
        self,
        key: Any,
        value: Any,
        *,
        ttl_seconds: float,
        stale_ttl_seconds: float,
    ) -> None:
        now = asyncio.get_running_loop().time()
        async with self._cache_lock:
            self._cache[key] = _CacheEntry(
                value=value,
                expires_at=now + ttl_seconds,
                stale_until=now + max(ttl_seconds, stale_ttl_seconds),
            )

    async def _record_stale_served(self, key: Any, served_stale: bool) -> None:
        async with self._cache_lock:
            self._record_stale_served_unlocked(key, served_stale)

    def _record_stale_served_unlocked(self, key: Any, served_stale: bool) -> None:
        if served_stale:
            self._last_served_stale[key] = True
        else:
            self._last_served_stale.pop(key, None)
