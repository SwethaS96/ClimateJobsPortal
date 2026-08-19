"""Tests for services.email_service.EmailDigestService.

Uses a fully isolated, temp SQLite database (monkeypatched in place of the
real production connection) and a recording fake EmailProvider — no real
email is ever sent, and the production database is never touched.
"""

from __future__ import annotations

import sqlite3

import pytest

from database.repositories import notification_repository
from database.schema import create_schema
from services.email_service import EmailDigestService


class RecordingEmailProvider:
    def __init__(self, deliver: bool = True) -> None:
        self.deliver = deliver
        self.calls: list[dict] = []

    def send(self, recipients: list[str], subject: str, html_body: str) -> bool:
        self.calls.append({"recipients": recipients, "subject": subject, "html_body": html_body})
        return self.deliver


class FailingEmailProvider:
    def send(self, recipients: list[str], subject: str, html_body: str) -> bool:
        raise RuntimeError("SMTP connection refused")


@pytest.fixture()
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test_email_service.db"
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


def _seed_org_and_website(get_connection, org_name="Org A", website_url="https://org-a.example/jobs"):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO organizations (name, short_name, homepage_url, country, state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (org_name, org_name[:3].upper(), f"https://{org_name}.example", "India", "Tamil Nadu",
         "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    org_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (org_id, "Jobs", website_url, "generic_html", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    website_id = cur.lastrowid
    conn.commit()
    conn.close()
    return org_id, website_id


def _insert_pdf(get_connection, notification_id, pdf_url):
    conn = get_connection()
    conn.execute(
        "INSERT INTO pdf_documents (notification_id, document_type, pdf_url, downloaded) VALUES (?, ?, ?, ?)",
        (notification_id, "notice", pdf_url, 0),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 1. No unsent notifications -> no email
# ---------------------------------------------------------------------------


def test_no_unsent_notifications_sends_no_email(isolated_db):
    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider)

    result = service.send_digest(recipients=["alerts@example.com"])

    assert result["sent"] is False
    assert result["message"] == "No new recruitment notifications."
    assert provider.calls == []


# ---------------------------------------------------------------------------
# 2. One notification -> one digest
# ---------------------------------------------------------------------------


def test_single_notification_sends_one_digest_email(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        org_id, website_id, "Research Associate Opening", page_url="https://org-a.example/1", hash="hash-1"
    )

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider)
    result = service.send_digest(recipients=["alerts@example.com"])

    assert result["sent"] is True
    assert result["notifications_included"] == 1
    assert len(provider.calls) == 1
    assert "Org A" in provider.calls[0]["html_body"]
    assert "Research Associate Opening" in provider.calls[0]["html_body"]


def test_subject_contains_expected_prefix_and_date(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert "Climate Research Job Radar — New Recruitment Alerts —" in provider.calls[0]["subject"]


# ---------------------------------------------------------------------------
# 3. Multiple organizations -> grouped digest
# ---------------------------------------------------------------------------


def test_multiple_organizations_grouped_in_one_email(isolated_db):
    org_a, site_a = _seed_org_and_website(isolated_db, "Org A", "https://org-a.example/jobs")
    org_b, site_b = _seed_org_and_website(isolated_db, "Org B", "https://org-b.example/jobs")
    notification_repository.insert_notification(org_a, site_a, "Opening A1", page_url="https://org-a.example/1", hash="h1")
    notification_repository.insert_notification(org_a, site_a, "Opening A2", page_url="https://org-a.example/2", hash="h2")
    notification_repository.insert_notification(org_b, site_b, "Opening B1", page_url="https://org-b.example/1", hash="h3")

    provider = RecordingEmailProvider()
    result = EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert result["sent"] is True
    assert result["organizations_included"] == 2
    assert result["notifications_included"] == 3
    assert len(provider.calls) == 1  # exactly ONE consolidated email, not one per org/job
    body = provider.calls[0]["html_body"]
    assert "Org A" in body and "Org B" in body
    assert "Opening A1" in body and "Opening B1" in body


# ---------------------------------------------------------------------------
# 4. PDF link included
# ---------------------------------------------------------------------------


def test_pdf_link_is_included_when_present(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_id = notification_repository.insert_notification(
        org_id, website_id, "SRF Opening", page_url="https://org-a.example/1", hash="h1"
    )
    _insert_pdf(isolated_db, notification_id, "https://org-a.example/notice.pdf")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    body = provider.calls[0]["html_body"]
    assert "PDF / Download Notice" in body
    assert "https://org-a.example/notice.pdf" in body


def test_no_pdf_link_rendered_when_absent(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert "PDF / Download Notice" not in provider.calls[0]["html_body"]


# ---------------------------------------------------------------------------
# 5. REVIEW candidates excluded (they live in notification_review_queue,
#    a separate table, structurally never reachable by the digest query)
# ---------------------------------------------------------------------------


def test_review_queue_candidates_are_never_included(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Valid Opening", page_url="https://org-a.example/1", hash="h1")

    conn = isolated_db()
    conn.execute(
        "INSERT INTO notification_review_queue "
        "(organization_id, website_id, title, url, reason, classification, hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (org_id, website_id, "Ambiguous Notice", "https://org-a.example/2", "no signal", "REVIEW", "rhash", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    provider = RecordingEmailProvider()
    result = EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert result["notifications_included"] == 1
    assert "Ambiguous Notice" not in provider.calls[0]["html_body"]


# ---------------------------------------------------------------------------
# 6. INVALID / inactive notifications excluded
# ---------------------------------------------------------------------------


def test_inactive_status_notifications_are_excluded(isolated_db):
    """INVALID candidates are discarded during scraping and never persisted
    at all, so there's no INVALID row to seed here. The equivalent,
    testable safety property against this same table is that only
    status='ACTIVE' rows are ever included — a soft-deleted/inactive
    notification must not be emailed."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Active Opening", page_url="https://org-a.example/1", hash="h1")
    inactive_id = notification_repository.insert_notification(
        org_id, website_id, "Inactive Opening", page_url="https://org-a.example/2", hash="h2"
    )
    conn = isolated_db()
    conn.execute("UPDATE notifications SET status = 'INACTIVE' WHERE id = ?", (inactive_id,))
    conn.commit()
    conn.close()

    provider = RecordingEmailProvider()
    result = EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert result["notifications_included"] == 1
    assert "Inactive Opening" not in provider.calls[0]["html_body"]
    assert "Active Opening" in provider.calls[0]["html_body"]


# ---------------------------------------------------------------------------
# 7 & 8. email_sent only becomes true after a successful delivery
# ---------------------------------------------------------------------------


def test_email_sent_remains_false_when_delivery_fails(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_id = notification_repository.insert_notification(
        org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1"
    )

    provider = RecordingEmailProvider(deliver=False)
    result = EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert result["sent"] is False
    assert result["message"] == "Email delivery failed; no notifications marked as sent."

    conn = isolated_db()
    row = conn.execute("SELECT email_sent FROM notifications WHERE id = ?", (notification_id,)).fetchone()
    conn.close()
    assert row["email_sent"] == 0


def test_email_sent_remains_false_when_provider_raises(isolated_db):
    """A provider that raises (e.g. an unhandled SMTP connection error) is
    treated the same as a failed delivery — it must not crash the digest
    process or mark anything as sent."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_id = notification_repository.insert_notification(
        org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1"
    )

    result = EmailDigestService(email_provider=FailingEmailProvider()).send_digest(recipients=["a@example.com"])

    assert result["sent"] is False
    conn = isolated_db()
    row = conn.execute("SELECT email_sent FROM notifications WHERE id = ?", (notification_id,)).fetchone()
    conn.close()
    assert row["email_sent"] == 0


def test_email_sent_becomes_true_only_after_successful_delivery(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_id = notification_repository.insert_notification(
        org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1"
    )

    provider = RecordingEmailProvider(deliver=True)
    result = EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert result["sent"] is True
    conn = isolated_db()
    row = conn.execute("SELECT email_sent FROM notifications WHERE id = ?", (notification_id,)).fetchone()
    conn.close()
    assert row["email_sent"] == 1


# ---------------------------------------------------------------------------
# 9. second digest does not resend already-sent notifications
# ---------------------------------------------------------------------------


def test_second_digest_does_not_resend_already_sent_notifications(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening 1", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider)

    first = service.send_digest(recipients=["a@example.com"])
    assert first["sent"] is True
    assert len(provider.calls) == 1

    second = service.send_digest(recipients=["a@example.com"])
    assert second["sent"] is False
    assert second["message"] == "No new recruitment notifications."
    assert len(provider.calls) == 1  # no second email sent

    # A newly-added notification after the first send IS picked up.
    notification_repository.insert_notification(org_id, website_id, "Opening 2", page_url="https://org-a.example/2", hash="h2")
    third = service.send_digest(recipients=["a@example.com"])
    assert third["sent"] is True
    assert third["notifications_included"] == 1
    assert len(provider.calls) == 2
    assert "Opening 1" not in provider.calls[1]["html_body"]
    assert "Opening 2" in provider.calls[1]["html_body"]


# ---------------------------------------------------------------------------
# 10. partial/limited digest leaves excluded notifications unsent
# ---------------------------------------------------------------------------


def test_limit_leaves_excluded_notifications_unsent(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    ids = [
        notification_repository.insert_notification(
            org_id, website_id, f"Opening {i}", page_url=f"https://org-a.example/{i}", hash=f"h{i}"
        )
        for i in range(5)
    ]

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider, max_notifications=2)
    result = service.send_digest(recipients=["a@example.com"])

    assert result["sent"] is True
    assert result["notifications_included"] == 2
    assert result["notifications_excluded"] == 3

    conn = isolated_db()
    rows = conn.execute("SELECT id, email_sent FROM notifications ORDER BY id").fetchall()
    conn.close()
    sent_count = sum(1 for r in rows if r["email_sent"] == 1)
    unsent_count = sum(1 for r in rows if r["email_sent"] == 0)
    assert sent_count == 2
    assert unsent_count == 3
    assert len(ids) == 5  # sanity: all 5 rows accounted for


def test_limit_does_not_silently_discard_excluded_notifications(isolated_db):
    """The excluded notifications must remain fully intact and eligible for
    a future digest — not deleted, not modified beyond email_sent."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    for i in range(3):
        notification_repository.insert_notification(
            org_id, website_id, f"Opening {i}", page_url=f"https://org-a.example/{i}", hash=f"h{i}"
        )

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider, max_notifications=1)
    service.send_digest(recipients=["a@example.com"])

    conn = isolated_db()
    total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    conn.close()
    assert total == 3  # nothing deleted

    # The 2 excluded ones are picked up by a subsequent digest.
    second = service.send_digest(recipients=["a@example.com"])
    assert second["notifications_included"] == 1
    third = service.send_digest(recipients=["a@example.com"])
    assert third["notifications_included"] == 1
    fourth = service.send_digest(recipients=["a@example.com"])
    assert fourth["sent"] is False


# ---------------------------------------------------------------------------
# 11. HTML escaping
# ---------------------------------------------------------------------------


def test_html_escaping_of_title_and_url(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        org_id,
        website_id,
        "<script>alert('xss')</script> Research & Development Opening",
        page_url="https://org-a.example/1?a=1&b=2\"onmouseover=\"alert(1)",
        hash="h1",
    )

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    body = provider.calls[0]["html_body"]
    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body
    assert "Research &amp; Development" in body
    assert 'onmouseover="alert(1)"' not in body


def test_html_escaping_of_organization_name(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db, org_name="Org <B> & Co")
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    body = provider.calls[0]["html_body"]
    assert "<B>" not in body
    assert "Org &lt;B&gt; &amp; Co" in body


# ---------------------------------------------------------------------------
# 12. duplicate notification protection — re-touching an already-sent
# notification (as the duplicate detector does on a repeat scrape) must
# never reset email_sent, so it is never emailed a second time.
# ---------------------------------------------------------------------------


def test_touching_an_already_sent_notification_does_not_reset_email_sent(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_id = notification_repository.insert_notification(
        org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1"
    )

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider)
    service.send_digest(recipients=["a@example.com"])

    # Simulate the same notice being seen again on a later scrape —
    # NotificationService/DuplicateDetector would call touch_last_seen(),
    # never touching email_sent.
    notification_repository.touch_last_seen(notification_id)

    second = service.send_digest(recipients=["a@example.com"])
    assert second["sent"] is False
    assert second["message"] == "No new recruitment notifications."
    assert len(provider.calls) == 1


# ---------------------------------------------------------------------------
# misc safety
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# notification_ids — targeted digest (Phase 34: one-off curated test send)
# ---------------------------------------------------------------------------


def test_notification_ids_selects_exactly_those_notifications(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    ids = [
        notification_repository.insert_notification(
            org_id, website_id, f"Opening {i}", page_url=f"https://org-a.example/{i}", hash=f"h{i}"
        )
        for i in range(5)
    ]
    chosen = [ids[0], ids[2], ids[4]]

    provider = RecordingEmailProvider()
    result = EmailDigestService(email_provider=provider).send_digest(
        recipients=["a@example.com"], notification_ids=chosen
    )

    assert result["sent"] is True
    assert result["notifications_included"] == 3
    body = provider.calls[0]["html_body"]
    assert "Opening 0" in body and "Opening 2" in body and "Opening 4" in body
    assert "Opening 1" not in body and "Opening 3" not in body

    conn = isolated_db()
    rows = conn.execute("SELECT id, email_sent FROM notifications ORDER BY id").fetchall()
    conn.close()
    sent_ids = {r["id"] for r in rows if r["email_sent"] == 1}
    assert sent_ids == set(chosen)


def test_notification_ids_excludes_already_sent_even_if_requested(isolated_db):
    """Safety net: an id that's already been sent (or isn't ACTIVE/unsent)
    is silently excluded, never re-sent, even if explicitly requested."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    already_sent_id = notification_repository.insert_notification(
        org_id, website_id, "Old Opening", page_url="https://org-a.example/old", hash="hold"
    )
    conn = isolated_db()
    conn.execute("UPDATE notifications SET email_sent = 1 WHERE id = ?", (already_sent_id,))
    conn.commit()
    conn.close()
    new_id = notification_repository.insert_notification(
        org_id, website_id, "New Opening", page_url="https://org-a.example/new", hash="hnew"
    )

    provider = RecordingEmailProvider()
    result = EmailDigestService(email_provider=provider).send_digest(
        recipients=["a@example.com"], notification_ids=[already_sent_id, new_id]
    )

    assert result["notifications_included"] == 1
    assert "New Opening" in provider.calls[0]["html_body"]
    assert "Old Opening" not in provider.calls[0]["html_body"]


def test_no_recipients_configured_does_not_send(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    result = EmailDigestService(email_provider=provider).send_digest(recipients=[])

    assert result["sent"] is False
    assert provider.calls == []


def test_build_pending_digest_never_writes_to_database(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    service = EmailDigestService(email_provider=RecordingEmailProvider())
    digest = service.build_pending_digest()
    assert digest.included_count == 1

    conn = isolated_db()
    row = conn.execute("SELECT email_sent FROM notifications WHERE title = 'Opening'").fetchone()
    conn.close()
    assert row["email_sent"] == 0
