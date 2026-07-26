"""Scrape history repository functions.

Contains CRUD functions for the `scrape_history` table.
"""
import sqlite3
from typing import Optional, List

from database.connection import get_connection, close_connection

import datetime


def _utc_iso_timestamp() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def insert_scrape_history(
    website_id: int,
    started_at: str,
    finished_at: str | None = None,
    duration_seconds: int | None = None,
    status: str = "",
    notifications_found: int = 0,
    notifications_added: int = 0,
    notifications_updated: int = 0,
    error_message: str | None = None,
) -> int:
    """Insert a new scrape history record and return its id."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO scrape_history
                (website_id, started_at, finished_at, duration_seconds, status,
                 notifications_found, notifications_added, notifications_updated, error_message)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                website_id,
                started_at,
                finished_at,
                duration_seconds,
                status,
                notifications_found,
                notifications_added,
                notifications_updated,
                error_message,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        close_connection(conn)


def get_scrape_history_by_id(scrape_history_id: int) -> Optional[sqlite3.Row]:
    """Return a single scrape history record by id or None if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM scrape_history WHERE id = ?",
            (scrape_history_id,),
        )
        return cur.fetchone()
    finally:
        close_connection(conn)


def get_all_scrape_history() -> List[sqlite3.Row]:
    """Return all scrape history records ordered by started_at descending."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM scrape_history ORDER BY started_at DESC"
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def get_scrape_history_by_website(website_id: int) -> List[sqlite3.Row]:
    """Return all scrape history records for a website ordered by started_at descending."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM scrape_history WHERE website_id = ? ORDER BY started_at DESC",
            (website_id,),
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def update_scrape_history(
    scrape_history_id: int,
    website_id: int | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    duration_seconds: int | None = None,
    status: str | None = None,
    notifications_found: int | None = None,
    notifications_added: int | None = None,
    notifications_updated: int | None = None,
    error_message: str | None = None,
) -> bool:
    """Update a scrape history record. Returns True if one row was updated."""
    fields: List[str] = []
    values: List[object] = []

    if website_id is not None:
        fields.append("website_id = ?")
        values.append(website_id)
    if started_at is not None:
        fields.append("started_at = ?")
        values.append(started_at)
    if finished_at is not None:
        fields.append("finished_at = ?")
        values.append(finished_at)
    if duration_seconds is not None:
        fields.append("duration_seconds = ?")
        values.append(duration_seconds)
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if notifications_found is not None:
        fields.append("notifications_found = ?")
        values.append(notifications_found)
    if notifications_added is not None:
        fields.append("notifications_added = ?")
        values.append(notifications_added)
    if notifications_updated is not None:
        fields.append("notifications_updated = ?")
        values.append(notifications_updated)
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)

    if not fields:
        return False

    values.append(scrape_history_id)
    sql = f"UPDATE scrape_history SET {', '.join(fields)} WHERE id = ?"

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(values))
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)


def delete_scrape_history(scrape_history_id: int) -> bool:
    """Delete a scrape history record physically. Returns True if one row was deleted."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM scrape_history WHERE id = ?",
            (scrape_history_id,),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)
