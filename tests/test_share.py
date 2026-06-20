"""Unit tests for shared-itinerary helpers (title extraction, id generation). Pure, no DB."""

from api.share import extract_title, new_share_id


def test_extract_title_uses_the_markdown_heading():
    assert extract_title("# Trip to Rome\n## Day 1") == "Trip to Rome"


def test_extract_title_takes_the_first_heading_only():
    assert extract_title("intro\n# Lisbon long weekend\n# later heading") == "Lisbon long weekend"


def test_extract_title_falls_back_when_there_is_no_heading():
    assert extract_title("no heading here") == "Shared itinerary"
    assert extract_title("") == "Shared itinerary"


def test_extract_title_ignores_non_h1_headings():
    assert extract_title("## Day 1\n### morning") == "Shared itinerary"


def test_new_share_id_is_urlsafe_and_unguessably_long():
    sid = new_share_id()
    assert len(sid) >= 16
    assert all(c.isalnum() or c in "-_" for c in sid)


def test_new_share_id_is_unique_across_calls():
    assert len({new_share_id() for _ in range(100)}) == 100
