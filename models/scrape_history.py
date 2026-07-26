"""Pydantic models for scrape history API payloads and responses."""
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ScrapeHistoryCreate(BaseModel):
    """Payload for creating a new scrape history record."""

    website_id: int
    started_at: str
    finished_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: str
    notifications_found: int = 0
    notifications_added: int = 0
    notifications_updated: int = 0
    error_message: Optional[str] = None


class ScrapeHistoryUpdate(BaseModel):
    """Payload for updating an existing scrape history record."""

    website_id: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: Optional[str] = None
    notifications_found: Optional[int] = None
    notifications_added: Optional[int] = None
    notifications_updated: Optional[int] = None
    error_message: Optional[str] = None


class ScrapeHistoryResponse(BaseModel):
    """Response model for scrape history resources."""

    id: int
    website_id: int
    started_at: str
    finished_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: str
    notifications_found: int
    notifications_added: int
    notifications_updated: int
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
