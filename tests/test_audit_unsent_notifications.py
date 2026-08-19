"""Tests for scripts/audit_unsent_notifications.py.

Pure-function tests for categorize(), plus end-to-end tests against an
isolated temp SQLite database (never the real production DB). No network
access, no writes verified explicitly.
"""

from __future__ import annotations

import io
import sqlite3

import pytest

import scripts.audit_unsent_notifications as audit
from database.repositories import notification_repository
from database.schema import create_schema

# ---------------------------------------------------------------------------
# categorize() — pure function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected_category",
    [
        ("Result of the written examination for JRF post", "RESULTS_OR_SELECTED_CANDIDATES"),
        ("List of Selected Candidates for the post of Technical Assistant", "RESULTS_OR_SELECTED_CANDIDATES"),
        ("Tender for supply of laboratory equipment", "TENDER_PROCUREMENT"),
        ("Expression of Interest (EOI) for catering services", "TENDER_PROCUREMENT"),
        ("Application for the Sir C.V. Raman Scientist Award 2026", "AWARDS_ACHIEVEMENTS"),
        ("Dr. X receives Best Paper Award at International Conference", "AWARDS_ACHIEVEMENTS"),
        ("National Scholarship Portal announcement", "SCHOLARSHIP"),
        ("National Fellowship and Scholarship for Higher Education of ST Students", "FELLOWSHIP_SCHEME_NOT_RECRUITMENT"),
        ("Admission Notice for PhD Programme 2026", "ADMISSION"),
        ("International Conference on Climate Science", "CONFERENCE_SEMINAR"),
        ("Training Programme on Soil Testing", "TRAINING_WORKSHOP"),
        ("Inauguration of new research building", "EVENT_CEREMONY"),
        ("Circular regarding office timings", "CIRCULAR_OFFICE_ORDER"),
        ("Recruitment and Promotion Rules for non-academic staff", "POLICY_RULES_REPORT"),
        ("Faculty Directory for the Department of Physics", "STAFF_FACULTY_DIRECTORY"),
    ],
)
def test_categorize_detects_expected_suspicious_category(title, expected_category):
    bucket, category = audit.categorize(title, "https://example.org/notice")
    assert category == expected_category
    assert bucket in (audit.LIKELY_FALSE_POSITIVE, audit.NEEDS_REVIEW)


def test_categorize_genuine_recruitment_is_high_confidence():
    bucket, category = audit.categorize(
        "Advertisement for the post of Junior Research Fellow (JRF) in Physics Department",
        "https://example.org/jrf-advt",
    )
    assert bucket == audit.HIGH_CONFIDENCE_RECRUITMENT
    assert category is None


def test_categorize_ambiguous_case_is_needs_review():
    """A suspicious category AND a strong recruitment signal both present
    -> genuinely ambiguous, not confidently bucketed either way."""
    bucket, category = audit.categorize(
        "JRF Recruitment Advertisement — Best Paper Award Ceremony details enclosed",
        "https://example.org/notice",
    )
    assert bucket == audit.NEEDS_REVIEW
    assert category == "AWARDS_ACHIEVEMENTS"


def test_categorize_detects_tender_via_url_when_title_is_generic():
    """Regression evidence from Phase 28/29: a bare 'Advertisement' title
    pointing at a URL folder literally named for tenders."""
    bucket, category = audit.categorize(
        "Advertisement",
        "https://example.org/templates/PDF/Paper_Tender/Notice_Office_Furniture.pdf",
    )
    assert bucket == audit.LIKELY_FALSE_POSITIVE
    assert category == "TENDER_PROCUREMENT"


def test_categorize_handles_none_title_and_url():
    bucket, category = audit.categorize(None, None)
    assert bucket == audit.HIGH_CONFIDENCE_RECRUITMENT
    assert category is None


# ---------------------------------------------------------------------------
# run() — end to end, isolated DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test_audit.db"
    connection = sqlite3.connect(db_path)
    create_schema(connection)
    connection.commit()
    connection.close()

    def fake_get_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(notification_repository, "get_connection", fake_get_connection)
    monkeypatch.setattr(notification_repository, "close_connection", lambda conn: conn.close())
    return fake_get_connection


