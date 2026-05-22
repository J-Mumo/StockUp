"""Simple Redis-backed rate limiting helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: int


def check_rate_limit(
    key: str,
    max_requests: int,
    window_seconds: int,
) -> RateLimitResult:
    """Check and increment a fixed-window rate limit counter.

    If Redis is unavailable, this helper fails open to avoid endpoint downtime.
    """
    settings = get_settings()
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    try:
        with redis_client.pipeline() as pipe:
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()

        if count == 1:
            redis_client.expire(key, window_seconds)
            ttl = window_seconds

        if ttl is None or ttl < 0:
            redis_client.expire(key, window_seconds)
            ttl = window_seconds

        if count > max_requests:
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after_seconds=int(ttl),
            )

        remaining = max(max_requests - int(count), 0)
        return RateLimitResult(
            allowed=True,
            remaining=remaining,
            retry_after_seconds=int(ttl),
        )
    except redis.RedisError as exc:
        logger.warning("Rate limiter unavailable, allowing request: %s", exc)
        return RateLimitResult(
            allowed=True,
            remaining=max_requests,
            retry_after_seconds=window_seconds,
        )
