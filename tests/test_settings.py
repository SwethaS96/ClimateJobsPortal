"""Tests for config/settings.py's EMAIL_MAX_NOTIFICATIONS parsing.

EMAIL_MAX_NOTIFICATIONS is no longer required and no longer defaults to a
hard cap — unset/blank/"unlimited" all mean "no limit at all".
"""

from __future__ import annotations

import pytest

from config.settings import _parse_email_max_notifications


@pytest.mark.parametrize(
    "raw",
    [None, "", "  ", "unlimited", "Unlimited", "UNLIMITED", "none", "None", "0", "-1"],
)
def test_unset_blank_or_unlimited_spellings_mean_no_cap(raw):
    assert _parse_email_max_notifications(raw) is None


@pytest.mark.parametrize(
    "raw,expected",
    [("50", 50), (" 200 ", 200), ("1", 1), ("1000000", 1000000)],
)
def test_positive_integer_still_configures_an_explicit_cap(raw, expected):
    assert _parse_email_max_notifications(raw) == expected
