from dataclasses import dataclass
from datetime import date, datetime

@dataclass
class Notification:
    id: int
    website_id: int
    title: str
    notification_number: str | None = None
    category: str | None = None
    notification_date: date | None = None
    application_deadline: date | None = None
    status: str | None = None
    page_url: str | None = None
    hash: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
