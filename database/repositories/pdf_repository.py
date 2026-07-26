"""PDF repository functions.

Contains CRUD functions for the `pdf_documents` table.
"""
import sqlite3
from typing import Optional, List

from database.connection import get_connection, close_connection

import datetime


def _utc_iso_timestamp() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def insert_pdf_document(
    notification_id: int,
    document_type: str | None = None,
    pdf_url: str | None = None,
    local_file: str | None = None,
    checksum: str | None = None,
    downloaded: bool | None = False,
    downloaded_at: str | None = None,
    file_size: int | None = None,
) -> int:
    """Insert a new PDF document and return its id."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pdf_documents
                (notification_id, document_type, pdf_url, local_file, checksum,
                 downloaded, downloaded_at, file_size)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                notification_id,
                document_type,
                pdf_url,
                local_file,
                checksum,
                1 if downloaded else 0,
                downloaded_at,
                file_size,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        close_connection(conn)


def get_pdf_document_by_id(pdf_document_id: int) -> Optional[sqlite3.Row]:
    """Return a single PDF document by id or None if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM pdf_documents WHERE id = ?",
            (pdf_document_id,),
        )
        return cur.fetchone()
    finally:
        close_connection(conn)


def get_all_pdf_documents() -> List[sqlite3.Row]:
    """Return all PDF documents ordered by id descending."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM pdf_documents ORDER BY id DESC"
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def get_pdf_documents_by_notification(notification_id: int) -> List[sqlite3.Row]:
    """Return all PDF documents for a given notification."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM pdf_documents WHERE notification_id = ? ORDER BY id DESC",
            (notification_id,),
        )
        return list(cur.fetchall())
    finally:
        close_connection(conn)


def update_pdf_document(
    pdf_document_id: int,
    document_type: str | None = None,
    pdf_url: str | None = None,
    local_file: str | None = None,
    checksum: str | None = None,
    downloaded: bool | None = None,
    downloaded_at: str | None = None,
    file_size: int | None = None,
) -> bool:
    """Update a PDF document. Returns True if one row was updated."""
    fields: List[str] = []
    values: List[object] = []

    if document_type is not None:
        fields.append("document_type = ?")
        values.append(document_type)
    if pdf_url is not None:
        fields.append("pdf_url = ?")
        values.append(pdf_url)
    if local_file is not None:
        fields.append("local_file = ?")
        values.append(local_file)
    if checksum is not None:
        fields.append("checksum = ?")
        values.append(checksum)
    if downloaded is not None:
        fields.append("downloaded = ?")
        values.append(1 if downloaded else 0)
    if downloaded_at is not None:
        fields.append("downloaded_at = ?")
        values.append(downloaded_at)
    if file_size is not None:
        fields.append("file_size = ?")
        values.append(file_size)

    if not fields:
        return False

    values.append(pdf_document_id)
    sql = f"UPDATE pdf_documents SET {', '.join(fields)} WHERE id = ?"

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(values))
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)


def delete_pdf_document(pdf_document_id: int) -> bool:
    """Delete a PDF document physically. Returns True if one row was deleted."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM pdf_documents WHERE id = ?",
            (pdf_document_id,),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_connection(conn)
