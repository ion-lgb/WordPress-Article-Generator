"""Resume script for interrupted article generation sessions."""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.article_generator import ArticleGenerator
from src.state_manager import StateManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


def list_available_sessions(state_dir: str = 'data/state') -> None:
    """List all available sessions for resumption.

    Args:
        state_dir: Directory containing state files
    """
    sessions = StateManager.list_sessions(state_dir)

    if not sessions:
        print("No sessions found to resume.")
        return

    print("\nAvailable sessions:")
    print("=" * 80)
    for i, session in enumerate(sessions, 1):
        print(f"\n[{i}] Session ID: {session['session_id']}")
        print(f"    File:        {session['file']}")
        print(f"    Started:     {session['started_at']}")
        print(f"    Last Update: {session['last_updated']}")
        print(f"    Progress:    {session['completed_tasks']}/{session['total_tasks']} "
              f"({session['completed_tasks']/session['total_tasks']*100:.1f}%)")
        print(f"    Status:      {session['completed_tasks']} completed, "
              f"{session['failed_tasks']} failed")

    print("\n" + "=" * 80)


async def resume_session(
    session_id: str,
    config_path: str = 'config/config.yaml',
    tone: str = 'professional',
    retry_failed: bool = False
) -> int:
    """Resume a specific session.

    Args:
        session_id: Session ID to resume
        config_path: Path to configuration file
        tone: Writing tone
        retry_failed: Whether to retry failed tasks

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    logger.info(f"Resuming session: {session_id}")

    try:
        generator = ArticleGenerator(config_path)

        result = await generator.resume_session(session_id)

        print(f"\n{'=' * 60}")
        print(f"Session '{session_id}' completed")
        print(f"{'=' * 60}")
        print(f"  Articles generated:  {result['successful']}")
        print(f"  Articles failed:     {result['failed']}")
        print(f"  Total tokens used:   {result['token_usage'].total_tokens:,}")

        return 0 if result['failed'] == 0 else 1

    except FileNotFoundError as e:
        logger.error(f"Session not found: {e}")
        return 1
    except Exception as e:
        logger.exception(f"Error resuming session: {e}")
        return 1


async def retry_failed_tasks(
    session_id: str,
    config_path: str = 'config/config.yaml',
    tone: str = 'professional'
) -> int:
    """Retry only failed tasks from a session.

    Args:
        session_id: Session ID
        config_path: Path to configuration file
        tone: Writing tone

    Returns:
        Exit code
    """
    logger.info(f"Retrying failed tasks from session: {session_id}")

    try:
        generator = ArticleGenerator(config_path)
        await generator.initialize(session_id=session_id, resume=True)

        result = await generator.generate(tone=tone, retry_failed=True)

        print(f"\nRetry complete:")
        print(f"  Successful: {result['successful']}")
        print(f"  Still failed: {result['failed']}")

        return 0

    except Exception as e:
        logger.exception(f"Error retrying tasks: {e}")
        return 1


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Resume interrupted article generation sessions"
    )

    parser.add_argument(
        '-c', '--config',
        default='config/config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--session-id',
        help='Specific session ID to resume'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all available sessions'
    )
    parser.add_argument(
        '--retry-failed',
        action='store_true',
        help='Retry only failed tasks'
    )
    parser.add_argument(
        '--tone',
        default='professional',
        choices=['professional', 'casual', 'friendly', 'technical', 'marketing'],
        help='Writing tone for articles'
    )

    args = parser.parse_args()

    # List mode
    if args.list:
        state_dir = Path(args.config).parent.parent / 'data/state'
        list_available_sessions(str(state_dir))
        return 0

    # Session ID required for other operations
    if not args.session_id:
        print("Error: --session-id is required (use --list to see available sessions)")
        return 1

    # Resume or retry
    if args.retry_failed:
        return await retry_failed_tasks(
            args.session_id,
            args.config,
            args.tone
        )
    else:
        return await resume_session(
            args.session_id,
            args.config,
            args.tone
        )


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
