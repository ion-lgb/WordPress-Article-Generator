"""Progress tracker for real-time monitoring of article generation."""

import logging
import sys
import time
import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class ProgressMetrics:
    """Metrics for tracking generation progress."""
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    started_at: Optional[datetime] = None
    last_update: Optional[datetime] = None

    @property
    def remaining(self) -> int:
        """Number of remaining tasks."""
        return self.total - self.completed - self.failed - self.skipped

    @property
    def progress_percent(self) -> float:
        """Progress percentage."""
        if self.total == 0:
            return 0.0
        return round(self.completed / self.total * 100, 2)

    @property
    def elapsed_time(self) -> timedelta:
        """Time elapsed since start."""
        if self.started_at is None:
            return timedelta()
        return datetime.now() - self.started_at

    @property
    def estimated_time_remaining(self) -> Optional[timedelta]:
        """Estimated time remaining based on current progress."""
        if self.completed == 0 or self.remaining == 0:
            return None

        elapsed = self.elapsed_time.total_seconds()
        if elapsed == 0:
            return None

        avg_time_per_task = elapsed / self.completed
        estimated_remaining = avg_time_per_task * self.remaining
        return timedelta(seconds=int(estimated_remaining))


@dataclass
class PerformanceMetrics:
    """Performance metrics for the generation process."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    retried_requests: int = 0
    total_tokens_used: int = 0
    total_generation_time: float = 0.0
    total_upload_time: float = 0.0

    @property
    def success_rate(self) -> float:
        """Success rate percentage."""
        if self.total_requests == 0:
            return 0.0
        return round(self.successful_requests / self.total_requests * 100, 2)

    @property
    def average_generation_time(self) -> float:
        """Average time per article generation in seconds."""
        if self.successful_requests == 0:
            return 0.0
        return round(self.total_generation_time / self.successful_requests, 2)

    @property
    def average_upload_time(self) -> float:
        """Average time per WordPress upload in seconds."""
        if self.successful_requests == 0:
            return 0.0
        return round(self.total_upload_time / self.successful_requests, 2)

    @property
    def average_tokens_per_article(self) -> int:
        """Average tokens used per article."""
        if self.successful_requests == 0:
            return 0
        return self.total_tokens_used // self.successful_requests


class ProgressTracker:
    """Tracks and displays progress of article generation."""

    def __init__(
        self,
        total: int,
        show_progress_bar: bool = True,
        update_interval: float = 1.0
    ):
        """Initialize the progress tracker.

        Args:
            total: Total number of tasks
            show_progress_bar: Whether to show a progress bar
            update_interval: Minimum seconds between console updates
        """
        self.metrics = ProgressMetrics(total=total, started_at=datetime.now())
        self.performance = PerformanceMetrics()
        self.show_progress_bar = show_progress_bar
        self.update_interval = update_interval
        self._last_update = 0
        self._lock = asyncio.Lock()
        self._start_time = time.monotonic()
        self._last_progress_time = self._start_time

        # Recent completion times for better ETA calculation
        self._recent_times: list = []
        self._max_recent_samples = 20

        # Animated indicators for live progress
        self._indicators = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        self._current_indicator = 0

        # Track if we've printed final newline after live progress
        self._live_progress_active = False

    async def update(
        self,
        completed: int = 0,
        failed: int = 0,
        skipped: int = 0,
        tokens_used: int = 0,
        generation_time: float = 0.0,
        upload_time: float = 0.0
    ) -> None:
        """Update progress metrics.

        Args:
            completed: Number of newly completed tasks
            failed: Number of newly failed tasks
            skipped: Number of newly skipped tasks
            tokens_used: Tokens used in this batch
            generation_time: Time spent on content generation
            upload_time: Time spent on WordPress upload
        """
        async with self._lock:
            self.metrics.completed += completed
            self.metrics.failed += failed
            self.metrics.skipped += skipped
            self.metrics.last_update = datetime.now()

            self.performance.total_requests += completed + failed
            self.performance.successful_requests += completed
            self.performance.failed_requests += failed
            self.performance.total_tokens_used += tokens_used
            self.performance.total_generation_time += generation_time
            self.performance.total_upload_time += upload_time

            if completed > 0:
                now = time.monotonic()
                batch_time = now - self._last_progress_time
                self._recent_times.append(batch_time)
                if len(self._recent_times) > self._max_recent_samples:
                    self._recent_times.pop(0)
                self._last_progress_time = now

            await self._maybe_display()

    async def _maybe_display(self) -> None:
        """Display progress if enough time has elapsed."""
        now = time.monotonic()
        if now - self._last_update < self.update_interval:
            return

        self._last_update = now
        self.display()

    def display(self) -> None:
        """Display current progress with live updates."""
        if not self.show_progress_bar:
            return

        eta = self.metrics.estimated_time_remaining
        eta_str = self._format_timedelta(eta) if eta else "Calculating..."

        # Update indicator
        indicator = self._indicators[self._current_indicator]
        self._current_indicator = (self._current_indicator + 1) % len(self._indicators)

        # Build progress bar (40 chars wide)
        progress_width = 40
        filled = int(progress_width * self.metrics.completed / self.metrics.total) if self.metrics.total > 0 else 0
        bar = "█" * filled + "░" * (progress_width - filled)

        # Format: [进度条] 完成% | 成功/失败 | ETA
        progress_line = (
            f"\r{indicator} [{bar}] {self.metrics.progress_percent:>5.1f}% | "
            f"✓{self.metrics.completed} ✗{self.metrics.failed} | "
            f"ETA: {eta_str}"
        )

        # Use sys.stdout.write for better control over output
        sys.stdout.write(progress_line)
        sys.stdout.flush()
        self._live_progress_active = True

        # Also log to file (less frequent)
        if self.metrics.completed % 10 == 0 or self.metrics.completed == self.metrics.total:
            logger.debug(
                f"Progress: {self.metrics.completed}/{self.metrics.total} "
                f"({self.metrics.progress_percent}%) | "
                f"Failed: {self.metrics.failed} | "
                f"Remaining: {self.metrics.remaining} | "
                f"ETA: {eta_str}"
            )

    def display_summary(self) -> None:
        """Display a summary of the completed generation."""
        # End live progress line if active
        if self._live_progress_active:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._live_progress_active = False

        elapsed = self.metrics.elapsed_time
        elapsed_str = self._format_timedelta(elapsed)

        # Print summary to stdout for immediate visibility
        print("\n" + "=" * 60)
        print("Generation Summary")
        print("=" * 60)
        print(f"Total tasks:        {self.metrics.total}")
        print(f"Completed:          {self.metrics.completed}")
        print(f"Failed:             {self.metrics.failed}")
        print(f"Skipped:            {self.metrics.skipped}")
        print(f"Success rate:       {self.performance.success_rate}%")
        print(f"Total time:         {elapsed_str}")
        print(f"Avg generation:     {self.performance.average_generation_time}s")
        print(f"Avg upload:         {self.performance.average_upload_time}s")
        print(f"Total tokens:       {self.performance.total_tokens_used:,}")
        print(f"Tokens per article: {self.performance.average_tokens_per_article}")
        print("=" * 60)

        # Also log to file
        logger.info("=" * 60)
        logger.info("Generation Summary")
        logger.info("=" * 60)
        logger.info(f"Total tasks:        {self.metrics.total}")
        logger.info(f"Completed:          {self.metrics.completed}")
        logger.info(f"Failed:             {self.metrics.failed}")
        logger.info(f"Skipped:            {self.metrics.skipped}")
        logger.info(f"Success rate:       {self.performance.success_rate}%")
        logger.info(f"Total time:         {elapsed_str}")
        logger.info(f"Avg generation:     {self.performance.average_generation_time}s")
        logger.info(f"Avg upload:         {self.performance.average_upload_time}s")
        logger.info(f"Total tokens:       {self.performance.total_tokens_used:,}")
        logger.info(f"Tokens per article: {self.performance.average_tokens_per_article}")
        logger.info("=" * 60)

    @staticmethod
    def _format_timedelta(td: timedelta) -> str:
        """Format a timedelta as a readable string.

        Args:
            td: Timedelta to format

        Returns:
            Formatted string like "1h 23m 45s"
        """
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def get_status(self) -> Dict[str, Any]:
        """Get current status as a dictionary.

        Returns:
            Dictionary containing current status
        """
        eta = self.metrics.estimated_time_remaining

        return {
            "total": self.metrics.total,
            "completed": self.metrics.completed,
            "failed": self.metrics.failed,
            "skipped": self.metrics.skipped,
            "remaining": self.metrics.remaining,
            "progress_percent": self.metrics.progress_percent,
            "elapsed_seconds": int(self.metrics.elapsed_time.total_seconds()),
            "estimated_remaining_seconds": int(eta.total_seconds()) if eta else None,
            "success_rate": self.performance.success_rate,
            "average_generation_time": self.performance.average_generation_time,
            "average_upload_time": self.performance.average_upload_time,
            "total_tokens_used": self.performance.total_tokens_used,
        }

    def is_complete(self) -> bool:
        """Check if all tasks are complete.

        Returns:
            True if all tasks are complete, failed, or skipped
        """
        return self.metrics.remaining == 0


class LiveProgressDisplay:
    """Live progress display with animated indicators."""

    def __init__(self, tracker: ProgressTracker):
        """Initialize the live display.

        Args:
            tracker: Progress tracker to display
        """
        self.tracker = tracker
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._indicators = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        self._current_indicator = 0

    async def start(self) -> None:
        """Start the live display."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._update_loop())

    async def stop(self) -> None:
        """Stop the live display."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _update_loop(self) -> None:
        """Update loop for the live display."""
        while self._running:
            await asyncio.sleep(self.tracker.update_interval)
            if self._running:
                self._display_with_indicator()

    def _display_with_indicator(self) -> None:
        """Display progress with animated indicator."""
        indicator = self._indicators[self._current_indicator]
        self._current_indicator = (self._current_indicator + 1) % len(self._indicators)

        eta = self.tracker.metrics.estimated_time_remaining
        eta_str = ProgressTracker._format_timedelta(eta) if eta else "Calculating..."

        print(
            f"\r{indicator} {self.tracker.metrics.completed}/{self.tracker.metrics.total} "
            f"({self.tracker.metrics.progress_percent}%) | "
            f"Failed: {self.tracker.metrics.failed} | "
            f"ETA: {eta_str}",
            end="", flush=True
        )
