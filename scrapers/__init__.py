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
    FoundationNorthScraper,
    GenericGrantListingScraper,
)
from scrapers.intl_funders import WellcomeScraper, RWJFScraper, OpenSocietyScraper
from scrapers.gets import GETSScraper

SCRAPER_REGISTRY = {
    "creative_nz": CreativeNZScraper,
    "nz_on_air": NZOnAirScraper,
    "community_matters": CommunityMattersScraper,
    "msd": MSDScraper,
    "tpk": TPKScraper,
    "foundation_north": FoundationNorthScraper,
    "generic_grant_listing": GenericGrantListingScraper,
    "wellcome": WellcomeScraper,
    "rwjf": RWJFScraper,
    "open_society": OpenSocietyScraper,
    "gets": GETSScraper,
}


def get_scraper(scraper_id: str, config: dict) -> BaseScraper:
    """Instantiate a scraper by its ID."""
    cls = SCRAPER_REGISTRY.get(scraper_id)
    if cls is None:
        raise ValueError(f"Unknown scraper: {scraper_id}")
    return cls(config)
