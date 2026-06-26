"""Deterministic (no-LLM) scorers for offline eval.

Pure functions over a finished planning run plus its golden-set scenario: no network, no clock, no
LLM. Each scorer returns a small structured dict; `score_run` composes them into one scorecard row
for one scenario. The thresholds here are deliberately lenient starting points, meant to be tuned
later against real runs rather than to gate anything today.

Run output shape consumed here (assembled by the eval harness):
  {
    "itinerary_text": str,                 # the compiled itinerary markdown ("" on a refusal)
    "itinerary_geo": {hotel, days[]},      # the map payload (see core/geo.build_itinerary_geo*)
    "destination_center": {"lat","lon"},   # optional; falls back to the geo's own anchor
    "turns_to_plan": int | None,           # user turns until a plan was delivered
    "asked_slots_per_turn": list[list[str]],  # soft slots put to the user, per turn
  }
"""

import re
from collections import defaultdict

from ..geo import _normalize_name, is_within_destination, optimize_day_route

# Lenient starting thresholds: tune against real runs, not load-bearing yet.
GROUNDEDNESS_MIN_RATIO = 0.7
GROUNDEDNESS_RADIUS_KM = 40.0  # mirrors research._CITY_RADIUS_KM, the hallucination-filter radius
ROUTE_MAX_DAY_KM = 120.0  # generous: a day trip can legitimately run long
MAX_TURNS_TO_PLAN = 6


def _all_places(geo: dict | None) -> list[dict]:
    """Flatten every plotted place across all days of the map payload."""
    if not geo:
        return []
    places = []
    for day in geo.get("days", []):
        places.extend(day.get("places", []))
    return places


# 1. Groundedness: share of recommended places that actually sit in the destination.


def score_groundedness(
    geo: dict | None, center_lat: float, center_lon: float, radius_km: float = GROUNDEDNESS_RADIUS_KM
) -> dict:
    """Fraction of plotted places within radius_km of the destination centroid, reusing
    is_within_destination. An ungeocoded place (missing coords) counts as ungrounded. An empty plan
    has nothing to ground, so it reports ratio 1.0 (vacuously grounded)."""
    places = _all_places(geo)
    grounded = []
    ungrounded = []
    for p in places:
        if is_within_destination(p.get("lat"), p.get("lon"), center_lat, center_lon, radius_km):
            grounded.append(p.get("name"))
        else:
            ungrounded.append(p.get("name"))
    total = len(places)
    ratio = len(grounded) / total if total else 1.0
    return {
        "total_places": total,
        "grounded": len(grounded),
        "ungrounded_places": ungrounded,
        "ratio": round(ratio, 3),
        "passed": ratio >= GROUNDEDNESS_MIN_RATIO,
    }


# 2. Format validity: does the itinerary text parse into well-formed days with no repeats.

_TITLE_RE = re.compile(r"^#\s+\S", re.MULTILINE)
_DAY_HEADER_RE = re.compile(r"^#{1,6}\s*Day\s+\d+", re.IGNORECASE | re.MULTILINE)
_ACCOMMODATION_RE = re.compile(r"^#{1,6}.*accommodation", re.IGNORECASE | re.MULTILINE)
# A stop is a markdown bullet or a bold time-block ("**Morning:** ...") under a day header.
_STOP_RE = re.compile(r"^\s*(?:[-*]\s+\S|\*\*\w)", re.MULTILINE)


def _split_days(text: str) -> list[tuple[str, str]]:
    """Slice the itinerary into (header_line, body) blocks, one per '### Day N' header."""
    matches = list(_DAY_HEADER_RE.finditer(text))
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        line_end = text.find("\n", start)
        if line_end == -1 or line_end > end:
            blocks.append((text[start:end], ""))
        else:
            blocks.append((text[start:line_end], text[line_end:end]))
    return blocks


