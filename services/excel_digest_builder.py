"""Builds the .xlsx workbook attached to the email digest.

Takes the EXACT notification list already selected by
`EmailDigestService.build_pending_digest()` — this module never redefines
"pending notification" or re-queries the database itself. It only reads
fields that already exist on that notification dict (see
`services/email_service.py`'s SQL); it never fabricates data.

Three sheets:
    New Opportunities — every notification in the digest, as an Excel
        Table with filter dropdowns, a frozen header row, and clickable
        hyperlinks.
    Summary           — counts computed directly from the same data.
    Closing Soon      — only notifications whose `application_deadline`
        can be reliably parsed AND falls within the next 14 days. Never
        guesses a deadline from title/description/URL text.

The workbook is written to a fresh temp directory (`tempfile.mkdtemp`) —
never inside the repository, never committed, never reused across sends.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

HYPERLINK_FONT = Font(color="0563C1", underline="single")
WRAP_ALIGNMENT = Alignment(wrap_text=True, vertical="top")
DATE_NUMBER_FORMAT = "yyyy-mm-dd"

# (header, dict key, kind) — kind is "text", "date", or "hyperlink".
NEW_OPPORTUNITIES_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("Organization", "organization_name", "text"),
    ("Position / Job Title", "title", "text"),
    ("Job Type", "job_type", "text"),
    ("Category", "category", "text"),
    ("Location", "_location", "text"),
    ("Posted Date", "first_seen", "date"),
    ("Last Seen", "last_seen", "date"),
    ("Deadline", "application_deadline", "date"),
    ("Application Link", "page_url", "hyperlink"),
    ("Official Notice / PDF Link", "pdf_url", "hyperlink"),
    ("Source Website", "website_url", "hyperlink"),
)

CLOSING_SOON_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("Organization", "organization_name", "text"),
    ("Position / Job Title", "title", "text"),
    ("Deadline", "application_deadline", "date"),
    ("Application Link", "page_url", "hyperlink"),
)

CLOSING_SOON_WINDOW_DAYS = 14

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%B %d, %Y", "%d %B %Y")


def _sanitize_cell_text(value: str) -> str:
    """Strip characters the OOXML/Excel format cannot store at all (a
    handful of ASCII control characters occasionally present in scraped
    text). This is format-level sanitization, not data alteration — the
    same visible text is preserved; only bytes Excel would outright
    reject are removed."""
    return ILLEGAL_CHARACTERS_RE.sub("", value)


def _location(notification: dict[str, Any]) -> str:
    """Not a stored field on its own — derived from the organization's
    already-existing state/country columns, never fabricated."""
    state = notification.get("organization_state")
    country = notification.get("organization_country")
    if state:
        return str(state)
    if country:
        return str(country)
    return ""


def parse_reliable_date(value: Any) -> date | None:
    """Best-effort, non-guessing parse of a stored date/timestamp string.
    Returns None (never invents a date) if the value is empty or doesn't
    match a recognized format."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return None


