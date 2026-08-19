"""Tests for the notification_review_queue repository."""

from __future__ import annotations

from pathlib import Path

import pytest

import database.connection as connection_module
from database.repositories.notification_review_queue_repository import (
    get_all_review_candidates,
    get_review_candidate_by_hash,
    get_review_candidate_by_id,
    insert_review_candidate,
    list_pending_reviews,
    mark_reviewed,
)
from database.schema import create_schema


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
            ("Test Org", "TST", "https://example.org", "India", "Tamil Nadu",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "Jobs", "https://example.org/jobs", "generic_html",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    return db_path


def test_insert_and_get_by_hash(isolated_db: Path) -> None:
    review_id = insert_review_candidate(
        organization_id=1,
        website_id=1,
        title="Departmental Update",
        url="https://example.org/news/42",
        reason="No clear actionable recruitment signal found; needs manual review.",
        classification="REVIEW",
        raw_html="<a href='/news/42'>Departmental Update</a>",
        metadata='{"parser": "generic_html"}',
        hash="hash-review-1",
    )

    row = get_review_candidate_by_id(review_id)
    assert row["title"] == "Departmental Update"
    assert row["review_status"] == "PENDING"
    assert row["reviewed_at"] is None

    by_hash = get_review_candidate_by_hash("hash-review-1")
    assert by_hash["id"] == review_id


def test_duplicate_hash_is_rejected(isolated_db: Path) -> None:
    insert_review_candidate(
        organization_id=1, website_id=1, title="A", url="https://example.org/a",
        reason="r", classification="REVIEW", hash="dup-hash",
    )

    with pytest.raises(ValueError):
        insert_review_candidate(
            organization_id=1, website_id=1, title="A", url="https://example.org/a",
            reason="r", classification="REVIEW", hash="dup-hash",
        )

    assert len(get_all_review_candidates()) == 1


def test_list_pending_reviews_excludes_resolved(isolated_db: Path) -> None:
    pending_id = insert_review_candidate(
        organization_id=1, website_id=1, title="Pending One", url="https://example.org/1",
        reason="r", classification="REVIEW", hash="hash-1",
    )
    resolved_id = insert_review_candidate(
        organization_id=1, website_id=1, title="Resolved One", url="https://example.org/2",
        reason="r", classification="REVIEW", hash="hash-2",
    )
    mark_reviewed(resolved_id)

    pending = list_pending_reviews()
    assert [row["id"] for row in pending] == [pending_id]


def test_mark_reviewed_sets_status_and_timestamp(isolated_db: Path) -> None:
    review_id = insert_review_candidate(
        organization_id=1, website_id=1, title="A", url="https://example.org/a",
        reason="r", classification="REVIEW", hash="hash-1",
    )

    updated = mark_reviewed(review_id)
    assert updated is True

    row = get_review_candidate_by_id(review_id)
    assert row["review_status"] == "RESOLVED"
    assert row["reviewed_at"] is not None


def test_mark_reviewed_accepts_custom_status(isolated_db: Path) -> None:
    review_id = insert_review_candidate(
        organization_id=1, website_id=1, title="A", url="https://example.org/a",
        reason="r", classification="REVIEW", hash="hash-1",
    )

    mark_reviewed(review_id, review_status="PROMOTED")

    row = get_review_candidate_by_id(review_id)
    assert row["review_status"] == "PROMOTED"


def test_mark_reviewed_twice_only_updates_once(isolated_db: Path) -> None:
    review_id = insert_review_candidate(
        organization_id=1, website_id=1, title="A", url="https://example.org/a",
        reason="r", classification="REVIEW", hash="hash-1",
    )

    first = mark_reviewed(review_id)
    second = mark_reviewed(review_id)

    assert first is True
    assert second is False  # no longer PENDING, so the second call matches no row


def test_mark_reviewed_unknown_id_returns_false(isolated_db: Path) -> None:
    assert mark_reviewed(99999) is False
