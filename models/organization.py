"""Pydantic models for organization API payloads and responses.

Uses Pydantic v2 `BaseModel` and is configured to support attribute-based
objects for response serialization.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OrganizationCreate(BaseModel):
    """Payload for creating a new organization."""

    name: str
    short_name: Optional[str] = None
    homepage_url: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None


class OrganizationUpdate(BaseModel):
    """Payload for updating an existing organization."""

    name: str
    short_name: Optional[str] = None
    homepage_url: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None


class OrganizationResponse(BaseModel):
    """Response model for organization resources.

    Configured with `from_attributes=True` so ORM-like objects with
    attributes (not just dicts) can be used to populate the model.
    """

    id: int
    name: str
    short_name: Optional[str] = None
    homepage_url: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    is_active: bool
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)
from dataclasses import dataclass

@dataclass
class Organization:
    id: int
    name: str
    short_name: str | None = None
    homepage_url: str | None = None
    country: str | None = None
    state: str | None = None
    is_active: bool = True
