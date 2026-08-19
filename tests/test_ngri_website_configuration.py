"""Regression tests for Phase 25's NGRI (website id 15) URL correction.

Verifies (a) the seed CSV records the new dedicated recruitment subdomain
discovered in Phase 24, and (b) updating a website's url/page_name via the
existing `update_website` repository function preserves organization_id,
parser_name, timeout, scrape interval, and enabled state — using a fully
isolated temp SQLite database, never the real production DB.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import database.connection as connection_module
from database.repositories.website_repository import get_websites_by_ids, update_website
from database.schema import create_schema

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEBSITES_CSV = PROJECT_ROOT / "data" / "seeds" / "websites.csv"


def test_seed_csv_records_ngri_recruitment_subdomain():
    with WEBSITES_CSV.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    ngri_rows = [r for r in rows if r["organization_name"] == "CSIR - National Geophysical Research Institute"]
    assert len(ngri_rows) == 1
    assert ngri_rows[0]["url"] == "https://rectt.ngri.res.in"
    assert ngri_rows[0]["page_name"] == "Recruitment"


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
            (14, "CSIR - National Geophysical Research Institute", "NGRI", "https://www.ngri.res.in",
             "India", "Telangana", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO websites
                (id, organization_id, page_name, url, parser_name, user_agent,
                 timeout_seconds, scrape_interval_minutes, is_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (15, 14, "Announcements / Careers (homepage — no dedicated page confirmed)",
             "https://www.ngri.res.in", "generic_html", "ClimateJobsBot/1.0", 30, 1440, 1,
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    return db_path


def test_update_website_url_preserves_other_fields(isolated_db):
    before = dict(get_websites_by_ids([15])[0])

    ok = update_website(website_id=15, page_name="Recruitment", url="https://rectt.ngri.res.in")
    assert ok is True

    after = dict(get_websites_by_ids([15])[0])

    assert after["url"] == "https://rectt.ngri.res.in"
    assert after["page_name"] == "Recruitment"
    assert after["organization_id"] == before["organization_id"]
    assert after["parser_name"] == before["parser_name"]
    assert after["timeout_seconds"] == before["timeout_seconds"]
    assert after["scrape_interval_minutes"] == before["scrape_interval_minutes"]
    assert after["is_enabled"] == before["is_enabled"]
    assert after["user_agent"] == before["user_agent"]


def test_update_website_does_not_touch_other_websites(isolated_db):
    conn = connection_module.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO websites
                (id, organization_id, page_name, url, parser_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 14, "Recruitment", "https://mausam.imd.gov.in/recruitment", "generic_html",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    update_website(website_id=15, page_name="Recruitment", url="https://rectt.ngri.res.in")

    unrelated = get_websites_by_ids([1])[0]
    assert unrelated["url"] == "https://mausam.imd.gov.in/recruitment"
