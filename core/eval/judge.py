"""Pairwise LLM-as-judge for subjective itinerary quality.

The deterministic scorers (scorers.py) already cover groundedness, format, constraints, and route
sanity. This judge handles only what they cannot: the subjective dimensions of coherence, fit to the
request, pacing, and variety. Pairwise comparison ("which of these two is better") is far more
reliable than absolute 1-10 scoring and is the core of the later model bake-off (M2).

Two biases get neutralized here:
  - Position bias: an LLM judge tends to favour whichever plan it reads first. We hide the real A/B
    identities behind positional labels, randomize the order (seedable, so tests are deterministic),
    and by default run BOTH orderings and only call a winner when the two passes agree. A flip
    between orderings collapses to a tie, which is the honest answer.
  - Verbosity bias: the rubric tells the judge that a longer plan is not automatically better.

The pure parts (order randomization, verdict parsing, mapping a positional verdict back to A/B,
combining the two orderings) live as standalone functions and are unit-tested without a model. Only
`judge_pairwise` and its `_judge_once` helper touch the network.
"""

import random

from langchain_core.messages import HumanMessage

from ..llm import get_llm_for_role

# A/B/tie in the caller's space; "first"/"second"/"tie" in the judge's positional space.
WINNERS = ("A", "B", "tie")

_RUBRIC = """You are an impartial judge comparing two travel itineraries written for the SAME request.
Decide which itinerary is better, considering ONLY these subjective dimensions:

- Coherence: do the days hang together geographically and thematically, in a sensible order?
- Fit to the request: does it answer what the traveler actually asked for (destination, vibe,
  interests, stated constraints), rather than a generic trip?
- Pacing: is each day realistically full without being exhausting, with sensible rhythm across days?
- Variety: is there genuine variety across days and venues, avoiding repetition and sameness?

Do NOT reward length. A longer or more verbose itinerary is not better for being longer; judge
quality and fit, not word count. Ignore minor formatting and factual-accuracy issues; those are
scored separately. Do not let the order in which the itineraries are presented sway you.

TRAVELER REQUEST:
{request}

ITINERARY 1:
{first}

ITINERARY 2:
{second}

First give one or two sentences of reasoning. Then, on the final line, output exactly one verdict in
the form `Verdict: 1`, `Verdict: 2`, or `Verdict: tie`."""


def _build_prompt(request: str, first_plan: str, second_plan: str) -> str:
    """Render the rubric with the two plans in positional slots. The caller decides which real plan
    lands in slot 1 vs slot 2; this function never sees the A/B identities."""
    return _RUBRIC.format(request=request or "(no request given)", first=first_plan, second=second_plan)


def _first_order_swapped(seed: int | None) -> bool:
    """Whether the first pass presents plan B before plan A. Drawn from a seeded RNG so production
    randomizes per call while tests pin the order. The second pass (when both orderings run) is the
    inverse of this, so the seed fully determines both passes."""
    return random.Random(seed).random() < 0.5


def _parse_verdict(reply: str) -> str:
    """Map the judge's free-text reply to a positional verdict: "first", "second", or "tie".

    Reads the verdict token after the last `verdict:` marker, falling back to the last standalone
    1/2/tie token if the marker is missing. A reply that names neither side, or both ambiguously,
    is treated as a tie: we never invent a winner the judge did not clearly state."""
    text = (reply or "").lower()
    marker = text.rfind("verdict")
    tail = text[marker:] if marker != -1 else text

    found = []
    for token in tail.replace(":", " ").replace("*", " ").split():
        if token in ("1", "one", "first"):
            found.append("first")
        elif token in ("2", "two", "second"):
            found.append("second")
        elif token in ("tie", "equal", "draw", "same"):
            found.append("tie")
    if len(set(found)) != 1:
        return "tie"
    return found[0]


def _resolve_winner(positional: str, swapped: bool) -> str:
    """Translate a positional verdict ("first"/"second"/"tie") back to the caller's A/B/tie, undoing
    the order swap. When swapped, slot 1 held plan B and slot 2 held plan A."""
    if positional == "tie":
        return "tie"
    first_is = "B" if swapped else "A"
    second_is = "A" if swapped else "B"
    return first_is if positional == "first" else second_is


def _combine(verdict_a: str, verdict_b: str) -> str:
    """Reduce two A/B/tie verdicts from opposite orderings to one. They must agree on a side to call
    a winner; any disagreement (including one pass tying) collapses to a tie. This is the consistency
    check that cancels position bias: a judge that flips when the order flips has not decided."""
    return verdict_a if verdict_a == verdict_b else "tie"


async def _judge_once(judge, request: str, plan_a: str, plan_b: str, swapped: bool) -> str:
    """One model call: lay out the plans in the (possibly swapped) positional order, parse the reply,
    and map it back to A/B. The only impure step."""
    first, second = (plan_b, plan_a) if swapped else (plan_a, plan_b)
    reply = await judge.ainvoke([HumanMessage(content=_build_prompt(request, first, second))])
    positional = _parse_verdict(getattr(reply, "content", "") or "")
    return _resolve_winner(positional, swapped)


async def judge_pairwise(
    request: str,
    plan_a: str,
    plan_b: str,
    *,
    seed: int | None = None,
    both_orderings: bool = True,
    llm=None,
) -> str:
    """Judge which of two itineraries better answers `request` on the subjective dimensions. Returns
    "A", "B", or "tie".

    By default runs both presentation orderings and returns a winner only when they agree, so the
    result is stable under order randomization (a flip means "tie"). Set both_orderings=False for a
    single, cheaper pass whose order is still randomized by `seed`. Pass `seed` to make the ordering
    deterministic (tests), or `llm` to inject a fake judge and skip the network."""
    judge = llm or get_llm_for_role("judge")
    swapped = _first_order_swapped(seed)

    first_pass = await _judge_once(judge, request, plan_a, plan_b, swapped)
    if not both_orderings:
        return first_pass

    second_pass = await _judge_once(judge, request, plan_a, plan_b, not swapped)
    return _combine(first_pass, second_pass)
