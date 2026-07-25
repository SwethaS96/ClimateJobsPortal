from dataclasses import dataclass

@dataclass
class Organization:
    id: int
    name: str
    short_name: str | None = None
    homepage_url: str | None = None
    country: str | None = None
    state: str | None = None
    is_active: bool = True
