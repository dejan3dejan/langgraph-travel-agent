# Golden set (eval task E1)

`golden_set.json` is a fixed, committed set of travel-request scenarios. Later eval tooling (E2/E3/E4)
runs the planning pipeline against each scenario and scores the result. This package holds the data
and a pure loader (`load_golden_set()`); it does no scoring itself. Treat the JSON like code: review
changes, keep the schema clean.

## Scenario schema

Each entry is an object with four required top-level keys.

- `id` (str): stable, unique, kebab-case. Eval reports key off this; do not rename casually.
- `messages` (list[str]): the user turns, in order. One entry is a one-shot request; multiple entries
  are a multi-turn interview, fed turn by turn into the same session.
- `expected` (object): what a correct run should resolve to. Fields:
  - `destination` (str): primary city or region. For multi-stop trips this is the first stop.
  - `destinations` (list[str], optional): all stops in order, present only on multi-destination trips.
  - `duration_days` (int): total trip length across all stops.
  - `legs` (list[{destination, days}], optional): per-stop breakdown for multi-destination trips.
  - `start_location` (str, optional): where the traveler departs from, when stated.
  - `needs_accommodation` (bool, optional): true when lodging must be researched, false when the
    traveler already has it (booked, staying with friends, already in the city). Omitted on refusals.
  - `hard_constraints` (list[str]): constraints a correct plan must never violate (allergies, dietary
    needs, accessibility, no-flights, room type). Empty list when none.
  - `refuse` (bool): true when the request is fictional, impossible, or self-contradictory and the
    pipeline must decline rather than plan.
  - `refuse_reason` (str, optional): present when `refuse` is true; one of the `TripFeasibility.issue`
    enums (`unknown_place`, `impossible_logistics`, `contradictory`, `other`).
- `must_not_violate` (list[str]): rule tags a correct plan must respect. Controlled vocabulary below.

## `must_not_violate` vocabulary

- `destination_honored`: the plan is for the expected destination(s).
- `duration_honored`: the plan covers the expected number of days, no collapse or overrun.
- `all_destinations_covered`: every stop in a multi-destination trip appears in the plan.
- `hard_constraints_honored`: no venue or choice violates a hard constraint.
- `lodging_present`: lodging is researched and present when `needs_accommodation` is true.
- `no_unrequested_lodging`: lodging is not pushed when the traveler already has it.
- `no_duplicate_venues_across_days`: no restaurant or activity repeats across days.
- `must_refuse`: the request must be declined (paired with `refuse: true`), not planned.
- `no_reask_answered_slot`: an interview slot answered on an earlier turn is never asked again.

## Coverage

~26 scenarios spanning happy paths (single-destination one-shots), multi-destination trips,
already-in-town and same-day trips, hard dietary/accessibility/lodging constraints, local
non-touristy requests, refusals (fictional place, off-planet, impossible logistics, absurd
duration), and interview-loop regressions where an already-answered slot must never be re-asked.

## Loader

```python
from core.eval import load_golden_set

for scenario in load_golden_set():
    ...
```
