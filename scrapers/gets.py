"""
Scraper for GETS — Government Electronic Tenders Service (gets.govt.nz).
Covers NZ government procurement: RFPs, RFTs, contracts.
"""
import logging
import time
import re
from typing import Optional
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapedOpportunity

logger = logging.getLogger(__name__)


# Categories/keywords to filter for relevance
RELEVANT_CATEGORIES = [
    "health", "mental health", "counselling", "counseling",
    "education", "youth", "community", "social service",
    "maori", "māori", "pacific", "wellbeing", "welfare",
    "research", "evaluation", "training", "workforce",
]

GETS_SEARCH_URL = "https://www.gets.govt.nz/Contracts/index.cfm"


class GETSScraper(BaseScraper):
    """
    Scraper for gets.govt.nz.

    GETS uses a forms-based search interface. We fetch the listing pages
    for health/social/education categories and filter for relevant opportunities.
    """

    # GETS listing pages — new URL format (changed from .cfm to .htm)
    # Main listing sorted by date; fetch multiple pages to get recent tenders.
    CATEGORY_URLS = [
        "https://www.gets.govt.nz/ExternalIndex.htm?orderBy=date",
        "https://www.gets.govt.nz/ExternalIndex.htm?page=2&orderBy=date",
        "https://www.gets.govt.nz/ExternalIndex.htm?page=3&orderBy=date",
    ]

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        seen_urls = set()

        for url in self.CATEGORY_URLS:
            html = self.fetch(url)
            if not html:
                continue
            opps = self._parse_listing(html, url)
            for o in opps:
                if o.url not in seen_urls:
                    seen_urls.add(o.url)
                    results.append(o)
            time.sleep(1)

        # Filter for relevance
        filtered = [o for o in results if self._is_relevant(o)]

        if not filtered and results:
            # Return all if none pass the relevance filter
            filtered = results[:20]

        logger.info(f"[gets] Found {len(filtered)} relevant tender opportunities")
        return filtered

    def _parse_listing(self, html: str, page_url: str) -> list[ScrapedOpportunity]:
        results = []
        soup = BeautifulSoup(html, "lxml")

        # GETS listing rows are typically in a table or list
        rows = (
            soup.select("tr.contract-row")
            or soup.select(".contract-listing tr")
            or soup.select("table tr")
            or soup.select(".tender-item")
            or soup.select("li.contract")
        )

        if rows:
            for row in rows[1:30]:  # skip header row
                opp = self._parse_row(row, page_url)
                if opp:
                    results.append(opp)

        # Fallback: look for any contract/tender links
        if not results:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "Contract" in href or "tender" in href.lower() or "rfp" in href.lower():
                    text = self.clean_text(a.get_text())
                    if len(text) < 6:
                        continue
                    opp = ScrapedOpportunity()
                    opp.source_id = self.source_id
                    opp.funder_name = "NZ Government (GETS)"
                    opp.grant_name = text[:400]
                    opp.url = self.make_absolute(href, "https://www.gets.govt.nz")
                    opp.is_tender = True
                    results.append(opp)

        return results

    def _parse_row(self, row, page_url: str) -> Optional[ScrapedOpportunity]:
        # GETS table layout: RFx ID | Reference # | Title | Type | Close Date | Organisation
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            return None

        cell_texts = [self.clean_text(c.get_text()) for c in cells]
        row_text = " ".join(cell_texts)

        # Col 0: RFx ID link (numeric ID — not the title)
        # Col 2: Title link (human-readable tender name)
        # Col 4: Close date
        # Col 5: Organisation
        all_links = row.find_all("a", href=True)
        title_link = None
        title = None

        # Prefer the link whose text is not purely numeric (that's the ID)
        for a in all_links:
            txt = self.clean_text(a.get_text())
            if txt and not txt.isdigit() and len(txt) >= 5:
                title_link = a
                title = txt
                break

        if not title_link:
            # All links are numeric IDs — use col 2 text and col 0 URL as fallback
            if len(cells) > 2:
                title = cell_texts[2]
            if not title or len(title) < 5:
                return None
            title_link = all_links[0] if all_links else None

        opp = ScrapedOpportunity()
        opp.source_id = self.source_id
        opp.is_tender = True

        opp.grant_name = title[:400]
        opp.url = self.make_absolute(
            title_link["href"] if title_link else "", "https://www.gets.govt.nz"
        )
        if not opp.url:
            return None

        # Organisation name: last non-empty cell, strip "(HISTORIC)" suffix
        org = ""
        for txt in reversed(cell_texts):
            cleaned = re.sub(r"\s*\(HISTORIC\)\s*", "", txt).strip()
            if cleaned and cleaned not in cell_texts[:2]:
                org = cleaned[:100]
                break
        opp.funder_name = f"NZ Government — {org}" if org else "NZ Government (GETS)"

        # Close date: look for datetime pattern in row text
        date_pattern = re.compile(
            r"\d{1,2}:\d{2}\s+(?:AM|PM)\s+\d{1,2}\s+\w+\s+\d{4}"  # "5:00 PM 28 Feb 2026"
            r"|\d{1,2}\s+\w+\s+\d{4}"                               # "28 Feb 2026"
            r"|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}",                   # "28/02/2026"
        )
        dates_found = date_pattern.findall(row_text)
        if dates_found:
            opp.deadline_text = dates_found[-1]
            opp.deadline = self.parse_date(opp.deadline_text)

        opp.description = row_text[:600]
        return opp

    def _is_relevant(self, opp: ScrapedOpportunity) -> bool:
        """Check if a tender is relevant to George's profile."""
        text = " ".join(filter(None, [
            opp.grant_name,
            opp.description,
            opp.funder_name,
            opp.eligibility_summary,
        ])).lower()
        return any(kw in text for kw in RELEVANT_CATEGORIES)
