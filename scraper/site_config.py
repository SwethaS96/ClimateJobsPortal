from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from pathlib import Path
from typing import Any, List

import yaml

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
    """Load scraper site configuration from the SQLite database and YAML onboarding files."""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        base_dir = Path(config_dir) if config_dir is not None else Path(__file__).resolve().parents[1] / "configs" / "websites"
        self.config_dir = Path(base_dir)

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

    def load_websites_by_ids(self, website_ids: list[int]) -> List[WebsiteConfig]:
        """Load specific websites by id, in the order the ids were given.

        Unlike `load_enabled_websites`, this does not filter on
        `is_enabled` — callers here are asking for specific sites by id
        (e.g. a controlled diagnostic scrape), so a disabled website is
        still returned rather than silently dropped. Ids with no matching
        row are simply absent from the result.
        """
        if not website_ids:
            return []

        connection = get_connection()
        try:
            cursor = connection.cursor()
            placeholders = ",".join("?" for _ in website_ids)
            cursor.execute(
                f"""
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
                WHERE id IN ({placeholders})
                """,
                tuple(website_ids),
            )
            rows_by_id = {int(row["id"]): row for row in cursor.fetchall()}
        finally:
            close_connection(connection)

        return [
            self._row_to_config(rows_by_id[website_id])
            for website_id in website_ids
            if website_id in rows_by_id
        ]

    def load_yaml_configs(self) -> list[dict[str, Any]]:
        """Discover website YAML files and validate their structure."""
        if not self.config_dir.exists():
            return []

        configs: list[dict[str, Any]] = []
        for yaml_path in sorted(self.config_dir.glob("*.yaml")):
            with yaml_path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            validated = self._validate_config(payload, yaml_path)
            configs.append(validated)
        return configs

    def _validate_config(self, payload: Any, yaml_path: Path) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError(f"{yaml_path} must contain a mapping at the top level")

        required_fields = ["organization", "url", "parser", "selectors", "rate_limit", "schedule"]
        missing = [field for field in required_fields if field not in payload]
        if missing:
            raise ValueError(f"{yaml_path} is missing required fields: {', '.join(missing)}")

        organization = payload["organization"]
        url = payload["url"]
        parser = payload["parser"]
        selectors = payload["selectors"]
        rate_limit = payload["rate_limit"]
        schedule = payload["schedule"]

        if not isinstance(organization, str) or not organization.strip():
            raise ValueError(f"{yaml_path} has an invalid organization")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValueError(f"{yaml_path} has an invalid url")
        if not isinstance(parser, str) or not parser.strip():
            raise ValueError(f"{yaml_path} has an invalid parser")
        if not isinstance(selectors, dict) or not selectors:
            raise ValueError(f"{yaml_path} has invalid selectors")
        if not isinstance(rate_limit, dict) or "requests_per_minute" not in rate_limit:
            raise ValueError(f"{yaml_path} has invalid rate_limit")
        if not isinstance(schedule, dict) or "interval_minutes" not in schedule:
            raise ValueError(f"{yaml_path} has invalid schedule")

        return {
            "organization": organization,
            "url": url,
            "parser": parser,
            "selectors": selectors,
            "rate_limit": rate_limit,
            "schedule": schedule,
            "source": str(yaml_path),
        }

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
