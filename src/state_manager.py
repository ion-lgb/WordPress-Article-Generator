"""State manager for checkpoint and resume functionality."""

import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of a task in the generation process."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ArticleTask:
    """Represents a single article generation task."""
    topic: str
    status: TaskStatus = TaskStatus.PENDING
    wordpress_id: Optional[int] = None
    wordpress_url: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, handling Enum serialization."""
        data = asdict(self)
        data['status'] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ArticleTask':
        """Create from dictionary, handling Enum deserialization."""
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = TaskStatus(data['status'])
        return cls(**data)


@dataclass
class GenerationState:
    """Overall state of the generation process."""
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    started_at: str
    last_updated: str
    tasks: List[ArticleTask]
    current_checkpoint: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'total_tasks': self.total_tasks,
            'completed_tasks': self.completed_tasks,
            'failed_tasks': self.failed_tasks,
            'skipped_tasks': self.skipped_tasks,
            'started_at': self.started_at,
            'last_updated': self.last_updated,
            'current_checkpoint': self.current_checkpoint,
            'tasks': [task.to_dict() for task in self.tasks]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GenerationState':
        """Create from dictionary."""
        data['tasks'] = [ArticleTask.from_dict(t) for t in data.get('tasks', [])]
        return cls(**data)


class StateManager:
    """Manages persistent state for article generation with checkpoint/resume support."""

    def __init__(self, state_dir: str = 'data/state', checkpoint_interval: int = 10):
        """Initialize the state manager.

        Args:
            state_dir: Directory to store state files
            checkpoint_interval: Save state every N completed tasks
        """
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_interval = checkpoint_interval
        self._lock = asyncio.Lock()
        self._state: Optional[GenerationState] = None
        self._state_file: Optional[Path] = None

    def get_state_file(self, session_id: str) -> Path:
        """Get the state file path for a session.

        Args:
            session_id: Unique session identifier

        Returns:
            Path to the state file
        """
        return self.state_dir / f"{session_id}.json"

    async def initialize_session(
        self,
        session_id: str,
        topics: List[str],
        resume: bool = False
    ) -> GenerationState:
        """Initialize a new session or resume an existing one.

        Args:
            session_id: Unique session identifier
            topics: List of topics to generate articles for
            resume: Whether to resume an existing session

        Returns:
            The generation state
        """
        async with self._lock:
            self._state_file = self.get_state_file(session_id)

            if resume and self._state_file.exists():
                logger.info(f"Resuming session from {self._state_file}")
                self._state = await self._load_state()
            else:
                logger.info(f"Initializing new session: {session_id}")
                self._state = GenerationState(
                    total_tasks=len(topics),
                    completed_tasks=0,
                    failed_tasks=0,
                    skipped_tasks=0,
                    started_at=datetime.now().isoformat(),
                    last_updated=datetime.now().isoformat(),
                    tasks=[ArticleTask(topic=topic) for topic in topics],
                    current_checkpoint=0
                )
                await self._save_state()

            return self._state

    async def _load_state(self) -> GenerationState:
        """Load state from file.

        Returns:
            The loaded generation state
        """
        try:
            with open(self._state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return GenerationState.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to load state: {e}")
            raise

    async def _save_state(self) -> None:
        """Save state to file."""
        if self._state is None or self._state_file is None:
            return

        self._state.last_updated = datetime.now().isoformat()

        try:
            with open(self._state_file, 'w', encoding='utf-8') as f:
                json.dump(self._state.to_dict(), f, indent=2, ensure_ascii=False)
            logger.debug(f"State saved to {self._state_file}")
        except (IOError, TypeError) as e:
            logger.error(f"Failed to save state: {e}")

    async def get_next_task(self) -> Optional[ArticleTask]:
        """Get the next pending task.

        Returns:
            The next pending task, or None if all tasks are complete
        """
        async with self._lock:
            if self._state is None:
                return None

            for task in self._state.tasks:
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.IN_PROGRESS
                    task.created_at = datetime.now().isoformat()
                    await self._save_state()
                    return task

            return None

    async def update_task(
        self,
        topic: str,
        status: TaskStatus,
        wordpress_id: Optional[int] = None,
        wordpress_url: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> None:
        """Update the status of a task.

        Args:
            topic: Topic of the article
            status: New status
            wordpress_id: WordPress post ID (if successful)
            wordpress_url: WordPress post URL (if successful)
            error_message: Error message (if failed)
        """
        async with self._lock:
            if self._state is None:
                return

            for task in self._state.tasks:
                if task.topic == topic:
                    old_status = task.status
                    task.status = status
                    task.wordpress_id = wordpress_id
                    task.wordpress_url = wordpress_url
                    task.error_message = error_message

                    if status == TaskStatus.COMPLETED:
                        task.completed_at = datetime.now().isoformat()
                        self._state.completed_tasks += 1
                    elif status == TaskStatus.FAILED:
                        task.retry_count += 1
                        if task.retry_count >= 3:
                            self._state.failed_tasks += 1
                        else:
                            task.status = TaskStatus.PENDING
                    elif status == TaskStatus.SKIPPED:
                        self._state.skipped_tasks += 1

                    logger.info(
                        f"Task updated: {topic} -> {status.value} "
                        f"(was {old_status.value})"
                    )

                    # Checkpoint save
                    self._state.current_checkpoint += 1
                    if self._state.current_checkpoint >= self.checkpoint_interval:
                        await self._save_state()
                        self._state.current_checkpoint = 0

                    return

    async def finalize(self) -> None:
        """Finalize the session and save final state."""
        async with self._lock:
            await self._save_state()
            logger.info("Session finalized")

    def get_state(self) -> Optional[GenerationState]:
        """Get the current state without locking.

        Returns:
            Current generation state or None
        """
        return self._state

    def get_progress_summary(self) -> Dict[str, Any]:
        """Get a summary of progress.

        Returns:
            Dictionary with progress statistics
        """
        if self._state is None:
            return {}

        total = self._state.total_tasks
        completed = self._state.completed_tasks
        failed = self._state.failed_tasks
        skipped = self._state.skipped_tasks

        return {
            'total': total,
            'completed': completed,
            'failed': failed,
            'skipped': skipped,
            'remaining': total - completed - failed - skipped,
            'progress_percent': round(completed / total * 100, 2) if total > 0 else 0,
            'started_at': self._state.started_at,
            'last_updated': self._state.last_updated,
        }

    async def get_failed_tasks(self) -> List[ArticleTask]:
        """Get all failed tasks for potential retry.

        Returns:
            List of failed tasks
        """
        async with self._lock:
            if self._state is None:
                return []

            return [
                task for task in self._state.tasks
                if task.status == TaskStatus.FAILED
            ]

    async def reset_failed_tasks(self) -> int:
        """Reset all failed tasks to pending for retry.

        Returns:
            Number of tasks reset
        """
        async with self._lock:
            if self._state is None:
                return 0

            count = 0
            for task in self._state.tasks:
                if task.status == TaskStatus.FAILED:
                    task.status = TaskStatus.PENDING
                    task.retry_count = 0
                    task.error_message = None
                    count += 1

            self._state.failed_tasks = 0
            await self._save_state()

            logger.info(f"Reset {count} failed tasks to pending")
            return count

    @staticmethod
    def list_sessions(state_dir: str = 'data/state') -> List[Dict[str, Any]]:
        """List all available sessions.

        Args:
            state_dir: Directory containing state files

        Returns:
            List of session information
        """
        state_path = Path(state_dir)
        if not state_path.exists():
            return []

        sessions = []
        for state_file in state_path.glob('*.json'):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                sessions.append({
                    'session_id': state_file.stem,
                    'file': str(state_file),
                    'total_tasks': data.get('total_tasks', 0),
                    'completed_tasks': data.get('completed_tasks', 0),
                    'failed_tasks': data.get('failed_tasks', 0),
                    'started_at': data.get('started_at'),
                    'last_updated': data.get('last_updated'),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return sorted(sessions, key=lambda x: x.get('last_updated', ''), reverse=True)
