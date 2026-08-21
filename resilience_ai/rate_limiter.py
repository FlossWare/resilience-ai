"""Per-provider rate limiter using a token-bucket algorithm.

Async-native (``asyncio.Lock``), zero external dependencies.  Parses
standard rate-limit response headers so the bucket can be adjusted
after each HTTP response.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProviderLimits:
    """Rate-limit configuration for a single provider.

    Parameters
    ----------
    requests_per_minute:
        Maximum request throughput.  ``0`` disables the request-rate
        limit.
    tokens_per_minute:
        Maximum token throughput.  ``0`` disables the token-rate limit.
    """

    requests_per_minute: float = 60.0
    tokens_per_minute: float = 0.0


@dataclass
class _BucketState:
    """Internal mutable state for one token bucket."""

    tokens: float
    capacity: float
    refill_rate: float
    last_refill: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def refill(self, now: float) -> None:
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.refill_rate,
            )
            self.last_refill = now


@dataclass
class RateLimitInfo:
    """Parsed rate-limit metadata from HTTP response headers."""

    remaining: int | None = None
    reset_at: float | None = None
    retry_after: float | None = None


class RateLimiter:
    """Per-provider token-bucket rate limiter.

    Each provider gets independent request-rate and (optionally)
    token-rate buckets.  Call :meth:`acquire` before issuing a request
    and :meth:`record_tokens` afterwards if token-rate limiting is
    enabled.

    Parameters
    ----------
    default_limits:
        Fallback limits applied when a provider has no explicit entry.
    provider_limits:
        Per-provider overrides keyed by provider name.
    """

    def __init__(
        self,
        default_limits: ProviderLimits | None = None,
        provider_limits: dict[str, ProviderLimits] | None = None,
    ) -> None:
        self._default_limits = default_limits or ProviderLimits()
        self._provider_limits: dict[str, ProviderLimits] = dict(provider_limits or {})
        self._request_buckets: dict[str, _BucketState] = {}
        self._token_buckets: dict[str, _BucketState] = {}

    def _limits_for(self, provider: str) -> ProviderLimits:
        return self._provider_limits.get(provider, self._default_limits)

    def _get_request_bucket(self, provider: str) -> _BucketState:
        if provider not in self._request_buckets:
            limits = self._limits_for(provider)
            capacity = limits.requests_per_minute
            refill_rate = capacity / 60.0
            self._request_buckets[provider] = _BucketState(
                tokens=capacity,
                capacity=capacity,
                refill_rate=refill_rate,
                last_refill=time.monotonic(),
            )
        return self._request_buckets[provider]

    def _get_token_bucket(self, provider: str) -> _BucketState:
        if provider not in self._token_buckets:
            limits = self._limits_for(provider)
            capacity = limits.tokens_per_minute
            refill_rate = capacity / 60.0
            self._token_buckets[provider] = _BucketState(
                tokens=capacity,
                capacity=capacity,
                refill_rate=refill_rate,
                last_refill=time.monotonic(),
            )
        return self._token_buckets[provider]

    async def acquire(self, provider: str, *, tokens: int = 0) -> float:
        """Wait until a request slot is available, then consume it.

        Returns the number of seconds spent waiting (``0.0`` if the
        bucket had capacity).

        Parameters
        ----------
        provider:
            Provider name (used to look up the correct bucket).
        tokens:
            Estimated token count for pre-flight token-rate checking.
            Pass ``0`` to skip token-bucket validation.
        """
        waited = 0.0

        limits = self._limits_for(provider)

        if limits.requests_per_minute > 0:
            waited += await self._acquire_from(
                self._get_request_bucket(provider), cost=1.0
            )

        if tokens > 0 and limits.tokens_per_minute > 0:
            waited += await self._acquire_from(
                self._get_token_bucket(provider), cost=float(tokens)
            )

        return waited

    async def record_tokens(self, provider: str, tokens: int) -> None:
        """Deduct *tokens* from the provider's token-rate bucket.

        Call this after receiving a response to account for the actual
        token usage (as opposed to a pre-flight estimate).
        """
        limits = self._limits_for(provider)
        if tokens <= 0 or limits.tokens_per_minute <= 0:
            return

        bucket = self._get_token_bucket(provider)
        async with bucket.lock:
            bucket.refill(time.monotonic())
            bucket.tokens = max(0.0, bucket.tokens - tokens)

    async def update_from_headers(self, provider: str, info: RateLimitInfo) -> None:
        """Adjust the request bucket based on server-reported limits."""
        if info.remaining is not None:
            bucket = self._get_request_bucket(provider)
            async with bucket.lock:
                bucket.tokens = min(float(info.remaining), bucket.capacity)

        if info.retry_after is not None and info.retry_after > 0:
            bucket = self._get_request_bucket(provider)
            async with bucket.lock:
                bucket.tokens = 0.0

    @staticmethod
    def parse_headers(headers: dict[str, str]) -> RateLimitInfo:
        """Extract rate-limit metadata from HTTP response headers.

        Recognises the following (case-insensitive) headers:

        * ``X-RateLimit-Remaining``
        * ``X-RateLimit-Reset`` (Unix epoch seconds)
        * ``Retry-After`` (seconds to wait)
        """
        info = RateLimitInfo()
        normalised = {k.lower(): v for k, v in headers.items()}

        raw_remaining = normalised.get("x-ratelimit-remaining")
        if raw_remaining is not None:
            try:
                info.remaining = int(raw_remaining)
            except (ValueError, TypeError):
                pass

        raw_reset = normalised.get("x-ratelimit-reset")
        if raw_reset is not None:
            try:
                info.reset_at = float(raw_reset)
            except (ValueError, TypeError):
                pass

        raw_retry = normalised.get("retry-after")
        if raw_retry is not None:
            try:
                info.retry_after = float(raw_retry)
            except (ValueError, TypeError):
                pass

        return info

    @staticmethod
    async def _acquire_from(bucket: _BucketState, *, cost: float) -> float:
        """Consume *cost* tokens from *bucket*, waiting if necessary."""
        if cost > bucket.capacity and bucket.capacity == 0:
            raise ValueError("Request cost exceeds bucket capacity (capacity is 0)")

        waited = 0.0
        while True:
            async with bucket.lock:
                bucket.refill(time.monotonic())
                if bucket.tokens >= cost:
                    bucket.tokens -= cost
                    return waited
                deficit = cost - bucket.tokens
                if bucket.refill_rate <= 0:
                    raise ValueError("Cannot acquire tokens: refill rate is 0")
                delay = deficit / bucket.refill_rate

            if delay <= 0:
                return waited

            await asyncio.sleep(delay)
            waited += delay
