"""FastAPI router for PDF document endpoints.

This router delegates business logic to the repository layer and uses
Pydantic v2 models for request/response validation.
"""
from typing import List

from fastapi import APIRouter, HTTPException, Response, status

from database.repositories.pdf_repository import (
    delete_pdf_document,
    get_all_pdf_documents,
    get_pdf_document_by_id,
    get_pdf_documents_by_notification,
    insert_pdf_document,
    update_pdf_document,
)
from models.pdf_document import (
    PDFDocumentCreate,
    PDFDocumentResponse,
    PDFDocumentUpdate,
)

router = APIRouter(prefix="/pdf-documents", tags=["PDF Documents"])


def _row_to_response(row) -> PDFDocumentResponse:
    """Convert a sqlite3.Row (or mapping) to PDFDocumentResponse."""
    if row is None:
        return None
    return PDFDocumentResponse.model_validate(dict(row))


@router.post("/", response_model=PDFDocumentResponse, status_code=status.HTTP_201_CREATED)
def create_pdf_document(payload: PDFDocumentCreate) -> PDFDocumentResponse:
    """Create a new PDF document and return it."""
    pdf_document_id = insert_pdf_document(
        payload.notification_id,
        payload.document_type,
        payload.pdf_url,
        payload.local_file,
        payload.checksum,
        payload.downloaded,
        payload.downloaded_at,
        payload.file_size,
    )
    row = get_pdf_document_by_id(pdf_document_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve created PDF document")
    return _row_to_response(row)


@router.get("/", response_model=List[PDFDocumentResponse])
def list_pdf_documents() -> List[PDFDocumentResponse]:
    """Return all PDF documents."""
    rows = get_all_pdf_documents()
    return [_row_to_response(row) for row in rows]


@router.get("/notification/{notification_id}", response_model=List[PDFDocumentResponse])
def get_pdf_documents_for_notification(notification_id: int) -> List[PDFDocumentResponse]:
    """Return all PDF documents belonging to a notification."""
    rows = get_pdf_documents_by_notification(notification_id)
    return [_row_to_response(row) for row in rows]


@router.get("/{pdf_id}", response_model=PDFDocumentResponse)
def get_pdf_document(pdf_id: int) -> PDFDocumentResponse:
    """Return a single PDF document by id."""
    row = get_pdf_document_by_id(pdf_id)
    if row is None:
        raise HTTPException(status_code=404, detail="PDF document not found")
    return _row_to_response(row)


@router.put("/{pdf_id}", response_model=PDFDocumentResponse)
def put_pdf_document(pdf_id: int, payload: PDFDocumentUpdate) -> PDFDocumentResponse:
    """Update an existing PDF document and return it."""
    updated = update_pdf_document(
        pdf_id,
        payload.document_type,
        payload.pdf_url,
        payload.local_file,
        payload.checksum,
        payload.downloaded,
        payload.downloaded_at,
        payload.file_size,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="PDF document not found")
    row = get_pdf_document_by_id(pdf_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated PDF document")
    return _row_to_response(row)


@router.delete("/{pdf_id}")
def delete_pdf_document_endpoint(pdf_id: int) -> Response:
    """Delete a PDF document physically."""
    deleted = delete_pdf_document(pdf_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="PDF document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
