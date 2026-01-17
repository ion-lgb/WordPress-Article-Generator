"""Logger configuration for the WordPress article generator."""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


class Logger:
    """Centralized logger with file and console handlers."""

    _instance: Optional['Logger'] = None
    _logger: Optional[logging.Logger] = None

    def __new__(cls, name: str = 'article_generator', log_dir: str = 'logs'):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._setup_logger(name, log_dir)
        return cls._instance

    @classmethod
    def _setup_logger(cls, name: str, log_dir: str) -> None:
        """Setup logger with file and console handlers."""
        cls._logger = logging.getLogger(name)
        cls._logger.setLevel(logging.DEBUG)

        # Avoid duplicate handlers
        if cls._logger.handlers:
            return

        # Create log directory if it doesn't exist
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        # File handler with timestamp
        timestamp = datetime.now().strftime('%Y%m%d')
        file_handler = logging.FileHandler(
            log_path / f'{name}_{timestamp}.log',
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(
            '%(levelname)s: %(message)s'
        )
        console_handler.setFormatter(console_format)

        cls._logger.addHandler(file_handler)
        cls._logger.addHandler(console_handler)

    @classmethod
    def get_logger(cls) -> logging.Logger:
        """Get the logger instance."""
        if cls._logger is None:
            cls._setup_logger('article_generator', 'logs')
        return cls._logger


def get_logger(name: str = 'article_generator', log_dir: str = 'logs') -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name
        log_dir: Directory to store log files

    Returns:
        Configured logger instance
    """
    return Logger(name, log_dir).get_logger()
