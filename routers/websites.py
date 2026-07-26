"""FastAPI router for website endpoints.

This router delegates business logic to the repository layer and uses
Pydantic v2 models for request/response validation.
"""
from typing import List

from fastapi import APIRouter, HTTPException, Response, status

from database.repositories.website_repository import (
    insert_website,
    get_all_websites,
    get_website_by_id,
    get_websites_by_organization,
    update_website,
    soft_delete_website,
)
from models.website import (
    WebsiteCreate,
    WebsiteUpdate,
    WebsiteResponse,
)

router = APIRouter(prefix="/websites", tags=["Websites"])


def _row_to_response(row) -> WebsiteResponse:
    """Convert a sqlite3.Row (or mapping) to WebsiteResponse."""
    if row is None:
        return None
    return WebsiteResponse.model_validate(dict(row))


@router.post("/", response_model=WebsiteResponse, status_code=status.HTTP_201_CREATED)
def create_website(payload: WebsiteCreate) -> WebsiteResponse:
    """Create a new website and return it."""
    website_id = insert_website(
        payload.organization_id,
        payload.page_name,
        payload.url,
        payload.parser_name,
        payload.scrape_frequency,
    )
    row = get_website_by_id(website_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve created website")
    return _row_to_response(row)


@router.get("/", response_model=List[WebsiteResponse])
def list_websites() -> List[WebsiteResponse]:
    """Return all enabled websites."""
    rows = get_all_websites()
    return [_row_to_response(r) for r in rows]


@router.get("/organization/{organization_id}", response_model=List[WebsiteResponse])
def get_websites_for_organization(organization_id: int) -> List[WebsiteResponse]:
    """Return all enabled websites belonging to a single organization."""
    rows = get_websites_by_organization(organization_id)
    return [_row_to_response(r) for r in rows]


@router.get("/{website_id}", response_model=WebsiteResponse)
def get_website(website_id: int) -> WebsiteResponse:
    """Return a single enabled website by id."""
    row = get_website_by_id(website_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Website not found")
    return _row_to_response(row)


@router.put("/{website_id}", response_model=WebsiteResponse)
def put_website(website_id: int, payload: WebsiteUpdate) -> WebsiteResponse:
    """Update an existing website and return it."""
    updated = update_website(
        website_id,
        payload.page_name,
        payload.url,
        payload.parser_name,
        payload.scrape_frequency,
        payload.is_enabled,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Website not found")
    row = get_website_by_id(website_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated website")
    return _row_to_response(row)


@router.delete("/{website_id}")
def delete_website(website_id: int) -> Response:
    """Soft-delete a website (mark as disabled)."""
    deleted = soft_delete_website(website_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Website not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
