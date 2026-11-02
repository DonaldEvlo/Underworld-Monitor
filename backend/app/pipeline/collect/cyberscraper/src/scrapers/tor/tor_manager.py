import aiohttp
from aiohttp_socks import ProxyConnector
import random
import logging

from .tor_config import TorConfig
from .utils import is_onion_url
from .exceptions import TorConnectionError, OnionServiceError, TorException
from ...utils.error_handler import ErrorMessages


class TorManager:
    def __init__(self, config: TorConfig = TorConfig()):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG if config.debug else logging.INFO)
        self.config = config
        self._setup_logging()
        self._session: aiohttp.ClientSession | None = None
        self._proxy_url = f"socks5://{self.config.socks_host}:{self.config.socks_port}"

    def _setup_logging(self):
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def get_headers(self) -> dict[str, str]:
        """Get randomized Tor Browser-like headers"""
        return {
            "User-Agent": random.choice(self.config.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an async session with SOCKS proxy connector."""
        if self._session is None or self._session.closed:
            # ssl=False : cette classe ne sert qu'à des URLs .onion (garde dans
            # fetch_content), qui s'auto-authentifient par leur adresse elle-même —
            # valider leur certif HTTPS contre une chaîne CA publique n'a pas de sens
            # (la plupart des services onion utilisent des certifs auto-signés, ce
            # qui fait échouer la validation par défaut sans rien apporter en retour).
            connector = ProxyConnector.from_url(self._proxy_url, ssl=False)
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(
                connector=connector, timeout=timeout, headers=self.get_headers()
            )
        return self._session

    async def close(self) -> None:
        """Close the session. Call on shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def verify_tor_connection(self) -> bool:
        """Verify Tor connection is working"""
        try:
            session = await self._get_session()
            async with session.get("https://check.torproject.org/api/ip") as response:
                data = await response.json()
                is_tor = data.get("IsTor", False)

                if is_tor:
                    self.logger.info("Successfully connected to Tor network")
                    return True
                else:
                    raise TorConnectionError("Connection is not using Tor network")

        except aiohttp.ClientError:
            raise TorConnectionError(ErrorMessages.TOR_PROXY_CONNECTION_FAILED)
        except TorConnectionError:
            raise
        except Exception:
            raise TorConnectionError(ErrorMessages.TOR_CONNECTION_ERROR)

    async def fetch_content(self, url: str) -> str:
        """Fetch content from an onion site"""
        if not is_onion_url(url):
            raise OnionServiceError(ErrorMessages.ONION_URL_INVALID)

        try:
            if self.config.verify_connection:
                await self.verify_tor_connection()

            session = await self._get_session()
            async with session.get(url) as response:
                response.raise_for_status()
                text = await response.text()

                self.logger.info(f"Successfully fetched content from {url}")
                return text

        except aiohttp.ClientError as e:
            error_msg = f"{ErrorMessages.TOR_CONNECTION_ERROR}\n\nDetails: {str(e)}"
            raise OnionServiceError(error_msg)
        except (OnionServiceError, TorConnectionError):
            raise
        except Exception as e:
            error_msg = f"{ErrorMessages.TOR_CONNECTION_ERROR}\n\nDetails: {str(e)}"
            raise TorException(error_msg)
