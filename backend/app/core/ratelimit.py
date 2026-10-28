"""Fixed-window rate limiter stored in Redis."""

from typing import Any

from app.core.errors import ApiError


async def hit(redis: Any, bucket: str, limit: int, window: int = 60) -> None:
    key = f"rl:{bucket}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)
    if count > limit:
        raise ApiError(429, "rate_limited", "Terlalu banyak permintaan, coba lagi sebentar lagi.")
