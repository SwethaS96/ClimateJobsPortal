"""Scraper engine for scraping websites and returning parsed results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from parser.base_parser import BaseParser
from parser.exceptions import ParserNotFoundError, ParserRegistrationError
from parser.generic_html import GenericHTMLParser
from parser.models import ParsedNotification
from parser.registry import ParserRegistry
from scraper.downloader import Downloader, DownloadResult
from scraper.site_config import SiteConfigLoader, WebsiteConfig


@dataclass
class ScrapeResult:
    """Result of scraping a single website."""

    website_id: int
    page_name: str
    success: bool
    status_code: int | None
    notifications: list[ParsedNotification]
    error: str | None
    started_at: datetime
    completed_at: datetime
    duration_seconds: float


@dataclass
class ScrapeSummary:
    """Aggregated outcome of processing all enabled websites."""

    total_websites: int
    successful: int
    failed: int
    notifications_found: int
    duration_seconds: float


class ScraperEngine:
    """Scrape a single website using a downloader and parser registry."""

    def __init__(self, downloader: Downloader, parser_registry: ParserRegistry) -> None:
        self.downloader = downloader
        self.parser_registry = parser_registry

    def scrape(self, site: WebsiteConfig) -> ScrapeResult:
        """Scrape one website and return structured execution details."""
        started_at = datetime.now(timezone.utc)

        try:
            download_result: DownloadResult = self.downloader.download(site)
        except Exception as exc:  # pragma: no cover - defensive fallback
            completed_at = datetime.now(timezone.utc)
            duration_seconds = (completed_at - started_at).total_seconds()
            return ScrapeResult(
                website_id=site.id,
                page_name=site.page_name,
                success=False,
                status_code=None,
                notifications=[],
                error=str(exc),
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
            )

        if not download_result.success:
            completed_at = datetime.now(timezone.utc)
            duration_seconds = (completed_at - started_at).total_seconds()
            return ScrapeResult(
                website_id=site.id,
                page_name=site.page_name,
                success=False,
                status_code=download_result.status_code,
                notifications=[],
                error=download_result.error,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
            )

        try:
            parser_class = self.parser_registry.get(site.parser_name)
        except ParserNotFoundError:
            completed_at = datetime.now(timezone.utc)
            duration_seconds = (completed_at - started_at).total_seconds()
            return ScrapeResult(
                website_id=site.id,
                page_name=site.page_name,
                success=False,
                status_code=download_result.status_code,
                notifications=[],
                error=f"Parser '{site.parser_name}' not found",
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
            )

        try:
            parser: BaseParser = parser_class()
            notifications = parser.parse(download_result.content or "", site.url)
        except Exception as exc:  # pragma: no cover - defensive fallback
            completed_at = datetime.now(timezone.utc)
            duration_seconds = (completed_at - started_at).total_seconds()
            return ScrapeResult(
                website_id=site.id,
                page_name=site.page_name,
                success=False,
                status_code=download_result.status_code,
                notifications=[],
                error=str(exc),
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
            )

        completed_at = datetime.now(timezone.utc)
        duration_seconds = (completed_at - started_at).total_seconds()
        return ScrapeResult(
            website_id=site.id,
            page_name=site.page_name,
            success=True,
            status_code=download_result.status_code,
            notifications=notifications,
            error=None,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
        )


class ScrapeEngine:
    """Scrape every enabled website using a downloader and parser registry."""

    def __init__(
        self,
        downloader: Downloader | None = None,
        parser_registry: ParserRegistry | None = None,
        site_config_loader: SiteConfigLoader | None = None,
    ) -> None:
        self.downloader = downloader or Downloader()
        self.parser_registry = parser_registry or ParserRegistry()
        self.site_config_loader = site_config_loader or SiteConfigLoader()
        self._single_site_engine = ScraperEngine(
            downloader=self.downloader,
            parser_registry=self.parser_registry,
        )
        self._register_default_parsers()

    def _register_default_parsers(self) -> None:
        try:
            self.parser_registry.register("generic_html", GenericHTMLParser)
        except ParserRegistrationError:
            pass

    def scrape(self, site: WebsiteConfig) -> ScrapeResult:
        """Scrape a single website using the shared downloader and parser registry."""
        return self._single_site_engine.scrape(site)

    def run(self) -> ScrapeSummary:
        """Load enabled websites, scrape each one, print a simple report, and return a summary."""
        started_at = datetime.now(timezone.utc)
        sites = self.site_config_loader.load_enabled_websites()

        successful = 0
        failed = 0
        notifications_found = 0

        try:
            for site in sites:
                result = self.scrape(site)
                if result.success:
                    successful += 1
                    notifications_found += len(result.notifications)
                else:
                    failed += 1

                print(f"Organization: {site.organization_id}")
                print(f"Website: {site.page_name}")
                print(f"Parser used: {site.parser_name}")
                print(f"Notifications found: {len(result.notifications)}")
                print(f"Download time: {result.duration_seconds:.3f}s")
                print("-" * 20)
        finally:
            self.downloader.close()

        completed_at = datetime.now(timezone.utc)
        duration_seconds = (completed_at - started_at).total_seconds()
        return ScrapeSummary(
            total_websites=len(sites),
            successful=successful,
            failed=failed,
            notifications_found=notifications_found,
            duration_seconds=duration_seconds,
        )

    def scrape(self, site: WebsiteConfig) -> ScrapeResult:
        """Scrape one website and return structured execution details.

        The engine is intentionally limited to one website and does not handle
        persistence, deduplication, scheduling, or downstream actions.
        """
        started_at = datetime.now(timezone.utc)

        try:
            download_result: DownloadResult = self.downloader.download(site)
        except Exception as exc:  # pragma: no cover - defensive fallback
            completed_at = datetime.now(timezone.utc)
            duration_seconds = (completed_at - started_at).total_seconds()
            return ScrapeResult(
                website_id=site.id,
                page_name=site.page_name,
                success=False,
                status_code=None,
                notifications=[],
                error=str(exc),
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
            )

        if not download_result.success:
            completed_at = datetime.now(timezone.utc)
            duration_seconds = (completed_at - started_at).total_seconds()
            return ScrapeResult(
                website_id=site.id,
                page_name=site.page_name,
                success=False,
                status_code=download_result.status_code,
                notifications=[],
                error=download_result.error,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
            )

        try:
            parser_class = self.parser_registry.get(site.parser_name)
        except ParserNotFoundError:
            completed_at = datetime.now(timezone.utc)
            duration_seconds = (completed_at - started_at).total_seconds()
            return ScrapeResult(
                website_id=site.id,
                page_name=site.page_name,
                success=False,
                status_code=download_result.status_code,
                notifications=[],
                error=f"Parser '{site.parser_name}' not found",
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
            )

        try:
            parser: BaseParser = parser_class()
            notifications = parser.parse(download_result.content or "", site.url)
        except Exception as exc:  # pragma: no cover - defensive fallback
            completed_at = datetime.now(timezone.utc)
            duration_seconds = (completed_at - started_at).total_seconds()
            return ScrapeResult(
                website_id=site.id,
                page_name=site.page_name,
                success=False,
                status_code=download_result.status_code,
                notifications=[],
                error=str(exc),
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
            )

        completed_at = datetime.now(timezone.utc)
        duration_seconds = (completed_at - started_at).total_seconds()
        return ScrapeResult(
            website_id=site.id,
            page_name=site.page_name,
            success=True,
            status_code=download_result.status_code,
            notifications=notifications,
            error=None,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
        )
