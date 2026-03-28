"""
Scrapers for New Zealand funders.

Each class targets one funder's public grants/funding pages.
Where page structure is uncertain, the raw HTML is preserved so the
AI scorer can extract data as a fallback.
"""
import logging
from typing import Optional

from scrapers.base import BaseScraper, ScrapedOpportunity

logger = logging.getLogger(__name__)


class CreativeNZScraper(BaseScraper):
    """
    Creative New Zealand — creativenz.govt.nz/funding-and-support
    Lists arts grants, residencies, and awards across visual art, music,
    writing, theatre, and more.
    """

    GRANTS_URL = "https://www.creativenz.govt.nz/funding-and-support"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            logger.warning("[creative_nz] Could not fetch funding page")
            return results

        soup = self.parse(html)

        # Creative NZ uses a card/list layout for funding rounds
        # Try multiple selector patterns as their site may vary
        cards = (
            soup.select(".funding-item")
            or soup.select(".grant-item")
            or soup.select("article.funding")
            or soup.select(".card")
        )

        if not cards:
            # Fallback: find substantive sections with grant-like links.
            # Exclude nav/menu items by requiring meaningful text length (>60 chars).
            cards = soup.find_all(
                lambda tag: tag.name in ("li", "div", "article")
                and tag.find("a")
                and len(tag.get_text(" ", strip=True)) > 60
                and any(
                    kw in tag.get_text(" ", strip=True).lower()
                    for kw in ["grant", "fund", "award", "residency", "scheme"]
                )
                and tag.name != "nav"
                and not any(p.name == "nav" for p in tag.parents),
            )

        for card in cards[:30]:  # cap to avoid noise
            opp = self._parse_card(card)
            if opp:
                results.append(opp)

        # If we got nothing from card parsing, store the full page for AI extraction
        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = f"{self.funder_name} — Funding Opportunities"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        logger.info(f"[creative_nz] Found {len(results)} opportunities")
        return results

    def _parse_card(self, card) -> Optional[ScrapedOpportunity]:
        link = card.find("a", href=True)
        if not link:
            return None
        title = self.clean_text(link.get_text())
        if not title or len(title) < 4:
            return None

        opp = ScrapedOpportunity()
        opp.source_id = self.source_id
        opp.funder_name = self.funder_name
        opp.grant_name = title
        opp.url = self.make_absolute(link["href"])

        text = self.clean_text(card.get_text(" "))
        opp.description = text[:800]

        # Try to find amount in card text
        opp.amount_text = self._extract_amount_text(text)
        opp.amount_min, opp.amount_max = self.parse_amount(opp.amount_text or "")

        # Try to find deadline
        deadline_text = self._extract_deadline_text(text)
        if deadline_text:
            opp.deadline_text = deadline_text
            opp.deadline = self.parse_date(deadline_text)

        return opp

    def _extract_amount_text(self, text: str) -> Optional[str]:
        import re
        m = re.search(r"(\$[\d,]+(?:\s*[–\-]\s*\$[\d,]+)?|\bup to \$[\d,]+)", text, re.I)
        return m.group(0) if m else None

    def _extract_deadline_text(self, text: str) -> Optional[str]:
        import re
        # Match patterns like "Closes 15 March 2025" or "Deadline: 31 Jan 2026"
        m = re.search(
            r"(?:closes?|deadline|open until|applications? close)[:\s]+([^\n.]{5,40})",
            text, re.I
        )
        return m.group(1).strip() if m else None


