"""Pydantic models for notification API payloads and responses."""
from typing import Optional

from pydantic import BaseModel, ConfigDict


class NotificationCreate(BaseModel):
    """Payload for creating a new notification."""

    organization_id: int
    website_id: int
    title: str
    notification_number: Optional[str] = None
    category: Optional[str] = None
    notification_date: Optional[str] = None
    application_deadline: Optional[str] = None
    page_url: Optional[str] = None
    hash: str


class NotificationUpdate(BaseModel):
    """Payload for updating an existing notification."""

    title: Optional[str] = None
    notification_number: Optional[str] = None
    category: Optional[str] = None
    notification_date: Optional[str] = None
    application_deadline: Optional[str] = None
    status: Optional[str] = None
    page_url: Optional[str] = None


class NotificationResponse(BaseModel):
    """Response model for notification resources."""

    id: int
    organization_id: int
    website_id: int
    title: str
    notification_number: Optional[str] = None
    category: Optional[str] = None
    notification_date: Optional[str] = None
    application_deadline: Optional[str] = None
    status: str
    page_url: Optional[str] = None
    hash: str
    first_seen: str
    last_seen: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)
