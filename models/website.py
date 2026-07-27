"""Pydantic models for website API payloads and responses."""
from typing import Optional

from pydantic import BaseModel, ConfigDict


class WebsiteCreate(BaseModel):
    """Payload for creating a new website."""

    organization_id: int
    page_name: str
    url: str
    parser_name: Optional[str] = None
    parser_metadata: Optional[str] = None
    user_agent: Optional[str] = None
    timeout_seconds: Optional[int] = None
    scrape_interval_minutes: Optional[int] = None


class WebsiteUpdate(BaseModel):
    """Payload for updating an existing website."""

    page_name: Optional[str] = None
    url: Optional[str] = None
    parser_name: Optional[str] = None
    parser_metadata: Optional[str] = None
    user_agent: Optional[str] = None
    timeout_seconds: Optional[int] = None
    scrape_interval_minutes: Optional[int] = None
    is_enabled: Optional[bool] = None
    


class WebsiteResponse(BaseModel):
    """Response model for website resources."""

    id: int
    organization_id: int
    page_name: str
    url: str
    parser_name: Optional[str] = None
    parser_metadata: Optional[str] = None
    user_agent: Optional[str] = None
    timeout_seconds: Optional[int] = None
    scrape_interval_minutes: Optional[int] = None
    is_enabled: bool
    last_scraped: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)
