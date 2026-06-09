"""Unit tests for shared node helpers. Pure, no API."""

from core.nodes._utils import _in_destination


def test_in_destination_exact_match():
    assert _in_destination({"start_location": "Bratislava", "destination": "Bratislava"}) is True


def test_in_destination_case_insensitive():
    assert _in_destination({"start_location": "rome", "destination": "Rome"}) is True


def test_in_destination_substring_either_way():
    # "I'm already in Bratislava" + destination geocoded as "Bratislava, Slovakia"
    assert _in_destination({"start_location": "Bratislava", "destination": "Bratislava, Slovakia"}) is True
    assert _in_destination({"start_location": "Paris, France", "destination": "Paris"}) is True


def test_in_destination_false_for_different_cities():
    assert _in_destination({"start_location": "New York", "destination": "Rome"}) is False


def test_in_destination_false_for_default_placeholder():
    assert _in_destination({"start_location": "the user's current location", "destination": "Rome"}) is False


def test_in_destination_false_when_missing():
    assert _in_destination({"destination": "Rome"}) is False
    assert _in_destination({"start_location": "", "destination": "Rome"}) is False
    assert _in_destination({}) is False
