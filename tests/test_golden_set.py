"""Unit tests for the golden-set loader and the integrity of golden_set.json (task E1). Pure, no API."""

from core.eval import REQUIRED_KEYS, load_golden_set

_RULE_VOCAB = {
    "destination_honored",
    "duration_honored",
    "all_destinations_covered",
    "hard_constraints_honored",
    "lodging_present",
    "no_unrequested_lodging",
    "no_duplicate_venues_across_days",
    "must_refuse",
    "no_reask_answered_slot",
}

_FEASIBILITY_ISSUES = {"unknown_place", "impossible_logistics", "contradictory", "other"}


def test_loads_a_substantial_set():
    assert len(load_golden_set()) >= 25


def test_ids_are_unique_and_nonempty():
    ids = [s["id"] for s in load_golden_set()]
    assert all(isinstance(i, str) and i for i in ids)
    assert len(ids) == len(set(ids))


def test_every_scenario_has_required_keys():
    for s in load_golden_set():
        for key in REQUIRED_KEYS:
            assert key in s, f"{s.get('id')} missing {key}"


def test_messages_are_nonempty_string_turns():
    for s in load_golden_set():
        assert isinstance(s["messages"], list) and s["messages"], s["id"]
        assert all(isinstance(m, str) and m.strip() for m in s["messages"]), s["id"]


def test_expected_carries_destination_and_duration():
    for s in load_golden_set():
        exp = s["expected"]
        assert isinstance(exp["destination"], str) and exp["destination"], s["id"]
        assert isinstance(exp["duration_days"], int) and exp["duration_days"] > 0, s["id"]


def test_must_not_violate_uses_known_vocab():
    for s in load_golden_set():
        rules = s["must_not_violate"]
        assert isinstance(rules, list) and rules, s["id"]
        assert set(rules) <= _RULE_VOCAB, f"{s['id']} has unknown rule tags: {set(rules) - _RULE_VOCAB}"


def test_refusals_are_well_formed():
    refusals = [s for s in load_golden_set() if s["expected"].get("refuse")]
    assert refusals, "golden set should include refusal cases"
    for s in refusals:
        assert "must_refuse" in s["must_not_violate"], s["id"]
        assert s["expected"]["refuse_reason"] in _FEASIBILITY_ISSUES, s["id"]


def test_multi_destination_legs_sum_to_duration():
    multi = [s for s in load_golden_set() if "legs" in s["expected"]]
    assert multi, "golden set should include multi-destination cases"
    for s in multi:
        exp = s["expected"]
        assert "all_destinations_covered" in s["must_not_violate"], s["id"]
        assert sum(leg["days"] for leg in exp["legs"]) == exp["duration_days"], s["id"]
        assert [leg["destination"] for leg in exp["legs"]] == exp["destinations"], s["id"]


def test_covers_tricky_categories():
    scenarios = load_golden_set()
    assert any("legs" in s["expected"] for s in scenarios), "multi-destination"
    assert any(s["expected"].get("refuse") for s in scenarios), "refusal"
    assert any(len(s["messages"]) > 1 for s in scenarios), "multi-turn interview"
    assert any("no_reask_answered_slot" in s["must_not_violate"] for s in scenarios), "re-ask regression"
    assert any(s["expected"].get("hard_constraints") for s in scenarios), "hard constraint"
    assert any(s["expected"].get("needs_accommodation") is False for s in scenarios), "already-has-lodging"