def _duplicate_venues(geo: dict | None) -> list[str]:
    """Venue names that appear on more than one day. Names come from the geo payload (the structured
    projection of the plan), matched loosely so 'The Louvre' and 'Louvre' count as one venue."""
    days_by_norm: dict[str, set[int]] = defaultdict(set)
    name_by_norm: dict[str, str] = {}
    for idx, day in enumerate((geo or {}).get("days", [])):
        for p in day.get("places", []):
            norm = _normalize_name(p.get("name", ""))
            if not norm:
                continue
            days_by_norm[norm].add(idx)
            name_by_norm.setdefault(norm, p.get("name"))
    return [name_by_norm[n] for n, days in days_by_norm.items() if len(days) > 1]


def score_format_validity(itinerary_text: str, geo: dict | None, needs_accommodation: bool) -> dict:
    """Structural validity of the plan: it has a title and at least one day, every day has stops, a
    hotel is present when lodging is required, and no venue repeats across days. Cross-day duplicate
    detection runs over the geo payload (clean, structured names) since venue names cannot be pulled
    reliably from free markdown."""
    text = itinerary_text or ""
    day_blocks = _split_days(text)
    parses = bool(_TITLE_RE.search(text)) and len(day_blocks) > 0
    days_without_stops = [header.strip() for header, body in day_blocks if not _STOP_RE.search(body)]
    hotel_present = bool(_ACCOMMODATION_RE.search(text)) or bool(re.search(r"\bhotel\b", text, re.IGNORECASE))
    hotel_ok = (not needs_accommodation) or hotel_present
    duplicate_venues = _duplicate_venues(geo)
    return {
        "parses": parses,
        "num_days": len(day_blocks),
        "days_without_stops": days_without_stops,
        "hotel_present": hotel_present,
        "hotel_ok": hotel_ok,
        "duplicate_venues": duplicate_venues,
        "passed": parses and not days_without_stops and hotel_ok and not duplicate_venues,
    }


# 3. Constraint violations: hard constraints contradicted by something in the plan text.

# Dietary/allergy constraints map to forbidden terms whose presence in the plan text signals a
# violation. Keys are matched as substrings of the constraint phrase ("allergic to shellfish" hits
# "shellfish"). Affirmative-requirement constraints (wheelchair accessible, private rooms) are NOT
# here: a forbidden-term scan cannot verify a positive requirement, so this scorer leaves them
# unflagged by design rather than guessing.
_FORBIDDEN_TERMS = {
    "shellfish": ["shellfish", "shrimp", "prawn", "oyster", "crab", "lobster", "clam", "mussel", "scallop"],
    "vegan": ["steak", "beef", "pork", "chicken", "bacon", "ham", "lamb", "seafood", "cheese", "butter", "milk", "egg"],
    "vegetarian": ["steak", "beef", "pork", "chicken", "bacon", "ham", "lamb", "seafood", "sausage"],
    "halal": ["pork", "bacon", "lard", "wine", "beer", "alcohol", "cocktail"],
    "kosher": ["pork", "bacon", "shellfish", "shrimp", "lobster", "crab"],
}

_NO_PREFIX_RE = re.compile(r"^\s*no[\s-]+(.+)$", re.IGNORECASE)


def _constraint_violated(constraint: str, text: str) -> bool:
    """True when the (lowercased) plan text contains a term that contradicts the hard constraint."""
    c = constraint.lower()
    for key, terms in _FORBIDDEN_TERMS.items():
        if key in c:
            return any(t in text for t in terms)
    no_match = _NO_PREFIX_RE.match(c)
    if no_match:
        term = no_match.group(1).strip().rstrip("s")  # "no flights" -> forbid "flight"
        return bool(term) and term in text
    return False


def score_constraint_violations(plan_text: str, hard_constraints: list[str]) -> list[str]:
    """Hard constraints that appear violated by the plan text. Returns the violated constraints, in
    the order given. Detects forbidden-term contradictions (allergies, dietary needs, 'no X'); it
    does not attempt to verify affirmative requirements."""
    text = (plan_text or "").lower()
    return [c for c in (hard_constraints or []) if _constraint_violated(c, text)]


# 4. Route sanity: each day's total nearest-neighbor route stays under a distance threshold.


