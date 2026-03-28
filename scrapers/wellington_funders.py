"""
Wellington-specific community grants scrapers.

Covers the key funders relevant to Wellington-region community organisations:
- Wellington City Council (community grants + Creative Communities Scheme)
- Greater Wellington Regional Council
- Wellington Community Trust
- Hutt City Council
- Upper Hutt City Council
- Lion Foundation
- Four Winds Foundation
- Māngai Pāho
- Pacific Trust Aotearoa
- Nikau Foundation (Wellington-based philanthropic funder)

These scrapers are intentionally regional. National funders (Creative NZ,
Community Matters/Lottery, MSD, TPK) are handled in nz_funders.py.
"""
import logging
import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedOpportunity

logger = logging.getLogger(__name__)


class WCCCommunityScraper(BaseScraper):
    """
    Wellington City Council — community grants and funding.
    wellington.govt.nz/community-and-safety/community-support/grants-and-funding

    Covers:
    - Community Grant Fund (contestable, twice yearly)
    - Creative Communities Scheme (locally administered by WCC)
    - Neighbourhood Fund
    - Events Fund
    """

    GRANTS_URL = (
        "https://wellington.govt.nz/community-support-and-resources/community-support/funding"
    )

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            logger.warning("[wcc] Could not fetch WCC grants page")
            return results

        soup = self.parse(html)

        # WCC uses accordion/card layout for individual grant programmes
        cards = (
            soup.select(".accordion-item")
            or soup.select(".grant-item")
            or soup.select(".funding-item")
            or soup.select("article")
            or soup.select(".card")
        )

        for card in cards[:25]:
            opp = self._parse_card(card)
            if opp:
                results.append(opp)

        # Strategy 2: heading + sibling description pattern
        if not results:
            for heading in soup.find_all(["h2", "h3", "h4"]):
                title = self.clean_text(heading.get_text())
                if len(title) < 5:
                    continue
                link = (
                    heading.find("a", href=True)
                    or heading.find_next_sibling("a", href=True)
                    or heading.find_parent("a", href=True)
                )
                if not link:
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
                    opp.description = self.clean_text(sibling.get_text(" "))[:800]
                results.append(opp)

        # Fallback: full page for AI extraction
        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Wellington City Council — Grants and Funding"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        logger.info(f"[wcc] Found {len(results)} opportunities")
        return results

    def _parse_card(self, card) -> Optional[ScrapedOpportunity]:
        link = card.find("a", href=True)
        if not link:
            return None
        title = self.clean_text(link.get_text())
        if not title or len(title) < 5:
            return None
        url = self.make_absolute(link["href"])
        if not url:
            return None

        opp = ScrapedOpportunity()
        opp.source_id = self.source_id
        opp.funder_name = self.funder_name
        opp.grant_name = title[:400]
        opp.url = url
        text = self.clean_text(card.get_text(" "))
        opp.description = text[:800]

        # Amount
        m = re.search(r"(\$[\d,]+(?:\s*[–\-]\s*\$[\d,]+)?|\bup to \$[\d,]+)", text, re.I)
        if m:
            opp.amount_text = m.group(0)
            opp.amount_min, opp.amount_max = self.parse_amount(opp.amount_text)

        # Deadline
        d = re.search(
            r"(?:closes?|deadline|applications?\s+close|open until)[:\s]+([^\n.]{5,40})",
            text, re.I
        )
        if d:
            opp.deadline_text = d.group(1).strip()
            opp.deadline = self.parse_date(opp.deadline_text)

        return opp


