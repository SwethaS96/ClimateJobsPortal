"""FastAPI router for notification endpoints.

This router delegates business logic to the repository layer and uses
Pydantic v2 models for request/response validation.
"""
from typing import List

from fastapi import APIRouter, HTTPException, Response, status

from database.repositories.notification_repository import (
    insert_notification,
    get_all_notifications,
    get_notification_by_id,
    get_notifications_by_website,
    update_notification,
    soft_delete_notification,
)
from models.notification import (
    NotificationCreate,
    NotificationUpdate,
    NotificationResponse,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _row_to_response(row) -> NotificationResponse:
    """Convert a sqlite3.Row (or mapping) to NotificationResponse."""
    if row is None:
        return None
    return NotificationResponse.model_validate(dict(row))


@router.post("/", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
def create_notification(payload: NotificationCreate) -> NotificationResponse:
    """Create a new notification and return it."""
    try:
        notification_id = insert_notification(
            payload.organization_id,
            payload.website_id,
            payload.title,
            payload.notification_number,
            payload.category,
            payload.notification_date,
            payload.application_deadline,
            payload.page_url,
            payload.hash,
        )
    except ValueError as exc:
        if str(exc) == "Notification with this hash already exists.":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Notification already exists.")
        raise

    row = get_notification_by_id(notification_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve created notification")
    return _row_to_response(row)


@router.get("/", response_model=List[NotificationResponse])
def list_notifications() -> List[NotificationResponse]:
    """Return all active notifications."""
    rows = get_all_notifications()
    return [_row_to_response(r) for r in rows]


@router.get("/website/{website_id}", response_model=List[NotificationResponse])
def get_notifications_for_website(website_id: int) -> List[NotificationResponse]:
    """Return all active notifications for a specific website."""
    rows = get_notifications_by_website(website_id)
    return [_row_to_response(r) for r in rows]


@router.get("/{notification_id}", response_model=NotificationResponse)
def get_notification(notification_id: int) -> NotificationResponse:
    """Return a single active notification by id."""
    row = get_notification_by_id(notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return _row_to_response(row)


@router.put("/{notification_id}", response_model=NotificationResponse)
def put_notification(notification_id: int, payload: NotificationUpdate) -> NotificationResponse:
    """Update an existing notification and return it."""
    updated = update_notification(
        notification_id,
        payload.title,
        payload.notification_number,
        payload.category,
        payload.notification_date,
        payload.application_deadline,
        payload.status,
        payload.page_url,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")
    row = get_notification_by_id(notification_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated notification")
    return _row_to_response(row)


@router.delete("/{notification_id}")
def delete_notification(notification_id: int) -> Response:
    """Soft-delete a notification (mark as inactive)."""
    deleted = soft_delete_notification(notification_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notification not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
