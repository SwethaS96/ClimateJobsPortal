from dataclasses import dataclass

@dataclass
class Website:
    id: int
    organization_id: int
    page_name: str
    url: str
    parser_name: str
    scrape_frequency: str | None = None
    is_enabled: bool = True
