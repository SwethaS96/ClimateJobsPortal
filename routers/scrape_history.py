"""FastAPI router for scrape history endpoints.

This router delegates business logic to the repository layer and uses
Pydantic v2 models for request/response validation.
"""
from typing import List

from fastapi import APIRouter, HTTPException, Response, status

from database.repositories.scrape_history_repository import (
    delete_scrape_history,
    get_all_scrape_history,
    get_scrape_history_by_id,
    get_scrape_history_by_website,
    insert_scrape_history,
    update_scrape_history,
)
from models.scrape_history import (
    ScrapeHistoryCreate,
    ScrapeHistoryResponse,
    ScrapeHistoryUpdate,
)

router = APIRouter(prefix="/scrape-history", tags=["Scrape History"])


def _row_to_response(row) -> ScrapeHistoryResponse:
    """Convert a sqlite3.Row (or mapping) to ScrapeHistoryResponse."""
    if row is None:
        return None
    return ScrapeHistoryResponse.model_validate(dict(row))


@router.post("/", response_model=ScrapeHistoryResponse, status_code=status.HTTP_201_CREATED)
def create_scrape_history(payload: ScrapeHistoryCreate) -> ScrapeHistoryResponse:
    """Create a new scrape history record and return it."""
    history_id = insert_scrape_history(
        payload.website_id,
        payload.started_at,
        payload.finished_at,
        payload.duration_seconds,
        payload.status,
        payload.notifications_found,
        payload.notifications_added,
        payload.notifications_updated,
        payload.error_message,
    )
    row = get_scrape_history_by_id(history_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve created scrape history record")
    return _row_to_response(row)


@router.get("/", response_model=List[ScrapeHistoryResponse])
def list_scrape_history() -> List[ScrapeHistoryResponse]:
    """Return all scrape history records."""
    rows = get_all_scrape_history()
    return [_row_to_response(row) for row in rows]


@router.get("/website/{website_id}", response_model=List[ScrapeHistoryResponse])
def get_scrape_history_for_website(website_id: int) -> List[ScrapeHistoryResponse]:
    """Return all scrape history records for a specific website."""
    rows = get_scrape_history_by_website(website_id)
    return [_row_to_response(row) for row in rows]


@router.get("/{history_id}", response_model=ScrapeHistoryResponse)
def get_scrape_history(history_id: int) -> ScrapeHistoryResponse:
    """Return a single scrape history record by id."""
    row = get_scrape_history_by_id(history_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Scrape history record not found")
    return _row_to_response(row)


@router.put("/{history_id}", response_model=ScrapeHistoryResponse)
def put_scrape_history(history_id: int, payload: ScrapeHistoryUpdate) -> ScrapeHistoryResponse:
    """Update an existing scrape history record and return it."""
    updated = update_scrape_history(
        history_id,
        payload.website_id,
        payload.started_at,
        payload.finished_at,
        payload.duration_seconds,
        payload.status,
        payload.notifications_found,
        payload.notifications_added,
        payload.notifications_updated,
        payload.error_message,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Scrape history record not found")
    row = get_scrape_history_by_id(history_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated scrape history record")
    return _row_to_response(row)


@router.delete("/{history_id}")
def delete_scrape_history_endpoint(history_id: int) -> Response:
    """Delete a scrape history record physically."""
    deleted = delete_scrape_history(history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scrape history record not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