class NZOnAirScraper(BaseScraper):
    """
    NZ On Air — nzonair.govt.nz/music/
    Music funding including NZ Music Month, the Music Is Our Business fund, Amplifier, etc.
    """

    MUSIC_URL = "https://www.nzonair.govt.nz/funding/music-funding/"
    FUNDING_URL = "https://www.nzonair.govt.nz/funding/"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        for url in [self.MUSIC_URL, self.FUNDING_URL]:
            html = self.fetch(url)
            if not html:
                continue
            soup = self.parse(html)
            results.extend(self._extract_from_page(soup, url))

        # Deduplicate by URL
        seen = set()
        unique = []
        for o in results:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"[nz_on_air] Found {len(unique)} opportunities")
        return unique

    def _extract_from_page(self, soup, page_url: str) -> list:
        results = []
        # NZ On Air uses .tile cards for funding stream items
        items = (
            soup.select(".tile")
            or soup.select(".funding-scheme")
            or soup.select(".funding-item")
            or soup.select(".scheme")
            or soup.select("article")
        )
        for item in items[:20]:
            link = item.find("a", href=True)
            if not link:
                continue
            title = self.clean_text(link.get_text())
            if not title or len(title) < 4:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title
            opp.url = self.make_absolute(link["href"], page_url)
            text = self.clean_text(item.get_text(" "))
            opp.description = text[:800]
            results.append(opp)

        # Fallback
        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = f"{self.funder_name} — Music Funding"
            opp.url = page_url
            opp.description = self.clean_text(soup.get_text(" "))[:2000]
            results.append(opp)

        return results


class CommunityMattersScraper(BaseScraper):
    """
    Community Matters / Lottery Grants Board — communitymatters.govt.nz
    Covers: Lottery Community, Lottery Welfare (Health), Lottery Environment & Heritage,
    Lottery Maori Purposes, etc.
    """

    GRANTS_URL = "https://www.communitymatters.govt.nz/lottery-grants-board/"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            return results
        soup = self.parse(html)

        # Lottery committee pages are usually listed as links/cards
        committees = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = self.clean_text(a.get_text())
            if "lottery" in text.lower() and len(text) > 8:
                committees.append((text, self.make_absolute(href)))

        # Scrape each committee page for open rounds
        seen_urls = set()
        for name, url in committees[:15]:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            opp = self._build_lottery_opp(name, url)
            if opp:
                results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Lottery Grants Board — Open Funding Rounds"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:2000]
            results.append(opp)

        logger.info(f"[community_matters] Found {len(results)} opportunities")
        return results

    def _build_lottery_opp(self, name: str, url: str) -> Optional[ScrapedOpportunity]:
        html = self.fetch(url)
        if not html:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = name
            opp.url = url
            return opp
        soup = self.parse(html)
        opp = ScrapedOpportunity()
        opp.source_id = self.source_id
        opp.funder_name = self.funder_name
        opp.grant_name = name
        opp.url = url
        opp.description = self.clean_text(soup.get_text(" "))[:1500]

        # Try extracting key eligibility text
        for tag in soup.find_all(["h2", "h3", "h4"]):
            heading_text = tag.get_text().lower()
            if "eligib" in heading_text or "who can" in heading_text or "criteria" in heading_text:
                next_tag = tag.find_next_sibling()
                if next_tag:
                    opp.eligibility_summary = self.clean_text(next_tag.get_text())[:500]
                break

        return opp


class MSDScraper(BaseScraper):
    """
    Ministry of Social Development — msd.govt.nz/funding-and-contracting
    """

    FUNDING_URL = "https://www.msd.govt.nz/what-we-can-do/providers/index.html"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.FUNDING_URL)
        if not html:
            return results
        soup = self.parse(html)

        # MSD has both grant listings and procurement notices
        links = soup.find_all("a", href=True)
        for a in links:
            href = a["href"]
            text = self.clean_text(a.get_text())
            if len(text) < 6:
                continue
            if any(
                kw in text.lower() or kw in href.lower()
                for kw in ["fund", "grant", "support"]
            ):
                opp = ScrapedOpportunity()
                opp.source_id = self.source_id
                opp.funder_name = self.funder_name
                opp.grant_name = text[:300]
                opp.url = self.make_absolute(href)
                parent = a.parent
                if parent:
                    opp.description = self.clean_text(parent.get_text(" "))[:500]
                results.append(opp)

        # Fallback
        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "MSD — Funding and Contracting"
            opp.url = self.FUNDING_URL
            opp.description = self.clean_text(soup.get_text(" "))[:2000]
            results.append(opp)

        # Deduplicate
        seen = set()
        unique = []
        for o in results[:25]:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"[msd] Found {len(unique)} opportunities")
        return unique


