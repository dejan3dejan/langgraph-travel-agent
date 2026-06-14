"""Unit tests for trip-request validation helpers. Pure, no API."""

import pytest

from core.validation import MAX_TRIP_DAYS, MIN_TRIP_DAYS, duration_issue, parse_trip_days


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3 days", 3),
        ("1 day", 1),
        ("0 days", 0),
        ("109 days", 109),
        ("30 days", 30),
        ("a week", None),  # no integer; extraction normally normalizes this, so leave it alone
        ("", None),
        ("4 days in Barcelona, 7 in Lisbon", 11),  # multi-destination: total length
        ("-3 days", -3),
    ],
)
def test_parse_trip_days(text, expected):
    assert parse_trip_days(text) == expected


def test_bounds_constants_sane():
    assert MIN_TRIP_DAYS == 1
    assert MAX_TRIP_DAYS == 30


def test_duration_issue_flags_too_short():
    assert duration_issue(0) is not None
    assert duration_issue(-3) is not None


def test_duration_issue_flags_too_long_and_names_the_cap():
    msg = duration_issue(109)
    assert msg is not None
    assert str(MAX_TRIP_DAYS) in msg


def test_duration_issue_accepts_in_range():
    assert duration_issue(MIN_TRIP_DAYS) is None
    assert duration_issue(15) is None
    assert duration_issue(MAX_TRIP_DAYS) is None
