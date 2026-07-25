from .base_parser import BaseParser

parsers = {}

def register_parser(name: str, parser: BaseParser):
    parsers[name] = parser


def get_parser(name: str) -> BaseParser | None:
    return parsers.get(name)