class GWRCScraper(BaseScraper):
    """
    Greater Wellington Regional Council — environment and community grants.
    gw.govt.nz/grants-and-funding

    Covers environmental, heritage, and community wellbeing grants
    across the Wellington region (including Hutt Valley, Kāpiti, Wairarapa).
    """

    GRANTS_URL = "https://www.gw.govt.nz/your-region/funding-and-awards/"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            logger.warning("[gwrc] Could not fetch GWRC grants page")
            return results

        soup = self.parse(html)

        # GWRC typically lists grants as cards or sections
        cards = (
            soup.select(".grant-item")
            or soup.select(".funding-programme")
            or soup.select(".card")
            or soup.select("article")
        )

        for card in cards[:20]:
            link = card.find("a", href=True)
            if not link:
                continue
            title = self.clean_text(link.get_text())
            if not title or len(title) < 5:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title[:400]
            opp.url = self.make_absolute(link["href"])
            opp.description = self.clean_text(card.get_text(" "))[:800]
            results.append(opp)

        # Fallback: heading links
        if not results:
            for heading in soup.find_all(["h2", "h3"]):
                link = heading.find("a") or heading.find_next_sibling("a")
                if not link:
                    continue
                title = self.clean_text(heading.get_text())
                if len(title) < 5:
                    continue
                url = self.make_absolute(link.get("href", ""))
                if not url:
                    continue
                opp = ScrapedOpportunity()
                opp.source_id = self.source_id
                opp.funder_name = self.funder_name
                opp.grant_name = title[:400]
                opp.url = url
                results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Greater Wellington Regional Council — Grants"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        logger.info(f"[gwrc] Found {len(results)} opportunities")
        return results


class WellingtonCommunityTrustScraper(BaseScraper):
    """
    Wellington Community Trust — wct.org.nz/grants
    One of the most significant philanthropic grant-makers in the Wellington region.
    Covers community wellbeing, arts, sport, environment, and social services.
    Dedicated scraper given regional importance.
    """

    GRANTS_URL = "https://wellingtoncommunityfund.org.nz/funding/"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            logger.warning("[wct] Could not fetch Wellington Community Trust page")
            return results

        soup = self.parse(html)

        # WCT typically uses card or section layout per grant category
        cards = (
            soup.select(".grant-type")
            or soup.select(".funding-category")
            or soup.select(".card")
            or soup.select("article")
            or soup.select(".programme")
        )

        for card in cards[:20]:
            link = card.find("a", href=True)
            if not link:
                continue
            title = self.clean_text(link.get_text())
            if not title or len(title) < 5:
                continue

            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title[:400]
            opp.url = self.make_absolute(link["href"])
            text = self.clean_text(card.get_text(" "))
            opp.description = text[:800]

            m = re.search(r"(\$[\d,]+(?:\s*[–\-]\s*\$[\d,]+)?|\bup to \$[\d,]+)", text, re.I)
            if m:
                opp.amount_text = m.group(0)
                opp.amount_min, opp.amount_max = self.parse_amount(opp.amount_text)

            d = re.search(
                r"(?:closes?|deadline|applications?\s+close)[:\s]+([^\n.]{5,40})",
                text, re.I
            )
            if d:
                opp.deadline_text = d.group(1).strip()
                opp.deadline = self.parse_date(opp.deadline_text)

            results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Wellington Community Trust — Grants"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        logger.info(f"[wct] Found {len(results)} opportunities")
        return results


class HuttCityScraper(BaseScraper):
    """
    Hutt City Council — community grants.
    huttcity.govt.nz/services/community-grants

    Covers contestable community grants for Lower Hutt organisations.
    """

    GRANTS_URL = "https://www.huttcity.govt.nz/services/community-grants"

    def scrape(self) -> list[ScrapedOpportunity]:
        return self._generic_council_scrape(
            self.GRANTS_URL, "[hutt_city]", "Hutt City Council — Community Grants"
        )

    def _generic_council_scrape(
        self, url: str, log_prefix: str, fallback_name: str
    ) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(url)
        if not html:
            logger.warning(f"{log_prefix} Could not fetch page")
            return results

        soup = self.parse(html)

        for heading in soup.find_all(["h2", "h3", "h4"]):
            title = self.clean_text(heading.get_text())
            if len(title) < 5:
                continue
            link = (
                heading.find("a", href=True)
                or heading.find_next_sibling("a", href=True)
                or heading.find_parent("a", href=True)
            )
            if not link:
                continue
            grant_url = self.make_absolute(link["href"])
            if not grant_url:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title[:400]
            opp.url = grant_url
            sibling = heading.find_next_sibling(["p", "div"])
            if sibling:
                opp.description = self.clean_text(sibling.get_text(" "))[:600]
            results.append(opp)

        if not results:
            for card in (soup.select(".card") or soup.select("article") or []):
                link = card.find("a", href=True)
                if not link:
                    continue
                title = self.clean_text(link.get_text())
                if len(title) < 5:
                    continue
                opp = ScrapedOpportunity()
                opp.source_id = self.source_id
                opp.funder_name = self.funder_name
                opp.grant_name = title[:400]
                opp.url = self.make_absolute(link["href"])
                opp.description = self.clean_text(card.get_text(" "))[:600]
                results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = fallback_name
            opp.url = url
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        seen = set()
        unique = []
        for o in results[:20]:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"{log_prefix} Found {len(unique)} opportunities")
        return unique


