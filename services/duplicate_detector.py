"""Duplicate notification detection service."""

from __future__ import annotations

import re
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from database.repositories.notification_repository import get_notification_by_hash, get_notifications_by_website
from utils.hashing import sha256

# Query parameters that are pure tracking noise — stripping them means
# "?utm_source=newsletter" doesn't make an otherwise identical link look
# like a different notice.
_TRACKING_QUERY_PARAMS = frozenset(
    {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "ref"}
)

# Some sites glue a date/category prefix onto a notice's anchor text when
# it's repeated in a news ticker or events list (e.g. "August14th2026Filling
# up..." or "14 Aug 2026Filling up..."), so the same underlying notice reads
# as a different title on every repeat. Matches both the glued and spaced
# forms; `count=1` in `_strip_date_prefix` only strips a single leading
# occurrence, never text elsewhere in the title.
_DATE_PREFIX_PATTERN = re.compile(
    r"^(?:"
    r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4}"
    r"|[A-Za-z]{3,9}\s*\d{1,2}(?:st|nd|rd|th)?\s*\d{4}"
    r")\s*",
    re.IGNORECASE,
)


def normalize_url(url: str | None) -> str:
    """Canonicalize a URL for duplicate comparison.

    Strips known tracking query parameters, sorts the remaining ones, and
    drops a trailing slash from the path — reordered/tracking-only query
    strings or a trailing "/" don't make an identical link look different.
    """
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query_pairs = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_QUERY_PARAMS
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query_pairs), ""))


def normalize_title(title: str | None) -> str:
    """Strip a leading date/category prefix and normalize for comparison.

    Only a recognized leading date pattern is stripped — arbitrary title
    text is never fuzzy-matched, so two genuinely different notices that
    happen to share wording stay distinct.
    """
    stripped = _DATE_PREFIX_PATTERN.sub("", (title or "").strip(), count=1)
    return re.sub(r"\s+", " ", stripped).strip().lower()


class DuplicateDetector:
    """Detect existing notifications by a stable content hash.

    A notification's identity is its title+url pair: those are the fields
    that stay stable across repeated scrapes of the same notice, unlike
    category/date/deadline text which sites sometimes reformat run to run.
    """

    def is_duplicate(self, title: str, url: str) -> bool:
        """Return True when a notification with the same title+url hash exists."""
        return self.find_existing(title, url) is not None

    def find_existing(self, title: str, url: str, website_id: int | None = None) -> sqlite3.Row | None:
        """Return the existing active notification row for title+url, or None.

        Always checks the exact title+url hash first (unchanged — the
        UNIQUE `hash` column lookup every existing row was written with).
        When `website_id` is also given and no exact match is found, also
        checks that website's existing notifications for a near-duplicate:
        the same canonical URL (see `normalize_url`) with a title that
        differs only by a recognized date/category prefix (see
        `normalize_title`). Omitting `website_id` reproduces prior
        behavior exactly — this is purely additive.
        """
        exact = self._hash_exists(self._build_hash(title, url))
        if exact is not None:
            return exact
        if website_id is None:
            return None
        return self._find_near_duplicate(title, url, website_id)

    def build_hash(self, title: str, url: str) -> str:
        """Public accessor for the stable title+url identity hash."""
        return self._build_hash(title, url)

    def _build_hash(self, title: str, url: str) -> str:
        return sha256("|".join([title.strip(), url.strip()]))

    def _hash_exists(self, hash_value: str) -> sqlite3.Row | None:
        return get_notification_by_hash(hash_value)

    def _find_near_duplicate(self, title: str, url: str, website_id: int) -> sqlite3.Row | None:
        target_url = normalize_url(url)
        target_title = normalize_title(title)
        if not target_url or not target_title:
            return None
        for row in get_notifications_by_website(website_id):
            if normalize_url(row["page_url"]) == target_url and normalize_title(row["title"]) == target_title:
                return row
        return None
