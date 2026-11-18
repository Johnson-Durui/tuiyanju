"""Per-IP sliding-window rate limiter for API endpoints."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Request


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int
    remaining: int
    limit: int


class SlidingWindowRateLimiter:
    """In-memory sliding-window rate limiter keyed by client identifier."""

    def __init__(
        self,
        max_requests: int = 20,
        window_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_tracked_keys: int = 4096,
    ) -> None:
        self.max_requests = max(0, int(max_requests))
        self.window_seconds = max(1.0, float(window_seconds))
        self._clock = clock
        self._max_tracked_keys = max(64, int(max_tracked_keys))
        self._buckets: dict[str, deque[float]] = {}

    def _evict_expired(self, bucket: deque[float], cutoff: float) -> None:
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def _prune_stale_keys(self, cutoff: float) -> None:
        if len(self._buckets) < self._max_tracked_keys:
            return
        empty_keys: list[str] = []
        for key, bucket in self._buckets.items():
            self._evict_expired(bucket, cutoff)
            if not bucket:
                empty_keys.append(key)
        for key in empty_keys:
            self._buckets.pop(key, None)

    def check(self, client_key: str) -> RateLimitDecision:
        if self.max_requests <= 0:
            return RateLimitDecision(allowed=True, retry_after=0, remaining=999_999, limit=0)

        now = self._clock()
        cutoff = now - self.window_seconds
        key = (client_key or "anonymous").strip() or "anonymous"

        self._prune_stale_keys(cutoff)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = deque()
            self._buckets[key] = bucket
        else:
            self._evict_expired(bucket, cutoff)

        if len(bucket) >= self.max_requests:
            oldest = bucket[0]
            retry_after = max(1, int(math.ceil((oldest + self.window_seconds) - now)))
            return RateLimitDecision(
                allowed=False,
                retry_after=retry_after,
                remaining=0,
                limit=self.max_requests,
            )

        bucket.append(now)
        remaining = max(0, self.max_requests - len(bucket))
        return RateLimitDecision(
            allowed=True,
            retry_after=0,
            remaining=remaining,
            limit=self.max_requests,
        )

    def reset(self) -> None:
        self._buckets.clear()


def extract_client_ip(request: Request | None) -> str:
    if request is None:
        return "local"
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        first_hop = forwarded.split(",")[0].strip()
        if first_hop:
            return first_hop
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    if request.client and request.client.host:
        return request.client.host
    return "local"
