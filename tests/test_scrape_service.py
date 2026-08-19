"""Tests for the scrape service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

import database.connection as connection_module
from database.schema import create_schema
from parser.generic_html import GenericHTMLParser
from parser.models import ParsedNotification
from scraper.downloader import Downloader, DownloadResult
from scraper.engine import ScrapeResult
from scraper.site_config import WebsiteConfig
from services.notification_service import NotificationService
from services.scrape_service import ScrapeService, ScrapeSummary


def make_site(site_id: int, organization_id: int) -> WebsiteConfig:
    return WebsiteConfig(
        id=site_id,
        organization_id=organization_id,
        page_name="Jobs",
        url=f"https://example.org/{site_id}",
        parser_name="generic_html",
        parser_metadata=None,
        user_agent=None,
        timeout_seconds=10,
        scrape_interval_minutes=60,
    )


def make_result(site: WebsiteConfig, success: bool, notifications: list[ParsedNotification] | None = None) -> ScrapeResult:
    return ScrapeResult(
        website_id=site.id,
        page_name=site.page_name,
        success=success,
        status_code=200 if success else 503,
        notifications=notifications or [],
        error=None if success else "failed",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        duration_seconds=0.1,
    )


def test_run_collects_summary_statistics() -> None:
    site_one = make_site(1, 10)
    site_two = make_site(2, 20)
    sites = [site_one, site_two]

    loader = Mock()
    loader.load_enabled_websites.return_value = sites

    engine = Mock()
    engine.scrape.side_effect = [
        make_result(site_one, True, [ParsedNotification(title="One", url="https://example.org/1")]),
        make_result(site_two, False),
    ]

    notification_service = Mock(spec=NotificationService)
    notification_service.persist.side_effect = [
        {"inserted": 1, "failed": 0},
        {"inserted": 0, "failed": 0},
    ]

    service = ScrapeService(
        site_config_loader=loader,
        scraper_engine=engine,
        notification_service=notification_service,
    )

    summary = service.run()

    assert isinstance(summary, ScrapeSummary)
    assert summary.websites_processed == 2
    assert summary.successful == 1
    assert summary.failed == 1
    assert summary.notifications_added == 1
    assert engine.scrape.call_count == 2
    assert notification_service.persist.call_count == 2


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "climate_jobs.db"
    monkeypatch.setattr(connection_module, "DATABASE_PATH", db_path)

    conn = connection_module.get_connection()
    try:
        create_schema(conn)
        conn.execute(
            """
            INSERT INTO organizations (id, name, short_name, homepage_url, country, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (10, "Test Org", "TST", "https://example.org", "India", "Tamil Nadu",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO websites (id, organization_id, page_name, url, parser_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 10, "Jobs", "https://example.org/1", "generic_html",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    return db_path


def test_default_construction_builds_a_working_scraper_engine() -> None:
    """`ScrapeService()` must build a `ScraperEngine` with real dependencies.

    Regression test: `ScrapeService.__init__` used to construct
    `ScraperEngine(downloader=None, parser_registry=None)`. Nothing raised
    at construction time (Python does not enforce type hints), and
    `ScraperEngine.scrape()` wraps its first call in a broad
    `except Exception`, so the `AttributeError` from a `None` downloader
    was silently swallowed — every website reported as failed forever.
    """
    service = ScrapeService()

    assert isinstance(service.scraper_engine.downloader, Downloader)
    assert service.scraper_engine.parser_registry.get("generic_html") is GenericHTMLParser


def test_default_construction_actually_scrapes_successfully(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end regression check: a default-constructed service must
    succeed, not silently fail every site as it did before the fix."""

    def fake_download(self, site):
        return DownloadResult(
            url=site.url,
            status_code=200,
            headers={},
            content='<a href="/jobs/1">Recruitment Notice for Scientist Posts</a>',
            elapsed_seconds=0.01,
            success=True,
            error=None,
        )

    monkeypatch.setattr(Downloader, "download", fake_download)

    site = make_site(1, 10)
    loader = Mock()
    loader.load_enabled_websites.return_value = [site]

    service = ScrapeService(site_config_loader=loader)
    summary = service.run()

    assert summary.successful == 1
    assert summary.failed == 0
    assert summary.notifications_added == 1
