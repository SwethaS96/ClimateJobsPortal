"""Tests for services.email_service.EmailDigestService.

Uses a fully isolated, temp SQLite database (monkeypatched in place of the
real production connection) and a recording fake EmailProvider — no real
email is ever sent, and the production database is never touched.
"""

from __future__ import annotations

import io
import sqlite3

import pytest
from openpyxl import load_workbook

from database.repositories import notification_repository
from database.schema import create_schema
from services.email_service import EmailDigestService


class RecordingEmailProvider:
    def __init__(self, deliver: bool = True) -> None:
        self.deliver = deliver
        self.calls: list[dict] = []

    def send(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        attachment_path: str | None = None,
        attachment_filename: str | None = None,
    ) -> bool:
        # Read the attachment now, like a real SMTP provider would — the
        # caller deletes the temp file right after send() returns, so this
        # is the only point at which the file is guaranteed to still exist.
        workbook_bytes = None
        if attachment_path:
            with open(attachment_path, "rb") as handle:
                workbook_bytes = handle.read()
        self.calls.append({
            "recipients": recipients,
            "subject": subject,
            "html_body": html_body,
            "attachment_path": attachment_path,
            "attachment_filename": attachment_filename,
            "workbook_bytes": workbook_bytes,
        })
        return self.deliver


class FailingEmailProvider:
    def send(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        attachment_path: str | None = None,
        attachment_filename: str | None = None,
    ) -> bool:
        raise RuntimeError("SMTP connection refused")


def _workbook_from_call(call):
    """Load the Excel attachment captured in a RecordingEmailProvider call."""
    return load_workbook(io.BytesIO(call["workbook_bytes"]))


def _new_opportunities_titles(call):
    ws = _workbook_from_call(call)["New Opportunities"]
    header = [c.value for c in ws[1]]
    col = header.index("Position / Job Title") + 1
    return [ws.cell(row=r, column=col).value for r in range(2, ws.max_row + 1)]


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
    # The short body no longer lists notification details...
    body = provider.calls[0]["html_body"]
    assert "1 new opportunity" in body
    assert "Research Associate Opening" not in body
    # ...the full record lives in the attached Excel workbook instead.
    assert "Research Associate Opening" in _new_opportunities_titles(provider.calls[0])


