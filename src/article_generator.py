"""Core article generator orchestrator."""

import logging
import asyncio
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from .wordpress_client import WordPressClient, WordPressConfig
from .ai_generator import AIGenerator, GenerationConfig
from .state_manager import StateManager, TaskStatus
from .progress_tracker import ProgressTracker, LiveProgressDisplay
from .batch_processor import BatchProcessor, ProcessingResult
from .rate_limiter import RateLimitConfig
from .utils.logger import get_logger

logger = get_logger(__name__)


class ArticleGenerator:
    """Main orchestrator for article generation and publishing."""

    def __init__(self, config_path: str = "config/config.yaml"):
        """Initialize the article generator.

        Args:
            config_path: Path to configuration file
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()

        # Initialize components
        self.wp_client: Optional[WordPressClient] = None
        self.ai_generator: Optional[AIGenerator] = None
        self.state_manager: Optional[StateManager] = None
        self.progress_tracker: Optional[ProgressTracker] = None
        self.batch_processor: Optional[BatchProcessor] = None
        self.live_display: Optional[LiveProgressDisplay] = None

        # Session tracking
        self.session_id: Optional[str] = None

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file.

        Returns:
            Configuration dictionary
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        logger.info(f"Loaded configuration from {self.config_path}")
        return config

    async def initialize(
        self,
        session_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        resume: bool = False
    ) -> None:
        """Initialize all components.

        Args:
            session_id: Unique session identifier
            topics: List of topics to generate
            resume: Whether to resume an existing session
        """
        # Generate session ID if not provided
        if session_id is None:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = session_id

        logger.info(f"Initializing article generator (session: {self.session_id})")

        # Initialize WordPress client
        wp_config = WordPressConfig(
            base_url=self.config['wordpress']['base_url'],
            username=self.config['wordpress']['credentials']['username'],
            application_password=self.config['wordpress']['credentials']['application_password'],
            max_connections=self.config['wordpress'].get('max_connections', 10),
            timeout=self.config['wordpress'].get('timeout', 30)
        )
        self.wp_client = WordPressClient(wp_config)

        # Test WordPress connection
        logger.info("Testing WordPress connection...")
        if not await self.wp_client.test_connection():
            raise ConnectionError("Failed to connect to WordPress. Check your credentials.")

        # Initialize AI generator
        gen_config = GenerationConfig(
            model=self.config['openai'].get('model', 'gpt-4o'),
            max_tokens=self.config['openai'].get('max_tokens', 2500),
            temperature=self.config['openai'].get('temperature', 0.7),
            min_word_count=self.config['generation'].get('min_word_count', 500),
            max_word_count=self.config['generation'].get('max_word_count', 1500)
        )
        self.ai_generator = AIGenerator(
            api_key=self.config['openai']['api_key'],
            config=gen_config
        )

        # Load topics
        if topics is None:
            topics = self._load_topics()

        # Initialize state manager
        self.state_manager = StateManager(
            state_dir=self.config.get('data_dir', 'data/state'),
            checkpoint_interval=self.config['generation'].get('checkpoint_interval', 10)
        )
        await self.state_manager.initialize_session(session_id, topics, resume)

        # Initialize progress tracker
        state = self.state_manager.get_state()
        self.progress_tracker = ProgressTracker(
            total=state.total_tasks,
            show_progress_bar=self.config['generation'].get('show_progress', True),
            update_interval=self.config['generation'].get('update_interval', 1.0)
        )

        # Initialize batch processor
        self.batch_processor = BatchProcessor(
            wordpress_client=self.wp_client,
            ai_generator=self.ai_generator,
            state_manager=self.state_manager,
            progress_tracker=self.progress_tracker,
            max_concurrent=self.config['generation'].get('max_concurrent', 5),
            enable_rate_limiting=self.config['wordpress']['rate_limit'].get('enabled', True),
            requests_per_minute=self.config['wordpress']['rate_limit'].get('requests_per_minute', 60)
        )

        # Initialize live display if enabled
        if self.config['generation'].get('live_progress', False):
            self.live_display = LiveProgressDisplay(self.progress_tracker)
            await self.live_display.start()

        logger.info("Article generator initialized successfully")

    def _load_topics(self) -> List[str]:
        """Load topics from file or configuration.

        Returns:
            List of topics
        """
        # Check for topics file
        topics_file = Path(self.config.get('data_dir', 'data')) / 'keywords.csv'
        if topics_file.exists():
            with open(topics_file, 'r', encoding='utf-8') as f:
                topics = [line.strip() for line in f if line.strip()]
            logger.info(f"Loaded {len(topics)} topics from {topics_file}")
            return topics

        # Use topics from config
        topics = self.config.get('topics', [])
        if not topics:
            raise ValueError("No topics found. Specify topics in config or provide a topics file.")
        return topics

    async def generate(
        self,
        tone: str = "professional",
        retry_failed: bool = False,
        wait_on_complete: bool = False
    ) -> Dict[str, Any]:
        """Generate and publish all articles.

        Args:
            tone: Writing tone for articles
            retry_failed: Whether to retry failed tasks
            wait_on_complete: Whether to wait before closing resources

        Returns:
            Summary dictionary
        """
        if self.batch_processor is None:
            raise RuntimeError("Generator not initialized. Call initialize() first.")

        logger.info("Starting article generation...")

        try:
            # Process all articles
            results = await self.batch_processor.process_all(
                tone=tone,
                retry_failed=retry_failed
            )

            # Stop live display
            if self.live_display:
                await self.live_display.stop()

            # Display summary
            self.progress_tracker.display_summary()

            # Return summary
            return {
                'session_id': self.session_id,
                'total_results': len(results),
                'successful': sum(1 for r in results if r.success),
                'failed': sum(1 for r in results if not r.success),
                'token_usage': self.ai_generator.get_token_usage(),
                'progress_summary': self.state_manager.get_progress_summary()
            }

        finally:
            # Cleanup
            await self.batch_processor.shutdown()

    async def generate_single(
        self,
        topic: str,
        tone: str = "professional",
        publish: bool = True,
        cleanup: bool = True
    ) -> ProcessingResult:
        """Generate a single article.

        Args:
            topic: Article topic
            tone: Writing tone
            publish: Whether to publish to WordPress
            cleanup: Whether to cleanup resources after generation (default: True)

        Returns:
            ProcessingResult
        """
        # Track if we initialized components in this call
        _initialized_here = False

        if self.batch_processor is None:
            # Initialize minimal components for single article
            await self.initialize(
                session_id=f"single_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                topics=[topic]
            )
            _initialized_here = True

        logger.info(f"Generating single article: {topic}")

        try:
            result = await self.batch_processor.process_article(topic, tone)
            return result
        finally:
            # Always cleanup if we initialized here, or if cleanup is explicitly requested
            if cleanup and _initialized_here:
                await self.batch_processor.shutdown()

    async def get_status(self) -> Dict[str, Any]:
        """Get current generator status.

        Returns:
            Status dictionary
        """
        status = {
            'session_id': self.session_id,
            'initialized': self.batch_processor is not None
        }

        if self.batch_processor:
            status.update(self.batch_processor.get_status())

        if self.state_manager:
            status['sessions'] = StateManager.list_sessions(
                self.config.get('data_dir', 'data/state')
            )

        return status

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """List all available sessions.

        Returns:
            List of session information
        """
        return StateManager.list_sessions(
            self.config.get('data_dir', 'data/state')
        )

    async def resume_session(self, session_id: str) -> Dict[str, Any]:
        """Resume a previous session.

        Args:
            session_id: Session to resume

        Returns:
            Generation summary
        """
        self.session_id = session_id

        # Load topics from state file
        state_file = Path(self.config.get('data_dir', 'data/state')) / f"{session_id}.json"
        if not state_file.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        await self.initialize(session_id=session_id, resume=True)

        return await self.generate()

    async def verify_articles(self) -> Dict[str, Any]:
        """Verify all published articles.

        Returns:
            Verification summary
        """
        if self.batch_processor is None:
            raise RuntimeError("Generator not initialized.")

        verified, missing = await self.batch_processor.verify_published_articles()

        return {
            'verified': verified,
            'missing': missing,
            'total': verified + missing
        }


async def generate_articles(
    config_path: str = "config/config.yaml",
    topics: Optional[List[str]] = None,
    tone: str = "professional",
    resume: bool = False,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """Convenience function to generate articles.

    Args:
        config_path: Path to configuration file
        topics: Optional list of topics
        tone: Writing tone
        resume: Whether to resume a session
        session_id: Session ID for resume or new session

    Returns:
        Generation summary
    """
    generator = ArticleGenerator(config_path)

    await generator.initialize(
        session_id=session_id,
        topics=topics,
        resume=resume
    )

    return await generator.generate(tone=tone)
