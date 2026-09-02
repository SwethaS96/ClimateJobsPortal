"""Tests for scripts/import_expanded_institutions.py.

Uses an isolated temp SQLite database (never the real production DB) and
synthetic CSVs matching the ACTUAL expanded seed format used in
production: two files —

    data/seeds/organisation_expanded.csv  (name, short_name, homepage_url,
                                            country, state, is_active)
    data/seeds/websites_expanded.csv       (organization_name, page_name,
                                            url, parser_name,
                                            parser_metadata, user_agent,
                                            timeout_seconds,
                                            scrape_interval_minutes,
                                            is_enabled)
"""

from __future__ import annotations

import csv
import io
import sqlite3

import pytest

import database.connection as connection_module
import scripts.import_expanded_institutions as importer
from database.repositories import organization_repository, website_repository
from database.schema import create_schema


@pytest.fixture()
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test_import.db"
    connection_module_patch(monkeypatch, db_path)

    conn = sqlite3.connect(db_path)
    create_schema(conn)
    org_id = conn.execute(
        "INSERT INTO organizations (name, short_name, homepage_url, country, state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Indian Institute of Tropical Meteorology", "IITM", "https://www.tropmet.res.in", "India", "Maharashtra",
         "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    ).lastrowid
    conn.execute(
        "INSERT INTO websites (organization_id, page_name, url, parser_name, is_enabled, "
        "timeout_seconds, scrape_interval_minutes, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (org_id, "Announcements / Careers (homepage — no dedicated page confirmed)",
         "https://www.tropmet.res.in", "generic_html", 1, 30, 1440, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()
    return db_path


def connection_module_patch(monkeypatch, db_path):
    def fake_get_connection():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    monkeypatch.setattr(connection_module, "get_connection", fake_get_connection)
    monkeypatch.setattr(connection_module, "close_connection", lambda c: c.close())
    monkeypatch.setattr(importer, "get_connection", fake_get_connection)
    monkeypatch.setattr(importer, "close_connection", lambda c: c.close())
    monkeypatch.setattr(organization_repository, "get_connection", fake_get_connection)
    monkeypatch.setattr(organization_repository, "close_connection", lambda c: c.close())
    monkeypatch.setattr(website_repository, "get_connection", fake_get_connection)
    monkeypatch.setattr(website_repository, "close_connection", lambda c: c.close())


ORG_FIELDS = ["name", "short_name", "homepage_url", "country", "state", "is_active"]
SITE_FIELDS = [
    "organization_name", "page_name", "url", "parser_name", "parser_metadata",
    "user_agent", "timeout_seconds", "scrape_interval_minutes", "is_enabled",
]


def write_org_csv(tmp_path, rows: list[dict], name="organisation_expanded.csv"):
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORG_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in ORG_FIELDS})
    return path


def write_site_csv(tmp_path, rows: list[dict], name="websites_expanded.csv"):
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SITE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in SITE_FIELDS})
    return path


# ---------------------------------------------------------------------------
# categorize_organizations / categorize_websites — pure functions, no DB
# ---------------------------------------------------------------------------


def test_org_row_matching_existing_name_is_existing():
    entries = importer.categorize_organizations(
        [{"name": "Indian Institute of Tropical Meteorology"}],
        existing_org_names={"indian institute of tropical meteorology"},
    )
    assert entries[0]["category"] == importer.EXISTING


def test_org_row_not_matching_existing_name_is_new():
    entries = importer.categorize_organizations(
        [{"name": "Brand New Institute"}],
        existing_org_names={"indian institute of tropical meteorology"},
    )
    assert entries[0]["category"] == importer.NEW


def test_org_row_with_blank_name_is_missing_url_category():
    entries = importer.categorize_organizations([{"name": ""}], existing_org_names=set())
    assert entries[0]["category"] == importer.MISSING_URL


def test_duplicate_org_names_within_same_batch_second_is_existing():
    entries = importer.categorize_organizations(
        [{"name": "Brand New Institute"}, {"name": "Brand New Institute"}],
        existing_org_names=set(),
    )
    assert entries[0]["category"] == importer.NEW
    assert entries[1]["category"] == importer.EXISTING


