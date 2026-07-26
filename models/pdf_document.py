"""Pydantic models for PDF document API payloads and responses."""
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PDFDocumentCreate(BaseModel):
    """Payload for creating a new PDF document."""

    notification_id: int
    document_type: Optional[str] = None
    pdf_url: Optional[str] = None
    local_file: Optional[str] = None
    checksum: Optional[str] = None
    downloaded: Optional[bool] = False
    downloaded_at: Optional[str] = None
    file_size: Optional[int] = None


class PDFDocumentUpdate(BaseModel):
    """Payload for updating an existing PDF document."""

    document_type: Optional[str] = None
    pdf_url: Optional[str] = None
    local_file: Optional[str] = None
    checksum: Optional[str] = None
    downloaded: Optional[bool] = None
    downloaded_at: Optional[str] = None
    file_size: Optional[int] = None


class PDFDocumentResponse(BaseModel):
    """Response model for PDF document resources."""

    id: int
    notification_id: int
    document_type: Optional[str] = None
    pdf_url: Optional[str] = None
    local_file: Optional[str] = None
    checksum: Optional[str] = None
    downloaded: bool
    downloaded_at: Optional[str] = None
    file_size: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
