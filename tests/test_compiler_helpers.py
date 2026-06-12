"""Unit tests for compiler prompt-section helpers. Pure, no API."""

from core.nodes.compiler import (
    _accommodation_data_block,
    _accommodation_format_section,
    _anchor_coords,
    _base_label,
    _build_edit_prompt,
    _origin_known,
    _transport_section,
)

# proximity anchor


def test_anchor_uses_hotel_when_present():
    hotels = [{"lat": 48.1, "lon": 17.1}]
    places = [{"lat": 49.0, "lon": 18.0}]
    assert _anchor_coords(hotels, places) == (48.1, 17.1)


def test_anchor_centroid_when_no_hotel():
    places = [{"lat": 48.0, "lon": 17.0}, {"lat": 50.0, "lon": 19.0}]
    assert _anchor_coords([], places) == (49.0, 18.0)


def test_anchor_skips_hotel_without_coords():
    assert _anchor_coords([{"name": "no coords"}], [{"lat": 48.0, "lon": 17.0}]) == (48.0, 17.0)


def test_anchor_none_when_no_coords():
    assert _anchor_coords([], [{"name": "x"}]) == (None, None)
    assert _anchor_coords([], []) == (None, None)


# narrative base label


def test_base_label_is_hotel_when_lodging_needed():
    assert _base_label(True, False) == "your hotel"
    assert _base_label(True, True) == "your hotel"


def test_base_label_avoids_hotel_when_not_needed():
    assert "hotel" not in _base_label(False, True).lower()
    assert "hotel" not in _base_label(False, False).lower()


# accommodation sections


def test_accommodation_sections_empty_when_not_needed():
    assert _accommodation_data_block(False, '[{"name": "Hotel X"}]') == ""
    assert _accommodation_format_section(False) == ""


def test_accommodation_sections_present_when_needed():
    data = _accommodation_data_block(True, '[{"name": "Hotel X"}]')
    assert "ACCOMMODATION OPTIONS" in data and "Hotel X" in data
    assert "Recommended Accommodation" in _accommodation_format_section(True)


# origin known


def test_origin_known_for_real_city():
    assert _origin_known("London") is True
    assert _origin_known("New York, USA") is True


def test_origin_unknown_for_placeholder_and_sentinel():
    assert _origin_known("the user's current location") is False
    assert _origin_known("declined") is False
    assert _origin_known("") is False
    assert _origin_known(None) is False


# transport section (three states)


def test_transport_getting_there_from_known_origin():
    s = _transport_section(False, "Vienna", "Rome")
    assert "Getting There" in s and "Vienna" in s and "Rome" in s


def test_transport_getting_around_when_already_there():
    s = _transport_section(True, "Bratislava", "Bratislava")
    assert "Getting Around" in s and "Bratislava" in s
    assert "Getting There" not in s


def test_transport_arriving_when_origin_unknown():
    # unknown origin must NOT leak the placeholder into a "from X" line
    for unknown in ("the user's current location", "declined", ""):
        s = _transport_section(False, unknown, "Rome")
        assert "Arriving in Rome" in s
        assert "Getting There" not in s
        assert "current location" not in s.lower()


# edit mode (revise an existing plan)


def test_build_edit_prompt_includes_plan_and_instruction():
    prompt = _build_edit_prompt("# Trip to Rome\n## Day 1: Forum", "swap the Tuesday restaurant")
    assert "# Trip to Rome" in prompt
    assert "swap the Tuesday restaurant" in prompt


def test_build_edit_prompt_constrains_change_and_handles_the_note():
    prompt = _build_edit_prompt("# Trip to Rome", "add a beach day").lower()
    assert "only" in prompt  # apply only the requested change
    assert "updated:" in prompt  # lead with a one-line change note
    assert "replace" in prompt  # replace a prior note instead of stacking