def test_subject_contains_expected_prefix_and_date(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert "ClimateJobsPortal — Recruitment Digest —" in provider.calls[0]["subject"]


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
    titles = _new_opportunities_titles(provider.calls[0])
    assert set(titles) == {"Opening A1", "Opening A2", "Opening B1"}


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

    ws = _workbook_from_call(provider.calls[0])["New Opportunities"]
    header = [c.value for c in ws[1]]
    pdf_col = header.index("Official Notice / PDF Link") + 1
    cell = ws.cell(row=2, column=pdf_col)
    assert cell.value == "https://org-a.example/notice.pdf"
    assert cell.hyperlink is not None


def test_no_pdf_link_rendered_when_absent(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    ws = _workbook_from_call(provider.calls[0])["New Opportunities"]
    header = [c.value for c in ws[1]]
    pdf_col = header.index("Official Notice / PDF Link") + 1
    assert ws.cell(row=2, column=pdf_col).value is None


def _job_types_in_workbook(call):
    ws = _workbook_from_call(call)["New Opportunities"]
    header = [c.value for c in ws[1]]
    col = header.index("Job Type") + 1
    return [ws.cell(row=r, column=col).value for r in range(2, ws.max_row + 1)]


def test_job_type_is_included_when_present(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        org_id, website_id, "Project Associate-I (PA-I)", page_url="https://org-a.example/1", hash="h1",
        job_type="PROJECT_ASSOCIATE", job_type_confidence=0.85,
    )

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert _job_types_in_workbook(provider.calls[0]) == ["PROJECT_ASSOCIATE"]


def test_unknown_job_type_is_preserved_as_stored_in_workbook(isolated_db):
    """Unlike the old per-notification email body (which suppressed
    UNKNOWN), the Excel export is a full data dump — it preserves exactly
    what's stored, including UNKNOWN, rather than hiding it."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1",
        job_type="UNKNOWN", job_type_confidence=0.0,
    )

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert _job_types_in_workbook(provider.calls[0]) == ["UNKNOWN"]


def test_null_job_type_does_not_break_workbook_generation(isolated_db):
    """A row with job_type left NULL (e.g. predates classification) must
    still produce a valid workbook — a blank cell, not a crash."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1",
    )

    provider = RecordingEmailProvider()
    result = EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert result["sent"] is True
    assert _job_types_in_workbook(provider.calls[0]) == [None]


def test_jrf_job_type_is_included_when_present(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        org_id, website_id, "Junior Research Fellow (JRF)", page_url="https://org-a.example/1", hash="h1",
        job_type="JRF", job_type_confidence=0.85,
    )

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert _job_types_in_workbook(provider.calls[0]) == ["JRF"]


def test_faculty_job_type_is_included_when_present(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        org_id, website_id, "Assistant Professor", page_url="https://org-a.example/1", hash="h1",
        job_type="FACULTY", job_type_confidence=0.85,
    )

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert _job_types_in_workbook(provider.calls[0]) == ["FACULTY"]


def test_multiple_job_types_in_one_digest_are_each_preserved_correctly(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        org_id, website_id, "JRF Opening", page_url="https://org-a.example/1", hash="h1",
        job_type="JRF", job_type_confidence=0.85,
    )
    notification_repository.insert_notification(
        org_id, website_id, "Assistant Professor", page_url="https://org-a.example/2", hash="h2",
        job_type="FACULTY", job_type_confidence=0.85,
    )
    notification_repository.insert_notification(
        org_id, website_id, "Unclassifiable Opening", page_url="https://org-a.example/3", hash="h3",
        job_type="UNKNOWN", job_type_confidence=0.0,
    )

    provider = RecordingEmailProvider()
    result = EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert result["notifications_included"] == 3
    assert set(_job_types_in_workbook(provider.calls[0])) == {"JRF", "FACULTY", "UNKNOWN"}


def test_html_escaping_not_needed_for_job_type_in_workbook_but_body_is_still_clean(isolated_db):
    """job_type is a controlled enum in normal operation. The Excel cell
    preserves the raw stored value exactly (xlsx cells don't need HTML
    escaping — that's a different storage format entirely). The short
    email body no longer echoes job_type at all, so there's nothing to
    escape there either."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(
        org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1",
        job_type="<script>alert(1)</script>", job_type_confidence=0.5,
    )

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    body = provider.calls[0]["html_body"]
    assert "<script>alert" not in body
    assert _job_types_in_workbook(provider.calls[0]) == ["<script>alert(1)</script>"]


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
    titles = _new_opportunities_titles(provider.calls[0])
    assert "Inactive Opening" not in titles
    assert "Active Opening" in titles


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
    titles = _new_opportunities_titles(provider.calls[1])
    assert "Opening 1" not in titles
    assert "Opening 2" in titles


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
    """The short email body no longer echoes title/URL at all, so there is
    no HTML-injection surface there. The Excel cell preserves the raw
    stored text exactly, unescaped — xlsx is not HTML and needs no
    escaping; that's a correct "preserve source data exactly as stored",
    not a regression."""
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
    assert "Research & Development" not in body

    titles = _new_opportunities_titles(provider.calls[0])
    assert titles == ["<script>alert('xss')</script> Research & Development Opening"]


def test_html_escaping_of_organization_name(isolated_db):
    """Same reasoning as above — the short body never echoes the
    organization name, and the Excel cell preserves it exactly as stored."""
    org_id, website_id = _seed_org_and_website(isolated_db, org_name="Org <B> & Co")
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    body = provider.calls[0]["html_body"]
    assert "Org <B> & Co" not in body

    ws = _workbook_from_call(provider.calls[0])["New Opportunities"]
    header = [c.value for c in ws[1]]
    org_col = header.index("Organization") + 1
    assert ws.cell(row=2, column=org_col).value == "Org <B> & Co"


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
    titles = _new_opportunities_titles(provider.calls[0])
    assert "Opening 0" in titles and "Opening 2" in titles and "Opening 4" in titles
    assert "Opening 1" not in titles and "Opening 3" not in titles

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
    titles = _new_opportunities_titles(provider.calls[0])
    assert "New Opening" in titles
    assert "Old Opening" not in titles


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


# ---------------------------------------------------------------------------
# 12. Unlimited mode — no cap at all, no silent truncation at any scale
# ---------------------------------------------------------------------------


def _seed_many_notifications(get_connection, org_id, website_id, count):
    for i in range(count):
        notification_repository.insert_notification(
            org_id, website_id, f"Opening {i}", page_url=f"https://org-a.example/{i}", hash=f"h{i}"
        )


def test_unlimited_mode_sends_all_pending_notifications(isolated_db):
    """max_notifications=None (unlimited) must include every pending
    notification in one digest — well past any of the old hardcoded caps
    (50, 200)."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    _seed_many_notifications(isolated_db, org_id, website_id, 300)

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider, max_notifications=None)
    result = service.send_digest(recipients=["a@example.com"])

    assert result["sent"] is True
    assert result["notifications_included"] == 300
    assert result["notifications_excluded"] == 0

    conn = isolated_db()
    total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 1").fetchone()[0]
    conn.close()
    assert total == 300
    assert sent == 300