class TPKScraper(BaseScraper):
    """
    Te Puni Kokiri — tpk.govt.nz/en/a-matou-mahi/funding
    Maori development, housing, and community funding.
    """

    FUNDING_URL = "https://www.tpk.govt.nz/en/nga-putea-me-nga-ratonga"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.FUNDING_URL)
        if not html:
            return results
        soup = self.parse(html)

        # TPK funding items
        items = (
            soup.select(".funding-item")
            or soup.select(".grant")
            or soup.select("li.item")
        )
        for item in items[:20]:
            link = item.find("a", href=True)
            if not link:
                continue
            title = self.clean_text(link.get_text())
            if not title or len(title) < 5:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title
            opp.url = self.make_absolute(link["href"])
            opp.description = self.clean_text(item.get_text(" "))[:800]
            results.append(opp)

        if not results:
            # Fallback — any relevant links on the page
            for a in soup.find_all("a", href=True):
                text = self.clean_text(a.get_text())
                if len(text) > 6 and any(
                    kw in text.lower() for kw in ["fund", "grant", "support", "whanau"]
                ):
                    opp = ScrapedOpportunity()
                    opp.source_id = self.source_id
                    opp.funder_name = self.funder_name
                    opp.grant_name = text[:300]
                    opp.url = self.make_absolute(a["href"])
                    results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Te Puni Kokiri — Funding"
            opp.url = self.FUNDING_URL
            opp.description = self.clean_text(soup.get_text(" "))[:2000]
            results.append(opp)

        # Deduplicate
        seen = set()
        unique = []
        for o in results[:20]:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"[tpk] Found {len(unique)} opportunities")
        return unique


class GenericGrantListingScraper(BaseScraper):
    """
    Generic scraper for funders that follow a standard pattern:
    a page listing grants with title + link.
    Used for: Wellington Community Trust, Tindall Foundation, Todd Foundation,
    Open Society Foundations, RWJF.
    """

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.base_url)
        if not html:
            return results
        soup = self.parse(html)

        # Strategy 1: look for heading + link combos
        results = self._extract_heading_links(soup)

        # Strategy 2: look for card/list items
        if not results:
            results = self._extract_cards(soup)

        # Strategy 3: any content links
        if not results:
            results = self._extract_all_grant_links(soup)

        # Fallback: store whole page for AI parsing
        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = f"{self.funder_name} — Funding Opportunities"
            opp.url = self.base_url
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        seen = set()
        unique = []
        for o in results[:20]:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"[{self.source_id}] Found {len(unique)} opportunities")
        return unique

    def _extract_heading_links(self, soup) -> list:
        results = []
        for heading in soup.find_all(["h2", "h3", "h4"]):
            link = heading.find("a", href=True) or heading.find_next_sibling("a", href=True)
            if not link:
                parent_link = heading.find_parent("a", href=True)
                link = parent_link
            if not link:
                continue
            title = self.clean_text(heading.get_text())
            if len(title) < 5:
                continue
            url = self.make_absolute(link["href"])
            if not url:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title[:400]
            opp.url = url
            sibling = heading.find_next_sibling(["p", "div", "ul"])
            if sibling:
                opp.description = self.clean_text(sibling.get_text(" "))[:600]
            results.append(opp)
        return results

    def _extract_cards(self, soup) -> list:
        results = []
        cards = soup.select(".card") or soup.select("article") or soup.select("li.item")
        for card in cards[:25]:
            link = card.find("a", href=True)
            if not link:
                continue
            title = self.clean_text(link.get_text())
            if len(title) < 5:
                continue
            url = self.make_absolute(link["href"])
            if not url:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title[:400]
            opp.url = url
            opp.description = self.clean_text(card.get_text(" "))[:600]
            results.append(opp)
        return results

    def _extract_all_grant_links(self, soup) -> list:
        results = []
        grant_keywords = ["grant", "fund", "award", "scheme", "fellowship", "residency", "support"]
        for a in soup.find_all("a", href=True):
            text = self.clean_text(a.get_text())
            href = a["href"]
            if len(text) < 6:
                continue
            url = self.make_absolute(href)
            if not url:
                continue
            if any(kw in text.lower() or kw in href.lower() for kw in grant_keywords):
                opp = ScrapedOpportunity()
                opp.source_id = self.source_id
                opp.funder_name = self.funder_name
                opp.grant_name = text[:400]
                opp.url = url
                results.append(opp)
        return results
