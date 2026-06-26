"""One-command offline eval runner for the planning pipeline (eval task E3).

Runs every golden-set scenario through the real TravelOrchestrator, scores each finished run with the
deterministic scorers, aggregates to per-metric means plus per-scenario rows, writes a timestamped
JSON report under core/eval/reports/ (gitignored), and prints a compact table to stdout.

Kept OUT of CI on purpose: a full pass makes real LLM calls and hits the DB. Run it by hand:

    python -m core.eval.run                  # full golden set, default model config
    python -m core.eval.run --limit 3        # first three scenarios (a quick smoke pass)
    python -m core.eval.run --model-label X  # tag the report with a model-config label
    python -m core.eval.run --compare a b     # stub: two-config diff, filled in by task M2

The aggregation step (aggregate_scorecard) is pure: it takes finished scorecard rows and returns
per-metric means with no pipeline run, so it is unit-tested directly.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import load_golden_set, score_run

_REPORTS_DIR = Path(__file__).parent / "reports"


@dataclass(frozen=True)
class ModelConfig:
    """Which model setup a run used. Recorded into the report so two runs can be told apart and
    diffed. Today the pipeline uses whatever core/llm.py is wired to; carrying an override into the
    graph is task M2's job (the --compare path), so this stays a label plus free-form notes for now."""

    label: str = "default"
    notes: str = ""


@dataclass
class ScenarioOutput:
    """The run artifacts a scenario produced, in the shape score_run consumes."""

    itinerary_text: str = ""
    itinerary_geo: dict | None = None
    user_details: dict = field(default_factory=dict)
    turns_to_plan: int | None = None
    asked_slots_per_turn: list = field(default_factory=list)
    error: str | None = None


async def run_scenario(orchestrator, scenario: dict) -> ScenarioOutput:
    """Drive one golden-set scenario through the real streaming pipeline, turn by turn, and collect
    the final itinerary text, the map geo, the resolved user_details, and the interview trace. Slots
    asked per turn are the delta of the orchestrator's persisted asked-set, which it dedupes already,
    so a re-ask would only show up if the pipeline regressed."""
    history: list[dict[str, str]] = []
    prior_user_details: dict | None = None
    prior_asked_slots: list[str] = []

    out = ScenarioOutput()
    seen_slots: set[str] = set()

    for turn_idx, message in enumerate(scenario.get("messages", []), start=1):
        tokens: list[str] = []
        end: dict = {}
        try:
            async for event in orchestrator.stream_chat(
                user_message=message,
                history=history,
                prior_user_details=prior_user_details,
                prior_asked_slots=prior_asked_slots,
            ):
                kind = event.get("type")
                if kind == "token":
                    tokens.append(event.get("content", ""))
                elif kind == "end":
                    end = event
        except Exception as e:  # surface the failure on the row instead of aborting the whole pass
            out.error = f"{type(e).__name__}: {e}"
            return out

        reply = "".join(tokens)
        history.append({"role": "user", "content": message})
        history.append({"role": "model", "content": reply})

        prior_user_details = end.get("user_details") or prior_user_details
        asked_now = list(end.get("asked_slots") or [])
        prior_asked_slots = asked_now
        new_slots = sorted(set(asked_now) - seen_slots)
        out.asked_slots_per_turn.append(new_slots)
        seen_slots.update(asked_now)

        if end.get("is_itinerary"):
            if out.turns_to_plan is None:
                out.turns_to_plan = turn_idx
            out.itinerary_text = reply
            out.itinerary_geo = end.get("geo")
            out.user_details = end.get("user_details") or out.user_details

    return out


# Pure aggregation: scorecard rows in, per-metric means out. No pipeline, no I/O.

_BOOL_METRICS = {
    "produced_plan": lambda r: r.get("produced_plan"),
    "groundedness_passed": lambda r: r.get("groundedness", {}).get("passed"),
    "format_valid": lambda r: r.get("format_validity", {}).get("passed"),
    "constraints_clean": lambda r: not r.get("constraint_violations"),
    "route_sane": lambda r: r.get("route_sanity", {}).get("passed"),
    "within_turn_budget": lambda r: r.get("interview_health", {}).get("within_turn_budget"),
    "no_reask": lambda r: not r.get("interview_health", {}).get("reasked_answered_slot"),
}


def _mean(values: list[float]) -> float | None:
    """Mean of the non-None values, or None when nothing is measurable."""
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 3) if present else None


