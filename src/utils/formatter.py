"""Content formatting utilities for WordPress."""

import logging
from typing import Optional
import html as html_module

try:
    import markdown
    from markdown.extensions import extra
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

logger = logging.getLogger(__name__)


class ContentFormatter:
    """Format content for WordPress publishing."""

    def __init__(
        self,
        convert_markdown: bool = True,
        markdown_extensions: Optional[list] = None
    ):
        """Initialize the content formatter.

        Args:
            convert_markdown: Whether to convert Markdown to HTML
            markdown_extensions: List of Markdown extensions to use
        """
        self.convert_markdown = convert_markdown and HAS_MARKDOWN

        # Default Markdown extensions for WordPress compatibility
        default_extensions = [
            'markdown.extensions.extra',      # Tables, fenced code, etc.
            'markdown.extensions.codehilite',  # Syntax highlighting
            'markdown.extensions.toc',         # Table of contents
            'markdown.extensions.sane_lists',  # Better list handling
            'markdown.extensions.nl2br',       # New line to <br>
        ]
        self.markdown_extensions = markdown_extensions or default_extensions

        if self.convert_markdown:
            self.md = markdown.Markdown(extensions=self.markdown_extensions)
            logger.debug(f"Markdown converter initialized with extensions: {self.markdown_extensions}")
        else:
            if convert_markdown and not HAS_MARKDOWN:
                logger.warning("Markdown conversion requested but 'markdown' package not installed")
                logger.warning("Install with: pip install markdown>=3.5.0")

    def format_content(self, content: str) -> str:
        """Format content for WordPress.

        Args:
            content: Raw content (likely Markdown)

        Returns:
            Formatted content (HTML if Markdown conversion enabled)
        """
        if not content:
            return ""

        # Convert Markdown to HTML if enabled
        if self.convert_markdown:
            try:
                # Reset the Markdown instance for fresh conversion
                self.md.reset()
                html_content = self.md.convert(content)

                # Clean up any potential issues
                html_content = self._clean_html(html_content)

                logger.debug(f"Converted Markdown to HTML ({len(content)} -> {len(html_content)} chars)")
                return html_content
            except Exception as e:
                logger.error(f"Markdown conversion failed: {e}")
                # Fall back to original content
                return self._escape_html(content)

        # Escape HTML if not converting
        return self._escape_html(content)

    def _clean_html(self, html: str) -> str:
        """Clean generated HTML for WordPress compatibility.

        Args:
            html: Raw HTML from Markdown conversion

        Returns:
            Cleaned HTML
        """
        # Remove empty paragraphs
        html = html.replace('<p></p>', '')

        # Convert code blocks to WordPress-compatible format
        # WordPress prefers pre + code with language class
        # The codehilite extension should handle this

        return html.strip()

    def _escape_html(self, text: str) -> str:
        """Escape HTML entities in text.

        Args:
            text: Plain text with potential HTML

        Returns:
            HTML-escaped text
        """
        return html_module.escape(text)

    def extract_excerpt(self, content: str, max_length: int = 200) -> str:
        """Extract a plain text excerpt from content.

        Args:
            content: Content (Markdown or HTML)
            max_length: Maximum length of excerpt

        Returns:
            Plain text excerpt
        """
        if not content:
            return ""

        # Remove Markdown/HTML tags for plain text
        import re
        text = re.sub(r'<[^>]+>', '', content)  # Remove HTML tags
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)  # Remove images
        text = re.sub(r'\[.*?\]\(.*?\)', '', text)  # Remove links
        text = re.sub(r'[*_`#]+', '', text)  # Remove Markdown syntax
        text = ' '.join(text.split())  # Normalize whitespace

        # Truncate to max length
        if len(text) > max_length:
            text = text[:max_length].rsplit(' ', 1)[0] + '...'

        return text.strip()


# Global formatter instance
_default_formatter: Optional[ContentFormatter] = None


def get_formatter(
    convert_markdown: bool = True,
    markdown_extensions: Optional[list] = None
) -> ContentFormatter:
    """Get or create the default content formatter.

    Args:
        convert_markdown: Whether to convert Markdown to HTML
        markdown_extensions: List of Markdown extensions to use

    Returns:
        ContentFormatter instance
    """
    global _default_formatter
    if _default_formatter is None:
        _default_formatter = ContentFormatter(convert_markdown, markdown_extensions)
    return _default_formatter
