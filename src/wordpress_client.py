"""WordPress REST API client with async support."""

import logging
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

import aiohttp
from yarl import URL

logger = logging.getLogger(__name__)


@dataclass
class WordPressPost:
    """Represents a WordPress post."""
    id: int
    title: str
    content: str
    status: str
    link: str
    date: str
    excerpt: Optional[str] = None


@dataclass
class WordPressConfig:
    """Configuration for WordPress connection."""
    base_url: str
    username: str
    application_password: str
    timeout: int = 30
    max_connections: int = 10
    verify_ssl: bool = True


class WordPressClient:
    """Async WordPress REST API client with Basic Authentication."""

    def __init__(self, config: WordPressConfig):
        """Initialize the WordPress client.

        Args:
            config: WordPress configuration
        """
        self.config = config
        self.api_base = URL(config.base_url) / "wp/v2"
        self.auth = aiohttp.BasicAuth(config.username, config.application_password)
        self.connector = aiohttp.TCPConnector(
            limit=config.max_connections,
            limit_per_host=config.max_connections,
            verify_ssl=config.verify_ssl
        )
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the HTTP session.

        Returns:
            Active ClientSession
        """
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(
                connector=self.connector,
                auth=self.auth,
                timeout=timeout
            )
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            # Wait for connections to close
            await asyncio.sleep(0.25)

    async def test_connection(self) -> bool:
        """Test the connection to WordPress.

        Returns:
            True if connection is successful
        """
        try:
            session = await self._get_session()
            url = self.api_base / "users" / "me"

            async with session.get(url) as response:
                if response.status == 200:
                    logger.info("WordPress connection test successful")
                    return True
                else:
                    error = await response.text()
                    logger.error(f"WordPress connection test failed: {error}")
                    return False
        except Exception as e:
            logger.error(f"WordPress connection error: {e}")
            return False

    async def create_post(
        self,
        title: str,
        content: str,
        status: str = "draft",
        excerpt: Optional[str] = None,
        categories: Optional[List[int]] = None,
        tags: Optional[List[int]] = None,
        featured_media: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None
    ) -> WordPressPost:
        """Create a new post.

        Args:
            title: Post title
            content: Post content (HTML or plain text)
            status: Post status (draft, publish, pending, etc.)
            excerpt: Post excerpt
            categories: List of category IDs
            tags: List of tag IDs
            featured_media: Featured image ID
            meta: Meta fields (SEO, custom fields, etc.)

        Returns:
            Created WordPressPost

        Raises:
            Exception: If post creation fails
        """
        session = await self._get_session()
        url = self.api_base / "posts"

        data: Dict[str, Any] = {
            "title": title,
            "content": content,
            "status": status
        }

        if excerpt:
            data["excerpt"] = excerpt
        if categories:
            data["categories"] = categories
        if tags:
            data["tags"] = tags
        if featured_media:
            data["featured_media"] = featured_media
        if meta:
            data["meta"] = meta

        try:
            async with session.post(url, json=data) as response:
                if response.status == 201:
                    result = await response.json()
                    logger.info(f"Created post '{title}' with ID {result['id']}")
                    return WordPressPost(
                        id=result["id"],
                        title=result["title"]["rendered"],
                        content=result["content"]["rendered"],
                        status=result["status"],
                        link=result["link"],
                        date=result["date"],
                        excerpt=result.get("excerpt", {}).get("rendered")
                    )
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to create post (status {response.status}): {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error creating post: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating post: {e}")
            raise

    async def update_post(
        self,
        post_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
        status: Optional[str] = None
    ) -> WordPressPost:
        """Update an existing post.

        Args:
            post_id: Post ID to update
            title: New title
            content: New content
            status: New status

        Returns:
            Updated WordPressPost
        """
        session = await self._get_session()
        url = self.api_base / "posts" / str(post_id)

        data: Dict[str, Any] = {}
        if title:
            data["title"] = title
        if content:
            data["content"] = content
        if status:
            data["status"] = status

        try:
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Updated post ID {post_id}")
                    return WordPressPost(
                        id=result["id"],
                        title=result["title"]["rendered"],
                        content=result["content"]["rendered"],
                        status=result["status"],
                        link=result["link"],
                        date=result["date"]
                    )
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to update post (status {response.status}): {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error updating post: {e}")
            raise

    async def get_post(self, post_id: int) -> Optional[WordPressPost]:
        """Get a post by ID.

        Args:
            post_id: Post ID to retrieve

        Returns:
            WordPressPost or None if not found
        """
        session = await self._get_session()
        url = self.api_base / "posts" / str(post_id)

        try:
            async with session.get(url) as response:
                if response.status == 200:
                    result = await response.json()
                    return WordPressPost(
                        id=result["id"],
                        title=result["title"]["rendered"],
                        content=result["content"]["rendered"],
                        status=result["status"],
                        link=result["link"],
                        date=result["date"]
                    )
                elif response.status == 404:
                    logger.warning(f"Post {post_id} not found")
                    return None
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to get post (status {response.status}): {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error getting post: {e}")
            raise

    async def list_posts(
        self,
        status: str = "draft",
        per_page: int = 100,
        page: int = 1
    ) -> List[WordPressPost]:
        """List posts with optional filtering.

        Args:
            status: Post status filter
            per_page: Number of posts per page
            page: Page number

        Returns:
            List of WordPressPost
        """
        session = await self._get_session()
        url = (self.api_base / "posts").with_query({
            "status": status,
            "per_page": str(per_page),
            "page": str(page)
        })

        try:
            async with session.get(url) as response:
                if response.status == 200:
                    results = await response.json()
                    posts = []
                    for result in results:
                        posts.append(WordPressPost(
                            id=result["id"],
                            title=result["title"]["rendered"],
                            content=result["content"]["rendered"],
                            status=result["status"],
                            link=result["link"],
                            date=result["date"]
                        ))
                    return posts
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to list posts (status {response.status}): {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error listing posts: {e}")
            raise

    async def get_categories(self) -> List[Dict[str, Any]]:
        """Get all categories.

        Returns:
            List of category dictionaries
        """
        session = await self._get_session()
        url = self.api_base / "categories"

        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to get categories (status {response.status}): {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error getting categories: {e}")
            raise

    async def get_tags(self) -> List[Dict[str, Any]]:
        """Get all tags.

        Returns:
            List of tag dictionaries
        """
        session = await self._get_session()
        url = self.api_base / "tags"

        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to get tags (status {response.status}): {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error getting tags: {e}")
            raise

    async def upload_media(
        self,
        filename: str,
        content: bytes,
        mime_type: str = "image/jpeg"
    ) -> Dict[str, Any]:
        """Upload media to WordPress.

        Args:
            filename: Name of the file
            content: File content as bytes
            mime_type: MIME type of the file

        Returns:
            Dictionary with media details including ID
        """
        session = await self._get_session()
        url = self.api_base / "media"

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime_type
        }

        try:
            async with session.post(url, data=content, headers=headers) as response:
                if response.status == 201:
                    result = await response.json()
                    logger.info(f"Uploaded media '{filename}' with ID {result['id']}")
                    return result
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to upload media (status {response.status}): {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error uploading media: {e}")
            raise

    async def __aenter__(self):
        """Async context manager entry."""
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
