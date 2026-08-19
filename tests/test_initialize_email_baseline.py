"""Tests for scripts/initialize_email_baseline.py.

Uses a fully isolated temp SQLite database — never the real production
database. No network access.
"""

from __future__ import annotations

import io
import sqlite3

import pytest

import database.connection as connection_module
import scripts.initialize_email_baseline as baseline
from database.repositories import notification_repository
from database.repositories.notification_repository import insert_notification
from database.schema import create_schema


@pytest.fixture()
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test_baseline.db"
    connection = sqlite3.connect(db_path)
    create_schema(connection)
    connection.execute(
        "INSERT INTO organizations (name, short_name, homepage_url, country, state, created_at, updated_at) "
        "VALUES ('Org A', 'OA', 'https://org-a.example', 'India', 'Tamil Nadu', ?, ?)",
        ("2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    connection.execute(
        "INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at) "
        "VALUES (1, 'Jobs', 'https://org-a.example/jobs', 'generic_html', ?, ?)",
        ("2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    connection.commit()
    connection.close()

    def fake_get_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(connection_module, "get_connection", fake_get_connection)
    monkeypatch.setattr(connection_module, "close_connection", lambda conn: conn.close())
    monkeypatch.setattr(baseline, "get_connection", fake_get_connection)
    monkeypatch.setattr(baseline, "close_connection", lambda conn: conn.close())
    # insert_notification() (used by _seed_notifications below) is defined
    # in notification_repository and calls ITS OWN module-level
    # get_connection/close_connection references — patching
    # connection_module's names alone does not affect it.
    monkeypatch.setattr(notification_repository, "get_connection", fake_get_connection)
    monkeypatch.setattr(notification_repository, "close_connection", lambda conn: conn.close())
    return fake_get_connection


def _seed_notifications(get_connection, count=3):
    ids = []
    for i in range(count):
        nid = insert_notification(1, 1, f"Opening {i}", page_url=f"https://org-a.example/{i}", hash=f"h{i}")
        ids.append(nid)
    return ids


# ---------------------------------------------------------------------------
# --dry-run: read-only
# ---------------------------------------------------------------------------


def test_dry_run_makes_no_changes(isolated_db):
    ids = _seed_notifications(isolated_db, 3)

    out = io.StringIO()
    args = baseline.parse_args(["--dry-run"])
    exit_code = baseline.run(args, out=out)

    assert exit_code == 0
    output = out.getvalue()
    assert "Total notifications: 3" in output
    assert "Currently email_sent=0" in output
    assert "DRY RUN" in output

    conn = isolated_db()
    unsent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 0").fetchone()[0]
    conn.close()
    assert unsent == 3


def test_dry_run_reports_before_counts_accurately(isolated_db):
    ids = _seed_notifications(isolated_db, 5)
    conn = isolated_db()
    conn.execute("UPDATE notifications SET email_sent = 1 WHERE id = ?", (ids[0],))
    conn.commit()
    conn.close()

    out = io.StringIO()
    baseline.run(baseline.parse_args(["--dry-run"]), out=out)
    output = out.getvalue()

    assert "Total notifications: 5" in output
    assert "Already email_sent=1: 1" in output
    assert "baseline candidates): 4" in output


# ---------------------------------------------------------------------------
# --confirm: the actual mutation
# ---------------------------------------------------------------------------


def test_confirm_marks_all_unsent_as_sent(isolated_db):
    ids = _seed_notifications(isolated_db, 4)

    out = io.StringIO()
    exit_code = baseline.run(baseline.parse_args(["--confirm"]), out=out)

    assert exit_code == 0
    conn = isolated_db()
    unsent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 0").fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 1").fetchone()[0]
    conn.close()
    assert unsent == 0
    assert sent == 4
    assert "Baseline initialized" in out.getvalue()


def test_confirm_does_not_touch_already_sent_notifications_differently(isolated_db):
    ids = _seed_notifications(isolated_db, 3)
    conn = isolated_db()
    conn.execute("UPDATE notifications SET email_sent = 1 WHERE id = ?", (ids[0],))
    conn.commit()
    conn.close()

    baseline.run(baseline.parse_args(["--confirm"]), out=io.StringIO())

    conn = isolated_db()
    sent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 1").fetchone()[0]
    conn.close()
    assert sent == 3  # the 1 already-sent + the 2 newly-baselined


def test_confirm_never_touches_first_seen_or_last_seen(isolated_db):
    ids = _seed_notifications(isolated_db, 2)
    conn = isolated_db()
    before = {
        r["id"]: (r["first_seen"], r["last_seen"])
        for r in conn.execute("SELECT id, first_seen, last_seen FROM notifications").fetchall()
    }
    conn.close()

    baseline.run(baseline.parse_args(["--confirm"]), out=io.StringIO())

    conn = isolated_db()
    after = {
        r["id"]: (r["first_seen"], r["last_seen"])
        for r in conn.execute("SELECT id, first_seen, last_seen FROM notifications").fetchall()
    }
    conn.close()
    assert before == after


def test_confirm_never_touches_review_queue(isolated_db):
    conn = isolated_db()
    conn.execute(
        "INSERT INTO notification_review_queue "
        "(organization_id, website_id, title, url, reason, classification, hash, created_at, review_status) "
        "VALUES (1, 1, 'Ambiguous', 'https://org-a.example/r', 'no signal', 'REVIEW', 'rh', ?, 'PENDING')",
        ("2026-01-01T00:00:00",),
    )
    conn.commit()
    conn.close()
    _seed_notifications(isolated_db, 1)

    baseline.run(baseline.parse_args(["--confirm"]), out=io.StringIO())

    conn = isolated_db()
    row = conn.execute("SELECT review_status FROM notification_review_queue").fetchone()
    conn.close()
    assert row["review_status"] == "PENDING"


def test_confirm_never_deletes_notifications(isolated_db):
    _seed_notifications(isolated_db, 6)
    baseline.run(baseline.parse_args(["--confirm"]), out=io.StringIO())

    conn = isolated_db()
    total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    conn.close()
    assert total == 6


def test_confirm_with_nothing_unsent_is_a_clean_no_op(isolated_db):
    ids = _seed_notifications(isolated_db, 2)
    conn = isolated_db()
    conn.execute("UPDATE notifications SET email_sent = 1")
    conn.commit()
    conn.close()

    out = io.StringIO()
    exit_code = baseline.run(baseline.parse_args(["--confirm"]), out=out)

    assert exit_code == 0
    assert "Nothing to do" in out.getvalue()


# ---------------------------------------------------------------------------
# safety
# ---------------------------------------------------------------------------


def test_requires_explicit_dry_run_or_confirm_flag():
    with pytest.raises(SystemExit):
        baseline.parse_args([])


def test_rejects_both_flags_at_once():
    with pytest.raises(SystemExit):
        baseline.parse_args(["--dry-run", "--confirm"])


def test_runs_integrity_check_before_any_change(isolated_db):
    _seed_notifications(isolated_db, 1)
    out = io.StringIO()
    baseline.run(baseline.parse_args(["--confirm"]), out=out)
    assert "Database integrity check: ok" in out.getvalue()


# ---------------------------------------------------------------------------
# 15. historical notifications cannot accidentally be emailed after baseline
# ---------------------------------------------------------------------------


def test_after_baseline_email_digest_finds_nothing_to_send(isolated_db, monkeypatch):
    """The exact scenario Part 7/Part 15 exist to prevent: after running
    the baseline, EmailDigestService (patched to use the same isolated DB)
    must find zero unsent notifications — not the entire historical set."""
    from database.repositories import notification_repository
    from services.email_service import EmailDigestService

    monkeypatch.setattr(notification_repository, "get_connection", isolated_db)
    monkeypatch.setattr(notification_repository, "close_connection", lambda c: c.close())

    _seed_notifications(isolated_db, 50)
    baseline.run(baseline.parse_args(["--confirm"]), out=io.StringIO())

    provider = type("P", (), {"send": lambda self, recipients, subject, html_body: True})()
    service = EmailDigestService(email_provider=provider)
    digest = service.build_pending_digest()

    assert digest.included_count == 0
    assert digest.total_unsent == 0
