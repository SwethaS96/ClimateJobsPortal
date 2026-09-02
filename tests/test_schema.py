"""Tests for database/schema.py's additive migration mechanism
(ADDED_COLUMNS_BY_TABLE + create_schema()) — Phase 42's job_type /
job_type_confidence migration in particular.

Always uses a temp file/in-memory SQLite database — never the production
database.
"""

from __future__ import annotations

import sqlite3

from database.schema import ADDED_COLUMNS_BY_TABLE, create_schema


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    return {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_database_gets_job_type_columns():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    cols = _columns(conn, "notifications")
    assert "job_type" in cols
    assert "job_type_confidence" in cols
    assert cols["job_type"] == "TEXT"
    assert cols["job_type_confidence"] == "REAL"


def test_create_schema_is_idempotent_on_a_fresh_database():
    """Running create_schema() twice on a brand-new database must not
    raise (e.g. duplicate-column ALTER TABLE errors)."""
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    create_schema(conn)  # must not raise
    cols = _columns(conn, "notifications")
    assert "job_type" in cols
    assert "job_type_confidence" in cols


def test_migrating_a_pre_job_type_database_adds_columns_without_touching_data():
    """Simulates Phase 42's exact real-world scenario: an existing database
    created BEFORE job_type/job_type_confidence existed, with real rows
    already in it, then migrated via create_schema()."""
    conn = sqlite3.connect(":memory:")

    # Build the schema as it existed before job_type/job_type_confidence
    # were added — i.e. skip them out of ADDED_COLUMNS_BY_TABLE for this
    # first pass, to reproduce the pre-migration production shape.
    from database.schema import TABLES, INDEXES

    cursor = conn.cursor()
    for statement in TABLES:
        cursor.execute(statement)
    for table_name, added_columns in ADDED_COLUMNS_BY_TABLE.items():
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        for column_name, column_type in added_columns.items():
            if column_name in ("job_type", "job_type_confidence"):
                continue  # deliberately omitted, simulating pre-Phase-42 state
            if column_name not in existing_columns:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
    for statement in INDEXES:
        cursor.execute(statement)
    conn.commit()

    assert "job_type" not in _columns(conn, "notifications")

    conn.execute(
        "INSERT INTO organizations (name, created_at, updated_at) VALUES ('Org', 't', 't')"
    )
    conn.execute(
        "INSERT INTO websites (organization_id, page_name, url, created_at, updated_at) "
        "VALUES (1, 'Careers', 'https://example.org', 't', 't')"
    )
    conn.execute(
        "INSERT INTO notifications (organization_id, website_id, title, hash, first_seen, "
        "last_seen, created_at, updated_at) VALUES (1, 1, 'Existing Notice', 'h1', 't', 't', 't', 't')"
    )
    conn.commit()

    row_before = dict(zip(
        [d[0] for d in conn.execute("SELECT * FROM notifications").description],
        conn.execute("SELECT * FROM notifications WHERE id = 1").fetchone(),
    ))

    # Now apply the real, current create_schema() — this is the Phase 42 migration.
    create_schema(conn)

    cols = _columns(conn, "notifications")
    assert "job_type" in cols
    assert "job_type_confidence" in cols

    count = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    assert count == 1  # no rows lost, none duplicated

    row_after = conn.execute("SELECT * FROM notifications WHERE id = 1").fetchone()
    row_after_dict = dict(zip([d[0] for d in conn.execute("SELECT * FROM notifications").description], row_after))

    for key, value in row_before.items():
        assert row_after_dict[key] == value  # every pre-existing field untouched

    assert row_after_dict["job_type"] is None  # migration never backfills
    assert row_after_dict["job_type_confidence"] is None


def test_running_create_schema_a_second_time_after_migration_changes_nothing():
    """Phase 42 Part N: applying the migration twice must be a true no-op
    the second time — no duplicate-column errors, no data changes."""
    conn = sqlite3.connect(":memory:")
    create_schema(conn)

    conn.execute(
        "INSERT INTO organizations (name, created_at, updated_at) VALUES ('Org', 't', 't')"
    )
    conn.execute(
        "INSERT INTO websites (organization_id, page_name, url, created_at, updated_at) "
        "VALUES (1, 'Careers', 'https://example.org', 't', 't')"
    )
    conn.execute(
        "INSERT INTO notifications (organization_id, website_id, title, hash, first_seen, "
        "last_seen, created_at, updated_at, job_type, job_type_confidence) "
        "VALUES (1, 1, 'Existing Notice', 'h1', 't', 't', 't', 't', 'JRF', 0.9)"
    )
    conn.commit()

    cols_before = _columns(conn, "notifications")
    row_before = dict(zip(
        [d[0] for d in conn.execute("SELECT * FROM notifications").description],
        conn.execute("SELECT * FROM notifications WHERE id = 1").fetchone(),
    ))

    create_schema(conn)  # second run — must be a no-op

    cols_after = _columns(conn, "notifications")
    assert cols_after == cols_before

    count = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    assert count == 1

    row_after = conn.execute("SELECT * FROM notifications WHERE id = 1").fetchone()
    row_after_dict = dict(zip([d[0] for d in conn.execute("SELECT * FROM notifications").description], row_after))
    assert row_after_dict == row_before
    assert row_after_dict["job_type"] == "JRF"
    assert row_after_dict["job_type_confidence"] == 0.9
