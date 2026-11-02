"""
CyberScraper-2077 Scrapers Module

This module provides the PlaywrightScraper for advanced web scraping with anti-detection features.
"""

from .playwright_scraper import PlaywrightScraper

# Re-export volontaire : c'est l'API publique du module (code vendorise
# CyberScraper-2077). `__all__` le declare explicitement plutot que de
# laisser un import qui parait inutilise.
__all__ = ["PlaywrightScraper"]
