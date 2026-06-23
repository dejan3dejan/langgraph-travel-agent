"""Implicit interaction signals: pure aggregation into a personalization block.

This module is I/O-free and deterministic. The boundary (api/chat.py via
core/signal_store) loads a user's recent signals and profile, calls aggregate_signals
to derive a small structured "portrait", and render_learned_context to turn it into a
prompt block for the compiler.

Guardrail (llm-guardrails / OWASP LLM01): the only untrusted text is an edit
instruction. It is never echoed back. It is mapped to a fixed enum vocabulary, and
descriptor values (trip_type, interests) are accepted only when they fall in a known
vocabulary. So the rendered block is built solely from enums, counts, and whitelisted
values: there is no path for stored free text to act as an instruction.
"""

from collections import defaultdict
from datetime import UTC, datetime

# Event types

ITINERARY_KEPT = "itinerary_kept"
ITINERARY_EDITED = "itinerary_edited"
ITINERARY_REGENERATED = "itinerary_regenerated"
VARIANT_KEPT = "variant_kept"
VARIANT_REJECTED = "variant_rejected"
TRIP_OPENED = "trip_opened"
THUMB_UP = "thumb_up"
THUMB_DOWN = "thumb_down"

EVENT_TYPES = frozenset(
    {
        ITINERARY_KEPT,
        ITINERARY_EDITED,
        ITINERARY_REGENERATED,
        VARIANT_KEPT,
        VARIANT_REJECTED,
        TRIP_OPENED,
        THUMB_UP,
        THUMB_DOWN,
    }
)

# Trust tiers (recommender-systems lesson: absence is not a negative, and a paired
# choice the user actually saw is the only clean signal). Paired variants and explicit
# thumbs are highest; a passive keep is medium; a reopen is weak.
_TRUST = {
    THUMB_UP: 1.0,
    THUMB_DOWN: 1.0,
    VARIANT_KEPT: 1.0,
    VARIANT_REJECTED: 1.0,
    ITINERARY_KEPT: 0.6,
    TRIP_OPENED: 0.3,
    ITINERARY_REGENERATED: 0.5,
}
_POSITIVE = {ITINERARY_KEPT, VARIANT_KEPT, THUMB_UP, TRIP_OPENED}
_NEGATIVE = {VARIANT_REJECTED, THUMB_DOWN}
_EDIT_WEIGHT = 1.0  # an explicit edit is a deliberate act, weighted like a thumb

# Edit-intent vocabulary. Order defines the stable output order. Substring match on the
# lowercased instruction; an instruction that matches nothing (including an injection
# payload) maps to no intent.
_EDIT_INTENT_TRIGGERS = {
    "pace_lighter": [
        "lighter",
        "less packed",
        "too packed",
        "slow down",
        "slower pace",
        "relaxed pace",
        "more downtime",
        "fewer activities",
        "spread out",
        "too much in one day",
        "too busy",
        "less rushed",
    ],
    "pace_fuller": ["more to do", "pack more", "busier", "add more activities", "too empty", "fuller", "more packed"],
    "more_food": ["restaurant", "food", "more places to eat", "cuisine", "dining", "foodie"],
    "fewer_museums": ["fewer museum", "less museum", "too many museum", "no museum", "skip the museum", "skip museums"],
    "more_museums": ["more museum", "add a museum", "another museum"],
    "more_budget_conscious": [
        "cheaper",
        "too expensive",
        "less expensive",
        "budget",
        "save money",
        "lower cost",
        "more affordable",
        "costs too much",
    ],
    "more_upscale": ["fancier", "nicer", "upscale", "luxury", "splurge", "high-end", "more premium"],
    "more_nightlife": ["nightlife", "bars", "a bar", "club", "drinks", "party", "going out"],
    "more_outdoors": ["outdoor", "hike", "hiking", "nature", "park", "outside", "scenic walk"],
    "less_walking": ["less walking", "too much walking", "tired of walking", "no stairs", "less on foot"],
}

