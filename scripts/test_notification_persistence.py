#!/usr/bin/env python3
"""Diagnostic tool: demonstrate notification persistence behavior.

Uses a temporary, throwaway SQLite database and a controlled/mock
`ParsedNotification` (no real network access) to demonstrate that:

  - first run:  a new notification candidate is inserted (1 row created)
  - second run: the same candidate is recognized as already seen —
                zero new rows are created, and the existing row's
                `last_seen` is refreshed instead of being duplicated

Never sends email and never touches the real project database.

Usage:
    .venv/bin/python scripts/test_notification_persistence.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from unittest.mock import Mock

import database.connection as connection_module
from database.schema import create_schema
from parser.models import ParsedNotification
from pdf.pdf_downloader import PDFDownloader
from scraper.engine import ScrapeResult
from services.notification_service import NotificationService
from services.pdf_processing_service import PDFProcessingService

ORGANIZATION_ID = 1
WEBSITE_ID = 1


def _build_offline_pdf_processing_service(download_dir: Path) -> PDFProcessingService:
    """A PDFProcessingService with a mocked HTTP session — keeps this
    diagnostic script fully offline and deterministic, per its original
    design intent (no real network access)."""
    session = Mock()
    response = Mock()
    response.content = b"%PDF-1.4\n%mock diagnostic pdf\n"
    response.status_code = 200
    response.headers = {"Content-Type": "application/pdf"}
    response.raise_for_status.return_value = None
    session.get.return_value = response

    downloader = PDFDownloader(download_dir=download_dir, session=session)
    return PDFProcessingService(pdf_downloader=downloader)


def _seed_organization_and_website(db_path: Path) -> None:
    connection_module.DATABASE_PATH = db_path
    conn = connection_module.get_connection()
    try:
        create_schema(conn)
        conn.execute(
            """
            INSERT INTO organizations (name, short_name, homepage_url, country, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Diagnostic Org", "DIAG", "https://example.org", "India", "Tamil Nadu",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ORGANIZATION_ID, "Careers", "https://example.org/careers", "generic_html",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)


def _fetch_notification_rows() -> list[dict]:
    conn = connection_module.get_connection()
    try:
        rows = conn.execute("SELECT * FROM notifications WHERE website_id = ?", (WEBSITE_ID,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection_module.close_connection(conn)


def _fetch_pdf_rows(notification_id: int) -> list[dict]:
    conn = connection_module.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM pdf_documents WHERE notification_id = ?", (notification_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection_module.close_connection(conn)


def _run_scrape(service: NotificationService, notification: ParsedNotification) -> dict:
    scrape_result = ScrapeResult(
        website_id=WEBSITE_ID,
        page_name="Careers",
        success=True,
        status_code=200,
        notifications=[notification],
        error=None,
        started_at=None,  # type: ignore[arg-type]
        completed_at=None,  # type: ignore[arg-type]
        duration_seconds=0.0,
    )
    return service.persist(scrape_result, organization_id=ORGANIZATION_ID)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "diagnostic_climate_jobs.db"
        print(f"Using temporary database: {db_path}")
        _seed_organization_and_website(db_path)

        mock_notification = ParsedNotification(
            title="Recruitment of Project Associate 2026",
            url="https://example.org/careers/notice-45",
            pdf_url="https://example.org/careers/notice-45.pdf",
            category="Research",
            reference_number="NOTICE-45",
        )

        pdf_processing_service = _build_offline_pdf_processing_service(Path(tmp_dir) / "downloads")
        service = NotificationService(pdf_processing_service=pdf_processing_service)

        print("-" * 60)
        print("FIRST RUN")
        first_result = _run_scrape(service, mock_notification)
        print(f"Result: {first_result}")

        rows_after_first = _fetch_notification_rows()
        print(f"Rows in notifications table: {len(rows_after_first)}")
        assert first_result["inserted"] == 1, "expected first run to insert exactly 1 notification"
        assert len(rows_after_first) == 1, "expected exactly 1 row after first run"

        notification_id = rows_after_first[0]["id"]
        first_seen = rows_after_first[0]["first_seen"]
        last_seen_after_first = rows_after_first[0]["last_seen"]
        print(f"first_seen: {first_seen}")
        print(f"last_seen:  {last_seen_after_first}")

        pdf_rows_after_first = _fetch_pdf_rows(notification_id)
        print(f"Linked PDF documents: {len(pdf_rows_after_first)}")

        print("-" * 60)
        print("SECOND RUN (same candidate, simulating the next weekly scrape)")
        second_result = _run_scrape(service, mock_notification)
        print(f"Result: {second_result}")

        rows_after_second = _fetch_notification_rows()
        print(f"Rows in notifications table: {len(rows_after_second)}")
        assert second_result["inserted"] == 0, "expected second run to insert 0 new notifications"
        assert second_result["updated"] == 1, "expected second run to update the existing notification"
        assert len(rows_after_second) == 1, "expected still exactly 1 row after second run (no duplicate)"
        assert rows_after_second[0]["first_seen"] == first_seen, "first_seen must not change"

        last_seen_after_second = rows_after_second[0]["last_seen"]
        print(f"first_seen: {rows_after_second[0]['first_seen']} (unchanged)")
        print(f"last_seen:  {last_seen_after_second}")

        pdf_rows_after_second = _fetch_pdf_rows(notification_id)
        print(f"Linked PDF documents: {len(pdf_rows_after_second)} (must not duplicate)")
        assert len(pdf_rows_after_second) == len(pdf_rows_after_first)

        print("-" * 60)
        print("PASS: repeated scrapes of the same notification do not create duplicate rows.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