class ExcelDigestBuilder:
    """Stateless — `build()` takes the notification list and generation
    time, returns the path to a freshly written .xlsx file."""

    def build(self, notifications: list[dict[str, Any]], generated_at: datetime) -> Path:
        workbook = Workbook()

        new_opportunities_sheet = workbook.active
        new_opportunities_sheet.title = "New Opportunities"
        self._build_new_opportunities_sheet(new_opportunities_sheet, notifications)

        summary_sheet = workbook.create_sheet("Summary")
        self._build_summary_sheet(summary_sheet, notifications, generated_at)

        closing_soon_sheet = workbook.create_sheet("Closing Soon")
        self._build_closing_soon_sheet(closing_soon_sheet, notifications, generated_at.date())

        output_dir = Path(tempfile.mkdtemp(prefix="climate_jobs_digest_"))
        path = output_dir / f"ClimateJobsPortal_{generated_at.date().isoformat()}.xlsx"
        workbook.save(path)
        return path

    # -- New Opportunities ---------------------------------------------

    def _build_new_opportunities_sheet(self, sheet: Worksheet, notifications: list[dict[str, Any]]) -> None:
        headers = [header for header, _, _ in NEW_OPPORTUNITIES_COLUMNS]
        sheet.append(headers)

        for notification in notifications:
            row_values = []
            for _, key, kind in NEW_OPPORTUNITIES_COLUMNS:
                value = _location(notification) if key == "_location" else notification.get(key)
                if kind == "date":
                    row_values.append(parse_reliable_date(value) or (_sanitize_cell_text(str(value)) if value else None))
                else:
                    row_values.append(_sanitize_cell_text(str(value)) if value not in (None, "") else None)
            sheet.append(row_values)

        self._style_table(sheet, "NewOpportunities", NEW_OPPORTUNITIES_COLUMNS, len(notifications))

    # -- Summary ----------------------------------------------------------

    def _build_summary_sheet(
        self, sheet: Worksheet, notifications: list[dict[str, Any]], generated_at: datetime
    ) -> None:
        sheet.append(["ClimateJobsPortal — Digest Summary"])
        sheet["A1"].font = Font(bold=True, size=14)
        sheet.append(["Digest generation date", generated_at.strftime("%Y-%m-%d %H:%M UTC")])
        sheet.append(["Total opportunities", len(notifications)])
        sheet.append([])

        sheet.append(["Job Type", "Count"])
        job_type_counts = Counter(
            (n.get("job_type") or "(unclassified)") for n in notifications
        )
        for job_type, count in sorted(job_type_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            sheet.append([_sanitize_cell_text(str(job_type)), count])
        sheet.append([])

        sheet.append(["Organization", "Count"])
        org_counts = Counter(n.get("organization_name") or "(unknown)" for n in notifications)
        for organization, count in sorted(org_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            sheet.append([_sanitize_cell_text(str(organization)), count])
        sheet.append([])

        parseable_deadlines = [
            parse_reliable_date(n.get("application_deadline")) for n in notifications
        ]
        parseable_deadlines = [d for d in parseable_deadlines if d is not None]
        window_end = generated_at.date() + timedelta(days=CLOSING_SOON_WINDOW_DAYS)
        closing_soon_count = sum(
            1 for d in parseable_deadlines if generated_at.date() <= d <= window_end
        )
        sheet.append(["Notifications with a reliably parseable deadline", len(parseable_deadlines)])
        sheet.append([f"Closing within {CLOSING_SOON_WINDOW_DAYS} days", closing_soon_count])

        sheet.column_dimensions["A"].width = 45
        sheet.column_dimensions["B"].width = 20

    # -- Closing Soon -----------------------------------------------------

    def _build_closing_soon_sheet(
        self, sheet: Worksheet, notifications: list[dict[str, Any]], today: date
    ) -> None:
        headers = [header for header, _, _ in CLOSING_SOON_COLUMNS]
        sheet.append(headers)

        window_end = today + timedelta(days=CLOSING_SOON_WINDOW_DAYS)
        qualifying: list[tuple[date, dict[str, Any]]] = []
        for notification in notifications:
            deadline = parse_reliable_date(notification.get("application_deadline"))
            if deadline is not None and today <= deadline <= window_end:
                qualifying.append((deadline, notification))
        qualifying.sort(key=lambda pair: pair[0])

        for deadline, notification in qualifying:
            row_values = []
            for _, key, kind in CLOSING_SOON_COLUMNS:
                if kind == "date":
                    row_values.append(deadline)
                else:
                    value = notification.get(key)
                    row_values.append(_sanitize_cell_text(str(value)) if value not in (None, "") else None)
            sheet.append(row_values)

        self._style_table(sheet, "ClosingSoon", CLOSING_SOON_COLUMNS, len(qualifying))

    # -- Shared styling -----------------------------------------------------

    def _style_table(
        self,
        sheet: Worksheet,
        table_name: str,
        columns: tuple[tuple[str, str, str], ...],
        row_count: int,
    ) -> None:
        sheet.freeze_panes = "A2"

        for col_index, (header, _, kind) in enumerate(columns, start=1):
            letter = sheet.cell(row=1, column=col_index).column_letter
            width = 22
            if kind == "hyperlink":
                width = 40
            elif header in ("Position / Job Title", "Organization"):
                width = 35
            elif kind == "date":
                width = 14
            sheet.column_dimensions[letter].width = width

        # An Excel Table with zero data rows (just the header) is valid
        # and still shows filter dropdowns — no placeholder row needed,
        # so an empty "Closing Soon" sheet genuinely has zero data rows.
        last_col_letter = sheet.cell(row=1, column=len(columns)).column_letter
        table_ref = f"A1:{last_col_letter}{1 + row_count}"
        table = Table(displayName=table_name, ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showRowStripes=True, showFirstColumn=False,
        )
        sheet.add_table(table)

        for row_index in range(2, 2 + row_count):
            for col_index, (header, _, kind) in enumerate(columns, start=1):
                cell = sheet.cell(row=row_index, column=col_index)
                if kind == "date" and isinstance(cell.value, date):
                    cell.number_format = DATE_NUMBER_FORMAT
                elif kind == "hyperlink" and cell.value:
                    cell.hyperlink = cell.value
                    cell.font = HYPERLINK_FONT
                if header in ("Position / Job Title",):
                    cell.alignment = WRAP_ALIGNMENT
