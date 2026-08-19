"""Tests for scripts/test_email_digest.py — the read-only digest dry-run.

Uses an isolated temp database. Asserts no email is sent (the script never
constructs an EmailProvider) and no email_sent flag is ever modified.
"""

from __future__ import annotations

import io
import sqlite3

import pytest

import scripts.test_email_digest as digest_script
from database.repositories import notification_repository
from database.schema import create_schema
from services.email_service import EmailDigestService


@pytest.fixture()
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test_email_digest_script.db"
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
    monkeypatch.setattr(digest_script, "get_connection", fake_get_connection)
    monkeypatch.setattr(digest_script, "close_connection", lambda conn: conn.close())
    return fake_get_connection


def _seed_notification(get_connection, title="Opening"):
    conn = get_connection()
    conn.execute(
        "INSERT INTO organizations (name, short_name, homepage_url, country, state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Org A", "OA", "https://org-a.example", "India", "Tamil Nadu", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at) "
        "VALUES (1, 'Jobs', 'https://org-a.example/jobs', 'generic_html', ?, ?)",
        ("2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()
    notification_repository.insert_notification(1, 1, title, page_url="https://org-a.example/1", hash="h1")


def test_dry_run_reports_no_new_notifications_when_empty(isolated_db):
    out = io.StringIO()
    exit_code = digest_script.run(out=out)

    assert exit_code == 0
    output = out.getvalue()
    assert "UNSENT VALID NOTIFICATIONS: 0" in output
    assert "No new recruitment notifications." in output
    assert "DRY RUN COMPLETE" in output


def test_dry_run_reports_pending_notifications(isolated_db):
    _seed_notification(isolated_db)
    out = io.StringIO()
    digest_script.run(out=out)

    output = out.getvalue()
    assert "UNSENT VALID NOTIFICATIONS: 1" in output
    assert "Org A" in output
    assert "Opening" in output


def test_dry_run_never_modifies_email_sent(isolated_db):
    _seed_notification(isolated_db)
    digest_script.run(out=io.StringIO())

    conn = isolated_db()
    row = conn.execute("SELECT email_sent FROM notifications WHERE title = 'Opening'").fetchone()
    conn.close()
    assert row["email_sent"] == 0


def test_dry_run_never_sends_email():
    """The diagnostic script never even constructs an EmailProvider —
    structurally impossible for it to send anything."""
    import inspect

    source = inspect.getsource(digest_script)
    assert "EmailProvider(" not in source
    assert ".send(" not in source


def test_dry_run_reports_pending_review_queue_count(isolated_db):
    _seed_notification(isolated_db)
    conn = isolated_db()
    conn.execute(
        "INSERT INTO notification_review_queue "
        "(organization_id, website_id, title, url, reason, classification, hash, created_at, review_status) "
        "VALUES (1, 1, 'Ambiguous', 'https://org-a.example/2', 'no signal', 'REVIEW', 'rh', ?, 'PENDING')",
        ("2026-01-01T00:00:00",),
    )
    conn.commit()
    conn.close()

    out = io.StringIO()
    digest_script.run(out=out)
    assert "REVIEW NOTIFICATIONS EXCLUDED (pending manual review, never emailed): 1" in out.getvalue()
