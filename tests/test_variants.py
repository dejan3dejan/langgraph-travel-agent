"""Unit tests for the A/B variant flow: orchestrator variant-B input building and compare gating,
plus the chat router's per-variant stream accumulation and keep-variant selection. Pure, no LLM/DB."""

from api.chat import _apply_stream_event, _new_variant_buckets, _new_variant_meta, _select_variant, _should_stage
from core.orchestrator import _should_compare, _tag_event, _variant_b_inputs

# orchestrator: compare gating


def test_should_compare_only_a_fresh_produced_plan():
    assert _should_compare(compare=True, produced_itinerary=True, is_edit=False) is True


def test_should_compare_off_when_not_requested():
    assert _should_compare(compare=False, produced_itinerary=True, is_edit=False) is False


def test_should_compare_off_for_a_non_itinerary_turn():
    # an interview question under compare=True must not spawn a second variant
    assert _should_compare(compare=True, produced_itinerary=False, is_edit=False) is False


def test_should_compare_off_for_an_edit():
    # an in-place edit is never compared; there is one plan to revise
    assert _should_compare(compare=True, produced_itinerary=True, is_edit=True) is False


# orchestrator: event tagging


def test_tag_event_adds_variant_when_set():
    assert _tag_event({"type": "token", "content": "x"}, "B") == {"type": "token", "content": "x", "variant": "B"}


def test_tag_event_leaves_untagged_when_none():
    # the single-itinerary flow stays byte-for-byte as before, so old clients are unaffected
    assert _tag_event({"type": "token", "content": "x"}, None) == {"type": "token", "content": "x"}


# orchestrator: variant-B inputs reuse variant-A research, no second pipeline


def test_variant_b_inputs_reuse_research_and_diversify():
    captured = {
        "user_details": {"destination": "Rome"},
        "season_suggestion": "Shoulder season",
        "food_data": ["f"],
        "activity_data": ["a"],
        "hotel_data": ["h"],
        "draft": "# Trip to Rome\n## Day 1",
    }
    out = _variant_b_inputs(captured, nonce=42)
    assert out["user_details"] == {"destination": "Rome"}
    assert out["season_suggestion"] == "Shoulder season"
    assert out["food_data"] == ["f"]
    assert out["activity_data"] == ["a"]
    assert out["hotel_data"] == ["h"]
    # diversification: variant B is the regenerate path with A as the avoid-this reference
    assert out["regenerate"] is True
    assert out["base_itinerary"] == "# Trip to Rome\n## Day 1"
    assert out["request_nonce"] == 42


def test_variant_b_inputs_default_empty_pools():
    out = _variant_b_inputs({}, nonce=1)
    assert out["food_data"] == []
    assert out["activity_data"] == []
    assert out["hotel_data"] == []
    assert out["regenerate"] is True


# chat: per-variant accumulation


def test_apply_stream_event_untagged_folds_into_bucket_a():
    variants, meta = _new_variant_buckets(), _new_variant_meta()
    _apply_stream_event(variants, meta, {"type": "token", "content": "# Trip"})
    _apply_stream_event(variants, meta, {"type": "token", "content": " to Rome"})
    _apply_stream_event(
        variants,
        meta,
        {"type": "end", "is_itinerary": True, "user_details": {"destination": "Rome"}, "geo": {"days": []}},
    )
    assert variants["A"]["text"] == "# Trip to Rome"
    assert variants["A"]["geo"] == {"days": []}
    assert variants["B"]["text"] == ""
    assert meta["is_itinerary"] is True
    assert meta["user_details"] == {"destination": "Rome"}


def test_apply_stream_event_routes_tagged_variants_separately():
    variants, meta = _new_variant_buckets(), _new_variant_meta()
    _apply_stream_event(variants, meta, {"type": "token", "content": "plan A", "variant": "A"})
    _apply_stream_event(variants, meta, {"type": "end", "is_itinerary": True, "geo": {"days": ["a"]}, "variant": "A"})
    _apply_stream_event(variants, meta, {"type": "token", "content": "plan B", "variant": "B"})
    _apply_stream_event(variants, meta, {"type": "end", "is_itinerary": True, "geo": {"days": ["b"]}, "variant": "B"})
    assert variants["A"]["text"] == "plan A"
    assert variants["A"]["geo"] == {"days": ["a"]}
    assert variants["B"]["text"] == "plan B"
    assert variants["B"]["geo"] == {"days": ["b"]}


def test_apply_stream_event_reset_clears_only_its_variant():
    variants, meta = _new_variant_buckets(), _new_variant_meta()
    _apply_stream_event(variants, meta, {"type": "token", "content": "draft", "variant": "B"})
    _apply_stream_event(variants, meta, {"type": "reset", "variant": "B"})
    _apply_stream_event(variants, meta, {"type": "token", "content": "final", "variant": "B"})
    assert variants["B"]["text"] == "final"


def test_apply_stream_event_captures_edit_meta_on_a():
    variants, meta = _new_variant_buckets(), _new_variant_meta()
    _apply_stream_event(variants, meta, {"type": "token", "content": "revised"})
    _apply_stream_event(
        variants, meta, {"type": "end", "is_itinerary": True, "is_edit": True, "edit_summary": "Swapped lunch"}
    )
    assert meta["is_edit"] is True


# chat: when to stage two variants vs persist a single result


def test_should_stage_when_b_has_text():
    variants = _new_variant_buckets()
    variants["A"]["text"] = "A plan"
    variants["B"]["text"] = "B plan"
    assert _should_stage(variants) is True


def test_should_stage_false_with_no_b():
    variants = _new_variant_buckets()
    variants["A"]["text"] = "only A"
    assert _should_stage(variants) is False


# chat: keep-variant selection guards


def test_select_variant_returns_chosen_bucket():
    pending = {"A": {"text": "a", "geo": None}, "B": {"text": "b", "geo": None}}
    assert _select_variant(pending, "B") == {"text": "b", "geo": None}


def test_select_variant_rejects_unknown_tag():
    pending = {"A": {"text": "a"}, "B": {"text": "b"}}
    assert _select_variant(pending, "C") is None


def test_select_variant_rejects_missing_pending():
    assert _select_variant(None, "A") is None
    assert _select_variant({}, "A") is None
