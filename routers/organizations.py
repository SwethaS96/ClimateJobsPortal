"""FastAPI router for organization endpoints.

This router delegates business logic to the repository layer and uses
Pydantic v2 models for request/response validation.
"""
from typing import List

from fastapi import APIRouter, HTTPException, status

from database.repositories.organization_repository import (
    insert_organization,
    get_all_organizations,
    get_organization_by_id,
    update_organization,
    soft_delete_organization,
)
from models.organization import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
)

router = APIRouter(prefix="/organizations", tags=["Organizations"])


def _row_to_response(row) -> OrganizationResponse:
    """Convert a sqlite3.Row (or mapping) to OrganizationResponse."""
    if row is None:
        return None
    data = dict(row)
    # normalize is_active to bool
    data["is_active"] = bool(data.get("is_active"))
    return OrganizationResponse.model_validate(data)


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate) -> OrganizationResponse:
    """Create a new organization and return it."""
    org_id = insert_organization(
        payload.name,
        payload.short_name,
        payload.homepage_url,
        payload.country,
        payload.state,
    )
    row = get_organization_by_id(org_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve created organization")
    return _row_to_response(row)


@router.get("/", response_model=List[OrganizationResponse])
def list_organizations() -> List[OrganizationResponse]:
    """Return all active organizations."""
    rows = get_all_organizations()
    return [_row_to_response(r) for r in rows]


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(organization_id: int) -> OrganizationResponse:
    """Return a single active organization by id."""
    row = get_organization_by_id(organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _row_to_response(row)


@router.put("/{organization_id}", response_model=OrganizationResponse)
def put_organization(organization_id: int, payload: OrganizationUpdate) -> OrganizationResponse:
    """Update an existing active organization and return it."""
    updated = update_organization(
        organization_id,
        payload.name,
        payload.short_name,
        payload.homepage_url,
        payload.country,
        payload.state,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Organization not found")
    row = get_organization_by_id(organization_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated organization")
    return _row_to_response(row)


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(organization_id: int):
    """Soft-delete an organization (mark as inactive)."""
    deleted = soft_delete_organization(organization_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Organization not found")
    return None
