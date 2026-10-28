"""Per-job event log in a Redis Stream.

A stream (not plain pub/sub) gives every chunk an id, so an SSE client that
reconnects with Last-Event-ID resumes exactly where it stopped, and a client that
opens the page later can replay the whole answer.
"""

import json
from typing import Any, Protocol


class StreamRedis(Protocol):
    async def xadd(self, name: str, fields: Any, *args: Any, **kwargs: Any) -> Any: ...
    async def xread(self, streams: Any, count: Any = ..., block: Any = ...) -> Any: ...
    async def expire(self, name: str, time: int) -> Any: ...
    async def exists(self, *names: str) -> int: ...
    async def set(self, name: str, value: Any, *args: Any, **kwargs: Any) -> Any: ...


def stream_key(job_id: str) -> str:
    return f"jobstream:{job_id}"


def cancel_key(job_id: str) -> str:
    return f"jobcancel:{job_id}"


class JobEvents:
    def __init__(self, redis: StreamRedis, ttl: int = 3600) -> None:
        self.redis = redis
        self.ttl = ttl

    async def publish(self, job_id: str, kind: str, data: dict[str, Any]) -> str:
        key = stream_key(job_id)
        event_id = await self.redis.xadd(key, {"type": kind, "data": json.dumps(data)})
        await self.redis.expire(key, self.ttl)
        return event_id.decode() if isinstance(event_id, bytes) else str(event_id)

    async def read(
        self, job_id: str, after: str, block_ms: int, count: int = 200
    ) -> list[tuple[str, str, dict[str, Any]]]:
        response = await self.redis.xread({stream_key(job_id): after}, count=count, block=block_ms)
        events: list[tuple[str, str, dict[str, Any]]] = []
        for _stream, entries in response or []:
            for raw_id, fields in entries:
                decoded = {_s(k): _s(v) for k, v in fields.items()}
                events.append((_s(raw_id), decoded["type"], json.loads(decoded["data"])))
        return events

    async def has_stream(self, job_id: str) -> bool:
        return bool(await self.redis.exists(stream_key(job_id)))

    async def request_cancel(self, job_id: str) -> None:
        await self.redis.set(cancel_key(job_id), "1", ex=self.ttl)

    async def is_cancelled(self, job_id: str) -> bool:
        return bool(await self.redis.exists(cancel_key(job_id)))


def _s(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
