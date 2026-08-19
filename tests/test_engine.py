"""Unit tests for ScraperEngine."""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from parser.models import ParsedNotification
from parser.registry import ParserRegistry
from scraper.downloader import DownloadResult, Downloader
from scraper.engine import ScrapeResult, ScraperEngine
from scraper.site_config import WebsiteConfig


def make_site(**overrides: object) -> WebsiteConfig:
    defaults = {
        "id": 7,
        "organization_id": 1,
        "page_name": "Jobs",
        "url": "https://example.org/jobs",
        "parser_name": "generic_html",
        "parser_metadata": None,
        "user_agent": None,
        "timeout_seconds": 10,
        "scrape_interval_minutes": 60,
    }
    defaults.update(overrides)
    return WebsiteConfig(**defaults)


def test_successful_scrape() -> None:
    downloader = Mock(spec=Downloader)
    downloader.download.return_value = DownloadResult(
        url="https://example.org/jobs",
        status_code=200,
        headers={"Content-Type": "text/html"},
        content="<a href='/one'>One</a>",
        elapsed_seconds=0.1,
        success=True,
        error=None,
    )

    registry = ParserRegistry()

    class DummyParser:
        def __init__(self) -> None:
            pass

        def parse(self, html: str, page_url: str) -> list[ParsedNotification]:
            return [ParsedNotification(title="One", url=page_url)]

    registry.register("generic_html", DummyParser)
    engine = ScraperEngine(downloader=downloader, parser_registry=registry)

    result = engine.scrape(make_site())

    assert isinstance(result, ScrapeResult)
    assert result.success is True
    assert result.status_code == 200
    assert len(result.notifications) == 1
    assert result.error is None


def test_failed_download() -> None:
    downloader = Mock(spec=Downloader)
    downloader.download.return_value = DownloadResult(
        url="https://example.org/jobs",
        status_code=503,
        headers={},
        content=None,
        elapsed_seconds=0.2,
        success=False,
        error="HTTP 503 Service Unavailable",
    )

    registry = ParserRegistry()
    engine = ScraperEngine(downloader=downloader, parser_registry=registry)

    result = engine.scrape(make_site())

    assert result.success is False
    assert result.status_code == 503
    assert result.notifications == []
    assert result.error == "HTTP 503 Service Unavailable"


def test_parser_not_found() -> None:
    downloader = Mock(spec=Downloader)
    downloader.download.return_value = DownloadResult(
        url="https://example.org/jobs",
        status_code=200,
        headers={},
        content="<html></html>",
        elapsed_seconds=0.1,
        success=True,
        error=None,
    )

    registry = ParserRegistry()
    engine = ScraperEngine(downloader=downloader, parser_registry=registry)

    result = engine.scrape(make_site(parser_name="missing_parser"))

    assert result.success is False
    assert result.error == "Parser 'missing_parser' not found"
    assert result.notifications == []


def test_empty_html() -> None:
    downloader = Mock(spec=Downloader)
    downloader.download.return_value = DownloadResult(
        url="https://example.org/jobs",
        status_code=200,
        headers={},
        content="",
        elapsed_seconds=0.1,
        success=True,
        error=None,
    )

    registry = ParserRegistry()

    class EmptyParser:
        def parse(self, html: str, page_url: str) -> list[ParsedNotification]:
            return []

    registry.register("generic_html", EmptyParser)
    engine = ScraperEngine(downloader=downloader, parser_registry=registry)

    result = engine.scrape(make_site())

    assert result.success is True
    assert result.notifications == []


def test_parser_returns_notifications() -> None:
    downloader = Mock(spec=Downloader)
    downloader.download.return_value = DownloadResult(
        url="https://example.org/jobs",
        status_code=200,
        headers={},
        content="<html>data</html>",
        elapsed_seconds=0.1,
        success=True,
        error=None,
    )

    registry = ParserRegistry()

    class NotificationParser:
        def parse(self, html: str, page_url: str) -> list[ParsedNotification]:
            return [
                ParsedNotification(title="A", url=page_url),
                ParsedNotification(title="B", url=f"{page_url}/2"),
            ]

    registry.register("generic_html", NotificationParser)
    engine = ScraperEngine(downloader=downloader, parser_registry=registry)

    result = engine.scrape(make_site())

    assert result.success is True
    assert len(result.notifications) == 2
    assert [notification.title for notification in result.notifications] == ["A", "B"]


def test_duration_seconds_is_non_negative() -> None:
    downloader = Mock(spec=Downloader)
    downloader.download.return_value = DownloadResult(
        url="https://example.org/jobs",
        status_code=200,
        headers={},
        content="<html></html>",
        elapsed_seconds=0.1,
        success=True,
        error=None,
    )

    registry = ParserRegistry()

    class DummyParser:
        def parse(self, html: str, page_url: str) -> list[ParsedNotification]:
            return []

    registry.register("generic_html", DummyParser)
    engine = ScraperEngine(downloader=downloader, parser_registry=registry)

    result = engine.scrape(make_site())

    assert result.duration_seconds >= 0
    assert isinstance(result.started_at, datetime)
    assert isinstance(result.completed_at, datetime)