def test_unlimited_mode_uses_settings_default_when_max_notifications_not_passed(isolated_db, monkeypatch):
    """No explicit max_notifications and EMAIL_MAX_NOTIFICATIONS unset/blank
    in the environment -> still unlimited, not silently capped."""
    import config.settings as settings_module

    monkeypatch.setattr(settings_module, "EMAIL_MAX_NOTIFICATIONS", None)

    org_id, website_id = _seed_org_and_website(isolated_db)
    _seed_many_notifications(isolated_db, org_id, website_id, 75)

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider)  # no max_notifications passed
    result = service.send_digest(recipients=["a@example.com"])

    assert result["notifications_included"] == 75


def test_zero_pending_notifications_in_unlimited_mode_sends_nothing(isolated_db):
    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider, max_notifications=None)
    result = service.send_digest(recipients=["a@example.com"])

    assert result["sent"] is False
    assert result["notifications_included"] == 0
    assert provider.calls == []


def test_unlimited_mode_successful_send_marks_every_included_notification_sent(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    _seed_many_notifications(isolated_db, org_id, website_id, 120)

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider, max_notifications=None)
    service.send_digest(recipients=["a@example.com"])

    conn = isolated_db()
    unsent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 0").fetchone()[0]
    conn.close()
    assert unsent == 0


def test_unlimited_mode_failed_send_leaves_every_notification_unsent(isolated_db):
    """A large batch that fails to deliver must leave ALL of them
    email_sent=0 — not partially marked, not any of them lost."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    _seed_many_notifications(isolated_db, org_id, website_id, 150)

    provider = RecordingEmailProvider(deliver=False)
    service = EmailDigestService(email_provider=provider, max_notifications=None)
    result = service.send_digest(recipients=["a@example.com"])

    assert result["sent"] is False

    conn = isolated_db()
    total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    unsent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 0").fetchone()[0]
    conn.close()
    assert total == 150
    assert unsent == 150


def test_unlimited_mode_does_not_truncate_past_old_hardcoded_caps(isolated_db):
    """Explicit regression guard: neither the old 50 nor the old 200
    default silently reappears — a batch bigger than both goes out whole."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    _seed_many_notifications(isolated_db, org_id, website_id, 250)

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider, max_notifications=None)
    result = service.send_digest(recipients=["a@example.com"])

    assert result["notifications_included"] == 250
    assert result["notifications_included"] != 50
    assert result["notifications_included"] != 200


def test_explicit_cap_still_works_when_configured():
    """EMAIL_MAX_NOTIFICATIONS is no longer required, but a positive
    integer must still work as an opt-in cap for anyone who wants one."""
    service = EmailDigestService(email_provider=RecordingEmailProvider(), max_notifications=10)
    assert service.max_notifications == 10


# ---------------------------------------------------------------------------
# 13. Excel digest — full send_digest() flow, exact row counts, and the
# generate -> verify -> send -> mark-sent ordering.
# ---------------------------------------------------------------------------


def test_300_pending_notifications_excel_contains_exactly_300_rows(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    _seed_many_notifications(isolated_db, org_id, website_id, 300)

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider, max_notifications=None)
    result = service.send_digest(recipients=["a@example.com"])

    assert result["notifications_included"] == 300
    ws = _workbook_from_call(provider.calls[0])["New Opportunities"]
    assert ws.max_row == 301  # header + 300 data rows


