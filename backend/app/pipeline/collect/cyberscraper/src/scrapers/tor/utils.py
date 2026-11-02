"""Shared utilities for Tor-related scraping."""

from urllib.parse import urlparse


def is_onion_url(url: str) -> bool:
    """
    Check if the given URL is an onion service.

    Args:
        url: The URL to check

    Returns:
        True if the URL is a .onion address, False otherwise
    """
    try:
        parsed = urlparse(url)
        return parsed.hostname.endswith(".onion") if parsed.hostname else False
    except Exception:
        return False
