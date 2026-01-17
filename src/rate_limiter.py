"""Rate limiter for API calls to prevent exceeding quotas."""

import asyncio
import time
import logging
from collections import deque
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    requests_per_minute: int = 60
    requests_per_hour: Optional[int] = None
    burst_size: int = 10


class RateLimiter:
    """Token bucket rate limiter for controlling API request rates.

    Supports per-minute and per-hour limits with burst capacity.
    Uses a sliding window approach for accurate rate limiting.
    """

    def __init__(self, config: RateLimitConfig):
        """Initialize the rate limiter.

        Args:
            config: Rate limit configuration
        """
        self.config = config
        self.minute_tokens = deque()
        self.hour_tokens = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        """Acquire tokens from the bucket, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire
        """
        async with self._lock:
            await self._wait_for_capacity(tokens)
            self._record_request(tokens)

    async def _wait_for_capacity(self, tokens: int) -> None:
        """Wait until capacity is available.

        Args:
            tokens: Number of tokens needed
        """
        now = time.monotonic()

        # Clean up old tokens
        self._cleanup_old_tokens(now)

        # Check minute limit
        while len(self.minute_tokens) + tokens > self.config.requests_per_minute:
            wait_time = 60 - (now - self.minute_tokens[0])
            if wait_time > 0:
                logger.debug(f"Rate limit reached, waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
                now = time.monotonic()
                self._cleanup_old_tokens(now)
            else:
                break

        # Check hour limit if configured
        if self.config.requests_per_hour:
            while len(self.hour_tokens) + tokens > self.config.requests_per_hour:
                oldest_in_hour = self.hour_tokens[0]
                wait_time = 3600 - (now - oldest_in_hour)
                if wait_time > 0:
                    logger.warning(
                        f"Hourly rate limit reached, waiting {wait_time:.1f}s"
                    )
                    await asyncio.sleep(min(wait_time, 60))
                    now = time.monotonic()
                    self._cleanup_old_tokens(now)
                else:
                    break

    def _cleanup_old_tokens(self, now: float) -> None:
        """Remove tokens that are outside the time window.

        Args:
            now: Current monotonic time
        """
        minute_ago = now - 60
        hour_ago = now - 3600

        while self.minute_tokens and self.minute_tokens[0] < minute_ago:
            self.minute_tokens.popleft()

        while self.hour_tokens and self.hour_tokens[0] < hour_ago:
            self.hour_tokens.popleft()

    def _record_request(self, tokens: int) -> None:
        """Record a request in the token buckets.

        Args:
            tokens: Number of tokens used
        """
        now = time.monotonic()
        for _ in range(tokens):
            self.minute_tokens.append(now)
            if self.config.requests_per_hour:
                self.hour_tokens.append(now)

    async def __aenter__(self):
        """Context manager entry."""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        pass

    def get_current_usage(self) -> dict:
        """Get current rate limit usage statistics.

        Returns:
            Dictionary with usage statistics
        """
        now = time.monotonic()
        self._cleanup_old_tokens(now)

        return {
            "requests_last_minute": len(self.minute_tokens),
            "requests_last_hour": len(self.hour_tokens) if self.config.requests_per_hour else None,
            "minute_limit": self.config.requests_per_minute,
            "hour_limit": self.config.requests_per_hour,
            "minute_remaining": self.config.requests_per_minute - len(self.minute_tokens),
            "hour_remaining": (
                self.config.requests_per_hour - len(self.hour_tokens)
                if self.config.requests_per_hour else None
            ),
        }


class SemaphoreRateLimiter:
    """Simple semaphore-based rate limiter for concurrent request limiting.

    Useful for limiting concurrent connections rather than request rate.
    """

    def __init__(self, max_concurrent: int):
        """Initialize the semaphore rate limiter.

        Args:
            max_concurrent: Maximum number of concurrent operations
        """
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def acquire(self) -> None:
        """Acquire a permit."""
        await self.semaphore.acquire()

    def release(self) -> None:
        """Release a permit."""
        self.semaphore.release()

    async def __aenter__(self):
        """Context manager entry."""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()


class CompositeRateLimiter:
    """Combines multiple rate limiters for comprehensive control.

    Useful for combining time-based rate limiting with concurrency limits.
    """

    def __init__(self, limiters: list):
        """Initialize the composite rate limiter.

        Args:
            limiters: List of rate limiters to combine
        """
        self.limiters = limiters

    async def acquire(self) -> None:
        """Acquire permits from all limiters."""
        for limiter in self.limiters:
            if hasattr(limiter, 'acquire'):
                await limiter.acquire()

    async def __aenter__(self):
        """Context manager entry."""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        for limiter in self.limiters:
            if hasattr(limiter, 'release'):
                limiter.release()
