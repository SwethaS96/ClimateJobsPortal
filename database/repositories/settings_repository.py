"""Settings repository functions.

Contains CRUD functions for the `application_settings` table.
"""
import sqlite3
from typing import Optional, List

from database.connection import get_connection, close_connection


def insert_setting(key: str, value: str) -> bool:
    """Insert a new application setting and return True."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO application_settings
                (key, value)
            VALUES
                (?, ?)
            """,
            (key, value),
        )
        conn.commit()
        return True
    finally:
        close_connection(conn)


def get_setting(key: str) -> Optional[sqlite3.Row]:
    """Return a single application setting by key or None if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM application_settings WHERE key = ?",
            (key,),
        )
        return cur.fetchone()
    finally:
        close_connection(conn)


def get_all_settings() -> List[sqlite3.Row]:
    """Return all application settings ordered by key ascending."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM application_settings ORDER BY key ASC"
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def update_setting(key: str, value: str) -> bool:
    """Update the value of an application setting. Returns True if updated."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE application_settings SET value = ? WHERE key = ?",
            (value, key),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)


def delete_setting(key: str) -> bool:
    """Delete an application setting physically. Returns True if one row was deleted."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM application_settings WHERE key = ?",
            (key,),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)
