"""
Configuration management for the Opportunity Intelligence Agent.
"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from the project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    FLASK_ENV = os.environ.get("FLASK_ENV", "production")
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

    # Database — use absolute path so SQLite can find it from any working directory
    _default_db = f"sqlite:///{BASE_DIR / 'data' / 'opportunity_agent.db'}"
    DATABASE_URL = os.environ.get("DATABASE_URL", _default_db)
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Anthropic
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")

    # App
    PORT = int(os.environ.get("PORT", 5000))
    BASE_DIR = BASE_DIR
    DATA_DIR = BASE_DIR / "data"
    APPLICATIONS_DIR = BASE_DIR / "applications"
    PROFILE_PATH = BASE_DIR / "profile.json"

    # Scraping
    REQUEST_TIMEOUT = 30
    REQUEST_DELAY = 2  # seconds between requests per domain
    USER_AGENT = (
        "Mozilla/5.0 (compatible; OpportunityAgent/1.0; "
        "+https://github.com/gjohnston/opportunity-agent)"
    )

    # Scoring
    HIGH_VALUE_THRESHOLD = 50000  # flag tenders > $50k

    @classmethod
    def ensure_dirs(cls):
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load_profile(cls) -> dict:
        with open(cls.PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def save_profile(cls, profile: dict):
        with open(cls.PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)


# Funder sources configuration
FUNDER_SOURCES = [
    # NZ Funders
    {
        "id": "creative_nz",
        "name": "Creative New Zealand",
        "url": "https://www.creativenz.govt.nz/funding-and-support",
        "scraper": "creative_nz",
        "category": "arts_culture",
        "country": "NZ",
        "enabled": True,
    },
    {
        "id": "nz_on_air",
        "name": "NZ On Air",
        "url": "https://www.nzonair.govt.nz/funding/music-funding/",
        "scraper": "nz_on_air",
        "category": "arts_culture",
        "country": "NZ",
        "enabled": True,
    },
    {
        "id": "community_matters",
        "name": "Community Matters (Lottery Grants Board)",
        "url": "https://www.communitymatters.govt.nz/lottery-grants-board/",
        "scraper": "community_matters",
        "category": "community",
        "country": "NZ",
        "enabled": True,
    },
    {
        "id": "msd",
        "name": "Ministry of Social Development",
        "url": "https://www.msd.govt.nz/what-we-can-do/providers/index.html",
        "scraper": "msd",
        "category": "social_health",
        "country": "NZ",
        "enabled": True,
    },
    {
        "id": "tpk",
        "name": "Te Puni Kokiri",
        "url": "https://www.tpk.govt.nz/en/nga-putea-me-nga-ratonga",
        "scraper": "tpk",
        "category": "maori_development",
        "country": "NZ",
        "enabled": True,
    },
    {
        "id": "foundation_north",
        "name": "Foundation North",
        "url": "https://www.foundationnorth.org.nz/funding/",
        "scraper": "foundation_north",
        "category": "community",
        "country": "NZ",
        "enabled": True,
    },
    {
        "id": "wct",
        "name": "Wellington Community Trust",
        "url": "https://wellingtoncommunityfund.org.nz/funding/",
        "scraper": "generic_grant_listing",
        "category": "community",
        "country": "NZ",
        "enabled": True,
    },
    {
        "id": "tindall",
        "name": "Tindall Foundation",
        "url": "https://tindall.org.nz/how-we-give/",
        "scraper": "generic_grant_listing",
        "category": "community",
        "country": "NZ",
        "enabled": True,
    },
    {
        "id": "todd",
        "name": "Todd Foundation",
        "url": "https://www.toddfoundation.org.nz/funding/",
        "scraper": "generic_grant_listing",
        "category": "community",
        "country": "NZ",
        "enabled": True,
    },
    # International Funders
    {
        "id": "wellcome",
        "name": "Wellcome Trust",
        "url": "https://wellcome.org/grant-funding/schemes",
        "scraper": "wellcome",
        "category": "health_research",
        "country": "UK",
        "enabled": True,
    },
    {
        "id": "open_society",
        "name": "Open Society Foundations",
        "url": "https://www.opensocietyfoundations.org/grants",
        "scraper": "open_society",
        "category": "social_justice",
        "country": "International",
        "enabled": True,
    },
    {
        "id": "rwjf",
        "name": "Robert Wood Johnson Foundation",
        "url": "https://www.rwjf.org/en/grants/active-funding-opportunities.html",
        "scraper": "rwjf",
        "category": "health",
        "country": "US",
        "enabled": True,
    },
]

# GETS (Government tenders) configuration
GETS_CONFIG = {
    "base_url": "https://www.gets.govt.nz",
    "search_url": "https://www.gets.govt.nz/Contracts/",
    "categories": [
        "health", "mental health", "counselling", "education", "youth",
        "community services", "Maori development", "social services",
        "research and evaluation"
    ],
    "enabled": True,
}
