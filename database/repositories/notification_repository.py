"""Notification repository functions.

Contains CRUD functions for the `notifications` table.
"""
import sqlite3
from typing import Optional, List

from database.connection import get_connection, close_connection

import datetime


def _utc_iso_timestamp() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def insert_notification(
    organization_id: int,
    website_id: int,
    title: str,
    notification_number: str | None = None,
    category: str | None = None,
    notification_date: str | None = None,
    application_deadline: str | None = None,
    page_url: str | None = None,
    hash: str = None,
) -> int:
    """Insert a new notification and return its id."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        ts = _utc_iso_timestamp()
        try:
            cur.execute(
                """
                INSERT INTO notifications
                    (organization_id, website_id, title, notification_number, category,
                     notification_date, application_deadline, status, page_url, hash,
                     first_seen, last_seen, created_at, updated_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    organization_id,
                    website_id,
                    title,
                    notification_number,
                    category,
                    notification_date,
                    application_deadline,
                    "ACTIVE",
                    page_url,
                    hash,
                    ts,
                    ts,
                    ts,
                    ts,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "notifications.hash" in str(exc):
                raise ValueError("Notification with this hash already exists.") from exc
            raise
        conn.commit()
        return int(cur.lastrowid)
    finally:
        close_connection(conn)


def get_notification_by_hash(hash_value: str) -> Optional[sqlite3.Row]:
    """Return a single active notification matching `hash_value`, or None."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM notifications WHERE hash = ? AND status = 'ACTIVE'",
            (hash_value,),
        )
        return cur.fetchone()
    finally:
        close_connection(conn)


def touch_last_seen(notification_id: int) -> bool:
    """Update `last_seen` (and `updated_at`) for an active notification to now.

    Returns True if a row was updated.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        ts = _utc_iso_timestamp()
        cur.execute(
            "UPDATE notifications SET last_seen = ?, updated_at = ? WHERE id = ? AND status = 'ACTIVE'",
            (ts, ts, notification_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)


def get_notification_by_id(notification_id: int) -> Optional[sqlite3.Row]:
    """Return a single active notification by id or None if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM notifications WHERE id = ? AND status = 'ACTIVE'",
            (notification_id,),
        )
        return cur.fetchone()
    finally:
        close_connection(conn)


def get_all_notifications() -> List[sqlite3.Row]:
    """Return all active notifications ordered by notification_date descending."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM notifications WHERE status = 'ACTIVE' ORDER BY notification_date DESC"
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def get_unsent_notifications() -> List[sqlite3.Row]:
    """Return all active, not-yet-emailed notifications, joined with their
    organization name and first linked PDF url (if any). Read-only —
    used by the email digest and by read-only audit tooling.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT n.id, n.organization_id, o.name AS organization_name, n.title,
                   n.page_url, n.first_seen, n.application_deadline, n.category,
                   (
                       SELECT p.pdf_url FROM pdf_documents p
                       WHERE p.notification_id = n.id
                       ORDER BY p.id LIMIT 1
                   ) AS pdf_url
            FROM notifications n
            JOIN organizations o ON o.id = n.organization_id
            WHERE n.status = 'ACTIVE' AND n.email_sent = 0
            ORDER BY o.name COLLATE NOCASE ASC, n.id ASC
            """
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def get_notifications_by_website(website_id: int) -> List[sqlite3.Row]:
    """Return all active notifications for a specific website."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM notifications WHERE website_id = ? AND status = 'ACTIVE' ORDER BY notification_date DESC",
            (website_id,),
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def update_notification(
    notification_id: int,
    title: str | None = None,
    notification_number: str | None = None,
    category: str | None = None,
    notification_date: str | None = None,
    application_deadline: str | None = None,
    status: str | None = None,
    page_url: str | None = None,
) -> bool:
    """Update an active notification. Returns True if one row was updated."""
    fields: List[str] = []
    values: List[object] = []

    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if notification_number is not None:
        fields.append("notification_number = ?")
        values.append(notification_number)
    if category is not None:
        fields.append("category = ?")
        values.append(category)
    if notification_date is not None:
        fields.append("notification_date = ?")
        values.append(notification_date)
    if application_deadline is not None:
        fields.append("application_deadline = ?")
        values.append(application_deadline)
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if page_url is not None:
        fields.append("page_url = ?")
        values.append(page_url)

    if not fields:
        return False

    fields.append("updated_at = ?")
    values.append(_utc_iso_timestamp())
    values.append(notification_id)

    sql = f"UPDATE notifications SET {', '.join(fields)} WHERE id = ? AND status = 'ACTIVE'"

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(values))
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)


def soft_delete_notification(notification_id: int) -> bool:
    """Soft-delete a notification by marking it inactive."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE notifications
            SET status = 'INACTIVE',
                updated_at = ?
            WHERE id = ? AND status = 'ACTIVE'
            """,
            (_utc_iso_timestamp(), notification_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)