class UpperHuttScraper(HuttCityScraper):
    """
    Upper Hutt City Council — community grants.
    upperhutt.govt.nz/community/grants-and-funding
    """

    GRANTS_URL = "https://www.upperhutt.govt.nz/community/Grants-and-funding"

    def scrape(self) -> list[ScrapedOpportunity]:
        return self._generic_council_scrape(
            self.GRANTS_URL, "[upper_hutt]", "Upper Hutt City Council — Grants and Funding"
        )


class NikauFoundationScraper(BaseScraper):
    """
    Nikau Foundation — nikaufoundation.org.nz
    Wellington's community foundation. Administers both open grants
    and donor-advised funds for community wellbeing across the region.
    Particularly strong in health, social services, arts, and environment.
    """

    GRANTS_URL = "https://www.nikaufoundation.nz/funding-hub"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            logger.warning("[nikau] Could not fetch Nikau Foundation page")
            return results

        soup = self.parse(html)

        # Nikau Foundation typically lists grant streams as sections or cards
        cards = (
            soup.select(".grant-stream")
            or soup.select(".funding-area")
            or soup.select(".card")
            or soup.select("article")
            or soup.select(".programme")
        )

        for card in cards[:20]:
            link = card.find("a", href=True)
            if not link:
                continue
            title = self.clean_text(link.get_text())
            if not title or len(title) < 5:
                continue

            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title[:400]
            opp.url = self.make_absolute(link["href"])
            text = self.clean_text(card.get_text(" "))
            opp.description = text[:800]

            m = re.search(r"(\$[\d,]+(?:\s*[–\-]\s*\$[\d,]+)?|\bup to \$[\d,]+)", text, re.I)
            if m:
                opp.amount_text = m.group(0)
                opp.amount_min, opp.amount_max = self.parse_amount(opp.amount_text)

            results.append(opp)

        # Fallback: heading-based extraction
        if not results:
            for heading in soup.find_all(["h2", "h3"]):
                title = self.clean_text(heading.get_text())
                if len(title) < 5:
                    continue
                link = heading.find("a") or heading.find_next_sibling("a")
                if not link:
                    continue
                url = self.make_absolute(link.get("href", ""))
                if not url:
                    continue
                opp = ScrapedOpportunity()
                opp.source_id = self.source_id
                opp.funder_name = self.funder_name
                opp.grant_name = title[:400]
                opp.url = url
                results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Nikau Foundation — Community Grants"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        logger.info(f"[nikau] Found {len(results)} opportunities")
        return results


class LionFoundationScraper(BaseScraper):
    """
    Lion Foundation — lionfoundation.org.nz
    National funder but one of the most actively accessed by Wellington
    community orgs. Covers sport, recreation, community, and arts.
    Monthly grant rounds — high frequency, high relevance.
    """

    GRANTS_URL = "https://www.lionfoundation.org.nz/grants/apply"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            logger.warning("[lion] Could not fetch Lion Foundation page")
            return results

        soup = self.parse(html)

        # Lion Foundation has category-based grant types
        cards = (
            soup.select(".grant-category")
            or soup.select(".funding-type")
            or soup.select(".card")
            or soup.select("article")
        )

        for card in cards[:20]:
            link = card.find("a", href=True)
            if not link:
                continue
            title = self.clean_text(link.get_text())
            if not title or len(title) < 5:
                continue

            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title[:400]
            opp.url = self.make_absolute(link["href"])
            text = self.clean_text(card.get_text(" "))
            opp.description = text[:800]

            m = re.search(r"(\$[\d,]+(?:\s*[–\-]\s*\$[\d,]+)?|\bup to \$[\d,]+)", text, re.I)
            if m:
                opp.amount_text = m.group(0)
                opp.amount_min, opp.amount_max = self.parse_amount(opp.amount_text)

            results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Lion Foundation — Community Grants"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        logger.info(f"[lion] Found {len(results)} opportunities")
        return results


