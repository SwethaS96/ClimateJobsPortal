"""Organization repository functions.

Contains CRUD functions for the `organizations` table.
"""
import sqlite3
from typing import Optional, List

from database.connection import get_connection, close_connection

import datetime


def _utc_iso_timestamp() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def insert_organization(
    name: str,
    short_name: str | None,
    homepage_url: str | None,
    country: str | None,
    state: str | None,
) -> int:
    """Insert a new organization and return its id.

    Automatically sets `created_at`, `updated_at` (UTC ISO-8601) and
    `is_active = 1`.
    Raises sqlite3.Error on DB errors.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        ts = _utc_iso_timestamp()
        cur.execute(
            """
            INSERT INTO organizations
                (name, short_name, homepage_url, country, state, is_active, created_at, updated_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, short_name, homepage_url, country, state, 1, ts, ts),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        close_connection(conn)


def get_organization_by_id(organization_id: int) -> Optional[sqlite3.Row]:
    """Return a single organization by id or None if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM organizations WHERE id = ? AND is_active = 1",
            (organization_id,),
        )
        row = cur.fetchone()
        return row
    finally:
        close_connection(conn)


def get_organization_by_name(name: str) -> Optional[sqlite3.Row]:
    """Return a single organization matching `name` or None if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM organizations WHERE name = ? AND is_active = 1",
            (name,),
        )
        return cur.fetchone()
    finally:
        close_connection(conn)


def get_all_organizations() -> List[sqlite3.Row]:
    """Return all active organizations ordered alphabetically by name."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM organizations WHERE is_active = 1 ORDER BY name COLLATE NOCASE ASC"
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def update_organization(
    organization_id: int,
    name: str,
    short_name: str | None,
    homepage_url: str | None,
    country: str | None,
    state: str | None,
) -> bool:
    """Update an organization. Returns True if one row was updated."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        ts = _utc_iso_timestamp()
        cur.execute(
            """
            UPDATE organizations
            SET name = ?,
                short_name = ?,
                homepage_url = ?,
                country = ?,
                state = ?,
                updated_at = ?
            WHERE id = ? AND is_active = 1
            """,
            (name, short_name, homepage_url, country, state, ts, organization_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)


def soft_delete_organization(organization_id: int) -> bool:
    """Soft-delete an organization by setting `is_active = 0` and updating `updated_at`.

    Uses SQLite's `CURRENT_TIMESTAMP` (UTC) in the SQL statement.
    Returns True if a row was updated.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE organizations
            SET is_active = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND is_active = 1
            """,
            (organization_id,),
        )
        conn.commit()
        return cur.rowcount >= 1
    finally:
        close_connection(conn)
