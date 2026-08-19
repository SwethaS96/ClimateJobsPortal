"""Tests for notification persistence service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

import database.connection as connection_module
import services.notification_service as notification_service_module
from database.schema import create_schema
from parser.models import ParsedNotification
from pdf.pdf_downloader import PDFDownloader
from scraper.engine import ScrapeResult
from services.notification_service import NotificationService
from services.pdf_processing_service import PDFProcessingService


def make_fake_pdf_processing_service(tmp_path: Path, pdf_bytes: bytes = b"%PDF-1.4\n%hello\n") -> PDFProcessingService:
    """A PDFProcessingService backed by a mocked HTTP session — no real network."""
    session = Mock()
    response = Mock()
    response.content = pdf_bytes
    response.status_code = 200
    response.headers = {"Content-Type": "application/pdf"}
    response.raise_for_status.return_value = None
    session.get.return_value = response

    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    return PDFProcessingService(pdf_downloader=downloader)


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "climate_jobs.db"
    monkeypatch.setattr(connection_module, "DATABASE_PATH", db_path)

    conn = connection_module.get_connection()
    try:
        create_schema(conn)
        conn.execute(
            """
            INSERT INTO organizations (name, short_name, homepage_url, country, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Test Org",
                "TST",
                "https://example.org",
                "India",
                "Tamil Nadu",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Jobs",
                "https://example.org/jobs",
                "generic_html",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    return db_path


def make_scrape_result(notifications: list[ParsedNotification], website_id: int = 1) -> ScrapeResult:
    return ScrapeResult(
        website_id=website_id,
        page_name="Jobs",
        success=True,
        status_code=200,
        notifications=notifications,
        error=None,
        started_at=None,  # type: ignore[arg-type]
        completed_at=None,  # type: ignore[arg-type]
        duration_seconds=0.0,
    )


def fetch_notification_rows(website_id: int = 1):
    conn = connection_module.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM notifications WHERE website_id = ?",
            (website_id,),
        ).fetchall()
    finally:
        connection_module.close_connection(conn)


def fetch_review_queue_rows(website_id: int = 1):
    conn = connection_module.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM notification_review_queue WHERE website_id = ?",
            (website_id,),
        ).fetchall()
    finally:
        connection_module.close_connection(conn)


