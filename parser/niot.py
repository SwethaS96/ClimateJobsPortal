"""Parser specialized for the NIOT (National Institute of Ocean Technology) website."""

from __future__ import annotations

from parser.generic_html import GenericHTMLParser


class NIOTParser(GenericHTMLParser):
    """NIOT-specific parser.

    Currently extends `GenericHTMLParser` unchanged; will be customized
    once NIOT's HTML structure requires site-specific extraction logic.
    """