class FourWindsFoundationScraper(BaseScraper):
    """
    Four Winds Foundation — fourwindsfoundation.org.nz
    Wellington-based funder focused on community wellbeing, youth,
    families, and social services. Smaller but highly Wellington-relevant.
    """

    GRANTS_URL = "https://www.fourwindsfoundation.org.nz/apply"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            logger.warning("[four_winds] Could not fetch Four Winds Foundation page")
            return results

        soup = self.parse(html)

        for heading in soup.find_all(["h2", "h3", "h4"]):
            title = self.clean_text(heading.get_text())
            if len(title) < 5:
                continue
            link = (
                heading.find("a", href=True)
                or heading.find_next_sibling("a", href=True)
                or heading.find_parent("a", href=True)
            )
            if not link:
                continue
            url = self.make_absolute(link["href"])
            if not url:
                continue
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title[:400]
            opp.url = url
            sibling = heading.find_next_sibling(["p", "div"])
            if sibling:
                opp.description = self.clean_text(sibling.get_text(" "))[:600]
            results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Four Winds Foundation — Grants"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        logger.info(f"[four_winds] Found {len(results)} opportunities")
        return results


class MangaiPahoScraper(BaseScraper):
    """
    Māngai Pāho — mangaipaho.govt.nz
    Te reo Māori broadcasting and community media funding.
    Relevant for Wellington community orgs with Māori kaupapa,
    reo revitalisation programmes, or community media projects.
    """

    GRANTS_URL = "https://www.mangaipaho.govt.nz/funding"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []
        html = self.fetch(self.GRANTS_URL)
        if not html:
            logger.warning("[mangai_paho] Could not fetch Māngai Pāho page")
            return results

        soup = self.parse(html)

        cards = (
            soup.select(".funding-stream")
            or soup.select(".grant-item")
            or soup.select(".card")
            or soup.select("article")
        )

        for card in cards[:15]:
            link = card.find("a", href=True)
            if not link:
                continue
            title = self.clean_text(link.get_text())
            if not title or len(title) < 5:
                continue

            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = title[:400]
            opp.url = self.make_absolute(link["href"])
            opp.description = self.clean_text(card.get_text(" "))[:800]
            results.append(opp)

        if not results:
            opp = ScrapedOpportunity()
            opp.source_id = self.source_id
            opp.funder_name = self.funder_name
            opp.grant_name = "Māngai Pāho — Funding"
            opp.url = self.GRANTS_URL
            opp.description = self.clean_text(soup.get_text(" "))[:3000]
            opp.raw_html = html[:10000]
            results.append(opp)

        logger.info(f"[mangai_paho] Found {len(results)} opportunities")
        return results


