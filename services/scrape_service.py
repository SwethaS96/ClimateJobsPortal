"""Service for running scraper jobs across enabled websites."""

from __future__ import annotations

from dataclasses import dataclass

from parser.registry import ParserRegistry
from scraper.downloader import Downloader
from scraper.engine import ScrapeResult
from scraper.site_config import SiteConfigLoader, WebsiteConfig
from services.notification_service import NotificationService
from scraper.engine import ScraperEngine


@dataclass
class ScrapeSummary:
    """Aggregated outcome of processing all enabled websites."""

    websites_processed: int
    successful: int
    failed: int
    notifications_added: int


def _build_default_scraper_engine() -> ScraperEngine:
    """Build a working `ScraperEngine` with a real downloader and populated registry.

    `ScraperEngine` requires a real `Downloader` and `ParserRegistry` — it
    has no defaults of its own. Passing `None` for either previously slipped
    through unnoticed because `ScraperEngine.scrape()` wraps its first call
    (`self.downloader.download(...)`) in a broad `except Exception`, so a
    `None` downloader failed every single site silently instead of raising.
    """
    parser_registry = ParserRegistry()
    parser_registry.register_builtin_parsers()
    return ScraperEngine(downloader=Downloader(), parser_registry=parser_registry)


class ScrapeService:
    """Process every enabled website and persist any parsed notifications."""

    def __init__(
        self,
        site_config_loader: SiteConfigLoader | None = None,
        scraper_engine: ScraperEngine | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.site_config_loader = site_config_loader or SiteConfigLoader()
        self.scraper_engine = scraper_engine or _build_default_scraper_engine()
        self.notification_service = notification_service or NotificationService()

    def run(self) -> ScrapeSummary:
        """Load enabled websites, scrape each one, and persist notifications."""
        sites = self.site_config_loader.load_enabled_websites()

        successful = 0
        failed = 0
        notifications_added = 0

        for site in sites:
            scrape_result = self.scraper_engine.scrape(site)
            if scrape_result.success:
                successful += 1
            else:
                failed += 1

            persist_result = self.notification_service.persist(scrape_result, site.organization_id)
            notifications_added += persist_result.get("inserted", 0)

        return ScrapeSummary(
            websites_processed=len(sites),
            successful=successful,
            failed=failed,
            notifications_added=notifications_added,
        )
