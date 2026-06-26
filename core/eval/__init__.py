"""Offline eval package for the planning pipeline.

`golden_set.json` is a hand-curated, committed set of travel-request scenarios that the eval tooling
runs the pipeline against; this module loads it. `scorers.py` holds the deterministic, no-LLM scorers
and `score_run`, which turn a finished run plus its scenario into one scorecard row. `judge.py` holds
the pairwise LLM-as-judge for the subjective dimensions the deterministic scorers cannot reach. See
README.md for the scenario schema and the `must_not_violate` rule vocabulary.
"""

import json
from pathlib import Path

from .judge import judge_pairwise
from .scorers import score_run

_GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"

REQUIRED_KEYS = ("id", "messages", "expected", "must_not_violate")

__all__ = ["load_golden_set", "score_run", "judge_pairwise"]


def load_golden_set() -> list[dict]:
    """Read the golden-set scenarios from golden_set.json. Pure: no scoring, no network, no clock."""
    with _GOLDEN_SET_PATH.open(encoding="utf-8") as f:
        return json.load(f)
