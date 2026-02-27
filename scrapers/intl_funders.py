"""
Scrapers for international funders.
"""
import logging
from scrapers.base import BaseScraper, ScrapedOpportunity

logger = logging.getLogger(__name__)


class WellcomeScraper(BaseScraper):
    """
    Wellcome Trust — wellcome.org/grant-funding/schemes
    Major UK biomedical and health funder with schemes relevant to
    mental health research, community health, and humanities/social science.
    """

    SCHEMES_URL = "https://wellcome.org/grant-funding/schemes"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.SCHEMES_URL)
        if not html:
            return results
        soup = self.parse(html)

        # Wellcome uses a card grid for funding schemes
        cards = (
            soup.select(".scheme-card")
            or soup.select(".funding-scheme")
            or soup.select("[data-component='card']")
            or soup.select(".card")
            or soup.select("article")
        )

        for card in cards[:30]:
            link = card.find("a", href=True)
            if not link:
                continue
            title = self.clean_text(link.get_text())
            if len(title) < 5:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title
            opp.url = self.make_absolute(link["href"], "https://wellcome.org")
            opp.description = self.clean_text(card.get_text(" "))[:800]
            results.append(opp)

        # Fallback
        if not results:
            for a in soup.find_all("a", href=True):
                text = self.clean_text(a.get_text())
                if len(text) > 10 and any(
                    kw in text.lower()
                    for kw in ["grant", "fund", "fellowship", "award", "scheme"]
                ):
                    opp = ScrapedOpportunity()
                    opp.source_id = self.source_id
                    opp.funder_name = self.funder_name
                    opp.grant_name = text[:400]
                    opp.url = self.make_absolute(a["href"], "https://wellcome.org")
                    results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Wellcome Trust — Funding Schemes"
            opp.url = self.SCHEMES_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            results.append(opp)

        # Deduplicate
        seen = set()
        unique = []
        for o in results[:25]:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"[wellcome] Found {len(unique)} opportunities")
        return unique


class RWJFScraper(BaseScraper):
    """
    Robert Wood Johnson Foundation — rwjf.org
    US health equity and community health funder.
    """

    RFP_URL = "https://www.rwjf.org/en/grants/active-funding-opportunities.html"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.RFP_URL)
        if not html:
            return results
        soup = self.parse(html)

        # RWJF uses .cmp-customcard divs (AEM / Adobe Experience Manager)
        # Cards have the title in h4 but links may be on the card wrapper
        items = (
            soup.select(".cmp-customcard")
            or soup.select("[data-component='card']")
            or soup.select(".call-item")
            or soup.select(".grant-listing")
            or soup.select("article")
        )

        for item in items[:20]:
            # Title is in h4.card-heading-title or similar
            title_tag = (
                item.find("h4")
                or item.find("h3")
                or item.find("h2")
                or item.find("a", href=True)
            )
            if not title_tag:
                continue
            title = self.clean_text(title_tag.get_text())
            if len(title) < 5:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title
            # Use link if present, otherwise fall back to main page URL
            link = item.find("a", href=True)
            opp.url = self.make_absolute(link["href"], "https://www.rwjf.org") if link else self.RFP_URL
            opp.description = self.clean_text(item.get_text(" "))[:800]
            results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "RWJF — Active Funding Opportunities"
            opp.url = self.RFP_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            results.append(opp)

        logger.info(f"[rwjf] Found {len(results)} opportunities")
        return results


class OpenSocietyScraper(BaseScraper):
    """
    Open Society Foundations — opensocietyfoundations.org/grants
    Social justice, democracy, human rights, health systems.
    """

    GRANTS_URL = "https://www.opensocietyfoundations.org/grants"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            return results
        soup = self.parse(html)

        # OSF uses .m-cardsList__item li with .a-grantsCard links
        cards = (
            soup.select(".m-cardsList__item")
            or soup.select(".grant-card")
            or soup.select(".opportunity")
            or soup.select("article")
            or soup.select(".item")
        )

        for card in cards[:20]:
            link = card.find("a", class_="a-grantsCard") or card.find("a", href=True)
            if not link:
                continue
            title_tag = card.find("h2", class_="a-grantsCard__title") or card.find("h2") or card.find("h3")
            title = self.clean_text((title_tag or link).get_text())
            if len(title) < 5:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title
            opp.url = self.make_absolute(link["href"], "https://www.opensocietyfoundations.org")
            opp.description = self.clean_text(card.get_text(" "))[:800]
            # Try to extract deadline from footer
            footer = card.find("footer", class_="a-grantsCard__footer")
            if footer:
                opp.deadline_text = self.clean_text(footer.get_text())
            results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Open Society Foundations — Grants"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            results.append(opp)

        logger.info(f"[open_society] Found {len(results)} opportunities")
        return results
