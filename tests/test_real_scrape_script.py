"""Tests for scripts/test_real_scrape.py using mocked collaborators.

No real network or database access happens here — Downloader, the parser,
and NotificationService are all mocked, per the "controlled scrape" design.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from parser.generic_html import GenericHTMLParser
from parser.models import ParsedNotification
from scraper.engine import ScrapeResult
from scraper.site_config import WebsiteConfig
from services.notification_service import NotificationService
from services.notification_validator import NotificationValidator

import scripts.test_real_scrape as runner


def make_site(site_id: int = 1, organization_id: int = 10) -> WebsiteConfig:
    return WebsiteConfig(
        id=site_id,
        organization_id=organization_id,
        page_name="Careers",
        url=f"https://example.org/{site_id}",
        parser_name="generic_html",
        parser_metadata=None,
        user_agent=None,
        timeout_seconds=15,
        scrape_interval_minutes=60,
    )


def make_scrape_result(
    site: WebsiteConfig,
    success: bool = True,
    notifications: list[ParsedNotification] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> ScrapeResult:
    return ScrapeResult(
        website_id=site.id,
        page_name=site.page_name,
        success=success,
        status_code=status_code if success else 503,
        notifications=notifications or [],
        error=error,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        duration_seconds=0.05,
    )


def organization_lookup_stub(organization_id: int):
    return {"name": f"Org {organization_id}"}


class FakeEngine:
    def __init__(self, results_by_site_id: dict[int, ScrapeResult]) -> None:
        self.results_by_site_id = results_by_site_id
        self.downloader = Mock()
        self.scrape_calls: list[int] = []

    def scrape(self, site: WebsiteConfig) -> ScrapeResult:
        self.scrape_calls.append(site.id)
        return self.results_by_site_id[site.id]


def test_parse_args_requires_website_ids():
    with pytest.raises(SystemExit):
        runner.parse_args([])


def test_parse_args_parses_ids_dry_run_and_limit():
    args = runner.parse_args(["--website-ids", "1", "2", "3", "--dry-run", "--limit", "2"])

    assert args.website_ids == [1, 2, 3]
    assert args.dry_run is True
    assert args.limit == 2


def test_run_persists_valid_candidates_for_a_successful_site():
    site = make_site(1, 10)
    candidate = ParsedNotification(
        title="Recruitment of Project Associate",
        url="https://example.org/jobs/1",
        metadata={"candidate_score": "6"},
    )
    result = make_scrape_result(site, success=True, notifications=[candidate])

    site_loader = Mock()
    site_loader.load_websites_by_ids.return_value = [site]

    engine = FakeEngine({1: result})

    notification_service = Mock(spec=NotificationService)
    notification_service.persist.return_value = {
        "inserted": 1,
        "updated": 0,
        "skipped_invalid": 0,
        "failed": 0,
        "errors": [],
    }

    args = runner.parse_args(["--website-ids", "1"])
    out = io.StringIO()

    exit_code = runner.run(
        args,
        site_loader=site_loader,
        engine=engine,
        notification_service=notification_service,
        organization_lookup=organization_lookup_stub,
        out=out,
    )

    assert exit_code == 0
    notification_service.persist.assert_called_once_with(result, 10)
    engine.downloader.close.assert_called_once()

    output = out.getvalue()
    assert "Organization: Org 10" in output
    assert "Page: Careers" in output
    assert "Parser: generic_html" in output
    assert "Download: SUCCESS" in output
    assert "New notifications: 1" in output
    assert "Websites processed: 1" in output
    assert "Successful: 1" in output


def test_run_dry_run_never_calls_persist():
    site = make_site(1, 10)
    candidate = ParsedNotification(
        title="Recruitment of Project Associate",
        url="https://example.org/jobs/1",
        metadata={"candidate_score": "6"},
    )
    result = make_scrape_result(site, success=True, notifications=[candidate])

    site_loader = Mock()
    site_loader.load_websites_by_ids.return_value = [site]

    engine = FakeEngine({1: result})

    notification_service = Mock(spec=NotificationService)
    duplicate_detector = Mock()
    duplicate_detector.find_existing.return_value = None  # would be new

    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(
        args,
        site_loader=site_loader,
        engine=engine,
        notification_service=notification_service,
        validator=NotificationValidator(),
        duplicate_detector=duplicate_detector,
        organization_lookup=organization_lookup_stub,
        out=out,
    )

    notification_service.persist.assert_not_called()
    duplicate_detector.find_existing.assert_called_once_with(
        "Recruitment of Project Associate", "https://example.org/jobs/1"
    )

    output = out.getvalue()
    assert "New notifications: 1" in output
    assert "SUMMARY (dry run)" in output


def test_run_dry_run_rejects_invalid_candidates_without_touching_duplicate_detector():
    site = make_site(1, 10)
    candidate = ParsedNotification(title="Gallery", url="https://example.org/gallery")
    result = make_scrape_result(site, success=True, notifications=[candidate])

    site_loader = Mock()
    site_loader.load_websites_by_ids.return_value = [site]
    engine = FakeEngine({1: result})
    notification_service = Mock(spec=NotificationService)
    duplicate_detector = Mock()

    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(
        args,
        site_loader=site_loader,
        engine=engine,
        notification_service=notification_service,
        validator=NotificationValidator(),
        duplicate_detector=duplicate_detector,
        organization_lookup=organization_lookup_stub,
        out=out,
    )

    duplicate_detector.find_existing.assert_not_called()
    output = out.getvalue()
    assert "Invalid candidates: 1" in output
    assert "New notifications: 0" in output


def test_run_counts_download_failure_and_does_not_persist():
    site = make_site(1, 10)
    result = make_scrape_result(site, success=False, error="Connection timed out")

    site_loader = Mock()
    site_loader.load_websites_by_ids.return_value = [site]
    engine = FakeEngine({1: result})
    notification_service = Mock(spec=NotificationService)

    args = runner.parse_args(["--website-ids", "1"])
    out = io.StringIO()

    runner.run(
        args,
        site_loader=site_loader,
        engine=engine,
        notification_service=notification_service,
        organization_lookup=organization_lookup_stub,
        out=out,
    )

    notification_service.persist.assert_not_called()
    output = out.getvalue()
    assert "Download: FAILED" in output
    assert "Errors: 1" in output
    assert "Connection timed out" in output
    assert "Failed: 1" in output


def test_run_warns_about_unknown_website_ids_and_skips_them():
    site_loader = Mock()
    site_loader.load_websites_by_ids.return_value = []
    engine = FakeEngine({})
    notification_service = Mock(spec=NotificationService)

    args = runner.parse_args(["--website-ids", "999"])
    out = io.StringIO()

    exit_code = runner.run(
        args,
        site_loader=site_loader,
        engine=engine,
        notification_service=notification_service,
        organization_lookup=organization_lookup_stub,
        out=out,
    )

    assert exit_code == 0
    output = out.getvalue()
    assert "WARNING: website id 999 not found" in output
    assert "Websites processed: 0" in output
    engine.downloader.close.assert_called_once()


def test_run_respects_limit_by_truncating_requested_ids():
    site_one = make_site(1, 10)
    site_two = make_site(2, 10)
    results = {
        1: make_scrape_result(site_one, success=True),
        2: make_scrape_result(site_two, success=True),
    }

    site_loader = Mock()
    site_loader.load_websites_by_ids.return_value = [site_one]

    engine = FakeEngine(results)
    notification_service = Mock(spec=NotificationService)
    notification_service.persist.return_value = {
        "inserted": 0, "updated": 0, "skipped_invalid": 0, "failed": 0, "errors": [],
    }

    args = runner.parse_args(["--website-ids", "1", "2", "3", "--limit", "1"])
    out = io.StringIO()

    runner.run(
        args,
        site_loader=site_loader,
        engine=engine,
        notification_service=notification_service,
        organization_lookup=organization_lookup_stub,
        out=out,
    )

    site_loader.load_websites_by_ids.assert_called_once_with([1])
    assert engine.scrape_calls == [1]


def test_build_default_engine_registers_builtin_parsers():
    engine = runner.build_default_engine()

    assert engine.parser_registry.get("generic_html") is GenericHTMLParser
    for name in ("iitm", "imd", "niot", "csir"):
        assert engine.parser_registry.get(name) is not None
