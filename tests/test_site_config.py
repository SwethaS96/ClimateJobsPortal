from pathlib import Path
from tempfile import TemporaryDirectory

import database.connection as db_connection
import tests.mock_data as mock_data
from database.connection import get_connection, close_connection
from database.repositories import organization_repository
from database.repositories.website_repository import insert_website, soft_delete_website
from database.schema import create_schema
from scraper.site_config import SiteConfigLoader, WebsiteConfig


def setup_isolated_database() -> TemporaryDirectory:
    temp_dir = TemporaryDirectory()
    database_path = Path(temp_dir.name) / "climate_jobs.db"
    db_connection.DATABASE_PATH = database_path

    connection = get_connection()
    try:
        create_schema(connection)
    finally:
        close_connection(connection)

    return temp_dir


def test_load_enabled_websites_empty_database():
    temp_dir = setup_isolated_database()
    try:
        loader = SiteConfigLoader()
        configs = loader.load_enabled_websites()
        assert configs == []
    finally:
        temp_dir.cleanup()


def test_load_enabled_websites_one_enabled_website():
    temp_dir = setup_isolated_database()
    try:
        org_id = organization_repository.insert_organization(**mock_data.ORGANIZATION_1)
        website_id = insert_website(
            organization_id=org_id,
            page_name="Test Page",
            url="https://example.com",
            parser_name="html_parser",
            parser_metadata="{}",
            user_agent="CustomAgent/1.0",
            timeout_seconds=45,
            scrape_interval_minutes=120,
            
        )

        loader = SiteConfigLoader()
        configs = loader.load_enabled_websites()

        assert len(configs) == 1
        assert configs[0] == WebsiteConfig(
            id=website_id,
            organization_id=org_id,
            page_name="Test Page",
            url="https://example.com",
            parser_name="html_parser",
            parser_metadata="{}",
            user_agent="CustomAgent/1.0",
            timeout_seconds=45,
            scrape_interval_minutes=120,
        )
    finally:
        temp_dir.cleanup()


def test_load_enabled_websites_multiple_enabled_websites():
    temp_dir = setup_isolated_database()
    try:
        org_id_a = organization_repository.insert_organization(**mock_data.ORGANIZATION_1)
        org_id_b = organization_repository.insert_organization(**mock_data.ORGANIZATION_2)

        insert_website(
            organization_id=org_id_b,
            page_name="B Page",
            url="https://example.org/b",
            parser_name="generic_html",
            parser_metadata=None,
            user_agent=None,
            timeout_seconds=30,
            scrape_interval_minutes=60,
            
        )
        insert_website(
            organization_id=org_id_a,
            page_name="A Page",
            url="https://example.org/a",
            parser_name="custom_parser",
            parser_metadata="metadata",
            user_agent="Agent/2.0",
            timeout_seconds=15,
            scrape_interval_minutes=30,
            
        )

        loader = SiteConfigLoader()
        configs = loader.load_enabled_websites()

        assert [config.page_name for config in configs] == ["A Page", "B Page"]
        assert configs[0].organization_id == org_id_a
        assert configs[1].organization_id == org_id_b
        assert configs[0].parser_name == "custom_parser"
        assert configs[1].parser_name == "generic_html"
        assert configs[1].timeout_seconds == 30
        assert configs[1].scrape_interval_minutes == 60
    finally:
        temp_dir.cleanup()


def test_load_enabled_websites_ignores_disabled_websites():
    temp_dir = setup_isolated_database()
    try:
        org_id = organization_repository.insert_organization(**mock_data.ORGANIZATION_1)
        enabled_id = insert_website(
            organization_id=org_id,
            page_name="Enabled Page",
            url="https://enabled.example.com",
            parser_name="enabled_parser",
            parser_metadata=None,
            user_agent=None,
            timeout_seconds=30,
            scrape_interval_minutes=60,
            
        )
        disabled_id = insert_website(
            organization_id=org_id,
            page_name="Disabled Page",
            url="https://disabled.example.com",
            parser_name="disabled_parser",
            parser_metadata=None,
            user_agent=None,
            timeout_seconds=30,
            scrape_interval_minutes=60,
            
        )

        soft_delete_website(disabled_id)

        loader = SiteConfigLoader()
        configs = loader.load_enabled_websites()

        assert len(configs) == 1
        assert configs[0].id == enabled_id
        assert configs[0].page_name == "Enabled Page"
    finally:
        temp_dir.cleanup()


def test_load_websites_by_ids_returns_requested_order():
    temp_dir = setup_isolated_database()
    try:
        org_id = organization_repository.insert_organization(**mock_data.ORGANIZATION_1)
        id_a = insert_website(
            organization_id=org_id,
            page_name="A Page",
            url="https://example.org/a",
            parser_name="generic_html",
            parser_metadata=None,
            user_agent=None,
            timeout_seconds=30,
            scrape_interval_minutes=60,
        )
        id_b = insert_website(
            organization_id=org_id,
            page_name="B Page",
            url="https://example.org/b",
            parser_name="generic_html",
            parser_metadata=None,
            user_agent=None,
            timeout_seconds=30,
            scrape_interval_minutes=60,
        )

        loader = SiteConfigLoader()
        configs = loader.load_websites_by_ids([id_b, id_a])

        assert [config.id for config in configs] == [id_b, id_a]
    finally:
        temp_dir.cleanup()


def test_load_websites_by_ids_includes_disabled_websites():
    temp_dir = setup_isolated_database()
    try:
        org_id = organization_repository.insert_organization(**mock_data.ORGANIZATION_1)
        disabled_id = insert_website(
            organization_id=org_id,
            page_name="Disabled Page",
            url="https://disabled.example.com",
            parser_name="generic_html",
            parser_metadata=None,
            user_agent=None,
            timeout_seconds=30,
            scrape_interval_minutes=60,
        )
        soft_delete_website(disabled_id)

        loader = SiteConfigLoader()
        configs = loader.load_websites_by_ids([disabled_id])

        assert len(configs) == 1
        assert configs[0].id == disabled_id
    finally:
        temp_dir.cleanup()


def test_load_websites_by_ids_ignores_unknown_ids():
    temp_dir = setup_isolated_database()
    try:
        org_id = organization_repository.insert_organization(**mock_data.ORGANIZATION_1)
        known_id = insert_website(
            organization_id=org_id,
            page_name="Known Page",
            url="https://example.org/known",
            parser_name="generic_html",
            parser_metadata=None,
            user_agent=None,
            timeout_seconds=30,
            scrape_interval_minutes=60,
        )

        loader = SiteConfigLoader()
        configs = loader.load_websites_by_ids([known_id, 999999])

        assert len(configs) == 1
        assert configs[0].id == known_id
    finally:
        temp_dir.cleanup()


def test_load_websites_by_ids_empty_list_returns_empty():
    temp_dir = setup_isolated_database()
    try:
        loader = SiteConfigLoader()
        assert loader.load_websites_by_ids([]) == []
    finally:
        temp_dir.cleanup()
