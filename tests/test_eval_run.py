"""Unit tests for the pure aggregation step of the eval runner.

aggregate_scorecard reduces score_run rows to per-metric means. It runs no pipeline and does no I/O,
so these tests feed it fake scorecard rows and assert the means exactly. The real-pipeline parts of
core.eval.run (run_scenario, run_eval) are deliberately not exercised here: they cost tokens and a DB.
"""

from core.eval.run import aggregate_scorecard


def _row(
    scenario_id="gs_x",
    produced_plan=True,
    grounded_passed=True,
    grounded_ratio=1.0,
    format_valid=True,
    constraint_violations=None,
    route_passed=True,
    max_day_km=10.0,
    within_budget=True,
    reasked=False,
    is_refusal=False,
):
    """A scorecard row in the shape score_run returns, with only the fields the aggregator reads."""
    return {
        "scenario_id": scenario_id,
        "is_refusal_scenario": is_refusal,
        "produced_plan": produced_plan,
        "groundedness": {"passed": grounded_passed, "ratio": grounded_ratio},
        "format_validity": {"passed": format_valid},
        "constraint_violations": constraint_violations or [],
        "route_sanity": {"passed": route_passed, "max_day_km": max_day_km},
        "interview_health": {"within_turn_budget": within_budget, "reasked_answered_slot": reasked},
    }


def test_all_passing_rows_give_full_pass_rates():
    rows = [_row(), _row(), _row()]
    agg = aggregate_scorecard(rows)
    assert agg["num_scenarios"] == 3
    means = agg["means"]
    assert means["produced_plan"] == 1.0
    assert means["groundedness_passed"] == 1.0
    assert means["format_valid"] == 1.0
    assert means["constraints_clean"] == 1.0
    assert means["route_sane"] == 1.0
    assert means["within_turn_budget"] == 1.0
    assert means["no_reask"] == 1.0
    assert means["groundedness_ratio"] == 1.0
    assert means["max_day_km"] == 10.0


def test_half_failing_rows_give_half_pass_rates():
    rows = [
        _row(format_valid=True, route_passed=True, constraint_violations=[]),
        _row(format_valid=False, route_passed=False, constraint_violations=["allergic to shellfish"]),
    ]
    means = aggregate_scorecard(rows)["means"]
    assert means["format_valid"] == 0.5
    assert means["route_sane"] == 0.5
    assert means["constraints_clean"] == 0.5


def test_none_metrics_are_skipped_not_counted_as_failure():
    # A refusal-style row where groundedness could not be computed (passed=None, ratio=None) must not
    # drag the pass rate down: it is excluded from the denominator, not scored as a fail.
    rows = [
        _row(grounded_passed=True, grounded_ratio=0.9),
        _row(grounded_passed=None, grounded_ratio=None),
    ]
    means = aggregate_scorecard(rows)["means"]
    assert means["groundedness_passed"] == 1.0  # one measurable row, it passed
    assert means["groundedness_ratio"] == 0.9


def test_reask_regression_lowers_no_reask_rate():
    rows = [_row(reasked=False), _row(reasked=True), _row(reasked=False), _row(reasked=False)]
    means = aggregate_scorecard(rows)["means"]
    assert means["no_reask"] == 0.75


def test_empty_rows_give_none_means_and_zero_count():
    agg = aggregate_scorecard([])
    assert agg["num_scenarios"] == 0
    assert all(v is None for v in agg["means"].values())


def test_groundedness_ratio_averages_only_present_ratios():
    rows = [_row(grounded_ratio=1.0), _row(grounded_ratio=0.5), _row(grounded_ratio=None)]
    means = aggregate_scorecard(rows)["means"]
    assert means["groundedness_ratio"] == 0.75