def test_new_notification_is_inserted(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [ParsedNotification(title="Vacancy for Vacancy for Climate Scientist Role", url="https://example.org/jobs/1")]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["inserted"] == 1
    assert result["updated"] == 0
    assert result["failed"] == 0

    rows = fetch_notification_rows()
    assert len(rows) == 1
    assert rows[0]["title"] == "Vacancy for Vacancy for Climate Scientist Role"


def test_organization_and_website_association_is_recorded(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [ParsedNotification(title="Vacancy for Climate Scientist Role", url="https://example.org/jobs/1")],
        website_id=1,
    )

    service.persist(scrape_result, organization_id=1)

    rows = fetch_notification_rows()
    assert rows[0]["organization_id"] == 1
    assert rows[0]["website_id"] == 1


def test_duplicate_notification_within_same_batch_is_not_inserted_twice(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [
            ParsedNotification(title="Vacancy for Climate Scientist Role", url="https://example.org/jobs/1"),
            ParsedNotification(title="Vacancy for Climate Scientist Role", url="https://example.org/jobs/1"),
        ]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["inserted"] == 1
    assert result["updated"] == 1
    assert result["failed"] == 0

    rows = fetch_notification_rows()
    assert len(rows) == 1


def test_repeated_scrape_does_not_duplicate_and_updates_last_seen(isolated_db: Path) -> None:
    service = NotificationService()
    notification = ParsedNotification(title="Vacancy for Climate Scientist Role", url="https://example.org/jobs/1")

    first = service.persist(make_scrape_result([notification]), organization_id=1)
    rows_after_first = fetch_notification_rows()
    first_last_seen = rows_after_first[0]["last_seen"]
    first_seen = rows_after_first[0]["first_seen"]

    second = service.persist(make_scrape_result([notification]), organization_id=1)
    rows_after_second = fetch_notification_rows()

    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["updated"] == 1

    assert len(rows_after_second) == 1
    assert rows_after_second[0]["first_seen"] == first_seen
    assert rows_after_second[0]["last_seen"] >= first_last_seen


def test_pdf_notification_creates_linked_pdf_document(isolated_db: Path, tmp_path: Path) -> None:
    service = NotificationService(pdf_processing_service=make_fake_pdf_processing_service(tmp_path))

    scrape_result = make_scrape_result(
        [
            ParsedNotification(
                title="Advertisement for Project Associate",
                url="https://example.org/jobs/2",
                pdf_url="https://example.org/jobs/advertisement_2.pdf",
            )
        ]
    )

    service.persist(scrape_result, organization_id=1)

    rows = fetch_notification_rows()
    notification_id = rows[0]["id"]

    conn = connection_module.get_connection()
    try:
        pdf_rows = conn.execute(
            "SELECT * FROM pdf_documents WHERE notification_id = ?",
            (notification_id,),
        ).fetchall()
    finally:
        connection_module.close_connection(conn)

    assert len(pdf_rows) == 1
    assert pdf_rows[0]["pdf_url"] == "https://example.org/jobs/advertisement_2.pdf"
    assert pdf_rows[0]["downloaded"] == 1
    assert pdf_rows[0]["extraction_status"] in ("SUCCESS", "EMPTY", "FAILED")


def test_pdf_document_is_not_duplicated_on_repeated_scrape(isolated_db: Path, tmp_path: Path) -> None:
    service = NotificationService(pdf_processing_service=make_fake_pdf_processing_service(tmp_path))
    notification = ParsedNotification(
        title="Advertisement for Project Associate",
        url="https://example.org/jobs/2",
        pdf_url="https://example.org/jobs/advertisement_2.pdf",
    )

    service.persist(make_scrape_result([notification]), organization_id=1)
    service.persist(make_scrape_result([notification]), organization_id=1)

    rows = fetch_notification_rows()
    notification_id = rows[0]["id"]

    conn = connection_module.get_connection()
    try:
        pdf_rows = conn.execute(
            "SELECT * FROM pdf_documents WHERE notification_id = ?",
            (notification_id,),
        ).fetchall()
    finally:
        connection_module.close_connection(conn)

    assert len(pdf_rows) == 1


def test_invalid_candidate_is_rejected_and_not_persisted(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [ParsedNotification(title="Scientists", url="https://example.org/scientists.php")]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["inserted"] == 0
    assert result["skipped_invalid"] == 1
    assert fetch_notification_rows() == []


@pytest.mark.parametrize(
    "title",
    ["Home", "About Us", "Contact", "Gallery", "Annual Report 2026", "Tenders", "Login", "Privacy Policy"],
)
def test_configured_reject_keywords_are_rejected(isolated_db: Path, title: str) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [ParsedNotification(title=title, url=f"https://example.org/{title.lower()}")]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["skipped_invalid"] == 1
    assert fetch_notification_rows() == []


def test_multiple_distinct_notifications_from_one_website_are_all_inserted(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [
            ParsedNotification(title="Vacancy for JRF Position", url="https://example.org/jobs/1"),
            ParsedNotification(title="Vacancy for SRF Position", url="https://example.org/jobs/2"),
            ParsedNotification(title="Recruitment of Project Scientist", url="https://example.org/jobs/3"),
        ]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["inserted"] == 3
    assert len(fetch_notification_rows()) == 3


def test_one_notification_failure_does_not_stop_remaining_notifications(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_insert_notification = notification_service_module.insert_notification

    def flaky_insert_notification(**kwargs):
        if kwargs["title"] == "Vacancy Boom Notification":
            raise RuntimeError("simulated database failure")
        return real_insert_notification(**kwargs)

    monkeypatch.setattr(notification_service_module, "insert_notification", flaky_insert_notification)

    service = NotificationService()
    scrape_result = make_scrape_result(
        [
            ParsedNotification(title="Vacancy for JRF Position", url="https://example.org/jobs/1"),
            ParsedNotification(title="Vacancy Boom Notification", url="https://example.org/jobs/boom"),
            ParsedNotification(title="Vacancy for SRF Position", url="https://example.org/jobs/2"),
        ]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["inserted"] == 2
    assert result["failed"] == 1
    assert len(result["errors"]) == 1
    assert "simulated database failure" in result["errors"][0]

    rows = fetch_notification_rows()
    assert {row["title"] for row in rows} == {"Vacancy for JRF Position", "Vacancy for SRF Position"}


def test_persist_rejects_real_world_false_positives_and_keeps_the_genuine_notice(isolated_db: Path) -> None:
    """Regression for the false positives found in the phase-20 real scrape:

    Careers / Retired Scientist / results announcements are not actionable
    opportunities and must not be persisted, even though a bare keyword
    filter previously let them through.
    """
    service = NotificationService()

    scrape_result = make_scrape_result(
        [
            ParsedNotification(title="Careers", url="https://example.org/careers"),
            ParsedNotification(title="Retired Scientist", url="https://example.org/retired_scientists.php"),
            ParsedNotification(
                title="RA Advertisement - Results (August 2026 Quarter)",
                url="https://example.org/463-news_details",
            ),
            ParsedNotification(title="RA Advertisement", url="https://example.org/jobs/ra-advertisement"),
        ]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["inserted"] == 1
    assert result["skipped_invalid"] == 3

    rows = fetch_notification_rows()
    assert {row["title"] for row in rows} == {"RA Advertisement"}


def test_review_candidate_with_no_clear_signal_is_not_persisted(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [ParsedNotification(title="Departmental Update", url="https://example.org/news/42")]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["inserted"] == 0
    assert result["skipped_review"] == 1
    assert fetch_notification_rows() == []


def test_classification_and_reason_are_recorded_in_metadata(isolated_db: Path) -> None:
    service = NotificationService()
    notification = ParsedNotification(title="RA Advertisement", url="https://example.org/jobs/ra-advertisement")

    service.persist(make_scrape_result([notification]), organization_id=1)

    assert notification.metadata["classification"] == "VALID"
    assert notification.metadata["classification_reason"]


def test_review_candidate_enters_review_queue_not_notifications(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [ParsedNotification(title="Departmental Update", url="https://example.org/news/42")]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["skipped_review"] == 1
    assert fetch_notification_rows() == []

    review_rows = fetch_review_queue_rows()
    assert len(review_rows) == 1
    assert review_rows[0]["title"] == "Departmental Update"
    assert review_rows[0]["classification"] == "REVIEW"
    assert review_rows[0]["review_status"] == "PENDING"
    assert review_rows[0]["reason"]
    assert review_rows[0]["organization_id"] == 1
    assert review_rows[0]["website_id"] == 1


def test_invalid_candidate_does_not_enter_review_queue(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [ParsedNotification(title="Careers", url="https://example.org/careers")]
    )

    service.persist(scrape_result, organization_id=1)

    assert fetch_review_queue_rows() == []


def test_valid_candidate_does_not_enter_review_queue(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [ParsedNotification(title="RA Advertisement", url="https://example.org/jobs/1")]
    )

    service.persist(scrape_result, organization_id=1)

    assert fetch_review_queue_rows() == []
    assert len(fetch_notification_rows()) == 1


def test_repeated_review_candidate_does_not_duplicate_in_queue(isolated_db: Path) -> None:
    service = NotificationService()
    notification = ParsedNotification(title="Departmental Update", url="https://example.org/news/42")

    first = service.persist(make_scrape_result([notification]), organization_id=1)
    second = service.persist(make_scrape_result([notification]), organization_id=1)

    assert first["skipped_review"] == 1
    assert second["skipped_review"] == 1
    assert len(fetch_review_queue_rows()) == 1


def test_review_candidate_never_downloads_a_pdf(isolated_db: Path, tmp_path: Path) -> None:
    """REVIEW candidates must never trigger a PDF download, even if pdf_url is set."""
    fake_pdf_service = make_fake_pdf_processing_service(tmp_path)
    service = NotificationService(pdf_processing_service=fake_pdf_service)

    scrape_result = make_scrape_result(
        [
            ParsedNotification(
                title="Departmental Update",
                url="https://example.org/news/42",
                pdf_url="https://example.org/news/42.pdf",
            )
        ]
    )

    service.persist(scrape_result, organization_id=1)

    fake_pdf_service.pdf_downloader.session.get.assert_not_called()

    conn = connection_module.get_connection()
    try:
        pdf_rows = conn.execute("SELECT * FROM pdf_documents").fetchall()
    finally:
        connection_module.close_connection(conn)
    assert pdf_rows == []


def test_review_queue_candidate_can_be_marked_reviewed(isolated_db: Path) -> None:
    from database.repositories.notification_review_queue_repository import mark_reviewed

    service = NotificationService()
    service.persist(
        make_scrape_result([ParsedNotification(title="Departmental Update", url="https://example.org/news/42")]),
        organization_id=1,
    )

    review_id = fetch_review_queue_rows()[0]["id"]
    updated = mark_reviewed(review_id)

    assert updated is True
    row = fetch_review_queue_rows()[0]
    assert row["review_status"] == "RESOLVED"
    assert row["reviewed_at"] is not None


def test_persist_reports_pdf_pipeline_stats_for_successful_pdf(isolated_db: Path, tmp_path: Path) -> None:
    service = NotificationService(pdf_processing_service=make_fake_pdf_processing_service(tmp_path))

    scrape_result = make_scrape_result(
        [
            ParsedNotification(
                title="Advertisement for Project Associate",
                url="https://example.org/jobs/2",
                pdf_url="https://example.org/jobs/advertisement_2.pdf",
            )
        ]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["pdf_processed"] == 1
    assert result["pdf_downloaded"] == 1
    assert result["pdf_download_failed"] == 0
    assert result["pdf_extraction_success"] + result["pdf_extraction_failed"] == 1


def test_persist_reports_zero_pdf_stats_when_no_pdf_candidates(isolated_db: Path) -> None:
    service = NotificationService()

    scrape_result = make_scrape_result(
        [ParsedNotification(title="RA Advertisement", url="https://example.org/jobs/1")]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["pdf_processed"] == 0
    assert result["pdf_downloaded"] == 0
    assert result["pdf_extraction_success"] == 0
    assert result["pdf_extraction_failed"] == 0


def test_persist_reports_pdf_download_failure(isolated_db: Path, tmp_path: Path) -> None:
    session = Mock()
    response = Mock()
    response.status_code = 404
    response.headers = {}
    import requests

    response.raise_for_status.side_effect = requests.HTTPError("404 Client Error")
    session.get.return_value = response

    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    service = NotificationService(pdf_processing_service=PDFProcessingService(pdf_downloader=downloader))

    scrape_result = make_scrape_result(
        [
            ParsedNotification(
                title="Advertisement for Project Associate",
                url="https://example.org/jobs/2",
                pdf_url="https://example.org/jobs/missing.pdf",
            )
        ]
    )

    result = service.persist(scrape_result, organization_id=1)

    assert result["pdf_processed"] == 1
    assert result["pdf_downloaded"] == 0
    assert result["pdf_download_failed"] == 1
    assert result["pdf_extraction_success"] == 0
    assert result["pdf_extraction_failed"] == 0
