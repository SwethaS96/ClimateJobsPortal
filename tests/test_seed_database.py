from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import database.connection as db_connection
from database.connection import close_connection, get_connection
from database.schema import create_schema
from scripts.seed_database import seed_database


def _setup_temp_database(tmp_path: Path) -> Path:
    db_path = tmp_path / "seed_test.db"
    db_connection.DATABASE_PATH = db_path
    connection = get_connection()
    try:
        create_schema(connection)
    finally:
        close_connection(connection)
    return db_path


def test_seed_database_imports_and_skips_duplicates(tmp_path: Path) -> None:
    _setup_temp_database(tmp_path)

    organizations_csv = tmp_path / "organizations.csv"
    websites_csv = tmp_path / "websites.csv"

    with organizations_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "short_name", "homepage_url", "country", "state"])
        writer.writerow(["Org One", "OO", "https://org1.example", "India", "TN"])
        writer.writerow(["Org One", "OO", "https://org1.example", "India", "TN"])
        writer.writerow(["", "", "", "", ""])

    with websites_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["organization_name", "page_name", "url", "parser_name", "parser_metadata", "user_agent", "timeout_seconds", "scrape_interval_minutes"])
        writer.writerow(["Org One", "Careers", "https://org1.example/careers", "generic_html", "{}", "Agent/1", "30", "60"])
        writer.writerow(["Org One", "Careers", "https://org1.example/careers", "generic_html", "{}", "Agent/1", "30", "60"])
        writer.writerow(["Missing Org", "Broken", "https://missing.example", "generic_html", "{}", "Agent/1", "30", "60"])

    summary = seed_database(organizations_csv, websites_csv)

    assert summary["organizations_inserted"] == 1
    assert summary["organizations_skipped"] == 1
    assert summary["websites_inserted"] == 1
    assert summary["websites_skipped"] == 1
    assert len(summary["errors"]) == 2

    connection = get_connection()
    try:
        organization_count = connection.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
        website_count = connection.execute("SELECT COUNT(*) FROM websites").fetchone()[0]
    finally:
        close_connection(connection)

    assert organization_count == 1
    assert website_count == 1


def test_seed_database_is_idempotent(tmp_path: Path) -> None:
    _setup_temp_database(tmp_path)

    organizations_csv = tmp_path / "organizations.csv"
    websites_csv = tmp_path / "websites.csv"

    with organizations_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "short_name", "homepage_url", "country", "state"])
        writer.writerow(["Org Two", "OT", "https://org2.example", "India", "KA"])

    with websites_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["organization_name", "page_name", "url", "parser_name", "parser_metadata", "user_agent", "timeout_seconds", "scrape_interval_minutes"])
        writer.writerow(["Org Two", "Jobs", "https://org2.example/jobs", "generic_html", "{}", "Agent/2", "30", "60"])

    first = seed_database(organizations_csv, websites_csv)
    second = seed_database(organizations_csv, websites_csv)

    assert first["organizations_inserted"] == 1
    assert first["websites_inserted"] == 1
    assert second["organizations_skipped"] == 1
    assert second["websites_skipped"] == 1