def aggregate_scorecard(rows: list[dict]) -> dict:
    """Reduce per-scenario scorecard rows (the dicts score_run returns) to per-metric means. Boolean
    metrics become pass rates over the rows where the metric is defined (None is skipped, not counted
    as a failure); groundedness ratio is averaged over the rows that have one. Pure: feed it fake rows
    and the means are exactly determined."""
    means = {
        name: _mean([1.0 if v else 0.0 if v is not None else None for v in (getter(r) for r in rows)])
        for name, getter in _BOOL_METRICS.items()
    }
    means["groundedness_ratio"] = _mean([r.get("groundedness", {}).get("ratio") for r in rows])
    means["max_day_km"] = _mean([r.get("route_sanity", {}).get("max_day_km") for r in rows])
    return {"num_scenarios": len(rows), "means": means}


def _row_marks(row: dict) -> str:
    """One-line pass/fail glyphs for a scenario row, in metric order."""
    order = ["produced_plan", "groundedness_passed", "format_valid", "constraints_clean", "route_sane"]
    marks = []
    for name in order:
        v = _BOOL_METRICS[name](row)
        marks.append("." if v is None else ("P" if v else "F"))
    return "".join(marks)


def print_table(rows: list[dict], aggregate: dict, config: ModelConfig) -> None:
    """Compact, terminal-readable scorecard: a per-scenario line then the per-metric means."""
    print(f"\nEval scorecard  (model_config={config.label}, n={aggregate['num_scenarios']})")
    print("columns: produced groundedness format constraints route  (P pass / F fail / . n/a)\n")
    print(f"  {'scenario':40s}  plan ground fmt cons rout")
    for row in rows:
        marks = _row_marks(row)
        glyphs = "  ".join(marks)
        refusal = " [refusal]" if row.get("is_refusal_scenario") else ""
        print(f"  {row.get('scenario_id', '?'):40s}   {glyphs}{refusal}")

    print("\n  per-metric means:")
    for name, value in aggregate["means"].items():
        shown = "n/a" if value is None else f"{value}"
        print(f"    {name:24s} {shown}")


def write_report(rows: list[dict], aggregate: dict, config: ModelConfig, outputs: list[dict]) -> Path:
    """Write a timestamped JSON report under reports/ (gitignored) so two runs can be diffed later."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = _REPORTS_DIR / f"eval_{config.label}_{stamp}.json"
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model_config": asdict(config),
        "aggregate": aggregate,
        "rows": rows,
        "raw_outputs": outputs,
    }
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


async def run_eval(config: ModelConfig, limit: int | None = None) -> dict:
    """Run the golden set end to end: pipeline -> score_run -> aggregate. Returns the report dict."""
    from ..orchestrator import TravelOrchestrator

    scenarios = load_golden_set()
    if limit is not None:
        scenarios = scenarios[:limit]

    orchestrator = TravelOrchestrator()
    rows: list[dict] = []
    outputs: list[dict] = []
    for i, scenario in enumerate(scenarios, start=1):
        sid = scenario.get("id", "?")
        print(f"[{i}/{len(scenarios)}] {sid} ...", flush=True)
        output = await run_scenario(orchestrator, scenario)
        if output.error:
            print(f"    error: {output.error}", flush=True)
        out_dict = asdict(output)
        outputs.append({"scenario_id": sid, **out_dict})
        rows.append(score_run(out_dict, scenario))

    aggregate = aggregate_scorecard(rows)
    print_table(rows, aggregate, config)
    path = write_report(rows, aggregate, config, outputs)
    print(f"\nreport written: {path}")
    return {"aggregate": aggregate, "rows": rows, "report_path": str(path)}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m core.eval.run", description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="run only the first N scenarios (smoke pass)")
    parser.add_argument("--model-label", default="default", help="label recorded into the report")
    parser.add_argument("--model-notes", default="", help="free-form notes about the model config")
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("CONFIG_A", "CONFIG_B"),
        help="stub: run two model configs and diff their scorecards (filled in by task M2)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.compare:
        a, b = args.compare
        print(
            f"--compare ({a} vs {b}) is a stub: model-config overrides are not wired into the graph "
            "yet. Task M2 will run two configs and diff their scorecards. Run without --compare to "
            "score a single config today."
        )
        return 2

    config = ModelConfig(label=args.model_label, notes=args.model_notes)
    asyncio.run(run_eval(config, limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