def test_website_row_for_existing_url_is_duplicate_not_reinserted():
    """Websites don't get a separate EXISTING bucket — a URL that already
    exists in the DB is categorized DUPLICATE, same as a within-batch
    repeat. Both mean the same thing: never insert it again."""
    entries = importer.categorize_websites(
        [{"organization_name": "Indian Institute of Tropical Meteorology", "url": "https://www.tropmet.res.in"}],
        existing_website_urls={"https://www.tropmet.res.in"},
        all_known_org_names={"indian institute of tropical meteorology"},
    )
    assert entries[0]["category"] == importer.DUPLICATE


def test_website_row_for_new_org_with_new_url_is_new():
    entries = importer.categorize_websites(
        [{"organization_name": "Brand New Institute", "url": "https://newinstitute.example.org/careers"}],
        existing_website_urls=set(),
        all_known_org_names={"brand new institute"},
    )
    assert entries[0]["category"] == importer.NEW


def test_website_row_with_missing_url_is_missing_url():
    entries = importer.categorize_websites(
        [{"organization_name": "Brand New Institute", "url": ""}],
        existing_website_urls=set(),
        all_known_org_names={"brand new institute"},
    )
    assert entries[0]["category"] == importer.MISSING_URL


def test_website_row_with_malformed_url_is_invalid_url():
    entries = importer.categorize_websites(
        [{"organization_name": "Brand New Institute", "url": "not-a-url"}],
        existing_website_urls=set(),
        all_known_org_names={"brand new institute"},
    )
    assert entries[0]["category"] == importer.INVALID_URL


def test_website_row_with_unknown_organization_is_orphan():
    entries = importer.categorize_websites(
        [{"organization_name": "Nobody Has Heard Of This Institute", "url": "https://ghost.example.org"}],
        existing_website_urls=set(),
        all_known_org_names={"brand new institute"},
    )
    assert entries[0]["category"] == importer.ORPHAN_ORGANIZATION


def test_website_row_with_duplicate_url_across_different_org_is_duplicate():
    entries = importer.categorize_websites(
        [{"organization_name": "A Slightly Different Name", "url": "https://www.tropmet.res.in"}],
        existing_website_urls={"https://www.tropmet.res.in"},
        all_known_org_names={"a slightly different name"},
    )
    assert entries[0]["category"] == importer.DUPLICATE


def test_duplicate_urls_within_the_same_website_batch_are_caught():
    entries = importer.categorize_websites(
        [
            {"organization_name": "First New Institute", "url": "https://shared.example.org"},
            {"organization_name": "Second New Institute", "url": "https://shared.example.org"},
        ],
        existing_website_urls=set(),
        all_known_org_names={"first new institute", "second new institute"},
    )
    assert entries[0]["category"] == importer.NEW
    assert entries[1]["category"] == importer.DUPLICATE


# ---------------------------------------------------------------------------
# run() end to end — isolated DB, two-file CSV format
# ---------------------------------------------------------------------------


def test_dry_run_makes_no_database_changes(isolated_db, tmp_path):
    org_csv = write_org_csv(tmp_path, [
        {"name": "Indian Institute of Tropical Meteorology"},
        {"name": "Brand New Institute"},
    ])
    site_csv = write_site_csv(tmp_path, [
        {"organization_name": "Indian Institute of Tropical Meteorology", "url": "https://www.tropmet.res.in",
         "page_name": "Recruitment"},
        {"organization_name": "Brand New Institute", "url": "https://newinstitute.example.org/careers",
         "page_name": "Careers", "is_enabled": "1"},
    ])

    out = io.StringIO()
    args = importer.parse_args([str(org_csv), str(site_csv)])
    exit_code = importer.run(args, out=out)

    assert exit_code == 0
    assert "DRY RUN" in out.getvalue()

    conn = sqlite3.connect(isolated_db)
    org_count = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    site_count = conn.execute("SELECT COUNT(*) FROM websites").fetchone()[0]
    conn.close()
    assert org_count == 1  # only the pre-seeded IITM
    assert site_count == 1


