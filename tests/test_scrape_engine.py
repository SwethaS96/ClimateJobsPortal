from __future__ import annotations

from unittest.mock import Mock

from parser.models import ParsedNotification
from parser.registry import ParserRegistry
from scraper.downloader import DownloadResult, Downloader
from scraper.engine import ScrapeEngine, ScrapeSummary
from scraper.site_config import SiteConfigLoader, WebsiteConfig


class DummyParser:
    def parse(self, html: str, page_url: str) -> list[ParsedNotification]:
        return [ParsedNotification(title="One", url=page_url)]


def make_site(site_id: int, page_name: str, parser_name: str = "generic_html") -> WebsiteConfig:
    return WebsiteConfig(
        id=site_id,
        organization_id=1,
        page_name=page_name,
        url=f"https://example.org/{page_name.lower()}",
        parser_name=parser_name,
        parser_metadata=None,
        user_agent=None,
        timeout_seconds=10,
        scrape_interval_minutes=60,
    )


def test_scrape_engine_runs_all_sites_and_returns_summary(capsys) -> None:
    loader = Mock(spec=SiteConfigLoader)
    loader.load_enabled_websites.return_value = [
        make_site(1, "Jobs"),
        make_site(2, "Careers"),
    ]

    downloader = Mock(spec=Downloader)
    downloader.download.side_effect = [
        DownloadResult(
            url="https://example.org/jobs",
            status_code=200,
            headers={"Content-Type": "text/html"},
            content="<html></html>",
            elapsed_seconds=0.1,
            success=True,
            error=None,
        ),
        DownloadResult(
            url="https://example.org/careers",
            status_code=503,
            headers={},
            content=None,
            elapsed_seconds=0.1,
            success=False,
            error="HTTP 503 Service Unavailable",
        ),
    ]

    registry = ParserRegistry()
    registry.register("generic_html", DummyParser)

    engine = ScrapeEngine(site_config_loader=loader, downloader=downloader, parser_registry=registry)
    summary = engine.run()

    assert isinstance(summary, ScrapeSummary)
    assert summary.total_websites == 2
    assert summary.successful == 1
    assert summary.failed == 1
    assert summary.notifications_found == 1
    assert summary.duration_seconds >= 0

    output = capsys.readouterr().out
    assert "Organization" in output
    assert "Website" in output
    assert "Parser used" in output
    assert "Notifications found" in output

    downloader.close.assert_called_once()
