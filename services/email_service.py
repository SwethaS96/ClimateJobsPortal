"""Production email digest service.

Builds and sends ONE consolidated email per run covering every unsent
VALID notification, then marks only the notifications actually included
in a successfully-delivered email as `email_sent = 1`. REVIEW candidates
live in a separate table (`notification_review_queue`) and INVALID
candidates are never persisted at all, so the `notifications` table this
service reads from is VALID-only by construction — no extra
classification filter is needed here.

Delivery format: DATABASE -> EXCEL DIGEST -> SHORT EMAIL WITH EXCEL
ATTACHMENT. The email body itself stays short (a few sentences, no
per-notification listing) — the full notification list, with filtering
and sorting, lives in an attached .xlsx workbook built by
`ExcelDigestBuilder` from the exact same notification set
`build_pending_digest()` already selects.

The `EmailProvider` protocol keeps the delivery mechanism swappable: SMTP
today (`SMTPEmailProvider`), a different provider later, without touching
`EmailDigestService`.
"""

from __future__ import annotations

import html as html_lib
import shutil
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Protocol

from config import settings
from database.repositories import notification_repository
from services.excel_digest_builder import ExcelDigestBuilder


class EmailProvider(Protocol):
    """Abstract interface for an email delivery backend."""

    def send(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        attachment_path: str | None = None,
        attachment_filename: str | None = None,
    ) -> bool:
        """Send an HTML email, optionally with one file attached, and
        return whether the delivery succeeded."""


