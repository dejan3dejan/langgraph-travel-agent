"""Unit tests for the deterministic eval scorers: no I/O, no LLM, fully deterministic.

Each scorer gets a passing and a failing fixture; score_run composes them into one scorecard row.
"""

from core.eval.scorers import (
    score_constraint_violations,
    score_format_validity,
    score_groundedness,
    score_interview_health,
    score_route_sanity,
    score_run,
)

PARIS = (48.8566, 2.3522)
ROME = (41.9028, 12.4964)


def _place(name, lat, lon, kind="activity"):
    return {"name": name, "lat": lat, "lon": lon, "kind": kind}


def _geo(days, hotel=None):
    return {"hotel": hotel, "days": days}


# Groundedness


def test_groundedness_all_in_city_passes():
    lat, lon = PARIS
    geo = _geo(
        [
            {"day": 1, "title": "A", "places": [_place("Louvre", lat + 0.01, lon), _place("Orsay", lat + 0.02, lon)]},
        ]
    )
    result = score_groundedness(geo, lat, lon)
    assert result["total_places"] == 2
    assert result["grounded"] == 2
    assert result["ungrounded_places"] == []
    assert result["ratio"] == 1.0
    assert result["passed"] is True


def test_groundedness_wrong_city_place_fails():
    lat, lon = PARIS
    geo = _geo(
        [
            {
                "day": 1,
                "title": "A",
                "places": [
                    _place("Louvre", lat + 0.01, lon),
                    _place("Colosseum", ROME[0], ROME[1]),  # hallucinated into another country
                    _place("Stranded", None, None),  # ungeocoded
                ],
            }
        ]
    )
    result = score_groundedness(geo, lat, lon)
    assert result["total_places"] == 3
    assert result["grounded"] == 1
    assert set(result["ungrounded_places"]) == {"Colosseum", "Stranded"}
    assert result["passed"] is False


# Format validity


_VALID_PLAN = """# 2 Day Trip to Vienna

## Overview
A lovely couple of days.

## Recommended Accommodation
Hotel Sacher fits the bill.

## Day-by-Day Itinerary

### Day 1: Old town
- **Morning:** Schonbrunn Palace
- **Lunch:** Cafe Central

### Day 2: Museums
- **Morning:** Belvedere
- **Dinner:** Plachutta
"""


def test_format_validity_well_formed_plan_passes():
    geo = _geo(
        [
            {"day": 1, "title": "Old town", "places": [_place("Schonbrunn Palace", 48.18, 16.31)]},
            {"day": 2, "title": "Museums", "places": [_place("Belvedere", 48.19, 16.38)]},
        ]
    )
    result = score_format_validity(_VALID_PLAN, geo, needs_accommodation=True)
    assert result["parses"] is True
    assert result["num_days"] == 2
    assert result["days_without_stops"] == []
    assert result["hotel_present"] is True
    assert result["duplicate_venues"] == []
    assert result["passed"] is True


def test_format_validity_catches_empty_day_missing_hotel_and_dupes():
    # Day 2 has a header but no stop lines; no accommodation section though one is required; the same
    # venue is planned on both days.
    text = """# 3 Day Trip to Bali

## Day-by-Day Itinerary

### Day 1: Beaches
- **Morning:** Kuta Beach

### Day 2: Nothing planned

### Day 3: More beaches
- **Morning:** Kuta Beach again
"""
    geo = _geo(
        [
            {"day": 1, "title": "Beaches", "places": [_place("Kuta Beach", -8.72, 115.17)]},
            {"day": 3, "title": "More beaches", "places": [_place("Kuta Beach", -8.72, 115.17)]},
        ]
    )
    result = score_format_validity(text, geo, needs_accommodation=True)
    assert result["parses"] is True
    assert result["num_days"] == 3
    assert len(result["days_without_stops"]) == 1
    assert result["hotel_ok"] is False
    assert result["duplicate_venues"] == ["Kuta Beach"]
    assert result["passed"] is False


def test_format_validity_no_hotel_needed_passes_without_accommodation():
    text = """# 1 Day in Paris

### Day 1: Centre
- **Morning:** Louvre
"""
    geo = _geo([{"day": 1, "title": "Centre", "places": [_place("Louvre", *PARIS)]}])
    result = score_format_validity(text, geo, needs_accommodation=False)
    assert result["hotel_ok"] is True
    assert result["passed"] is True


