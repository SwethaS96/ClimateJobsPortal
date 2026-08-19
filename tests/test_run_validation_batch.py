"""Tests for scripts/run_validation_batch.py using mocked collaborators.

No real network access. Dry-run DB-safety tests use a real isolated temp
SQLite database (with real repository calls) to prove zero writes happen;
everything else uses fakes/mocks for fast, isolated branch coverage.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

import database.connection as connection_module
import scripts.run_validation_batch as runner
from database.schema import create_schema
from parser.models import ParsedNotification
from scraper.engine import ScrapeResult
from scraper.site_config import WebsiteConfig
from services.duplicate_detector import DuplicateDetector
from services.notification_service import NotificationService
from services.notification_validator import NotificationValidator


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


def make_result(
    site: WebsiteConfig,
    success: bool = True,
    notifications=None,
    error: str | None = None,
    status_code: int | None = 200,
) -> ScrapeResult:
    return ScrapeResult(
        website_id=site.id,
        page_name=site.page_name,
        success=success,
        status_code=status_code,
        notifications=notifications or [],
        error=error,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        duration_seconds=0.05,
    )


def org_lookup_stub(organization_id):
    return {"name": f"Org {organization_id}"}


class FakeEngine:
    def __init__(self, results_by_site_id: dict[int, ScrapeResult]) -> None:
        self.results_by_site_id = results_by_site_id
        self.downloader = Mock()
        self.scrape_calls: list[int] = []

    def scrape(self, site: WebsiteConfig) -> ScrapeResult:
        self.scrape_calls.append(site.id)
        return self.results_by_site_id[site.id]


def make_site_loader(sites: list[WebsiteConfig]) -> Mock:
    loader = Mock()
    loader.load_websites_by_ids.return_value = sites
    return loader


def noop_scrape_history_writer(**kwargs):
    pass


# ---------------------------------------------------------------------------
# HTTP outcome classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "success,status_code,error,expected",
    [
        (True, 200, None, runner.HTTP_SUCCESS),
        (False, 404, "HTTP 404 Not Found", runner.HTTP_4XX),
        (False, 403, "HTTP 403", runner.HTTP_4XX),
        (False, 503, "HTTP 503 Server Error", runner.HTTP_5XX),
        (False, None, "Timeout after 15 seconds", runner.HTTP_TIMEOUT),
        (False, None, "Connection error: refused", runner.HTTP_CONNECTION_ERROR),
        (False, 200, "ValueError: parser exploded", runner.HTTP_OTHER),
    ],
)
def test_classify_http_outcome(success, status_code, error, expected):
    site = make_site()
    result = make_result(site, success=success, status_code=status_code, error=error)
    assert runner.classify_http_outcome(result) == expected


# ---------------------------------------------------------------------------
# --confirm safety gate
# ---------------------------------------------------------------------------


def test_real_mode_without_confirm_refuses_and_does_not_scrape():
    site = make_site(1, 10)
    engine = FakeEngine({1: make_result(site)})
    args = runner.parse_args(["--website-ids", "1"])
    out = io.StringIO()

    exit_code = runner.run(
        args,
        site_loader=make_site_loader([site]),
        engine=engine,
        notification_service=Mock(spec=NotificationService),
        organization_lookup=org_lookup_stub,
        out=out,
    )

    assert exit_code == 1
    assert engine.scrape_calls == []
    output = out.getvalue()
    assert "REAL RUN — DATABASE WILL BE MODIFIED" in output
    assert "--confirm" in output


def test_dry_run_shows_dry_run_banner():
    site = make_site(1, 10)
    engine = FakeEngine({1: make_result(site, notifications=[])})
    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(args, site_loader=make_site_loader([site]), engine=engine, organization_lookup=org_lookup_stub, out=out)

    assert "DRY RUN — NO DATABASE WRITES" in out.getvalue()


def test_real_mode_with_confirm_proceeds():
    site = make_site(1, 10)
    engine = FakeEngine({1: make_result(site, notifications=[])})
    notification_service = Mock(spec=NotificationService)
    notification_service.persist.return_value = {
        "inserted": 0, "updated": 0, "skipped_invalid": 0, "skipped_review": 0, "failed": 0, "errors": [],
        "pdf_processed": 0, "pdf_downloaded": 0, "pdf_download_failed": 0,
        "pdf_extraction_success": 0, "pdf_extraction_failed": 0,
    }
    args = runner.parse_args(["--website-ids", "1", "--confirm"])
    out = io.StringIO()

    exit_code = runner.run(
        args,
        site_loader=make_site_loader([site]),
        engine=engine,
        notification_service=notification_service,
        organization_lookup=org_lookup_stub,
        scrape_history_writer=noop_scrape_history_writer,
        out=out,
    )

    assert exit_code == 0
    assert engine.scrape_calls == [1]


# ---------------------------------------------------------------------------
# Candidate classification (dry-run) and per-site reporting
# ---------------------------------------------------------------------------


def test_dry_run_classifies_valid_invalid_review_candidates():
    site = make_site(1, 10)
    candidates = [
        ParsedNotification(title="RA Advertisement", url="https://example.org/1"),
        ParsedNotification(title="Careers", url="https://example.org/careers"),
        ParsedNotification(title="Departmental Update", url="https://example.org/news/1"),
    ]
    engine = FakeEngine({1: make_result(site, notifications=candidates)})
    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(
        args,
        site_loader=make_site_loader([site]),
        engine=engine,
        validator=NotificationValidator(),
        organization_lookup=org_lookup_stub,
        out=out,
    )

    output = out.getvalue()
    assert "VALID: 1" in output
    assert "INVALID: 1" in output
    assert "REVIEW: 1" in output
    assert "Candidates found: 3" in output


def test_dry_run_counts_pdf_candidates():
    site = make_site(1, 10)
    candidates = [
        ParsedNotification(title="RA Advertisement", url="https://example.org/1", pdf_url="https://example.org/1.pdf"),
        ParsedNotification(title="Recruitment", url="https://example.org/2"),
    ]
    engine = FakeEngine({1: make_result(site, notifications=candidates)})
    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(
        args, site_loader=make_site_loader([site]), engine=engine,
        validator=NotificationValidator(), organization_lookup=org_lookup_stub, out=out,
    )

    assert "PDF candidates: 1" in out.getvalue()


def test_http_404_is_reported_and_counted():
    site = make_site(1, 10)
    result = make_result(site, success=False, status_code=404, error="HTTP 404 Not Found")
    engine = FakeEngine({1: result})
    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(args, site_loader=make_site_loader([site]), engine=engine, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "HTTP status: 404" in output
    assert "Download: FAILED" in output
    assert "HTTP 4xx: 1" in output


def test_http_403_is_reported_and_counted():
    site = make_site(1, 10)
    result = make_result(site, success=False, status_code=403, error="HTTP 403")
    engine = FakeEngine({1: result})
    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(args, site_loader=make_site_loader([site]), engine=engine, organization_lookup=org_lookup_stub, out=out)

    assert "HTTP 4xx: 1" in out.getvalue()


def test_timeout_is_reported_and_counted():
    site = make_site(1, 10)
    result = make_result(site, success=False, status_code=None, error="Timeout after 15 seconds")
    engine = FakeEngine({1: result})
    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(args, site_loader=make_site_loader([site]), engine=engine, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "Timeouts: 1" in output
    assert "Timeout after 15 seconds" in output


def test_parser_failure_is_reported_as_other_failure():
    site = make_site(1, 10)
    result = make_result(site, success=False, status_code=200, error="ValueError: parser exploded")
    engine = FakeEngine({1: result})
    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(args, site_loader=make_site_loader([site]), engine=engine, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "Other failures: 1" in output
    assert "parser exploded" in output


def test_one_website_failure_does_not_stop_the_batch():
    site_one = make_site(1, 10)
    site_two = make_site(2, 20)
    engine = FakeEngine(
        {
            1: make_result(site_one, success=False, status_code=500, error="HTTP 500 Server Error"),
            2: make_result(site_two, success=True, notifications=[ParsedNotification(title="Recruitment", url="https://example.org/2")]),
        }
    )
    args = runner.parse_args(["--website-ids", "1", "2", "--dry-run"])
    out = io.StringIO()

    runner.run(
        args, site_loader=make_site_loader([site_one, site_two]), engine=engine,
        validator=NotificationValidator(), organization_lookup=org_lookup_stub, out=out,
    )

    output = out.getvalue()
    assert engine.scrape_calls == [1, 2]
    assert "Websites processed: 2" in output
    assert "HTTP 5xx: 1" in output
    assert "Successful: 1" in output


# ---------------------------------------------------------------------------
# Dry-run database safety
# ---------------------------------------------------------------------------


def test_dry_run_causes_zero_database_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
            (1, 10, "Careers", "https://example.org/1", "generic_html",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    site = make_site(1, 10)
    candidates = [
        ParsedNotification(title="RA Advertisement", url="https://example.org/1", pdf_url="https://example.org/1.pdf"),
        ParsedNotification(title="Careers", url="https://example.org/careers"),
        ParsedNotification(title="Departmental Update", url="https://example.org/news/1"),
    ]
    engine = FakeEngine({1: make_result(site, notifications=candidates)})
    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    out = io.StringIO()

    runner.run(
        args,
        site_loader=make_site_loader([site]),
        engine=engine,
        validator=NotificationValidator(),
        duplicate_detector=DuplicateDetector(),
        organization_lookup=org_lookup_stub,
        out=out,
    )

    conn = connection_module.get_connection()
    try:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("notifications", "notification_review_queue", "pdf_documents", "scrape_history")
        }
    finally:
        connection_module.close_connection(conn)

    assert counts == {
        "notifications": 0,
        "notification_review_queue": 0,
        "pdf_documents": 0,
        "scrape_history": 0,
    }


def test_real_mode_calls_notification_service_persist():
    site = make_site(1, 10)
    candidate = ParsedNotification(title="RA Advertisement", url="https://example.org/1")
    result = make_result(site, notifications=[candidate])
    engine = FakeEngine({1: result})

    notification_service = Mock(spec=NotificationService)
    notification_service.persist.return_value = {
        "inserted": 1, "updated": 0, "skipped_invalid": 0, "skipped_review": 0, "failed": 0, "errors": [],
        "pdf_processed": 0, "pdf_downloaded": 0, "pdf_download_failed": 0,
        "pdf_extraction_success": 0, "pdf_extraction_failed": 0,
    }

    args = runner.parse_args(["--website-ids", "1", "--confirm"])
    out = io.StringIO()

    runner.run(
        args,
        site_loader=make_site_loader([site]),
        engine=engine,
        notification_service=notification_service,
        organization_lookup=org_lookup_stub,
        scrape_history_writer=noop_scrape_history_writer,
        out=out,
    )

    notification_service.persist.assert_called_once_with(result, 10)
    output = out.getvalue()
    assert "New notifications: 1" in output


def test_real_mode_writes_scrape_history():
    site = make_site(1, 10)
    result = make_result(site, notifications=[])
    engine = FakeEngine({1: result})
    notification_service = Mock(spec=NotificationService)
    notification_service.persist.return_value = {
        "inserted": 0, "updated": 0, "skipped_invalid": 0, "skipped_review": 0, "failed": 0, "errors": [],
        "pdf_processed": 0, "pdf_downloaded": 0, "pdf_download_failed": 0,
        "pdf_extraction_success": 0, "pdf_extraction_failed": 0,
    }
    history_calls = []

    args = runner.parse_args(["--website-ids", "1", "--confirm"])
    runner.run(
        args,
        site_loader=make_site_loader([site]),
        engine=engine,
        notification_service=notification_service,
        organization_lookup=org_lookup_stub,
        scrape_history_writer=lambda **kwargs: history_calls.append(kwargs),
        out=io.StringIO(),
    )

    assert len(history_calls) == 1
    assert history_calls[0]["website_id"] == 1
    assert history_calls[0]["status"] == "SUCCESS"
    assert history_calls[0]["status_code"] == 200


def test_scrape_history_write_failure_does_not_crash_the_batch():
    """Regression for Phase 30: the production `scrape_history` table was
    missing a column the writer expected (schema drift), and the resulting
    exception took down the entire batch after just one site. Recording
    scrape_history is bookkeeping — a failure there must never lose
    already-persisted notifications or abort the run."""
    site = make_site(1, 10)
    result = make_result(site, notifications=[])
    engine = FakeEngine({1: result})
    notification_service = Mock(spec=NotificationService)
    notification_service.persist.return_value = {
        "inserted": 1, "updated": 0, "skipped_invalid": 0, "skipped_review": 0, "failed": 0, "errors": [],
        "pdf_processed": 0, "pdf_downloaded": 0, "pdf_download_failed": 0,
        "pdf_extraction_success": 0, "pdf_extraction_failed": 0,
    }
    out = io.StringIO()

    def broken_writer(**kwargs):
        raise __import__("sqlite3").OperationalError("table scrape_history has no column named status_code")

    args = runner.parse_args(["--website-ids", "1", "--confirm"])
    exit_code = runner.run(
        args,
        site_loader=make_site_loader([site]),
        engine=engine,
        notification_service=notification_service,
        organization_lookup=org_lookup_stub,
        scrape_history_writer=broken_writer,
        out=out,
    )

    assert exit_code == 0
    output = out.getvalue()
    assert "WARNING: failed to record scrape_history for website 1" in output
    assert "New notifications: 1" in output
    assert "VALIDATION SUMMARY" in output
    notification_service.persist.assert_called_once()


def test_scrape_history_write_failure_on_one_site_does_not_skip_the_next():
    site_1 = make_site(1, 10)
    site_2 = make_site(2, 10)
    result_1 = make_result(site_1, notifications=[])
    result_2 = make_result(site_2, notifications=[])
    engine = FakeEngine({1: result_1, 2: result_2})
    notification_service = Mock(spec=NotificationService)
    notification_service.persist.return_value = {
        "inserted": 0, "updated": 0, "skipped_invalid": 0, "skipped_review": 0, "failed": 0, "errors": [],
        "pdf_processed": 0, "pdf_downloaded": 0, "pdf_download_failed": 0,
        "pdf_extraction_success": 0, "pdf_extraction_failed": 0,
    }
    history_calls = []

    def flaky_writer(**kwargs):
        if kwargs["website_id"] == 1:
            raise RuntimeError("simulated scrape_history failure")
        history_calls.append(kwargs)

    args = runner.parse_args(["--website-ids", "1", "2", "--confirm"])
    runner.run(
        args,
        site_loader=make_site_loader([site_1, site_2]),
        engine=engine,
        notification_service=notification_service,
        organization_lookup=org_lookup_stub,
        scrape_history_writer=flaky_writer,
        out=io.StringIO(),
    )

    assert engine.scrape_calls == [1, 2]
    assert notification_service.persist.call_count == 2
    assert len(history_calls) == 1
    assert history_calls[0]["website_id"] == 2


def test_dry_run_never_writes_scrape_history():
    site = make_site(1, 10)
    engine = FakeEngine({1: make_result(site, notifications=[])})
    history_calls = []

    args = runner.parse_args(["--website-ids", "1", "--dry-run"])
    runner.run(
        args,
        site_loader=make_site_loader([site]),
        engine=engine,
        organization_lookup=org_lookup_stub,
        scrape_history_writer=lambda **kwargs: history_calls.append(kwargs),
        out=io.StringIO(),
    )

    assert history_calls == []


def test_website_not_found_is_skipped_with_warning():
    args = runner.parse_args(["--website-ids", "999", "--dry-run"])
    out = io.StringIO()

    exit_code = runner.run(
        args, site_loader=make_site_loader([]), engine=FakeEngine({}), organization_lookup=org_lookup_stub, out=out
    )

    assert exit_code == 0
    output = out.getvalue()
    assert "WARNING: website id 999 not found" in output
    assert "Websites processed: 0" in output


def test_limit_truncates_requested_ids():
    site_one = make_site(1, 10)
    engine = FakeEngine({1: make_result(site_one, notifications=[])})
    site_loader = make_site_loader([site_one])

    args = runner.parse_args(["--website-ids", "1", "2", "3", "--dry-run", "--limit", "1"])
    runner.run(args, site_loader=site_loader, engine=engine, organization_lookup=org_lookup_stub, out=io.StringIO())

    site_loader.load_websites_by_ids.assert_called_once_with([1])
    assert engine.scrape_calls == [1]
