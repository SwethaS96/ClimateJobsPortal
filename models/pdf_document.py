from dataclasses import dataclass
from datetime import datetime

@dataclass
class PDFDocument:
    id: int
    notification_id: int
    document_type: str
    pdf_url: str
    local_file: str | None = None
    checksum: str | None = None
    downloaded: bool = False
    downloaded_at: datetime | None = None
    file_size: int | None = None