EDIT_INTENTS = frozenset(_EDIT_INTENT_TRIGGERS)

_EDIT_HINT_PHRASES = {
    "pace_lighter": "lighten the pace",
    "pace_fuller": "add more to each day",
    "more_food": "add more food and dining stops",
    "fewer_museums": "cut back on museums",
    "more_museums": "add more museums",
    "more_budget_conscious": "keep costs down",
    "more_upscale": "pick more upscale options",
    "more_nightlife": "include more nightlife",
    "more_outdoors": "add more outdoor time",
    "less_walking": "reduce walking",
}

# Whitelisted descriptor vocabularies. trip_type / interests come from LLM extraction of
# user text, so only known values are trusted into the portrait.
_TRIP_TYPE_VOCAB = frozenset({"romantic", "family", "adventure", "business", "workation", "relaxation"})
_BUDGET_VOCAB = frozenset({"low", "medium", "high"})
_INTEREST_VOCAB = {
    "food": ["food", "restaurant", "dining", "cuisine", "foodie", "culinary"],
    "nightlife": ["nightlife", "bar", "club", "party", "drinks"],
    "history": ["history", "historical", "historic"],
    "art": ["art", "gallery", "galleries"],
    "museums": ["museum"],
    "outdoors": ["outdoor", "hiking", "hike", "trek"],
    "nature": ["nature", "park", "wildlife", "scenery", "scenic"],
    "shopping": ["shopping", "shop", "market", "boutique"],
    "beaches": ["beach", "coast", "seaside"],
    "architecture": ["architecture", "architectural"],
    "music": ["music", "concert", "live music"],
    "relaxation": ["relax", "spa", "wellness", "leisure"],
}

_BUDGET_PHRASES = {
    "low": "budget-conscious, lower-cost",
    "medium": "mid-range",
    "high": "higher-end, upscale",
}

_MAX_INTERESTS = 4


def classify_edit_intent(text: str) -> list[str]:
    """Map an edit instruction to a bounded set of intent enums. Untrusted input is data:
    anything outside the vocabulary (including a prompt-injection payload) maps to nothing."""
    low = (text or "").lower()
    if not low.strip():
        return []
    return [intent for intent, triggers in _EDIT_INTENT_TRIGGERS.items() if any(t in low for t in triggers)]


def _extract_interests(value: str | None) -> list[str]:
    """Known interest tokens present in a free-text interests string; everything else is dropped."""
    low = (value or "").lower()
    if not low.strip():
        return []
    return [token for token, triggers in _INTEREST_VOCAB.items() if any(t in low for t in triggers)]


def _age_days(created_at, now: datetime | None) -> float | None:
    """Whole-and-fractional days between a signal and now, or None when either is missing."""
    if now is None or created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return (now - created_at).total_seconds() / 86400.0


def _decay(age_days: float | None, half_life_days: float) -> float:
    """Exponential recency decay; 1.0 when age is unknown or half-life is disabled."""
    if age_days is None or half_life_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def _edit_intents_for(payload: dict) -> list[str]:
    """Pre-classified intents if the capture site already stored them, else classify the raw
    instruction here. Either way the result is bounded to the enum vocabulary."""
    stored = payload.get("edit_intents")
    if isinstance(stored, list):
        return [i for i in stored if i in EDIT_INTENTS]
    return classify_edit_intent(payload.get("edit_instruction", ""))