def _route_anchor(hotel: dict | None, places: list[dict]) -> tuple[float, float] | None:
    """Start/end point for a day's route: the hotel when geocoded, else the centroid of the day's
    places, else None when nothing can be placed."""
    if hotel and hotel.get("lat") is not None and hotel.get("lon") is not None:
        return hotel["lat"], hotel["lon"]
    coords = [(p["lat"], p["lon"]) for p in places if p.get("lat") is not None and p.get("lon") is not None]
    if not coords:
        return None
    return sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords)


def score_route_sanity(geo: dict | None, threshold_km: float = ROUTE_MAX_DAY_KM) -> dict:
    """Per-day total route distance (nearest-neighbor from the anchor and back, via
    optimize_day_route) against a threshold. A day with no placeable stops contributes 0 km."""
    hotel = (geo or {}).get("hotel")
    per_day = []
    for day in (geo or {}).get("days", []):
        places = day.get("places", [])
        anchor = _route_anchor(hotel, places)
        total_km = optimize_day_route(places, anchor[0], anchor[1])["total_distance_km"] if anchor else 0.0
        per_day.append({"day": day.get("day"), "total_km": total_km, "ok": total_km <= threshold_km})
    return {
        "per_day": per_day,
        "max_day_km": max((d["total_km"] for d in per_day), default=0.0),
        "passed": all(d["ok"] for d in per_day),
    }


# 5. Interview health: how many turns to a plan, and whether an answered slot was re-asked.


def score_interview_health(turns_to_plan: int | None, asked_slots_per_turn: list[list[str]]) -> dict:
    """Turns taken to reach a plan, and whether any soft slot was put to the user on more than one
    turn (the re-asking regression). A slot re-asked within the same turn is not a re-ask."""
    asked_before: set[str] = set()
    reasked: list[str] = []
    for turn in asked_slots_per_turn or []:
        for slot in turn:
            if slot in asked_before and slot not in reasked:
                reasked.append(slot)
        asked_before.update(turn)
    return {
        "turns_to_plan": turns_to_plan,
        "reasked_slots": reasked,
        "reasked_answered_slot": bool(reasked),
        "within_turn_budget": turns_to_plan is not None and turns_to_plan <= MAX_TURNS_TO_PLAN,
    }


# Composition: one scorecard row per scenario.


def _derive_center(output: dict, geo: dict | None) -> tuple[float, float] | None:
    """Destination centroid for groundedness: the explicit center when the harness supplies one,
    else the plan's own anchor (hotel, then the centroid of all places). Stays pure: no geocoding."""
    center = output.get("destination_center")
    if center and center.get("lat") is not None and center.get("lon") is not None:
        return center["lat"], center["lon"]
    return _route_anchor((geo or {}).get("hotel"), _all_places(geo))


def score_run(output: dict, scenario: dict) -> dict:
    """Compose the scorers into one structured scorecard row for a single scenario. Pure: no network,
    no LLM. The scenario's `expected` block is the ground truth for accommodation need and hard
    constraints; the run `output` carries the plan, map, and interview trace."""
    expected = scenario.get("expected", {})
    text = output.get("itinerary_text", "") or ""
    geo = output.get("itinerary_geo") or {"hotel": None, "days": []}
    needs_accommodation = expected.get("needs_accommodation", True)
    hard_constraints = expected.get("hard_constraints", [])

    center = _derive_center(output, geo)
    if center is None:
        groundedness = {
            "total_places": len(_all_places(geo)),
            "grounded": 0,
            "ungrounded_places": [],
            "ratio": None,
            "passed": None,
            "note": "no destination center available",
        }
    else:
        groundedness = score_groundedness(geo, center[0], center[1])

    return {
        "scenario_id": scenario.get("id"),
        "is_refusal_scenario": bool(expected.get("refuse")),
        "produced_plan": bool(text.strip()) or bool(geo.get("days")),
        "groundedness": groundedness,
        "format_validity": score_format_validity(text, geo, needs_accommodation),
        "constraint_violations": score_constraint_violations(text, hard_constraints),
        "route_sanity": score_route_sanity(geo),
        "interview_health": score_interview_health(output.get("turns_to_plan"), output.get("asked_slots_per_turn", [])),
    }
