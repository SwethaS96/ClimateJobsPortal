"""Tests for duplicate notification detection."""

from __future__ import annotations

from pathlib import Path

import pytest

import database.connection as connection_module
from database.repositories.notification_repository import insert_notification
from database.schema import create_schema
from services.duplicate_detector import DuplicateDetector, normalize_title, normalize_url


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "climate_jobs.db"
    monkeypatch.setattr(connection_module, "DATABASE_PATH", db_path)

    conn = connection_module.get_connection()
    try:
        create_schema(conn)
        conn.execute(
            """
            INSERT INTO organizations (name, short_name, homepage_url, country, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Test Org",
                "TST",
                "https://example.org",
                "India",
                "Tamil Nadu",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Jobs",
                "https://example.org/jobs",
                "generic_html",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    return db_path


def test_duplicate_detector_identifies_existing_notification(isolated_db: Path) -> None:
    detector = DuplicateDetector()
    hash_value = detector._build_hash("Climate Scientist", "https://example.org/jobs/1")

    insert_notification(
        organization_id=1,
        website_id=1,
        title="Climate Scientist",
        notification_number="REF-1",
        category="Research",
        notification_date="2026-08-01",
        application_deadline="2026-08-15",
        page_url="https://example.org/jobs/1",
        hash=hash_value,
    )

    assert detector.is_duplicate("Climate Scientist", "https://example.org/jobs/1") is True


def test_duplicate_detector_returns_false_for_new_notification(isolated_db: Path) -> None:
    detector = DuplicateDetector()
    assert detector.is_duplicate("New Role", "https://example.org/jobs/2") is False


# ---------------------------------------------------------------------------
# normalize_url / normalize_title (Phase 27 Part D)
# ---------------------------------------------------------------------------


def test_normalize_url_strips_tracking_query_params():
    a = normalize_url("https://example.org/jobs/1?utm_source=newsletter&utm_medium=email")
    b = normalize_url("https://example.org/jobs/1")
    assert a == b


def test_normalize_url_sorts_remaining_query_params():
    a = normalize_url("https://example.org/jobs/1?b=2&a=1")
    b = normalize_url("https://example.org/jobs/1?a=1&b=2")
    assert a == b


def test_normalize_url_drops_trailing_slash():
    assert normalize_url("https://example.org/jobs/1/") == normalize_url("https://example.org/jobs/1")


def test_normalize_url_keeps_substantive_query_params_distinct():
    a = normalize_url("https://example.org/notice?id=1")
    b = normalize_url("https://example.org/notice?id=2")
    assert a != b


def test_normalize_url_handles_none_and_empty():
    assert normalize_url(None) == ""
    assert normalize_url("") == ""


def test_normalize_title_strips_glued_date_prefix():
    assert normalize_title("August14th2026Filling up of the posts") == "filling up of the posts"


def test_normalize_title_strips_spaced_date_prefix():
    assert normalize_title("14 Aug 2026Filling up of the posts") == "filling up of the posts"


def test_normalize_title_leaves_titles_without_a_date_prefix_unchanged():
    assert normalize_title("Filling up of the posts") == "filling up of the posts"


def test_normalize_title_does_not_touch_dates_elsewhere_in_the_title():
    """Only a *leading* date prefix is stripped — a date mentioned later in
    the title must survive untouched, so unrelated titles don't collapse."""
    result = normalize_title("Walk-in interview on 14 Aug 2026 for Project Assistant")
    assert "14 aug 2026" in result


# ---------------------------------------------------------------------------
# find_existing near-duplicate detection (Phase 27 Part D)
# ---------------------------------------------------------------------------


def test_same_url_with_date_prefixed_title_is_detected_as_duplicate(isolated_db: Path) -> None:
    """Regression for Phase 27: CIFT-style repeats — the identical notice
    appears in a news ticker with a glued date prefix, and again in an
    events grid without one, but both point at the same URL."""
    detector = DuplicateDetector()
    url = "https://example.org/jobs/technician-notice"
    hash_value = detector.build_hash("Filling up of the posts of Technical Assistant", url)

    insert_notification(
        organization_id=1,
        website_id=1,
        title="Filling up of the posts of Technical Assistant",
        page_url=url,
        hash=hash_value,
    )

    existing = detector.find_existing("August14th2026Filling up of the posts of Technical Assistant", url, 1)
    assert existing is not None
    assert existing["title"] == "Filling up of the posts of Technical Assistant"


def test_near_duplicate_check_is_opt_in_via_website_id(isolated_db: Path) -> None:
    """Without website_id, only the exact hash is checked — fully backward
    compatible with every existing caller that doesn't pass it."""
    detector = DuplicateDetector()
    url = "https://example.org/jobs/technician-notice"
    hash_value = detector.build_hash("Filling up of the posts of Technical Assistant", url)

    insert_notification(
        organization_id=1,
        website_id=1,
        title="Filling up of the posts of Technical Assistant",
        page_url=url,
        hash=hash_value,
    )

    existing = detector.find_existing("August14th2026Filling up of the posts of Technical Assistant", url)
    assert existing is None


def test_truly_different_notices_on_same_website_remain_separate(isolated_db: Path) -> None:
    detector = DuplicateDetector()
    hash_value = detector.build_hash("Research Associate Opening", "https://example.org/jobs/ra")

    insert_notification(
        organization_id=1,
        website_id=1,
        title="Research Associate Opening",
        page_url="https://example.org/jobs/ra",
        hash=hash_value,
    )

    existing = detector.find_existing("Project Assistant Opening", "https://example.org/jobs/pa", 1)
    assert existing is None


def test_tracking_query_string_difference_does_not_create_duplicate(isolated_db: Path) -> None:
    detector = DuplicateDetector()
    url = "https://example.org/jobs/1"
    hash_value = detector.build_hash("Research Associate Opening", url)

    insert_notification(
        organization_id=1,
        website_id=1,
        title="Research Associate Opening",
        page_url=url,
        hash=hash_value,
    )

    existing = detector.find_existing(
        "Research Associate Opening", "https://example.org/jobs/1?utm_source=newsletter", 1
    )
    assert existing is not None


def test_different_substantive_query_string_remains_separate(isolated_db: Path) -> None:
    detector = DuplicateDetector()
    hash_value = detector.build_hash("Notice", "https://example.org/notice?id=1")

    insert_notification(
        organization_id=1,
        website_id=1,
        title="Notice",
        page_url="https://example.org/notice?id=1",
        hash=hash_value,
    )

    existing = detector.find_existing("Notice", "https://example.org/notice?id=2", 1)
    assert existing is None
