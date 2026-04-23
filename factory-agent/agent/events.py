from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel

try:
    from redis.asyncio import Redis
except Exception:  # pragma: no cover
    Redis = None  # type: ignore


AgentEventType = Literal[
    "approval_decided",
    "session_resume",
    "tool_registry_updated",
    "session_cancel",
    "dlq_replay_requested",
    "worker_available",
]


class AgentEvent(BaseModel):
    event_type: AgentEventType
    session_id: str
    payload: dict[str, Any] = {}
    published_at: datetime


class EventBus:
    def __init__(self, *, redis_url: str | None, channel: str = "agent_events"):
        self._redis_url = redis_url
        self._channel = channel
        self._redis: Redis | None = None
        self._healthy: bool = False

    async def connect(self) -> None:
        if not self._redis_url or Redis is None:
            self._redis = None
            self._healthy = False
            return
        self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        # cheap health check
        await self._redis.ping()
        self._healthy = True

    @property
    def healthy(self) -> bool:
        return self._healthy

    async def ping(self) -> bool:
        if self._redis is None:
            self._healthy = False
            return False
        try:
            await self._redis.ping()
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False

    async def reconnect(self) -> bool:
        try:
            await self.close()
            await self.connect()
            return self._healthy
        except Exception:
            self._healthy = False
            return False

    async def close(self) -> None:
        if self._redis is not None:
            if hasattr(self._redis, "aclose"):
                await self._redis.aclose()
            else:  # pragma: no cover
                await self._redis.close()
        self._redis = None
        self._healthy = False

    async def publish(self, event: AgentEvent) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.publish(self._channel, event.model_dump_json())
            self._healthy = True
        except Exception:
            self._healthy = False
            raise

    async def listen(self, handler: Callable[[AgentEvent], Awaitable[None]]) -> None:
        if self._redis is None:
            return
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                try:
                    event = AgentEvent.model_validate_json(data)
                except Exception:
                    # Ignore malformed events
                    continue
                await handler(event)
        finally:
            self._healthy = False
            try:
                await pubsub.unsubscribe(self._channel)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass
