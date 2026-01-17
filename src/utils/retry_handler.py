"""Retry handler with exponential backoff for API calls."""

import asyncio
import logging
from typing import Callable, TypeVar, Optional
from functools import wraps

try:
    import openai
    from openai import APIError, RateLimitError, APIConnectionError, AuthenticationError
except ImportError:
    APIError = Exception
    RateLimitError = Exception
    APIConnectionError = Exception
    AuthenticationError = Exception

T = TypeVar('T')

logger = logging.getLogger(__name__)


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay with exponential backoff and optional jitter.

    Args:
        attempt: Current attempt number (0-indexed)
        config: Retry configuration

    Returns:
        Delay in seconds
    """
    delay = min(
        config.base_delay * (config.exponential_base ** attempt),
        config.max_delay
    )

    if config.jitter:
        import random
        delay *= (0.5 + random.random() * 0.5)

    return delay


async def async_retry_with_backoff(
    func: Callable[..., T],
    config: Optional[RetryConfig] = None,
    retryable_exceptions: tuple = (APIError, RateLimitError, APIConnectionError, Exception)
) -> T:
    """Execute an async function with retry and exponential backoff.

    Args:
        func: Async function to execute
        config: Retry configuration
        retryable_exceptions: Exceptions that trigger retry

    Returns:
        Function result

    Raises:
        Exception: Last exception if all retries exhausted
    """
    if config is None:
        config = RetryConfig()

    last_exception = None

    for attempt in range(config.max_retries):
        try:
            return await func()
        except AuthenticationError as e:
            # Authentication errors should not be retried
            logger.error(f"Authentication failed: {e}")
            raise
        except retryable_exceptions as e:
            last_exception = e

            if attempt == config.max_retries - 1:
                logger.error(f"All {config.max_retries} retries failed: {e}")
                raise

            delay = calculate_delay(attempt, config)
            logger.warning(
                f"Attempt {attempt + 1}/{config.max_retries} failed: {e}. "
                f"Retrying in {delay:.1f}s..."
            )
            await asyncio.sleep(delay)

    raise last_exception


def retry_with_backoff(
    func: Callable[..., T],
    config: Optional[RetryConfig] = None,
    retryable_exceptions: tuple = (APIError, RateLimitError, APIConnectionError, Exception)
) -> T:
    """Execute a synchronous function with retry and exponential backoff.

    Args:
        func: Function to execute
        config: Retry configuration
        retryable_exceptions: Exceptions that trigger retry

    Returns:
        Function result

    Raises:
        Exception: Last exception if all retries exhausted
    """
    if config is None:
        config = RetryConfig()

    last_exception = None

    for attempt in range(config.max_retries):
        try:
            return func()
        except AuthenticationError as e:
            logger.error(f"Authentication failed: {e}")
            raise
        except retryable_exceptions as e:
            last_exception = e

            if attempt == config.max_retries - 1:
                logger.error(f"All {config.max_retries} retries failed: {e}")
                raise

            delay = calculate_delay(attempt, config)
            logger.warning(
                f"Attempt {attempt + 1}/{config.max_retries} failed: {e}. "
                f"Retrying in {delay:.1f}s..."
            )
            asyncio.sleep(delay)

    raise last_exception


def async_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0
):
    """Decorator for async functions with retry capability.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff calculation
    """
    config = RetryConfig(max_retries, base_delay, max_delay, exponential_base)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async def bounded_func():
                return await func(*args, **kwargs)
            return await async_retry_with_backoff(bounded_func, config)
        return wrapper
    return decorator


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0
):
    """Decorator for synchronous functions with retry capability.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff calculation
    """
    config = RetryConfig(max_retries, base_delay, max_delay, exponential_base)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            def bounded_func():
                return func(*args, **kwargs)
            return retry_with_backoff(bounded_func, config)
        return wrapper
    return decorator