class SMTPEmailProvider:
    """SMTP-backed `EmailProvider`. Configuration is passed in explicitly —
    this class never reads environment variables itself, so it stays easy
    to test and to swap for a different provider later."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        use_tls: bool = True,
        timeout_seconds: int = 30,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.use_tls = use_tls
        self.timeout_seconds = timeout_seconds

    def send(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        attachment_path: str | None = None,
        attachment_filename: str | None = None,
    ) -> bool:
        if not recipients:
            return False

        message = MIMEMultipart("mixed")
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = ", ".join(recipients)

        body = MIMEMultipart("alternative")
        body.attach(MIMEText(html_body, "html"))
        message.attach(body)

        if attachment_path:
            with open(attachment_path, "rb") as handle:
                attachment = MIMEApplication(handle.read())
            attachment.add_header(
                "Content-Disposition", "attachment", filename=attachment_filename or Path(attachment_path).name
            )
            message.attach(attachment)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as server:
                if self.use_tls:
                    server.starttls()
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.sendmail(self.sender, recipients, message.as_string())
            return True
        except Exception:
            return False


@dataclass
class PendingDigest:
    """A snapshot of what a digest send would include, read-only."""

    notifications: list[dict[str, Any]]
    grouped: dict[str, list[dict[str, Any]]]
    total_unsent: int
    included_count: int
    excluded_count: int


class EmailDigestService:
    """Build and send the single consolidated production email digest."""

    def __init__(
        self,
        email_provider: EmailProvider | None = None,
        max_notifications: int | None = None,
    ) -> None:
        self.email_provider = email_provider
        self.max_notifications = (
            max_notifications if max_notifications is not None else settings.EMAIL_MAX_NOTIFICATIONS
        )

    def build_pending_digest(
        self, limit: int | None = None, notification_ids: list[int] | None = None
    ) -> PendingDigest:
        """Read-only: fetch unsent VALID notifications, grouped by
        organization. Never modifies the database.

        By default selects up to `limit` (or `self.max_notifications`)
        unsent notifications, most-recent-first per organization. Either
        one may be `None`, meaning no cap at all — every pending
        notification is included, with no silent truncation. When
        `notification_ids` is given, selects exactly those ids instead —
        still constrained to `status = 'ACTIVE' AND email_sent = 0` as a
        safety net, so an id that's already been sent or deactivated is
        silently excluded rather than re-sent. Used for a manually
        curated/verified digest (e.g. a controlled one-off test) rather
        than the routine "next N unsent" selection.
        """
        conn = notification_repository.get_connection()
        try:
            total_unsent = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE status = 'ACTIVE' AND email_sent = 0"
            ).fetchone()[0]

            if notification_ids is not None:
                if not notification_ids:
                    rows = []
                else:
                    placeholders = ",".join("?" for _ in notification_ids)
                    rows = conn.execute(
                        f"""
                        SELECT n.id, n.organization_id, o.name AS organization_name, n.title,
                               n.page_url, n.first_seen, n.last_seen, n.application_deadline,
                               n.category, n.job_type,
                               o.state AS organization_state, o.country AS organization_country,
                               w.url AS website_url,
                               (
                                   SELECT p.pdf_url FROM pdf_documents p
                                   WHERE p.notification_id = n.id
                                   ORDER BY p.id LIMIT 1
                               ) AS pdf_url
                        FROM notifications n
                        JOIN organizations o ON o.id = n.organization_id
                        JOIN websites w ON w.id = n.website_id
                        WHERE n.status = 'ACTIVE' AND n.email_sent = 0 AND n.id IN ({placeholders})
                        ORDER BY o.name COLLATE NOCASE ASC, n.first_seen DESC
                        """,
                        tuple(notification_ids),
                    ).fetchall()
            else:
                limit = self.max_notifications if limit is None else limit
                query = """
                    SELECT n.id, n.organization_id, o.name AS organization_name, n.title,
                           n.page_url, n.first_seen, n.last_seen, n.application_deadline,
                           n.category, n.job_type,
                           o.state AS organization_state, o.country AS organization_country,
                           w.url AS website_url,
                           (
                               SELECT p.pdf_url FROM pdf_documents p
                               WHERE p.notification_id = n.id
                               ORDER BY p.id LIMIT 1
                           ) AS pdf_url
                    FROM notifications n
                    JOIN organizations o ON o.id = n.organization_id
                    JOIN websites w ON w.id = n.website_id
                    WHERE n.status = 'ACTIVE' AND n.email_sent = 0
                    ORDER BY o.name COLLATE NOCASE ASC, n.first_seen DESC
                """
                if limit is None:
                    # No cap at all — every pending notification is
                    # included. No LIMIT clause, not a huge sentinel value,
                    # so there is no silent truncation at any scale.
                    rows = conn.execute(query).fetchall()
                else:
                    rows = conn.execute(query + " LIMIT ?", (limit,)).fetchall()
        finally:
            notification_repository.close_connection(conn)

        notifications = [dict(row) for row in rows]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for notification in notifications:
            grouped.setdefault(notification["organization_name"], []).append(notification)

        return PendingDigest(
            notifications=notifications,
            grouped=grouped,
            total_unsent=total_unsent,
            included_count=len(notifications),
            excluded_count=max(total_unsent - len(notifications), 0),
        )

    def render_digest_html(self, grouped: dict[str, list[dict[str, Any]]], generated_at: str) -> str:
        """Render the digest's HTML body. No raw scraped HTML is ever
        embedded — only structured fields, all HTML-escaped."""
        sections = []
        for organization_name in sorted(grouped.keys(), key=str.lower):
            items_html = []
            for notification in grouped[organization_name]:
                items_html.append(self._render_notification_html(notification))
            sections.append(
                f"<h3>{html_lib.escape(organization_name)}</h3>"
                f"<ul>{''.join(items_html)}</ul>"
            )

        return (
            "<html><body style=\"font-family: sans-serif;\">"
            "<h2>Climate Research Job Radar</h2>"
            f"<p>New recruitment notifications detected as of {html_lib.escape(generated_at)}.</p>"
            f"{''.join(sections)}"
            "</body></html>"
        )

    def _render_notification_html(self, notification: dict[str, Any]) -> str:
        title = html_lib.escape(notification.get("title") or "Untitled")
        page_url = notification.get("page_url") or ""

        link = f'<a href="{html_lib.escape(page_url, quote=True)}">{title}</a>' if page_url else title
        parts = [f"<li>{link}"]

        meta_parts = []
        job_type = notification.get("job_type")
        if job_type and job_type != "UNKNOWN":
            meta_parts.append(f"Job Type: {html_lib.escape(str(job_type))}")
        if notification.get("first_seen"):
            meta_parts.append(f"Detected: {html_lib.escape(str(notification['first_seen'])[:10])}")
        if notification.get("application_deadline"):
            meta_parts.append(f"Deadline: {html_lib.escape(str(notification['application_deadline']))}")
        if notification.get("category"):
            meta_parts.append(f"Category: {html_lib.escape(str(notification['category']))}")
        if meta_parts:
            parts.append(f"<br><small>{' &nbsp;|&nbsp; '.join(meta_parts)}</small>")

        summary = notification.get("summary")
        if summary:
            parts.append(f"<br><span>{html_lib.escape(str(summary))}</span>")

        pdf_url = notification.get("pdf_url")
        if pdf_url:
            parts.append(f'<br><a href="{html_lib.escape(pdf_url, quote=True)}">PDF / Download Notice</a>')

        parts.append("</li>")
        return "".join(parts)

    def render_short_digest_html(self, notification_count: int, generated_at: str) -> str:
        """The actual email body sent in production: short, no
        per-notification listing — the full list lives in the attached
        Excel workbook instead. Never grows with the number of
        notifications, however many thousand there are."""
        count_text = f"{notification_count:,} new opportunit{'y' if notification_count == 1 else 'ies'}"
        return (
            "<html><body style=\"font-family: sans-serif;\">"
            "<h2>ClimateJobsPortal — Recruitment Digest</h2>"
            f"<p>{html_lib.escape(generated_at)}</p>"
            f"<p>{count_text} {'is' if notification_count == 1 else 'are'} included in the attached "
            "Excel workbook.</p>"
            "<p>The workbook contains:</p>"
            "<ul>"
            "<li>New Opportunities</li>"
            "<li>Summary</li>"
            "<li>Closing Soon</li>"
            "</ul>"
            "<p>The Excel file supports filtering and sorting by the available fields.</p>"
            "<p>Please see the attached workbook for the complete list.</p>"
            "</body></html>"
        )

    def send_digest(
        self, recipients: list[str] | None = None, notification_ids: list[int] | None = None
    ) -> dict[str, Any]:
        """Send exactly one consolidated digest email for unsent VALID
        notifications — either the usual "every pending notification, or
        up to `self.max_notifications` if a cap is configured" selection,
        or exactly `notification_ids` when given (see `build_pending_digest`).

        Flow: build the digest -> generate the Excel workbook -> verify it
        was written -> send the short email with the workbook attached ->
        ONLY after successful delivery, mark every notification included
        in that exact digest as `email_sent = 1`. If Excel generation
        fails, or SMTP delivery fails, nothing is marked sent — a retry
        finds every one of those notifications still pending.
        """
        digest = self.build_pending_digest(notification_ids=notification_ids)

        if digest.included_count == 0:
            return {
                "sent": False,
                "message": "No new recruitment notifications.",
                "notifications_included": 0,
                "notifications_excluded": digest.excluded_count,
                "organizations_included": 0,
            }

        recipients = recipients if recipients is not None else settings.EMAIL_TO
        if not recipients:
            return {
                "sent": False,
                "message": "No recipients configured; email not sent.",
                "notifications_included": 0,
                "notifications_excluded": digest.total_unsent,
                "organizations_included": 0,
            }

        if self.email_provider is None:
            raise ValueError("An email provider is required")

        now = datetime.now(timezone.utc)
        generated_at_display = now.strftime("%B %d, %Y")
        subject = f"ClimateJobsPortal — Recruitment Digest — {generated_at_display}"
        html_body = self.render_short_digest_html(digest.included_count, generated_at_display)

        workbook_dir: Path | None = None
        try:
            workbook_path = ExcelDigestBuilder().build(digest.notifications, now)
            workbook_dir = workbook_path.parent
            if not workbook_path.exists() or workbook_path.stat().st_size == 0:
                raise RuntimeError("Excel workbook was not written")
        except Exception:
            if workbook_dir is not None:
                shutil.rmtree(workbook_dir, ignore_errors=True)
            return {
                "sent": False,
                "message": "Excel workbook generation failed; email not sent, no notifications marked as sent.",
                "notifications_included": 0,
                "notifications_excluded": digest.total_unsent,
                "organizations_included": 0,
            }

        try:
            try:
                delivered = self.email_provider.send(
                    recipients=recipients,
                    subject=subject,
                    html_body=html_body,
                    attachment_path=str(workbook_path),
                    attachment_filename=workbook_path.name,
                )
            except Exception:
                delivered = False
        finally:
            shutil.rmtree(workbook_dir, ignore_errors=True)

        if not delivered:
            return {
                "sent": False,
                "message": "Email delivery failed; no notifications marked as sent.",
                "notifications_included": 0,
                "notifications_excluded": digest.total_unsent,
                "organizations_included": 0,
            }

        conn = notification_repository.get_connection()
        try:
            timestamp = self._utc_timestamp()
            for notification in digest.notifications:
                conn.execute(
                    "UPDATE notifications SET email_sent = 1, updated_at = ? WHERE id = ?",
                    (timestamp, notification["id"]),
                )
            conn.commit()
        finally:
            notification_repository.close_connection(conn)

        return {
            "sent": True,
            "message": None,
            "notifications_included": digest.included_count,
            "notifications_excluded": digest.excluded_count,
            "organizations_included": len(digest.grouped),
        }

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