def aggregate_signals(
    signals: list[dict],
    profile: dict,
    *,
    now: datetime | None = None,
    half_life_days: float = 30.0,
    min_support: float = 0.8,
    recency_days: int = 120,
) -> dict:
    """Reduce raw signals to a small, bounded personalization portrait.

    Each signal is a dict: {event_type, payload (dict), created_at (datetime | None)}.
    Scoring is trust-tier weight x recency decay; a leaning or hint is emitted only once
    its weighted support clears min_support (denoising). Negatives can cancel a leaning
    but are never surfaced as a "leans toward" hint. Pure: pass `now` for deterministic
    recency; with now=None all signals are treated as fresh.
    """
    leaning_scores: dict[str, dict[str, float]] = {
        "trip_type": defaultdict(float),
        "budget": defaultdict(float),
        "interests": defaultdict(float),
    }
    edit_scores: dict[str, float] = defaultdict(float)
    variety_score = 0.0
    counted = 0

    for sig in signals:
        event = sig.get("event_type")
        if event not in EVENT_TYPES:
            continue
        age = _age_days(sig.get("created_at"), now)
        if age is not None and age > recency_days:
            continue
        counted += 1
        payload = sig.get("payload") or {}
        weight = _decay(age, half_life_days)

        if event == ITINERARY_EDITED:
            for intent in _edit_intents_for(payload):
                edit_scores[intent] += _EDIT_WEIGHT * weight
            continue
        if event == ITINERARY_REGENERATED:
            variety_score += _TRUST[event] * weight
            continue

        if event in _POSITIVE:
            sign = 1.0
        elif event in _NEGATIVE:
            sign = -1.0
        else:
            continue
        w = sign * _TRUST.get(event, 0.0) * weight

        trip_type = str(payload.get("trip_type", "")).strip().lower()
        if trip_type in _TRIP_TYPE_VOCAB:
            leaning_scores["trip_type"][trip_type] += w
        budget = str(payload.get("budget", "")).strip().lower()
        if budget in _BUDGET_VOCAB:
            leaning_scores["budget"][budget] += w
        for token in _extract_interests(payload.get("interests")):
            leaning_scores["interests"][token] += w

    leanings: dict[str, object] = {}
    for dim in ("trip_type", "budget"):
        if leaning_scores[dim]:
            value, score = max(leaning_scores[dim].items(), key=lambda kv: kv[1])
            if score >= min_support:
                leanings[dim] = value
    interest_hits = sorted(
        (t for t, s in leaning_scores["interests"].items() if s >= min_support),
        key=lambda t: leaning_scores["interests"][t],
        reverse=True,
    )
    if interest_hits:
        leanings["interests"] = interest_hits[:_MAX_INTERESTS]

    edit_hints = [i for i in _EDIT_INTENT_TRIGGERS if edit_scores.get(i, 0.0) >= min_support]

    return {
        "leanings": leanings,
        "edit_hints": edit_hints,
        "wants_variety": variety_score >= min_support,
        "signal_count": counted,
    }


def render_learned_context(portrait: dict) -> str | None:
    """Render a portrait to a compact, advisory prompt block, or None when nothing was
    learned. Built only from enums and whitelisted values, so it is injection-safe by
    construction and framed so it can never override a hard requirement."""
    leanings = portrait.get("leanings") or {}
    edit_hints = portrait.get("edit_hints") or []
    lines: list[str] = []

    if leanings.get("trip_type"):
        lines.append(f"- Past trips they keep lean toward a {leanings['trip_type']} style")
    if leanings.get("budget"):
        lines.append(f"- Tends to favor {_BUDGET_PHRASES[leanings['budget']]} options")
    if leanings.get("interests"):
        lines.append(f"- Recurring interests: {', '.join(leanings['interests'])}")
    if edit_hints:
        phrases = [_EDIT_HINT_PHRASES[i] for i in edit_hints]
        lines.append(f"- When given a plan, often asks to: {', '.join(phrases)}")
    if portrait.get("wants_variety"):
        lines.append(
            "- Has asked to regenerate plans before; favor fresh, less obvious picks over the usual highlights"
        )

    if not lines:
        return None

    header = (
        "LEARNED PREFERENCES (observed from this traveler's past trips; treat as soft hints, "
        "never override the hard requirements above):"
    )
    return header + "\n" + "\n".join(lines)
