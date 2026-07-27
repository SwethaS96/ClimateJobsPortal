from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import List

from database.connection import get_connection, close_connection


@dataclass(frozen=True)
class WebsiteConfig:
    id: int
    organization_id: int
    page_name: str
    url: str
    parser_name: str
    parser_metadata: str | None
    user_agent: str | None
    timeout_seconds: int
    scrape_interval_minutes: int


class SiteConfigLoader:
    """Load scraper site configuration from the SQLite database."""

    def load_enabled_websites(self) -> List[WebsiteConfig]:
        """Load all enabled websites and return them as WebsiteConfig objects."""
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT id,
                       organization_id,
                       page_name,
                       url,
                       parser_name,
                       parser_metadata,
                       user_agent,
                       timeout_seconds,
                       scrape_interval_minutes
                FROM websites
                WHERE is_enabled = 1
                ORDER BY organization_id ASC, page_name COLLATE NOCASE ASC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_config(row) for row in rows]
        finally:
            close_connection(connection)

    def _row_to_config(self, row: sqlite3.Row) -> WebsiteConfig:
        parser_name = row["parser_name"] if row["parser_name"] is not None else "generic_html"
        timeout_seconds = row["timeout_seconds"] if row["timeout_seconds"] is not None else 30
        scrape_interval_minutes = row["scrape_interval_minutes"] if row["scrape_interval_minutes"] is not None else 60

        return WebsiteConfig(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            page_name=row["page_name"],
            url=row["url"],
            parser_name=parser_name,
            parser_metadata=row["parser_metadata"],
            user_agent=row["user_agent"],
            timeout_seconds=int(timeout_seconds),
            scrape_interval_minutes=int(scrape_interval_minutes),
        )
