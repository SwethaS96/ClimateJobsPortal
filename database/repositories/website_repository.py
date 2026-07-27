"""Website repository functions.

Contains CRUD functions for the `websites` table.
"""
import sqlite3
from typing import Optional, List

from database.connection import get_connection, close_connection

import datetime


def _utc_iso_timestamp() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def insert_website(
    organization_id: int,
    page_name: str,
    url: str,
    parser_name: str | None = None,
    parser_metadata: str | None = None,
    user_agent: str | None = None,
    timeout_seconds: int | None = None,
    scrape_interval_minutes: int | None = None,
) -> int:
    """Insert a new website and return its id."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        ts = _utc_iso_timestamp()
        cur.execute(
            """
            INSERT INTO websites
                (organization_id, page_name, url, parser_name, parser_metadata,
                 user_agent, timeout_seconds, scrape_interval_minutes,
                 is_enabled, created_at, updated_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                page_name,
                url,
                parser_name,
                parser_metadata,
                user_agent,
                timeout_seconds,
                scrape_interval_minutes,
                1,
                ts,
                ts,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        close_connection(conn)


def get_website_by_id(website_id: int) -> Optional[sqlite3.Row]:
    """Return a single enabled website by id or None if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, organization_id, page_name, url, parser_name, parser_metadata,
                   user_agent, timeout_seconds, scrape_interval_minutes, is_enabled,
                   last_scraped, created_at, updated_at
            FROM websites
            WHERE id = ? AND is_enabled = 1
            """,
            (website_id,),
        )
        return cur.fetchone()
    finally:
        close_connection(conn)


def get_all_websites() -> List[sqlite3.Row]:
    """Return all enabled websites ordered by organization and page name."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, organization_id, page_name, url, parser_name, parser_metadata,
                   user_agent, timeout_seconds, scrape_interval_minutes, is_enabled,
                   last_scraped, created_at, updated_at
            FROM websites
            WHERE is_enabled = 1
            ORDER BY organization_id ASC, page_name COLLATE NOCASE ASC
            """
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def get_websites_by_organization(organization_id: int) -> List[sqlite3.Row]:
    """Return all enabled websites for a specific organization."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, organization_id, page_name, url, parser_name, parser_metadata,
                   user_agent, timeout_seconds, scrape_interval_minutes, is_enabled,
                   last_scraped, created_at, updated_at
            FROM websites
            WHERE organization_id = ? AND is_enabled = 1
            ORDER BY page_name COLLATE NOCASE ASC
            """,
            (organization_id,),
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def update_website(
    website_id: int,
    page_name: str | None = None,
    url: str | None = None,
    parser_name: str | None = None,
    parser_metadata: str | None = None,
    user_agent: str | None = None,
    timeout_seconds: int | None = None,
    scrape_interval_minutes: int | None = None,
    is_enabled: bool | None = None,
) -> bool:
    """Update an enabled website. Returns True if one row was updated."""
    fields: List[str] = []
    values: List[object] = []

    if page_name is not None:
        fields.append("page_name = ?")
        values.append(page_name)
    if url is not None:
        fields.append("url = ?")
        values.append(url)
    if parser_name is not None:
        fields.append("parser_name = ?")
        values.append(parser_name)
    if parser_metadata is not None:
        fields.append("parser_metadata = ?")
        values.append(parser_metadata)
    if user_agent is not None:
        fields.append("user_agent = ?")
        values.append(user_agent)
    if timeout_seconds is not None:
        fields.append("timeout_seconds = ?")
        values.append(timeout_seconds)
    if scrape_interval_minutes is not None:
        fields.append("scrape_interval_minutes = ?")
        values.append(scrape_interval_minutes)
    if is_enabled is not None:
        fields.append("is_enabled = ?")
        values.append(1 if is_enabled else 0)

    if not fields:
        return False

    fields.append("updated_at = ?")
    values.append(_utc_iso_timestamp())
    values.append(website_id)

    sql = f"UPDATE websites SET {', '.join(fields)} WHERE id = ?"

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(values))
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)


def soft_delete_website(website_id: int) -> bool:
    """Soft-delete a website by disabling it and updating its timestamp."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE websites
            SET is_enabled = 0,
                updated_at = ?
            WHERE id = ? AND is_enabled = 1
            """,
            (_utc_iso_timestamp(), website_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)
