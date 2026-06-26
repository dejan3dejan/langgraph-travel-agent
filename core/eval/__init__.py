"""Fixed golden set of request scenarios for offline eval (task E1).

This package owns `golden_set.json`, a hand-curated, committed set of travel-request scenarios that
later eval tooling (E2/E3/E4) runs the pipeline against. It is data plus this loader only; no scoring
lives here. See README.md for the scenario schema and the `must_not_violate` rule vocabulary.
"""

import json
from pathlib import Path

_GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"

REQUIRED_KEYS = ("id", "messages", "expected", "must_not_violate")


def load_golden_set() -> list[dict]:
    """Read the golden-set scenarios from golden_set.json. Pure: no scoring, no network, no clock."""
    with _GOLDEN_SET_PATH.open(encoding="utf-8") as f:
        return json.load(f)
