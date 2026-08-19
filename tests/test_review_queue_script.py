"""Tests for scripts/review_queue.py.

Two layers: a few tests exercise it against a real isolated temp SQLite
database (via the real repository functions, proving actual DB wiring
works), and the rest use fully in-memory fakes for fast, isolated
coverage of every CLI branch.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

import database.connection as connection_module
import scripts.review_queue as review_queue
from database.repositories.notification_review_queue_repository import (
    get_review_candidate_by_id,
    insert_review_candidate,
)
from database.schema import create_schema


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
            ("Test Org", "TST", "https://example.org", "India", "Tamil Nadu",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "Jobs", "https://example.org/jobs", "generic_html",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    return db_path


# ---------------------------------------------------------------------------
# Real-database tests
# ---------------------------------------------------------------------------


def test_default_lists_pending_against_real_db(isolated_db: Path) -> None:
    insert_review_candidate(
        organization_id=1, website_id=1, title="Departmental Update",
        url="https://example.org/news/42", reason="No clear signal.",
        classification="REVIEW", hash="hash-1",
    )

    args = review_queue.parse_args([])
    out = io.StringIO()
    exit_code = review_queue.run(args, out=out)

    assert exit_code == 0
    output = out.getvalue()
    assert "PENDING REVIEW CANDIDATES (1)" in output
    assert "Title: Departmental Update" in output
    assert "Organization: Test Org" in output


def test_resolve_against_real_db_updates_row(isolated_db: Path) -> None:
    review_id = insert_review_candidate(
        organization_id=1, website_id=1, title="Departmental Update",
        url="https://example.org/news/42", reason="No clear signal.",
        classification="REVIEW", hash="hash-1",
    )

    args = review_queue.parse_args(["--resolve", str(review_id)])
    out = io.StringIO()
    exit_code = review_queue.run(args, out=out)

    assert exit_code == 0
    assert "marked RESOLVED" in out.getvalue()

    row = get_review_candidate_by_id(review_id)
    assert row["review_status"] == "RESOLVED"
    assert row["reviewed_at"] is not None


def test_resolve_never_touches_notifications_or_pdf_documents(isolated_db: Path) -> None:
    review_id = insert_review_candidate(
        organization_id=1, website_id=1, title="Departmental Update",
        url="https://example.org/news/42", reason="No clear signal.",
        classification="REVIEW", hash="hash-1",
    )

    review_queue.run(review_queue.parse_args(["--resolve", str(review_id)]), out=io.StringIO())

    conn = connection_module.get_connection()
    try:
        notif_count = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        pdf_count = conn.execute("SELECT COUNT(*) FROM pdf_documents").fetchone()[0]
    finally:
        connection_module.close_connection(conn)

    assert notif_count == 0
    assert pdf_count == 0


# ---------------------------------------------------------------------------
# Fake-repository tests (fast, cover every branch)
# ---------------------------------------------------------------------------


def make_row(
    id_,
    title="Departmental Update",
    url="https://example.org/news/42",
    classification="REVIEW",
    reason="No clear actionable recruitment signal found; needs manual review.",
    raw_html=None,
    metadata=None,
    created_at="2026-08-19T00:00:00+00:00",
    reviewed_at=None,
    review_status="PENDING",
    organization_id=1,
    website_id=1,
):
    return {
        "id": id_,
        "organization_id": organization_id,
        "website_id": website_id,
        "title": title,
        "url": url,
        "classification": classification,
        "reason": reason,
        "raw_html": raw_html,
        "metadata": metadata,
        "created_at": created_at,
        "reviewed_at": reviewed_at,
        "review_status": review_status,
    }


def org_lookup_stub(organization_id):
    return {"name": f"Org {organization_id}"}


def test_empty_queue_shows_clean_message():
    args = review_queue.parse_args([])
    out = io.StringIO()

    exit_code = review_queue.run(
        args, list_pending=lambda: [], list_all=lambda: [], organization_lookup=org_lookup_stub, out=out
    )

    assert exit_code == 0
    output = out.getvalue()
    assert "PENDING REVIEW CANDIDATES (0)" in output
    assert "(none)" in output


def test_pending_flag_lists_only_pending():
    rows = [make_row(1)]
    args = review_queue.parse_args(["--pending"])
    out = io.StringIO()

    review_queue.run(args, list_pending=lambda: rows, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "PENDING REVIEW CANDIDATES (1)" in output
    assert "ID: 1" in output
    assert "Title: Departmental Update" in output
    assert "Classification: REVIEW" in output
    assert "Reason: No clear actionable" in output
    assert "Created At: 2026-08-19T00:00:00+00:00" in output


def test_all_flag_lists_pending_and_resolved():
    rows = [make_row(1, review_status="PENDING"), make_row(2, title="Old One", review_status="RESOLVED")]
    args = review_queue.parse_args(["--all"])
    out = io.StringIO()

    review_queue.run(args, list_all=lambda: rows, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "ALL REVIEW CANDIDATES (2)" in output
    assert "Status: PENDING" in output
    assert "Status: RESOLVED" in output


def test_multiple_pending_candidates_are_all_listed():
    rows = [make_row(1, title="First"), make_row(2, title="Second"), make_row(3, title="Third")]
    args = review_queue.parse_args([])
    out = io.StringIO()

    review_queue.run(args, list_pending=lambda: rows, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    for title in ("First", "Second", "Third"):
        assert f"Title: {title}" in output


def test_show_displays_full_detail():
    row = make_row(
        7,
        raw_html="<a href='/news/42'>Departmental Update</a>",
        metadata='{"parser": "generic_html"}',
    )
    args = review_queue.parse_args(["--show", "7"])
    out = io.StringIO()

    exit_code = review_queue.run(args, get_by_id=lambda _id: row, organization_lookup=org_lookup_stub, out=out)

    assert exit_code == 0
    output = out.getvalue()
    assert "Title: Departmental Update" in output
    assert "URL: https://example.org/news/42" in output
    assert "Reason: No clear actionable" in output
    assert "Classification: REVIEW" in output
    assert "Raw HTML: <a href='/news/42'>Departmental Update</a>" in output
    assert "Metadata: {\"parser\": \"generic_html\"}" in output
    assert "Created At: 2026-08-19T00:00:00+00:00" in output
    assert "Review Status: PENDING" in output


def test_show_handles_missing_raw_html_and_metadata_gracefully():
    row = make_row(7, raw_html=None, metadata=None)
    args = review_queue.parse_args(["--show", "7"])
    out = io.StringIO()

    review_queue.run(args, get_by_id=lambda _id: row, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "Raw HTML: (none)" in output
    assert "Metadata: (none)" in output


def test_show_nonexistent_id_reports_cleanly():
    args = review_queue.parse_args(["--show", "999"])
    out = io.StringIO()

    exit_code = review_queue.run(args, get_by_id=lambda _id: None, organization_lookup=org_lookup_stub, out=out)

    assert exit_code == 1
    assert "999 not found" in out.getvalue()


def test_resolve_marks_pending_candidate():
    row = make_row(7, review_status="PENDING")
    resolve_calls = []
    args = review_queue.parse_args(["--resolve", "7"])
    out = io.StringIO()

    exit_code = review_queue.run(
        args,
        get_by_id=lambda _id: row,
        resolve=lambda review_id: resolve_calls.append(review_id) or True,
        out=out,
    )

    assert exit_code == 0
    assert resolve_calls == [7]
    output = out.getvalue()
    assert "marked RESOLVED" in output
    assert "Title: Departmental Update" in output


def test_resolve_already_resolved_candidate_is_a_clean_no_op():
    row = make_row(7, review_status="RESOLVED")
    resolve_calls = []
    args = review_queue.parse_args(["--resolve", "7"])
    out = io.StringIO()

    exit_code = review_queue.run(
        args,
        get_by_id=lambda _id: row,
        resolve=lambda review_id: resolve_calls.append(review_id) or True,
        out=out,
    )

    assert exit_code == 1
    assert resolve_calls == []  # never call the mutating repo function
    assert "already RESOLVED" in out.getvalue()


def test_resolve_nonexistent_id_reports_cleanly():
    args = review_queue.parse_args(["--resolve", "999"])
    out = io.StringIO()

    exit_code = review_queue.run(args, get_by_id=lambda _id: None, out=out)

    assert exit_code == 1
    assert "999 not found" in out.getvalue()


def test_resolve_and_all_flags_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        review_queue.parse_args(["--resolve", "1", "--all"])
