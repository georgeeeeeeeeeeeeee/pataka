"""
Scraper package for the Opportunity Intelligence Agent.
"""
from scrapers.base import BaseScraper
from scrapers.nz_funders import (
    CreativeNZScraper,
    NZOnAirScraper,
    CommunityMattersScraper,
    MSDScraper,
    TPKScraper,
    GenericGrantListingScraper,
)
from scrapers.intl_funders import WellcomeScraper, RWJFScraper, OpenSocietyScraper
from scrapers.wellington_funders import (
    WCCCommunityScraper,
    GWRCScraper,
    WellingtonCommunityTrustScraper,
    NikauFoundationScraper,
    HuttCityScraper,
    UpperHuttScraper,
    LionFoundationScraper,
    FourWindsFoundationScraper,
    MangaiPahoScraper,
    PacificTrustAotearoaScraper,
)

SCRAPER_REGISTRY = {
    # National NZ funders
    "creative_nz": CreativeNZScraper,
    "nz_on_air": NZOnAirScraper,
    "community_matters": CommunityMattersScraper,
    "msd": MSDScraper,
    "tpk": TPKScraper,
    "generic_grant_listing": GenericGrantListingScraper,
    # Wellington regional funders
    "wcc": WCCCommunityScraper,
    "gwrc": GWRCScraper,
    "wct": WellingtonCommunityTrustScraper,
    "nikau": NikauFoundationScraper,
    "hutt_city": HuttCityScraper,
    "upper_hutt": UpperHuttScraper,
    "lion": LionFoundationScraper,
    "four_winds": FourWindsFoundationScraper,
    "mangai_paho": MangaiPahoScraper,
    "pacific_trust": PacificTrustAotearoaScraper,
    # International funders
    "wellcome": WellcomeScraper,
    "rwjf": RWJFScraper,
    "open_society": OpenSocietyScraper,
}


def get_scraper(scraper_id: str, config: dict) -> BaseScraper:
    """Instantiate a scraper by its ID."""
    cls = SCRAPER_REGISTRY.get(scraper_id)
    if cls is None:
        raise ValueError(f"Unknown scraper: {scraper_id}")
    return cls(config)
