"""
Base scraper class with shared utilities.
"""
import time
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)


class ScrapedOpportunity:
    """
    Raw data structure returned by scrapers before scoring.
    The scorer will enrich this into a full Opportunity model.
    """
    def __init__(self):
        self.source_id: str = ""
        self.funder_name: str = ""
        self.grant_name: str = ""
        self.url: str = ""
        self.is_tender: bool = False
        self.amount_min: Optional[float] = None
        self.amount_max: Optional[float] = None
        self.amount_text: Optional[str] = None
        self.deadline: Optional[datetime] = None
        self.deadline_text: Optional[str] = None
        self.open_date: Optional[datetime] = None
        self.eligibility_summary: Optional[str] = None
        self.description: Optional[str] = None
        self.raw_html: Optional[str] = None  # page HTML for Claude extraction fallback

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "funder_name": self.funder_name,
            "grant_name": self.grant_name,
            "url": self.url,
            "is_tender": self.is_tender,
            "amount_min": self.amount_min,
            "amount_max": self.amount_max,
            "amount_text": self.amount_text,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "deadline_text": self.deadline_text,
            "open_date": self.open_date.isoformat() if self.open_date else None,
            "eligibility_summary": self.eligibility_summary,
            "description": self.description,
        }


class BaseScraper(ABC):
    """
    Abstract base for all scrapers.

    Subclasses implement `scrape()` and return a list of ScrapedOpportunity objects.
    """

    def __init__(self, funder_config: dict):
        self.config = funder_config
        self.source_id = funder_config.get("id", "unknown")
        self.funder_name = funder_config.get("name", "Unknown Funder")
        self.base_url = funder_config.get("url", "")
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-NZ,en;q=0.9",
            }
        )
        return session

    def fetch(self, url: str, timeout: int = 30) -> Optional[str]:
        """Fetch a URL and return HTML, or None on failure."""
        try:
            resp = self.session.get(url, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            time.sleep(1.5)  # polite delay
            return resp.text
        except requests.RequestException as e:
            logger.warning(f"[{self.source_id}] Failed to fetch {url}: {e}")
            return None

    def parse(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def clean_text(self, text: str) -> str:
        """Normalise whitespace and strip."""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    def parse_amount(self, text: str) -> tuple[Optional[float], Optional[float]]:
        """
        Try to extract min/max dollar amounts from a string like
        '$5,000 – $50,000' or 'Up to $20,000'.
        Returns (min, max) floats, either may be None.
        """
        if not text:
            return None, None
        text = text.replace(",", "").replace("\u2013", "-").replace("\u2014", "-")
        nums = re.findall(r"\$?\s*(\d+(?:\.\d+)?)\s*(?:k|K)?", text)
        amounts = []
        for n in nums:
            val = float(n)
            # handle e.g. "50k"
            idx = text.find(n)
            if idx >= 0 and idx + len(n) < len(text):
                suffix = text[idx + len(n): idx + len(n) + 1].strip().lower()
                if suffix == "k":
                    val *= 1000
            amounts.append(val)
        if len(amounts) == 0:
            return None, None
        if len(amounts) == 1:
            if "up to" in text.lower() or "maximum" in text.lower():
                return None, amounts[0]
            return amounts[0], amounts[0]
        return min(amounts), max(amounts)

    def parse_date(self, text: str) -> Optional[datetime]:
        """Try to parse a date string."""
        if not text:
            return None
        try:
            return date_parser.parse(text, dayfirst=True)
        except (ValueError, OverflowError):
            return None

    def make_absolute(self, url: str, base: str = None) -> str:
        """Convert a relative URL to absolute. Returns empty string for non-http schemes."""
        if not url:
            return base or self.base_url
        # Skip mailto:, tel:, javascript: etc.
        if ":" in url and not url.startswith("http"):
            return ""
        if url.startswith("http"):
            return url
        base = base or self.base_url
        from urllib.parse import urljoin
        return urljoin(base, url)

    @abstractmethod
    def scrape(self) -> list[ScrapedOpportunity]:
        """
        Scrape the funding source and return a list of ScrapedOpportunity objects.
        Must be implemented by each subclass.
        """
        raise NotImplementedError
