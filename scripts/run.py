"""Main execution script for WordPress article generator."""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.article_generator import ArticleGenerator, generate_articles
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def main():
    """Main entry point for article generation."""
    parser = argparse.ArgumentParser(
        description="WordPress Article Generator - Generate and publish AI articles"
    )

    # Configuration
    parser.add_argument(
        '-c', '--config',
        default='config/config.yaml',
        help='Path to configuration file (default: config/config.yaml)'
    )

    # Session management
    parser.add_argument(
        '--session-id',
        help='Specific session ID to use or resume'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume a previous session'
    )

    # Content options
    parser.add_argument(
        '--tone',
        default='professional',
        choices=['professional', 'casual', 'friendly', 'technical', 'marketing'],
        help='Writing tone for articles (default: professional)'
    )
    parser.add_argument(
        '--topic',
        action='append',
        help='Specific topic(s) to generate (can be used multiple times)'
    )
    parser.add_argument(
        '--topics-file',
        help='Path to file containing topics (one per line)'
    )

    # Processing options
    parser.add_argument(
        '--retry-failed',
        action='store_true',
        help='Retry failed tasks from previous runs'
    )
    parser.add_argument(
        '--test-mode',
        action='store_true',
        help='Run in test mode with minimal output'
    )

    # Utility commands
    parser.add_argument(
        '--list-sessions',
        action='store_true',
        help='List all available sessions'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify published articles'
    )
    parser.add_argument(
        '--test-connection',
        action='store_true',
        help='Test WordPress and OpenAI connections'
    )

    args = parser.parse_args()

    # Handle utility commands first
    if args.list_sessions:
        generator = ArticleGenerator(args.config)
        sessions = await generator.list_sessions()

        if not sessions:
            print("No sessions found.")
            return 0

        print("Available sessions:")
        print("-" * 80)
        for session in sessions:
            print(f"Session ID:  {session['session_id']}")
            print(f"Started:     {session['started_at']}")
            print(f"Last Update: {session['last_updated']}")
            print(f"Progress:    {session['completed_tasks']}/{session['total_tasks']} completed")
            if session['failed_tasks'] > 0:
                print(f"Failed:      {session['failed_tasks']}")
            print("-" * 80)
        return 0

    # Load topics from file if specified
    topics = None
    if args.topics_file:
        topics_path = Path(args.topics_file)
        if topics_path.exists():
            with open(topics_path, 'r', encoding='utf-8') as f:
                topics = [line.strip() for line in f if line.strip()]
            logger.info(f"Loaded {len(topics)} topics from {args.topics_file}")
        else:
            logger.error(f"Topics file not found: {args.topics_file}")
            return 1
    elif args.topic:
        topics = args.topic

    try:
        generator = ArticleGenerator(args.config)

        # Test connection mode
        if args.test_connection:
            print("Testing connections...")
            print("-" * 40)

            # Test WordPress
            print("WordPress: ", end="")
            try:
                await generator.initialize(topics=["test"])
                print("✓ Connected")
            except Exception as e:
                print(f"✗ Failed: {e}")
                return 1

            # Test OpenAI
            print("OpenAI: ", end="")
            try:
                result = await generator.generate_single("test", publish=False)
                if result.success:
                    print("✓ Connected")
                else:
                    print(f"✗ Failed: {result.error_message}")
                    return 1
            except Exception as e:
                print(f"✗ Failed: {e}")
                return 1

            print("-" * 40)
            print("All connections successful!")
            await generator.batch_processor.shutdown() if generator.batch_processor else None
            return 0

        # Verify mode
        if args.verify:
            if not args.session_id:
                print("Error: --session-id required for verification")
                return 1

            await generator.initialize(session_id=args.session_id, topics=[])
            result = await generator.verify_articles()
            print(f"Verification complete:")
            print(f"  Verified: {result['verified']}")
            print(f"  Missing:  {result['missing']}")
            await generator.batch_processor.shutdown()
            return 0

        # Resume mode
        if args.resume:
            if not args.session_id:
                print("Error: --session-id required for resume")
                return 1

            result = await generator.resume_session(args.session_id)
            print(f"\nSession resumed: {args.session_id}")
            print(f"Successful: {result['successful']}")
            print(f"Failed: {result['failed']}")
            return 0

        # Normal generation mode
        if args.test_mode and topics:
            # Test mode: generate just one article
            logger.info("Running in test mode - generating single article")
            await generator.initialize(topics=topics[:1])
            result = await generator.generate_single(topics[0], publish=False)
            print(f"\nTest result: {'SUCCESS' if result.success else 'FAILED'}")
            if result.error_message:
                print(f"Error: {result.error_message}")
            return 0 if result.success else 1

        # Full generation
        await generator.initialize(
            session_id=args.session_id,
            topics=topics
        )

        result = await generator.generate(
            tone=args.tone,
            retry_failed=args.retry_failed
        )

        print(f"\nGeneration complete: {args.session_id or generator.session_id}")
        print(f"Successful: {result['successful']}")
        print(f"Failed: {result['failed']}")

        return 0 if result['failed'] == 0 else 1

    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