class PacificTrustAotearoaScraper(BaseScraper):
    """
    Pacific Trust Aotearoa / Pasifika community funders.
    Covers Wellington's Pacific communities — one of the largest
    Pacific populations in Aotearoa outside Auckland.

    Primary source: Pacific Trust Aotearoa (pacifictrust.org.nz)
    Also checks: Ministry for Pacific Peoples contestable funding
    """

    GRANTS_URL = "https://www.pacifictrust.org.nz/grants"
    MPP_URL = "https://www.mpp.govt.nz/funding"

    def scrape(self) -> list[ScrapedOpportunity]:
        results = []

        for url, label in [(self.GRANTS_URL, "Pacific Trust"), (self.MPP_URL, "Ministry for Pacific Peoples")]:
            html = self.fetch(url)
            if not html:
                continue
            soup = self.parse(html)

            cards = (
                soup.select(".grant-item")
                or soup.select(".funding-stream")
                or soup.select(".card")
                or soup.select("article")
            )

            found = False
            for card in cards[:15]:
                link = card.find("a", href=True)
                if not link:
                    continue
                title = self.clean_text(link.get_text())
                if not title or len(title) < 5:
                    continue

                opp = ScrapedOpportunity()
                opp.source_id = self.source_id
                opp.funder_name = label
                opp.grant_name = title[:400]
                opp.url = self.make_absolute(link["href"])
                opp.description = self.clean_text(card.get_text(" "))[:800]
                results.append(opp)
                found = True

            if not found:
                opp = ScrapedOpportunity()
                opp.source_id = self.source_id
                opp.funder_name = label
                opp.grant_name = f"{label} — Funding"
                opp.url = url
                opp.description = self.clean_text(soup.get_text(" "))[:3000]
                opp.raw_html = html[:10000]
                results.append(opp)

        seen = set()
        unique = []
        for o in results:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"[pacific_trust] Found {len(unique)} opportunities")
        return unique


# ─── Funder config registry ───────────────────────────────────────────────────
# These configs are passed to each scraper's __init__ via funder_config.
# Add new Wellington funders here and register them in config.py / run.py.

WELLINGTON_FUNDERS = [
    {
        "id": "wcc",
        "name": "Wellington City Council",
        "url": "https://wellington.govt.nz/community-support-and-resources/community-support/funding",
        "scraper_class": "WCCCommunityScraper",
        "region": "wellington",
        "type": "local_council",
    },
    {
        "id": "gwrc",
        "name": "Greater Wellington Regional Council",
        "url": "https://www.gw.govt.nz/your-region/funding-and-awards/",
        "scraper_class": "GWRCScraper",
        "region": "wellington_region",
        "type": "regional_council",
    },
    {
        "id": "wct",
        "name": "Wellington Community Trust",
        "url": "https://wellingtoncommunityfund.org.nz/funding/",
        "scraper_class": "WellingtonCommunityTrustScraper",
        "region": "wellington",
        "type": "philanthropic_trust",
    },
    {
        "id": "nikau",
        "name": "Nikau Foundation",
        "url": "https://www.nikaufoundation.nz/funding-hub",
        "scraper_class": "NikauFoundationScraper",
        "region": "wellington",
        "type": "community_foundation",
    },
    {
        "id": "hutt_city",
        "name": "Hutt City Council",
        "url": "https://www.huttcity.govt.nz/services/community-grants",
        "scraper_class": "HuttCityScraper",
        "region": "lower_hutt",
        "type": "local_council",
    },
    {
        "id": "upper_hutt",
        "name": "Upper Hutt City Council",
        "url": "https://www.upperhutt.govt.nz/community/Grants-and-funding",
        "scraper_class": "UpperHuttScraper",
        "region": "upper_hutt",
        "type": "local_council",
    },
    {
        "id": "lion",
        "name": "Lion Foundation",
        "url": "https://www.lionfoundation.org.nz/grants/apply",
        "scraper_class": "LionFoundationScraper",
        "region": "national",
        "type": "gaming_trust",
        "note": "National funder, monthly rounds — high access frequency for Wellington orgs",
    },
    {
        "id": "four_winds",
        "name": "Four Winds Foundation",
        "url": "https://www.fourwindsfoundation.org.nz/apply",
        "scraper_class": "FourWindsFoundationScraper",
        "region": "wellington",
        "type": "philanthropic_trust",
    },
    {
        "id": "mangai_paho",
        "name": "Māngai Pāho",
        "url": "https://www.mangaipaho.govt.nz/funding",
        "scraper_class": "MangaiPahoScraper",
        "region": "national",
        "type": "crown_entity",
        "note": "Te reo Māori and community media funding — relevant for kaupapa Māori orgs",
    },
    {
        "id": "pacific_trust",
        "name": "Pacific Trust Aotearoa",
        "url": "https://www.pacifictrust.org.nz/grants",
        "scraper_class": "PacificTrustAotearoaScraper",
        "region": "wellington",
        "type": "community_trust",
        "note": "Also scrapes Ministry for Pacific Peoples contestable funding",
    },
]
