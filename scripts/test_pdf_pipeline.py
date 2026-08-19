#!/usr/bin/env python3
"""Diagnostic tool: run the PDF download + text-extraction pipeline once.

Accepts either an existing notification id (looks up its linked PDF via the
real database and processes it through the real pipeline — download via
`PDFDownloader`, extract via `extract_text`, persisted to `pdf_documents`
exactly as a real scrape would) or a bare PDF URL (downloaded to a scratch
temp file and extracted, with no database writes at all — there is no
notification to associate it with).

Never sends email.

Usage:
    .venv/bin/python scripts/test_pdf_pipeline.py --notification-id 5
    .venv/bin/python scripts/test_pdf_pipeline.py --pdf-url https://example.org/notice.pdf
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

from database.repositories.notification_repository import get_notification_by_id
from database.repositories.pdf_repository import get_pdf_documents_by_notification
from parser.models import ParsedNotification
from services.pdf_processing_service import PDFProcessingService
from services.pdf_text_extractor import PDFExtractionError, extract_text

PREVIEW_CHARS = 1000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--notification-id", type=int, help="An existing notification id to process.")
    group.add_argument("--pdf-url", type=str, help="A bare PDF URL to download and extract (no DB writes).")
    return parser.parse_args(argv)


def run(
    args: argparse.Namespace,
    pdf_processing_service: PDFProcessingService | None = None,
    notification_lookup=get_notification_by_id,
    pdf_lookup=get_pdf_documents_by_notification,
    session: requests.Session | None = None,
    out=sys.stdout,
) -> int:
    """Run the diagnostic. Returns a process exit code (0 success, 1 failure)."""
    if args.notification_id is not None:
        return _run_for_notification_id(
            args.notification_id,
            pdf_processing_service=pdf_processing_service or PDFProcessingService(),
            notification_lookup=notification_lookup,
            pdf_lookup=pdf_lookup,
            out=out,
        )
    return _run_for_pdf_url(args.pdf_url, session=session or requests.Session(), out=out)


def _run_for_notification_id(
    notification_id: int,
    *,
    pdf_processing_service: PDFProcessingService,
    notification_lookup,
    pdf_lookup,
    out,
) -> int:
    notification_row = notification_lookup(notification_id)
    if notification_row is None:
        print(f"Notification {notification_id} not found (or not ACTIVE).", file=out)
        return 1

    print(f"Notification ID: {notification_row['id']}", file=out)
    print(f"Title: {notification_row['title']}", file=out)
    print(f"Page URL: {notification_row['page_url']}", file=out)

    pdf_rows = pdf_lookup(notification_id)
    pdf_url = next((row["pdf_url"] for row in pdf_rows if row["pdf_url"]), None)

    print(f"PDF URL: {pdf_url}", file=out)
    print(file=out)

    if pdf_url is None:
        print("No PDF associated with this notification.", file=out)
        return 1

    notification = ParsedNotification(
        title=notification_row["title"],
        url=notification_row["page_url"] or "",
        pdf_url=pdf_url,
    )

    print("Downloading PDF...", file=out)
    result = pdf_processing_service.process(notification, notification_id)
    return _report_result(result, out)


def _run_for_pdf_url(pdf_url: str, *, session: requests.Session, out) -> int:
    print("Notification: (none — bare PDF URL, no database writes)", file=out)
    print(f"PDF URL: {pdf_url}", file=out)
    print(file=out)
    print("Downloading PDF...", file=out)

    try:
        response = session.get(pdf_url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Download: FAILED ({exc})", file=out)
        return 1

    http_status = response.status_code
    print("Download: SUCCESS", file=out)
    print(f"HTTP status: {http_status}", file=out)

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_path = Path(tmp_dir) / "diagnostic.pdf"
        local_path.write_bytes(response.content)
        print(f"Local path: {local_path} (scratch, discarded on exit)", file=out)
        print(file=out)

        print("Extracting text...", file=out)
        try:
            text = extract_text(local_path)
        except PDFExtractionError as exc:
            print(f"Extraction: FAILED ({exc})", file=out)
            return 1

        return _print_extracted_text(text, out)


def _report_result(result: dict, out) -> int:
    print(f"Download: {'SUCCESS' if result.get('downloaded') or result.get('skipped') else 'FAILED'}", file=out)
    print(f"HTTP status: {result.get('http_status')}", file=out)
    print(f"Local path: {result.get('path')}", file=out)
    if result.get("error"):
        print(f"Download error: {result['error']}", file=out)
        return 1
    print(file=out)

    extraction_status = result.get("extraction_status")
    print(f"Extraction: {extraction_status}", file=out)
    if result.get("extraction_error"):
        print(f"Extraction error: {result['extraction_error']}", file=out)
        return 1

    text = result.get("extracted_text") or ""
    return _print_extracted_text(text, out)


def _print_extracted_text(text: str, out) -> int:
    print(f"Extracted text length: {len(text)} characters", file=out)
    print(file=out)
    print("-" * 30 + f" first {PREVIEW_CHARS} characters " + "-" * 30, file=out)
    print(text[:PREVIEW_CHARS] if text else "(no text extracted)", file=out)
    print("-" * 80, file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
