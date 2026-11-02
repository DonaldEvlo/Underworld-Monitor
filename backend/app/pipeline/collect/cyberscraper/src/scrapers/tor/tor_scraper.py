import logging

from bs4 import BeautifulSoup

from .tor_manager import TorManager
from .tor_config import TorConfig
from .utils import is_onion_url
from ..base_scraper import BaseScraper
from ...utils.error_handler import ErrorMessages


class TorScraper(BaseScraper):
    """Scraper implementation for Tor hidden services"""

    # Re-export for backwards compatibility
    is_onion_url = staticmethod(is_onion_url)

    def __init__(self, config: TorConfig | None = None):
        config = config or TorConfig()
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG if config.debug else logging.INFO)
        self.tor_manager = TorManager(config)
        self.config = config

    async def fetch_content(self, url: str, proxy: str | None = None) -> str:
        """Fetch content from an onion site"""
        try:
            if not is_onion_url(url):
                raise ValueError(ErrorMessages.ONION_URL_INVALID)

            # Use Tor manager to fetch content
            content = await self.tor_manager.fetch_content(url)
            return content
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Error fetching onion content: {str(e)}")
            # Re-raise with user-friendly message if it's a raw exception
            if "Could not connect" in str(e) or "connect to proxy" in str(e).lower():
                raise Exception(ErrorMessages.TOR_PROXY_CONNECTION_FAILED)
            raise

    async def extract(self, content: str) -> dict:
        """Extract data from the fetched content"""
        try:
            soup = BeautifulSoup(content, "lxml")
            return {
                "title": soup.title.string if soup.title else "",
                "text": soup.get_text(),
                "links": [a["href"] for a in soup.find_all("a", href=True)],
                "raw_html": content,
            }
        except Exception as e:
            self.logger.error(f"Error extracting content: {str(e)}")
            raise

    async def scrape_onion(self, url: str) -> dict:
        """Main method to scrape onion sites"""
        try:
            content = await self.fetch_content(url)
            return await self.extract(content)
        except Exception as e:
            self.logger.error(f"Error during onion scraping: {str(e)}")
            raise
