"""Pydantic models for application settings API payloads and responses."""
from pydantic import BaseModel, ConfigDict


class ApplicationSettingCreate(BaseModel):
    """Payload for creating a new application setting."""

    key: str
    value: str


class ApplicationSettingUpdate(BaseModel):
    """Payload for updating an existing application setting."""

    value: str | None = None


class ApplicationSettingResponse(BaseModel):
    """Response model for application setting resources."""

    key: str
    value: str

    model_config = ConfigDict(from_attributes=True)