def test_report_shows_all_categories(isolated_db, tmp_path):
    org_csv = write_org_csv(tmp_path, [
        {"name": "Indian Institute of Tropical Meteorology"},
        {"name": "New Institute"},
        {"name": ""},
    ])
    site_csv = write_site_csv(tmp_path, [
        {"organization_name": "Indian Institute of Tropical Meteorology", "url": "https://www.tropmet.res.in"},
        {"organization_name": "Dup Institute", "url": "https://www.tropmet.res.in"},
        {"organization_name": "New Institute", "url": "not-a-url"},
        {"organization_name": "New Institute", "url": ""},
        {"organization_name": "Nobody Knows This One", "url": "https://ghost.example.org"},
        {"organization_name": "New Institute", "url": "https://newinstitute.example.org/careers", "is_enabled": "1"},
    ])

    out = io.StringIO()
    exit_code = importer.run(importer.parse_args([str(org_csv), str(site_csv)]), out=out)
    output = out.getvalue()

    assert exit_code == 0
    assert "EXISTING" in output
    assert "DUPLICATE" in output
    assert "INVALID_URL" in output
    assert "MISSING_URL" in output
    assert "ORPHAN_ORGANIZATION" in output
    assert "NEW" in output


def test_confirm_inserts_new_organization_and_website_as_disabled(isolated_db, tmp_path):
    org_csv = write_org_csv(tmp_path, [{"name": "New Verified Institute", "homepage_url": "https://verified.example.org"}])
    site_csv = write_site_csv(tmp_path, [
        {"organization_name": "New Verified Institute", "url": "https://verified.example.org/careers",
         "page_name": "Careers", "is_enabled": "1"},
    ])

    out = io.StringIO()
    importer.run(importer.parse_args([str(org_csv), str(site_csv), "--confirm"]), out=out)

    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT o.name, w.url, w.is_enabled, w.page_name FROM websites w "
        "JOIN organizations o ON o.id = w.organization_id "
        "WHERE o.name = 'New Verified Institute'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["is_enabled"] == 0  # ALWAYS disabled, even though the CSV said is_enabled=1
    assert row["url"] == "https://verified.example.org/careers"


def test_confirm_does_not_touch_existing_organization_or_website(isolated_db, tmp_path):
    org_csv = write_org_csv(tmp_path, [{"name": "Indian Institute of Tropical Meteorology"}])
    site_csv = write_site_csv(tmp_path, [
        {"organization_name": "Indian Institute of Tropical Meteorology", "url": "https://www.tropmet.res.in"},
    ])

    out = io.StringIO()
    importer.run(importer.parse_args([str(org_csv), str(site_csv), "--confirm"]), out=out)

    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT w.url, w.is_enabled FROM websites w JOIN organizations o ON o.id = w.organization_id "
        "WHERE o.name = 'Indian Institute of Tropical Meteorology'"
    ).fetchone()
    total_orgs = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    total_sites = conn.execute("SELECT COUNT(*) FROM websites").fetchone()[0]
    conn.close()

    # Unchanged: still the original URL, still enabled, no second row created.
    assert row["url"] == "https://www.tropmet.res.in"
    assert row["is_enabled"] == 1
    assert total_orgs == 1
    assert total_sites == 1


def test_confirm_never_enables_a_new_website(isolated_db, tmp_path):
    org_csv = write_org_csv(tmp_path, [{"name": "New Verified Institute"}])
    site_csv = write_site_csv(tmp_path, [
        {"organization_name": "New Verified Institute", "url": "https://verified.example.org/careers", "is_enabled": "1"},
    ])

    importer.run(importer.parse_args([str(org_csv), str(site_csv), "--confirm"]), out=io.StringIO())

    conn = sqlite3.connect(isolated_db)
    enabled_count = conn.execute("SELECT COUNT(*) FROM websites WHERE is_enabled = 1").fetchone()[0]
    conn.close()
    assert enabled_count == 1  # only the pre-existing IITM row; the new one is disabled


