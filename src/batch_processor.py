"""Batch processor for concurrent article generation and publishing."""

import asyncio
import logging
import time
from typing import Optional, Callable, List, Dict, Any, TypeVar, Tuple
from dataclasses import dataclass

from .rate_limiter import RateLimiter, RateLimitConfig, CompositeRateLimiter, SemaphoreRateLimiter
from .state_manager import StateManager, TaskStatus, ArticleTask
from .progress_tracker import ProgressTracker
from .wordpress_client import WordPressClient, WordPressConfig, WordPressPost
from .ai_generator import AIGenerator, GenerationResult, GenerationConfig

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class ProcessingResult:
    """Result of processing a single article."""
    topic: str
    success: bool
    wordpress_id: Optional[int] = None
    wordpress_url: Optional[str] = None
    error_message: Optional[str] = None
    generation_time: float = 0.0
    upload_time: float = 0.0
    tokens_used: int = 0


class BatchProcessor:
    """Processes article generation and publishing in batches with concurrency control."""

    def __init__(
        self,
        wordpress_client: WordPressClient,
        ai_generator: AIGenerator,
        state_manager: StateManager,
        progress_tracker: ProgressTracker,
        max_concurrent: int = 5,
        enable_rate_limiting: bool = True,
        requests_per_minute: int = 60
    ):
        """Initialize the batch processor.

        Args:
            wordpress_client: WordPress REST API client
            ai_generator: OpenAI content generator
            state_manager: State manager for persistence
            progress_tracker: Progress tracker
            max_concurrent: Maximum concurrent operations
            enable_rate_limiting: Whether to enable rate limiting
            requests_per_minute: API request rate limit
        """
        self.wp_client = wordpress_client
        self.ai_generator = ai_generator
        self.state_manager = state_manager
        self.progress_tracker = progress_tracker
        self.max_concurrent = max_concurrent

        # Setup rate limiters
        self.rate_limiters: List = []

        if enable_rate_limiting:
            wp_rate_limiter = RateLimiter(RateLimitConfig(
                requests_per_minute=requests_per_minute,
                requests_per_hour=requests_per_minute * 50  # 50x per hour limit
            ))
            self.rate_limiters.append(wp_rate_limiter)

        # Always add concurrency limiter
        self.semaphore = SemaphoreRateLimiter(max_concurrent)
        self.rate_limiters.append(self.semaphore)

        # Combine limiters
        if self.rate_limiters:
            self.composite_limiter = CompositeRateLimiter(self.rate_limiters)
        else:
            self.composite_limiter = None

    async def process_all(
        self,
        tone: str = "professional",
        retry_failed: bool = False
    ) -> List[ProcessingResult]:
        """Process all pending articles with concurrent execution.

        Args:
            tone: Writing tone for articles
            retry_failed: Whether to retry failed tasks

        Returns:
            List of ProcessingResult
        """
        if retry_failed:
            await self.state_manager.reset_failed_tasks()

        # Collect all pending tasks using batch fetching for better performance
        pending_tasks = []
        batch_size = max(self.max_concurrent, 10)  # Fetch at least max_concurrent or 10 tasks

        while True:
            # Fetch tasks in batches to reduce lock contention
            batch = await self.state_manager.get_next_tasks(batch_size)
            if not batch:
                break
            pending_tasks.extend(batch)

        if not pending_tasks:
            logger.info("No pending tasks to process")
            return []

        logger.info(f"Processing {len(pending_tasks)} tasks with max_concurrent={self.max_concurrent}")

        # Create a semaphore for concurrent control
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def process_with_state_update(task: ArticleTask) -> ProcessingResult:
            """Process a single task with state updates."""
            async with semaphore:
                try:
                    result = await self.process_article(task.topic, tone)

                    # Update state
                    if result.success:
                        await self.state_manager.update_task(
                            topic=task.topic,
                            status=TaskStatus.COMPLETED,
                            wordpress_id=result.wordpress_id,
                            wordpress_url=result.wordpress_url
                        )
                    else:
                        await self.state_manager.update_task(
                            topic=task.topic,
                            status=TaskStatus.FAILED,
                            error_message=result.error_message
                        )

                    # Update progress
                    await self.progress_tracker.update(
                        completed=1 if result.success else 0,
                        failed=0 if result.success else 1,
                        tokens_used=result.tokens_used,
                        generation_time=result.generation_time,
                        upload_time=result.upload_time
                    )

                    return result

                except Exception as e:
                    logger.error(f"Error processing task {task.topic}: {e}")
                    await self.state_manager.update_task(
                        topic=task.topic,
                        status=TaskStatus.FAILED,
                        error_message=str(e)
                    )
                    await self.progress_tracker.update(failed=1)
                    return ProcessingResult(
                        topic=task.topic,
                        success=False,
                        error_message=str(e)
                    )

        # Process all tasks concurrently
        results = await asyncio.gather(
            *[process_with_state_update(task) for task in pending_tasks],
            return_exceptions=True
        )

        # Filter out any exceptions (shouldn't happen due to try-except above)
        final_results = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Unexpected exception: {r}")
            else:
                final_results.append(r)

        return final_results

    async def process_article(
        self,
        topic: str,
        tone: str = "professional",
        keywords: Optional[List[str]] = None,
        publish: bool = True
    ) -> ProcessingResult:
        """Process a single article: generate and publish.

        Args:
            topic: Article topic
            tone: Writing tone
            keywords: Optional keywords to include

        Returns:
            ProcessingResult with outcome details
        """
        start_time = time.monotonic()
        generation_time = 0.0
        upload_time = 0.0
        tokens_used = 0

        # Use async context manager for rate limiting if available
        if self.composite_limiter:
            async with self.composite_limiter:
                return await self._process_article_internal(
                    topic, tone, keywords, start_time, publish
                )
        else:
            return await self._process_article_internal(
                topic, tone, keywords, start_time, publish
            )

    async def _process_article_internal(
        self,
        topic: str,
        tone: str,
        keywords: Optional[List[str]],
        start_time: float,
        publish: bool
    ) -> ProcessingResult:
        """Internal method to process article without rate limiting wrapper.

        Args:
            topic: Article topic
            tone: Writing tone
            keywords: Optional keywords to include
            start_time: Start time for metrics

        Returns:
            ProcessingResult with outcome details
        """
        generation_time = 0.0
        upload_time = 0.0
        tokens_used = 0

        try:
            # Step 1: Generate content
            logger.info(f"Generating article for: {topic}")
            gen_start = time.monotonic()

            generation_result = await self.ai_generator.generate_article(
                topic=topic,
                tone=tone,
                keywords=keywords
            )

            generation_time = time.monotonic() - gen_start
            tokens_used = generation_result.tokens_used

            wp_post = None
            if publish:
                logger.info(f"Publishing article: {generation_result.title}")
                upload_start = time.monotonic()

                wp_post = await self.wp_client.create_post(
                    title=generation_result.title or topic,
                    content=generation_result.content,
                    status="draft",  # Always start as draft
                    excerpt=generation_result.excerpt
                )

                upload_time = time.monotonic() - upload_start

            total_time = time.monotonic() - start_time
            logger.info(
                f"Successfully processed '{topic}' in {total_time:.2f}s "
                f"(gen: {generation_time:.2f}s, upload: {upload_time:.2f}s)"
            )

            return ProcessingResult(
                topic=topic,
                success=True,
                wordpress_id=wp_post.id if wp_post else None,
                wordpress_url=wp_post.link if wp_post else None,
                generation_time=generation_time,
                upload_time=upload_time,
                tokens_used=tokens_used
            )

        except Exception as e:
            total_time = time.monotonic() - start_time
            logger.error(f"Failed to process '{topic}': {e}")

            return ProcessingResult(
                topic=topic,
                success=False,
                error_message=str(e),
                generation_time=generation_time,
                upload_time=upload_time,
                tokens_used=tokens_used
            )

    async def process_batch(
        self,
        topics: List[str],
        tone: str = "professional"
    ) -> List[ProcessingResult]:
        """Process a batch of articles.

        Args:
            topics: List of topics to process
            tone: Writing tone

        Returns:
            List of ProcessingResult
        """
        tasks = [
            self.process_article(topic, tone)
            for topic in topics
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(ProcessingResult(
                    topic=topics[i],
                    success=False,
                    error_message=str(result)
                ))
            else:
                final_results.append(result)

        return final_results

    async def verify_published_articles(self) -> Tuple[int, int]:
        """Verify all published articles by checking WordPress.

        Returns:
            Tuple of (verified_count, missing_count)
        """
        state = self.state_manager.get_state()
        if not state:
            return 0, 0

        verified = 0
        missing = 0

        for task in state.tasks:
            if task.wordpress_id and task.status == TaskStatus.COMPLETED:
                post = await self.wp_client.get_post(task.wordpress_id)
                if post:
                    verified += 1
                else:
                    missing += 1
                    logger.warning(f"Post {task.wordpress_id} not found for topic: {task.topic}")

        return verified, missing

    def get_status(self) -> Dict[str, Any]:
        """Get current processor status.

        Returns:
            Dictionary with processor status
        """
        progress = self.progress_tracker.get_status()
        state = self.state_manager.get_state()

        status = {
            "progress": progress,
            "max_concurrent": self.max_concurrent,
            "rate_limiting_enabled": len(self.rate_limiters) > 1
        }

        if state:
            status["state"] = self.state_manager.get_progress_summary()

        return status

    async def shutdown(self) -> None:
        """Cleanup and shutdown resources."""
        await self.state_manager.finalize()
        await self.wp_client.close()
        await self.ai_generator.close()
        logger.info("Batch processor shutdown complete")


async def process_with_retry(
    processor: BatchProcessor,
    topic: str,
    max_retries: int = 3,
    tone: str = "professional",
    publish: bool = True
) -> ProcessingResult:
    """Process an article with retry logic.

    Args:
        processor: Batch processor instance
        topic: Article topic
        max_retries: Maximum retry attempts
        tone: Writing tone

    Returns:
        ProcessingResult
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            result = await processor.process_article(topic, tone, publish=publish)
            if result.success:
                return result
            last_error = result.error_message
        except Exception as e:
            last_error = str(e)

        if attempt < max_retries - 1:
            wait_time = 2 ** attempt  # Exponential backoff
            logger.warning(f"Retry {attempt + 1}/{max_retries} for '{topic}' after {wait_time}s")
            await asyncio.sleep(wait_time)

    return ProcessingResult(
        topic=topic,
        success=False,
        error_message=f"Failed after {max_retries} retries: {last_error}"
    )
