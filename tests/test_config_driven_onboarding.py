from __future__ import annotations

from pathlib import Path

import pytest

from parser.registry import ParserRegistry
from scraper.site_config import SiteConfigLoader


def test_loader_discovers_yaml_site_configs(tmp_path: Path) -> None:
    config_dir = tmp_path / "websites"
    config_dir.mkdir()
    (config_dir / "alpha.yaml").write_text(
        "organization: Alpha\n"
        "url: https://alpha.example/jobs\n"
        "parser: generic_html\n"
        "selectors:\n"
        "  listing: a.job\n"
        "rate_limit:\n"
        "  requests_per_minute: 30\n"
        "schedule:\n"
        "  interval_minutes: 45\n",
        encoding="utf-8",
    )

    loader = SiteConfigLoader(config_dir=config_dir)
    configs = loader.load_yaml_configs()

    assert len(configs) == 1
    assert configs[0]["organization"] == "Alpha"
    assert configs[0]["parser"] == "generic_html"
    assert configs[0]["selectors"]["listing"] == "a.job"


def test_loader_rejects_invalid_yaml_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "websites"
    config_dir.mkdir()
    (config_dir / "broken.yaml").write_text(
        "organization: Broken\n"
        "url: ftp://broken.example/jobs\n"
        "parser: generic_html\n"
        "selectors:\n"
        "  listing: a.job\n"
        "rate_limit:\n"
        "  requests_per_minute: 30\n",
        encoding="utf-8",
    )

    loader = SiteConfigLoader(config_dir=config_dir)

    with pytest.raises(ValueError):
        loader.load_yaml_configs()


def test_parser_registry_registers_yaml_parser_names() -> None:
    registry = ParserRegistry()
    registry.register_builtin_parsers()

    assert registry.get("generic_html") is not None
    assert registry.get("iitm") is not None
    assert registry.get("imd") is not None
    assert registry.get("niot") is not None
