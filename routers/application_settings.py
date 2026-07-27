"""FastAPI router for application settings endpoints.

This router delegates business logic to the repository layer and uses
Pydantic v2 models for request/response validation.
"""
from typing import List

from fastapi import APIRouter, HTTPException, Response, status

from database.repositories.settings_repository import (
    delete_setting,
    get_all_settings,
    get_setting,
    insert_setting,
    update_setting,
)
from models.application_setting import (
    ApplicationSettingCreate,
    ApplicationSettingResponse,
    ApplicationSettingUpdate,
)

router = APIRouter(prefix="/settings", tags=["Application Settings"])


def _row_to_response(row) -> ApplicationSettingResponse:
    """Convert a sqlite3.Row (or mapping) to ApplicationSettingResponse."""
    if row is None:
        return None
    return ApplicationSettingResponse.model_validate(dict(row))


@router.post("/", response_model=ApplicationSettingResponse, status_code=status.HTTP_201_CREATED)
def create_setting(payload: ApplicationSettingCreate) -> ApplicationSettingResponse:
    """Create a new application setting and return it."""
    insert_setting(payload.key, payload.value)
    row = get_setting(payload.key)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve created application setting")
    return _row_to_response(row)


@router.get("/", response_model=List[ApplicationSettingResponse])
def list_settings() -> List[ApplicationSettingResponse]:
    """Return all application settings."""
    rows = get_all_settings()
    return [_row_to_response(row) for row in rows]


@router.get("/{key}", response_model=ApplicationSettingResponse)
def get_application_setting(key: str) -> ApplicationSettingResponse:
    """Return a single application setting by key."""
    row = get_setting(key)
    if row is None:
        raise HTTPException(status_code=404, detail="Application setting not found")
    return _row_to_response(row)


@router.put("/{key}", response_model=ApplicationSettingResponse)
def put_application_setting(key: str, payload: ApplicationSettingUpdate) -> ApplicationSettingResponse:
    """Update an existing application setting and return it."""
    if payload.value is None:
        raise HTTPException(status_code=400, detail="No value provided for update")
    updated = update_setting(key, payload.value)
    if not updated:
        raise HTTPException(status_code=404, detail="Application setting not found")
    row = get_setting(key)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated application setting")
    return _row_to_response(row)


@router.delete("/{key}")
def delete_application_setting(key: str) -> Response:
    """Delete an application setting physically."""
    deleted = delete_setting(key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Application setting not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
