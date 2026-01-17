"""OpenAI API integration for article generation."""

import logging
import asyncio
import time
from typing import Optional, List, Dict, Any, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime

try:
    from openai import AsyncOpenAI, OpenAI
    from openai import APIError, RateLimitError, APIConnectionError, AuthenticationError
    from openai.types.chat import ChatCompletion, ChatCompletionChunk
except ImportError:
    raise ImportError(
        "OpenAI package is required. Install with: pip install openai>=1.12.0"
    )

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    """Result of an article generation."""
    content: str
    title: Optional[str] = None
    excerpt: Optional[str] = None
    tokens_used: int = 0
    model: str = ""
    generation_time: float = 0.0
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class GenerationConfig:
    """Configuration for content generation."""
    model: str = "gpt-4o"
    max_tokens: int = 2500
    temperature: float = 0.7
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    system_prompt: Optional[str] = None
    user_prompt_template: str = "Write a blog post about: {topic}"
    title_prompt_template: str = "Generate a catchy title for an article about: {topic}"
    excerpt_prompt_template: str = "Write a 2-3 sentence excerpt for an article about: {topic}"
    min_word_count: int = 500
    max_word_count: int = 1500
    enable_streaming: bool = False


@dataclass
class TokenUsage:
    """Track token usage statistics."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: 'TokenUsage') -> 'TokenUsage':
        """Combine token usage."""
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens
        )


class AIGenerator:
    """Async article generator using OpenAI API."""

    def __init__(
        self,
        api_key: str,
        config: Optional[GenerationConfig] = None
    ):
        """Initialize the AI generator.

        Args:
            api_key: OpenAI API key
            config: Generation configuration
        """
        self.api_key = api_key
        self.config = config or GenerationConfig()
        self.client = AsyncOpenAI(api_key=api_key)
        self._token_usage = TokenUsage()

    async def generate_article(
        self,
        topic: str,
        tone: str = "professional",
        keywords: Optional[List[str]] = None,
        custom_prompt: Optional[str] = None
    ) -> GenerationResult:
        """Generate a complete article.

        Args:
            topic: Article topic
            tone: Writing tone (professional, casual, friendly, etc.)
            keywords: Optional keywords to include
            custom_prompt: Optional custom prompt override

        Returns:
            GenerationResult with content and metadata
        """
        start_time = time.monotonic()

        # Build the system prompt
        system_prompt = self._build_system_prompt(tone, keywords)

        # Build the user prompt
        user_prompt = custom_prompt or self.config.user_prompt_template.format(topic=topic)

        try:
            # Generate the main content
            completion = await self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                presence_penalty=self.config.presence_penalty,
                frequency_penalty=self.config.frequency_penalty
            )

            content = completion.choices[0].message.content or ""
            generation_time = time.monotonic() - start_time

            # Track token usage
            if completion.usage:
                self._token_usage += TokenUsage(
                    prompt_tokens=completion.usage.prompt_tokens,
                    completion_tokens=completion.usage.completion_tokens,
                    total_tokens=completion.usage.total_tokens
                )

            # Generate title and excerpt
            title = await self._generate_title(topic)
            excerpt = await self._generate_excerpt(topic, content)

            result = GenerationResult(
                content=content,
                title=title,
                excerpt=excerpt,
                tokens_used=completion.usage.total_tokens if completion.usage else 0,
                model=self.config.model,
                generation_time=generation_time,
                raw_response={"finish_reason": completion.choices[0].finish_reason}
            )

            logger.info(f"Generated article for '{topic}' in {generation_time:.2f}s")
            return result

        except AuthenticationError as e:
            logger.error(f"OpenAI authentication failed: {e}")
            raise
        except RateLimitError as e:
            logger.error(f"OpenAI rate limit exceeded: {e}")
            raise
        except APIConnectionError as e:
            logger.error(f"OpenAI connection error: {e}")
            raise
        except APIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    async def generate_article_stream(
        self,
        topic: str,
        tone: str = "professional",
        keywords: Optional[List[str]] = None
    ) -> AsyncIterator[str]:
        """Generate an article with streaming output.

        Args:
            topic: Article topic
            tone: Writing tone
            keywords: Optional keywords to include

        Yields:
            Content chunks as they are generated
        """
        system_prompt = self._build_system_prompt(tone, keywords)
        user_prompt = self.config.user_prompt_template.format(topic=topic)

        try:
            stream = await self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                stream=True
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except (APIError, RateLimitError, APIConnectionError) as e:
            logger.error(f"Error during streaming generation: {e}")
            raise

    async def generate_batch(
        self,
        topics: List[str],
        tone: str = "professional",
        concurrency: int = 3
    ) -> List[GenerationResult]:
        """Generate multiple articles concurrently.

        Args:
            topics: List of topics
            tone: Writing tone
            concurrency: Maximum concurrent generations

        Returns:
            List of GenerationResult
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def generate_with_limit(topic: str) -> GenerationResult:
            async with semaphore:
                return await self.generate_article(topic, tone)

        tasks = [generate_with_limit(topic) for topic in topics]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and log errors
        successful_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to generate article for '{topics[i]}': {result}")
            else:
                successful_results.append(result)

        return successful_results

    def _build_system_prompt(
        self,
        tone: str,
        keywords: Optional[List[str]]
    ) -> str:
        """Build the system prompt for content generation.

        Args:
            tone: Writing tone
            keywords: Optional keywords

        Returns:
            System prompt string
        """
        base_prompt = self.config.system_prompt or (
            "You are a professional content writer. "
            "Create engaging, informative articles with proper structure, "
            "including headings, paragraphs, and a conclusion."
        )

        prompt_parts = [base_prompt]

        tone_instructions = {
            "professional": "Write in a formal, professional tone suitable for business audiences.",
            "casual": "Write in a relaxed, conversational tone that's easy to read.",
            "friendly": "Write in a warm, friendly tone that builds rapport with readers.",
            "technical": "Write with technical precision, including relevant details and terminology.",
            "marketing": "Write with persuasive language designed to engage and convert readers."
        }

        if tone in tone_instructions:
            prompt_parts.append(tone_instructions[tone])

        if keywords:
            prompt_parts.append(f"Naturally incorporate these keywords: {', '.join(keywords)}")

        prompt_parts.append(
            f"Target word count: {self.config.min_word_count}-{self.config.max_word_count} words."
        )

        return " ".join(prompt_parts)

    async def _generate_title(self, topic: str) -> str:
        """Generate a title for the article.

        Args:
            topic: Article topic

        Returns:
            Generated title
        """
        try:
            completion = await self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": "Generate a catchy, SEO-friendly title."},
                    {"role": "user", "content": self.config.title_prompt_template.format(topic=topic)}
                ],
                max_tokens=50,
                temperature=0.8
            )

            title = completion.choices[0].message.content or topic
            logger.debug(f"Generated title: {title}")
            return title.strip()

        except Exception as e:
            logger.warning(f"Failed to generate title: {e}, using topic as title")
            return topic

    async def _generate_excerpt(self, topic: str, content: str) -> Optional[str]:
        """Generate an excerpt for the article.

        Args:
            topic: Article topic
            content: Generated article content

        Returns:
            Generated excerpt or None
        """
        try:
            # Use first paragraph of content as context
            content_preview = content[:500] if len(content) > 500 else content

            completion = await self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": "Write a 2-3 sentence excerpt that summarizes the article."},
                    {"role": "user", "content": f"Article about '{topic}':\n\n{content_preview}\n\n{self.config.excerpt_prompt_template.format(topic=topic)}"}
                ],
                max_tokens=100,
                temperature=0.7
            )

            excerpt = completion.choices[0].message.content
            logger.debug(f"Generated excerpt: {excerpt[:50]}...")
            return excerpt.strip() if excerpt else None

        except Exception as e:
            logger.warning(f"Failed to generate excerpt: {e}")
            return None

    def get_token_usage(self) -> TokenUsage:
        """Get total token usage statistics.

        Returns:
            TokenUsage with cumulative statistics
        """
        return self._token_usage

    def reset_token_usage(self) -> None:
        """Reset token usage statistics."""
        self._token_usage = TokenUsage()

    async def close(self) -> None:
        """Close the client connection."""
        await self.client.close()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