# Constraint violations


def test_constraint_violations_flags_forbidden_terms():
    text = "Lunch: a fresh oyster platter and grilled shrimp. Evening: take a short flight to the coast."
    violated = score_constraint_violations(text, ["allergic to shellfish", "no flights"])
    assert violated == ["allergic to shellfish", "no flights"]


def test_constraint_violations_clean_plan_returns_empty():
    text = "Lunch: a vegetarian mezze platter. Travel by train along the coast."
    assert score_constraint_violations(text, ["allergic to shellfish", "no flights", "vegetarian"]) == []


# Route sanity


def test_route_sanity_compact_days_pass():
    lat, lon = PARIS
    geo = _geo(
        [
            {"day": 1, "title": "Centre", "places": [_place("A", lat + 0.005, lon), _place("B", lat + 0.01, lon)]},
        ],
        hotel={"name": "H", "lat": lat, "lon": lon},
    )
    result = score_route_sanity(geo)
    assert result["passed"] is True
    assert result["per_day"][0]["ok"] is True
    assert result["max_day_km"] < 5


def test_route_sanity_flags_sprawling_day():
    lat, lon = PARIS
    geo = _geo(
        [
            {"day": 1, "title": "Sprawl", "places": [_place("Here", lat, lon), _place("Rome", ROME[0], ROME[1])]},
        ],
        hotel={"name": "H", "lat": lat, "lon": lon},
    )
    result = score_route_sanity(geo, threshold_km=120.0)
    assert result["per_day"][0]["ok"] is False
    assert result["passed"] is False
    assert result["max_day_km"] > 120.0


# Interview health


def test_interview_health_clean_interview():
    result = score_interview_health(2, [["destination", "duration"], ["accommodation"]])
    assert result["turns_to_plan"] == 2
    assert result["reasked_slots"] == []
    assert result["reasked_answered_slot"] is False
    assert result["within_turn_budget"] is True


def test_interview_health_detects_reask_and_overrun():
    result = score_interview_health(7, [["origin"], ["accommodation"], ["origin"]])
    assert result["reasked_slots"] == ["origin"]
    assert result["reasked_answered_slot"] is True
    assert result["within_turn_budget"] is False


# score_run composition


_SCENARIO = {
    "id": "gs_vienna_2d_romantic",
    "expected": {
        "destination": "Vienna",
        "needs_accommodation": False,
        "hard_constraints": [],
        "refuse": False,
    },
}


def test_score_run_produces_single_scorecard_row():
    lat, lon = 48.2082, 16.3738  # Vienna
    output = {
        "itinerary_text": _VALID_PLAN,
        "itinerary_geo": _geo(
            [
                {"day": 1, "title": "Old town", "places": [_place("Schonbrunn", lat + 0.01, lon)]},
                {"day": 2, "title": "Museums", "places": [_place("Belvedere", lat + 0.02, lon)]},
            ],
            hotel={"name": "H", "lat": lat, "lon": lon},
        ),
        "destination_center": {"lat": lat, "lon": lon},
        "turns_to_plan": 1,
        "asked_slots_per_turn": [],
    }
    card = score_run(output, _SCENARIO)

    assert card["scenario_id"] == "gs_vienna_2d_romantic"
    assert card["is_refusal_scenario"] is False
    assert card["produced_plan"] is True
    assert set(card) >= {
        "scenario_id",
        "groundedness",
        "format_validity",
        "constraint_violations",
        "route_sanity",
        "interview_health",
    }
    assert card["groundedness"]["passed"] is True
    assert card["format_validity"]["passed"] is True
    assert card["constraint_violations"] == []
    assert card["route_sanity"]["passed"] is True


def test_score_run_derives_center_from_hotel_when_not_given():
    lat, lon = PARIS
    output = {
        "itinerary_text": "# Trip\n\n### Day 1: x\n- **Morning:** Louvre\n",
        "itinerary_geo": _geo(
            [{"day": 1, "title": "x", "places": [_place("Louvre", lat + 0.01, lon)]}],
            hotel={"name": "H", "lat": lat, "lon": lon},
        ),
        "turns_to_plan": 1,
    }
    scenario = {"id": "x", "expected": {"needs_accommodation": False, "hard_constraints": [], "refuse": False}}
    card = score_run(output, scenario)
    assert card["groundedness"]["passed"] is True
