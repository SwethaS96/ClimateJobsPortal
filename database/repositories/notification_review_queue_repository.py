"""Review queue repository functions.

Contains CRUD functions for the `notification_review_queue` table, which
holds REVIEW-classified candidates: recruitment-related links the
classifier could not confidently call VALID or INVALID.
"""
import sqlite3
from typing import Optional, List

from database.connection import get_connection, close_connection

import datetime


def _utc_iso_timestamp() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def insert_review_candidate(
    organization_id: int,
    website_id: int,
    title: str,
    url: str | None = None,
    reason: str | None = None,
    classification: str = "REVIEW",
    raw_html: str | None = None,
    metadata: str | None = None,
    hash: str = None,
) -> int:
    """Insert a new review-queue candidate and return its id.

    Raises:
        ValueError: when a candidate with this `hash` is already queued.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        ts = _utc_iso_timestamp()
        try:
            cur.execute(
                """
                INSERT INTO notification_review_queue
                    (organization_id, website_id, title, url, reason, classification,
                     raw_html, metadata, hash, created_at, review_status)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    organization_id,
                    website_id,
                    title,
                    url,
                    reason,
                    classification,
                    raw_html,
                    metadata,
                    hash,
                    ts,
                    "PENDING",
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "notification_review_queue.hash" in str(exc):
                raise ValueError("Review candidate with this hash is already queued.") from exc
            raise
        conn.commit()
        return int(cur.lastrowid)
    finally:
        close_connection(conn)


def get_review_candidate_by_hash(hash_value: str) -> Optional[sqlite3.Row]:
    """Return a single review-queue candidate matching `hash_value`, or None."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM notification_review_queue WHERE hash = ?",
            (hash_value,),
        )
        return cur.fetchone()
    finally:
        close_connection(conn)


def get_review_candidate_by_id(review_id: int) -> Optional[sqlite3.Row]:
    """Return a single review-queue candidate by id, or None if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM notification_review_queue WHERE id = ?",
            (review_id,),
        )
        return cur.fetchone()
    finally:
        close_connection(conn)


def list_pending_reviews() -> List[sqlite3.Row]:
    """Return all PENDING review-queue candidates, oldest first."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM notification_review_queue WHERE review_status = 'PENDING' ORDER BY created_at ASC"
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def get_all_review_candidates() -> List[sqlite3.Row]:
    """Return every review-queue candidate, oldest first."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM notification_review_queue ORDER BY created_at ASC")
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def mark_reviewed(review_id: int, review_status: str = "RESOLVED") -> bool:
    """Mark a PENDING review candidate as reviewed.

    Sets `reviewed_at` to now and `review_status` to `review_status`.
    Returns True if one row was updated (i.e. it existed and was PENDING).
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE notification_review_queue
            SET review_status = ?,
                reviewed_at = ?
            WHERE id = ? AND review_status = 'PENDING'
            """,
            (review_status, _utc_iso_timestamp(), review_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)
