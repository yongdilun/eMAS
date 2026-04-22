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

    async def connect(self) -> None:
        if not self._redis_url or Redis is None:
            self._redis = None
            return
        self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        # cheap health check
        await self._redis.ping()

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
        self._redis = None

    async def publish(self, event: AgentEvent) -> None:
        if self._redis is None:
            return
        await self._redis.publish(self._channel, event.model_dump_json())

    async def listen(self, handler: Callable[[AgentEvent], Awaitable[None]]) -> None:
        if self._redis is None:
            return
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel)
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