def test_1338_pending_notifications_excel_contains_exactly_1338_rows(isolated_db):
    """Mirrors the real production scenario this change was built for."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    _seed_many_notifications(isolated_db, org_id, website_id, 1338)

    provider = RecordingEmailProvider()
    service = EmailDigestService(email_provider=provider, max_notifications=None)
    result = service.send_digest(recipients=["a@example.com"])

    assert result["sent"] is True
    assert result["notifications_included"] == 1338
    ws = _workbook_from_call(provider.calls[0])["New Opportunities"]
    assert ws.max_row == 1339  # header + 1338 data rows

    conn = isolated_db()
    unsent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 0").fetchone()[0]
    conn.close()
    assert unsent == 0


def test_email_attachment_filename_matches_required_pattern(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    import re

    filename = provider.calls[0]["attachment_filename"]
    assert re.fullmatch(r"ClimateJobsPortal_\d{4}-\d{2}-\d{2}\.xlsx", filename)


def test_workbook_has_required_sheets_and_table(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    wb = _workbook_from_call(provider.calls[0])
    assert wb.sheetnames == ["New Opportunities", "Summary", "Closing Soon"]
    ws = wb["New Opportunities"]
    assert "NewOpportunities" in ws.tables
    assert ws.tables["NewOpportunities"].autoFilter is not None
    assert ws.freeze_panes == "A2"


def test_excel_generation_failure_sends_no_email_and_marks_nothing_sent(isolated_db, monkeypatch):
    """If workbook generation raises, send_digest() must not call the
    email provider at all, and every pending notification must remain
    email_sent=0 — verified with a real, unfaked provider so any call to
    it would raise and fail the test."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    import services.email_service as email_service_module

    class BrokenExcelDigestBuilder:
        def build(self, notifications, generated_at):
            raise RuntimeError("openpyxl blew up")

    monkeypatch.setattr(email_service_module, "ExcelDigestBuilder", BrokenExcelDigestBuilder)

    class ProviderThatMustNeverBeCalled:
        def send(self, *args, **kwargs):
            raise AssertionError("email provider must not be called when Excel generation fails")

    result = EmailDigestService(email_provider=ProviderThatMustNeverBeCalled()).send_digest(
        recipients=["a@example.com"]
    )

    assert result["sent"] is False
    assert "Excel" in result["message"]

    conn = isolated_db()
    unsent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 0").fetchone()[0]
    conn.close()
    assert unsent == 1


def test_excel_generation_failure_with_empty_workbook_file_also_blocks_sending(isolated_db, monkeypatch, tmp_path):
    """Defensive check: even if build() doesn't raise but produces a
    missing/empty file, send_digest() must still refuse to send."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    import services.email_service as email_service_module

    # A dedicated subdirectory of its own — send_digest() cleans up
    # workbook_path.parent on failure, so this must NOT be the same
    # directory pytest's isolated_db fixture put the test database in.
    fake_workbook_dir = tmp_path / "fake_workbook_output"
    fake_workbook_dir.mkdir()
    empty_path = fake_workbook_dir / "empty.xlsx"
    empty_path.touch()  # zero bytes

    class EmptyFileExcelDigestBuilder:
        def build(self, notifications, generated_at):
            return empty_path

    monkeypatch.setattr(email_service_module, "ExcelDigestBuilder", EmptyFileExcelDigestBuilder)

    class ProviderThatMustNeverBeCalled:
        def send(self, *args, **kwargs):
            raise AssertionError("email provider must not be called when the workbook file is empty")

    result = EmailDigestService(email_provider=ProviderThatMustNeverBeCalled()).send_digest(
        recipients=["a@example.com"]
    )

    assert result["sent"] is False
    conn = isolated_db()
    unsent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 0").fetchone()[0]
    conn.close()
    assert unsent == 1


def test_send_digest_flow_order_generate_verify_send_then_mark_sent(isolated_db):
    """End-to-end proof of the required flow: build digest -> generate
    Excel -> verify -> send with attachment -> only then mark sent."""
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_id = notification_repository.insert_notification(
        org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1"
    )

    provider = RecordingEmailProvider()
    result = EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    assert result["sent"] is True
    call = provider.calls[0]
    assert call["attachment_path"] is not None  # a real file existed at send() time
    assert call["workbook_bytes"] is not None
    assert len(call["workbook_bytes"]) > 0

    conn = isolated_db()
    row = conn.execute("SELECT email_sent FROM notifications WHERE id = ?", (notification_id,)).fetchone()
    conn.close()
    assert row["email_sent"] == 1


def test_temp_workbook_directory_is_cleaned_up_after_send(isolated_db):
    org_id, website_id = _seed_org_and_website(isolated_db)
    notification_repository.insert_notification(org_id, website_id, "Opening", page_url="https://org-a.example/1", hash="h1")

    provider = RecordingEmailProvider()
    EmailDigestService(email_provider=provider).send_digest(recipients=["a@example.com"])

    import os

    attachment_path = provider.calls[0]["attachment_path"]
    assert not os.path.exists(attachment_path)  # cleaned up after the send completed