def test_confirm_duplicate_and_existing_rows_are_never_inserted(isolated_db, tmp_path):
    org_csv = write_org_csv(tmp_path, [{"name": "Indian Institute of Tropical Meteorology"}])
    site_csv = write_site_csv(tmp_path, [
        {"organization_name": "Indian Institute of Tropical Meteorology", "url": "https://www.tropmet.res.in"},
        {"organization_name": "Dup Institute", "url": "https://www.tropmet.res.in"},
    ])

    importer.run(importer.parse_args([str(org_csv), str(site_csv), "--confirm"]), out=io.StringIO())

    conn = sqlite3.connect(isolated_db)
    org_count = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    site_count = conn.execute("SELECT COUNT(*) FROM websites").fetchone()[0]
    conn.close()
    assert org_count == 1
    assert site_count == 1


def test_confirm_skips_orphan_organization_website_row(isolated_db, tmp_path):
    org_csv = write_org_csv(tmp_path, [{"name": "Indian Institute of Tropical Meteorology"}])
    site_csv = write_site_csv(tmp_path, [
        {"organization_name": "Nobody Has Heard Of This Institute", "url": "https://ghost.example.org"},
    ])

    importer.run(importer.parse_args([str(org_csv), str(site_csv), "--confirm"]), out=io.StringIO())

    conn = sqlite3.connect(isolated_db)
    site_count = conn.execute("SELECT COUNT(*) FROM websites").fetchone()[0]
    conn.close()
    assert site_count == 1  # only the pre-seeded IITM row — the orphan was never inserted


def test_missing_csv_file_stops_cleanly(isolated_db, tmp_path):
    out = io.StringIO()
    exit_code = importer.run(
        importer.parse_args([str(tmp_path / "does_not_exist_orgs.csv"), str(tmp_path / "does_not_exist_sites.csv")]),
        out=out,
    )
    assert exit_code == 1
    assert "STOP" in out.getvalue()


def test_import_is_idempotent_running_twice_inserts_nothing_more(isolated_db, tmp_path):
    org_csv = write_org_csv(tmp_path, [{"name": "New Verified Institute"}])
    site_csv = write_site_csv(tmp_path, [
        {"organization_name": "New Verified Institute", "url": "https://verified.example.org/careers", "is_enabled": "1"},
    ])

    importer.run(importer.parse_args([str(org_csv), str(site_csv), "--confirm"]), out=io.StringIO())
    conn = sqlite3.connect(isolated_db)
    org_count_after_first = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    site_count_after_first = conn.execute("SELECT COUNT(*) FROM websites").fetchone()[0]
    conn.close()

    # Run the exact same import again.
    importer.run(importer.parse_args([str(org_csv), str(site_csv), "--confirm"]), out=io.StringIO())
    conn = sqlite3.connect(isolated_db)
    org_count_after_second = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    site_count_after_second = conn.execute("SELECT COUNT(*) FROM websites").fetchone()[0]
    conn.close()

    assert org_count_after_second == org_count_after_first
    assert site_count_after_second == site_count_after_first


def test_ncpor_typo_is_corrected_in_real_seed_file():
    """Regression guard for the Phase 38 fix — the real
    data/seeds/websites_expanded.csv must never regress back to
    'forx' and must resolve to a known organization name."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "seeds" / "websites_expanded.csv"
    if not path.exists():
        pytest.skip("real seed file not present in this environment")
    content = path.read_text(encoding="utf-8-sig")
    assert "forx" not in content
    assert "National Centre for Polar and Ocean Research" in content


def test_module_has_no_update_or_delete_functions_imported():
    """Guard against accidental modification of existing rows."""
    import inspect

    source = inspect.getsource(importer)
    for forbidden in ("update_organization", "soft_delete_organization", "soft_delete_website"):
        assert forbidden not in source
    # update_website is imported but ONLY ever called with is_enabled=False
    # on a row this same script just inserted — verified by
    # test_confirm_never_enables_a_new_website and
    # test_confirm_does_not_touch_existing_organization_or_website above.