def _seed_org_and_website(get_connection):
    conn = get_connection()
    conn.execute(
        "INSERT INTO organizations (name, short_name, homepage_url, country, state, created_at, updated_at) "
        "VALUES ('Org A', 'OA', 'https://org-a.example', 'India', 'Tamil Nadu', ?, ?)",
        ("2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at) "
        "VALUES (1, 'Jobs', 'https://org-a.example/jobs', 'generic_html', ?, ?)",
        ("2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()


def test_run_reports_totals_and_buckets(isolated_db):
    _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        1, 1, "Advertisement for JRF in Physics Department", page_url="https://org-a.example/1", hash="h1"
    )
    notification_repository.insert_notification(
        1, 1, "Application for the Sir C.V. Raman Scientist Award 2026", page_url="https://org-a.example/2", hash="h2"
    )

    out = io.StringIO()
    exit_code = audit.run(out=out)

    assert exit_code == 0
    output = out.getvalue()
    assert "Total unsent VALID notifications: 2" in output
    assert "HIGH_CONFIDENCE_RECRUITMENT" in output
    assert "LIKELY_FALSE_POSITIVE" in output
    assert "AWARDS_ACHIEVEMENTS" in output


def test_run_excludes_already_sent_notifications(isolated_db):
    _seed_org_and_website(isolated_db)
    notification_id = notification_repository.insert_notification(
        1, 1, "Some Award Notice", page_url="https://org-a.example/1", hash="h1"
    )
    conn = isolated_db()
    conn.execute("UPDATE notifications SET email_sent = 1 WHERE id = ?", (notification_id,))
    conn.commit()
    conn.close()

    out = io.StringIO()
    audit.run(out=out)
    assert "Total unsent VALID notifications: 0" in out.getvalue()


def test_run_shows_organization_wise_concentration(isolated_db):
    _seed_org_and_website(isolated_db)
    for i in range(3):
        notification_repository.insert_notification(
            1, 1, f"Best Paper Award Notification {i}", page_url=f"https://org-a.example/{i}", hash=f"h{i}"
        )

    out = io.StringIO()
    audit.run(out=out)
    output = out.getvalue()
    assert "ORGANIZATION-WISE FALSE-POSITIVE CONCENTRATION" in output
    assert "Org A" in output
    assert "3/3" in output


def test_run_does_not_modify_database(isolated_db):
    _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(1, 1, "Award Notice", page_url="https://org-a.example/1", hash="h1")

    audit.run(out=io.StringIO())

    conn = isolated_db()
    row = conn.execute("SELECT email_sent, status FROM notifications WHERE id = 1").fetchone()
    count = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    conn.close()
    assert row["email_sent"] == 0
    assert row["status"] == "ACTIVE"
    assert count == 1


def test_run_shows_reclassification_under_current_validator(isolated_db):
    """A row persisted as VALID under an older classifier (e.g. bare
    'award' wasn't a hard negative yet) must be reported as no longer
    VALID under the current NotificationValidator — proving the audit
    reflects real classifier changes, not just its own heuristic."""
    _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        1, 1, "Application for the Sir C.V. Raman Scientist Award 2026", page_url="https://org-a.example/1", hash="h1"
    )

    out = io.StringIO()
    audit.run(out=out)
    output = out.getvalue()
    assert "RE-CLASSIFICATION UNDER THE CURRENT NotificationValidator" in output
    assert "NOTIFICATIONS NO LONGER VALID UNDER THE UPDATED CLASSIFIER" in output
    assert "Sir C.V. Raman Scientist Award" in output
    assert "now INVALID" in output


def test_run_lists_top_suspicious_notifications_with_required_fields(isolated_db):
    _seed_org_and_website(isolated_db)
    notification_id = notification_repository.insert_notification(
        1, 1, "Tender for Office Furniture", page_url="https://org-a.example/tender", hash="h1"
    )
    conn = isolated_db()
    conn.execute(
        "INSERT INTO pdf_documents (notification_id, document_type, pdf_url, downloaded) VALUES (?, ?, ?, ?)",
        (notification_id, "notice", "https://org-a.example/tender.pdf", 0),
    )
    conn.commit()
    conn.close()

    out = io.StringIO()
    audit.run(out=out)
    output = out.getvalue()
    assert "Org A" in output
    assert "Tender for Office Furniture" in output
    assert "https://org-a.example/tender" in output
    assert "https://org-a.example/tender.pdf" in output
    assert "Classifier reason:" in output


def test_module_has_no_write_functions_imported():
    """Guard against accidental DB mutation."""
    import inspect

    source = inspect.getsource(audit)
    for forbidden in ("insert_", "update_", "delete_", "mark_reviewed", "touch_last_seen"):
        assert forbidden not in source
