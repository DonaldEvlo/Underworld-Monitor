"""Messages d'erreur pour le scraping (loggés, pas affichés à un humain — pas
d'UI interactive dans le pipeline automatisé)."""


class ErrorMessages:
    """Centralized error messages."""

    # Tor/Proxy errors
    TOR_PROXY_CONNECTION_FAILED = "Failed to connect to Tor proxy (socks host/port)."
    TOR_NOT_DETECTED = "Connection is not using the Tor network."
    ONION_URL_INVALID = "Invalid onion URL: must end with '.onion'."
    TOR_CONNECTION_ERROR = "Unexpected Tor connection error."

    # Scraping errors
    SCRAPING_FAILED = "Failed to scrape the website."
    URL_INVALID = "Invalid URL: must start with http:// or https://."
    TIMEOUT_ERROR = "Request timed out."
