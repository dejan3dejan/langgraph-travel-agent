"""Tests for the pairwise itinerary judge.

The pure parts (order randomization, verdict parsing, mapping a positional verdict back to A/B,
combining the two orderings) are tested directly with no model. judge_pairwise is exercised with a
fake judge injected, so the order/consistency logic is covered without the network. The one test that
hits a live model is marked `integration`.
"""

import pytest

from core.eval.judge import _combine, _first_order_swapped, _parse_verdict, _resolve_winner, judge_pairwise

# Order randomization: seeded, so deterministic and self-inverting across passes.


def test_same_seed_gives_same_order():
    assert _first_order_swapped(7) == _first_order_swapped(7)


def test_seed_spans_both_orders():
    # Across many seeds we must see both a swapped and an unswapped first pass, or the randomization
    # is not actually randomizing.
    seen = {_first_order_swapped(s) for s in range(50)}
    assert seen == {True, False}


# Verdict parsing: tolerant of phrasing, fails safe to a tie when unclear.


def test_parse_plain_verdict_tokens():
    assert _parse_verdict("Reasoning here.\nVerdict: 1") == "first"
    assert _parse_verdict("blah\nVerdict: 2") == "second"
    assert _parse_verdict("blah\nVerdict: tie") == "tie"


def test_parse_is_case_and_word_tolerant():
    assert _parse_verdict("VERDICT: First") == "first"
    assert _parse_verdict("verdict: Two") == "second"
    assert _parse_verdict("Verdict: **tie**") == "tie"


def test_parse_reads_token_after_last_marker():
    # Earlier mentions of "1" and "2" in the reasoning must not fool the parse; the verdict marker wins.
    assert _parse_verdict("Itinerary 1 and 2 are close.\nVerdict: 2") == "second"


def test_parse_ambiguous_or_missing_is_tie():
    assert _parse_verdict("They are both wonderful.") == "tie"
    assert _parse_verdict("Verdict: 1 or maybe 2") == "tie"
    assert _parse_verdict("") == "tie"


# Mapping a positional verdict back to A/B undoes the order swap.


def test_resolve_unswapped():
    assert _resolve_winner("first", swapped=False) == "A"
    assert _resolve_winner("second", swapped=False) == "B"
    assert _resolve_winner("tie", swapped=False) == "tie"


def test_resolve_swapped():
    assert _resolve_winner("first", swapped=True) == "B"
    assert _resolve_winner("second", swapped=True) == "A"
    assert _resolve_winner("tie", swapped=True) == "tie"


# Combining two orderings: agreement wins, any disagreement collapses to a tie.


def test_combine_agreement_wins():
    assert _combine("A", "A") == "A"
    assert _combine("B", "B") == "B"
    assert _combine("tie", "tie") == "tie"


def test_combine_disagreement_is_tie():
    assert _combine("A", "B") == "tie"
    assert _combine("A", "tie") == "tie"
    assert _combine("tie", "B") == "tie"


# judge_pairwise with a fake judge: no network, exercises the order + consistency wiring.


class _FakeJudge:
    """Returns a canned reply per call, in order. Used to drive judge_pairwise without a model."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.prompts = []

    async def ainvoke(self, messages):
        self.prompts.append(messages[0].content)

        class _R:
            content = self._replies.pop(0)

        return _R()


async def test_consistent_judge_yields_stable_winner_regardless_of_seed():
    # A judge that always prefers the SAME real plan must win for it under both orderings, for any
    # seed, because the slot the favourite occupies flips between the two passes. The fake cannot see
    # content, so each reply is set from the order the seed produces, tracking plan A across the swap.
    for seed in (0, 1, 2, 3):
        swapped_first = _first_order_swapped(seed)
        # pass 1: A is in slot 2 when swapped, slot 1 otherwise
        first_reply = "Verdict: 2" if swapped_first else "Verdict: 1"
        # pass 2 has the inverse order, so A sits in the opposite slot
        second_reply = "Verdict: 1" if swapped_first else "Verdict: 2"
        judge = _FakeJudge(first_reply, second_reply)
        winner = await judge_pairwise("req", "PLAN A", "PLAN B", seed=seed, llm=judge)
        assert winner == "A"


async def test_position_biased_judge_collapses_to_tie():
    # A judge that always says "slot 1 wins" disagrees with itself across the two orderings, so the
    # consistency check returns a tie rather than a position artefact.
    judge = _FakeJudge("Verdict: 1", "Verdict: 1")
    assert await judge_pairwise("req", "PLAN A", "PLAN B", seed=0, llm=judge) == "tie"


async def test_single_ordering_skips_second_pass():
    judge = _FakeJudge("Verdict: 1")
    winner = await judge_pairwise("req", "PLAN A", "PLAN B", seed=0, both_orderings=False, llm=judge)
    swapped = _first_order_swapped(0)
    assert winner == ("B" if swapped else "A")
    assert len(judge.prompts) == 1


async def test_real_plans_never_leak_ordering_label_to_caller():
    # Whichever slot a plan lands in, the returned winner is in A/B/tie space, never "first"/"second".
    judge = _FakeJudge("Verdict: tie", "Verdict: tie")
    assert await judge_pairwise("req", "PLAN A", "PLAN B", seed=42, llm=judge) == "tie"


@pytest.mark.integration
async def test_judge_pairwise_live_prefers_the_fitting_plan():
    # Live model: a coherent, on-request plan should beat a sloppy, off-request one, stably under
    # order randomization. Marked integration so the default suite never calls the model.
    request = "3 relaxed days in Kyoto focused on temples, tea houses, and traditional gardens."
    good = (
        "# Kyoto in 3 Relaxed Days\n"
        "## Day 1: Eastern Higashiyama\nMorning at Kiyomizu-dera, slow walk down Sannenzaka, "
        "matcha at a traditional tea house, evening stroll through Gion.\n"
        "## Day 2: Arashiyama\nBamboo grove early, Tenryu-ji garden, riverside lunch, "
        "Okochi Sanso villa garden in the afternoon.\n"
        "## Day 3: Northern temples\nKinkaku-ji, moss garden at Ryoan-ji, unhurried tea ceremony.\n"
    )
    bad = (
        "# Trip\n## Day 1\nWake up. Go to a mall. Eat fast food. See a temple maybe. "
        "Nightclub until late.\n## Day 2\nSame mall again. Burgers. Casino.\n"
        "## Day 3\nAirport shopping all day.\n"
    )
    winner = await judge_pairwise(request, good, bad, seed=1)
    assert winner == "A"
