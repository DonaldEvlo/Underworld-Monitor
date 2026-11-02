"""
Base Scraper Module

Defines the abstract base class for all scrapers in the CyberScraper-2077 project.
All scraper implementations should inherit from BaseScraper and implement its abstract methods.
"""

from abc import ABC, abstractmethod


class BaseScraper(ABC):
    """
    Abstract base class for all scraper implementations.

    This class defines the common interface that all scrapers must implement.
    Supports async context manager protocol for proper resource cleanup.
    """

    @abstractmethod
    async def fetch_content(self, url: str, proxy: str | None = None) -> str:
        """
        Fetch content from a given URL.

        Args:
            url: The URL to fetch content from
            proxy: Proxy server to use for the request

        Returns:
            The raw content fetched from the URL
        """
        pass

    @abstractmethod
    async def extract(self, content: str) -> dict:
        """
        Extract structured data from raw content.

        Args:
            content: Raw content to extract data from

        Returns:
            Structured data extracted from the content
        """
        pass

    async def close(self) -> None:
        """Clean up resources. Override in subclasses that need cleanup."""
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with cleanup."""
        await self.close()
        return False
