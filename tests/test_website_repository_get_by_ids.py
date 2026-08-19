"""Tests for `get_websites_by_ids` in database/repositories/website_repository.py.

Uses a temp, isolated SQLite database (same pattern as
tests/test_run_validation_batch.py) — never touches the real production DB.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import database.connection as connection_module
from database.repositories.website_repository import get_websites_by_ids
from database.schema import create_schema


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "climate_jobs.db"
    monkeypatch.setattr(connection_module, "DATABASE_PATH", db_path)

    conn = connection_module.get_connection()
    try:
        create_schema(conn)
        conn.execute(
            """
            INSERT INTO organizations (id, name, short_name, homepage_url, country, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (10, "Test Org", "TST", "https://example.org", "India", "Tamil Nadu",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO websites (id, organization_id, page_name, url, parser_name, is_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 10, "Recruitment", "https://example.org/1", "generic_html", 1,
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO websites (id, organization_id, page_name, url, parser_name, is_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (2, 10, "Careers", "https://example.org/2", "generic_html", 0,
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    return db_path


def test_get_websites_by_ids_returns_requested_websites(isolated_db):
    rows = get_websites_by_ids([1, 2])
    ids = {row["id"] for row in rows}
    assert ids == {1, 2}


def test_get_websites_by_ids_includes_disabled_websites(isolated_db):
    rows = get_websites_by_ids([2])
    assert len(rows) == 1
    assert rows[0]["is_enabled"] == 0


def test_get_websites_by_ids_skips_missing_ids(isolated_db):
    rows = get_websites_by_ids([1, 999])
    assert len(rows) == 1
    assert rows[0]["id"] == 1


def test_get_websites_by_ids_empty_list_returns_empty():
    assert get_websites_by_ids([]) == []
