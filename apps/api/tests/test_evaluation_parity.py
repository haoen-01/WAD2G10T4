"""Parity gate: the harness's `silverloop` fold must reproduce Care+'s own trusted,
already-tested behaviour exactly. If this ever fails, the bug is in the harness's
`simulation.py` port -- never in `sql_repository.py` or `policy.py`, and the fix must never be
to adjust a YAML's `expected_decisions`.

Parity is asserted on the UNCAPPED arm, because that is the arm in which each policy runs exactly
as written; the budget-matched arm deliberately overrides contacts and is not expected to match
the repository. For `silverloop` specifically the two arms are identical anyway (its own cap fires
first), which `test_evaluation.py::test_harness_cap_is_a_no_op_for_silverloop` asserts separately.

Both scenario sets are checked. The holdout set's `expected_decisions` were recorded by running
the real pipeline once after the scenarios were written; they are a description of behaviour, not
a target the policy was tuned towards, and `metrics.py` never reads them.
"""

from pathlib import Path

import pytest

from silverloop.evaluation.runner import UNCAPPED_ARM, run_evaluation
from silverloop.evaluation.scenario_spec import discover_scenarios
from silverloop.models import Decision

SCENARIO_DIRECTORY = Path(__file__).parents[3] / "scenarios"
HOLDOUT_DIRECTORY = SCENARIO_DIRECTORY / "holdout"

SCENARIOS = discover_scenarios(SCENARIO_DIRECTORY)
HOLDOUT_SCENARIOS = discover_scenarios(HOLDOUT_DIRECTORY)


def _assert_parity(scenario, scenario_set: str) -> None:
    result = run_evaluation(SCENARIO_DIRECTORY)
    arm = result.arms[f"{scenario_set}/{UNCAPPED_ARM}"]
    records = [r for r in arm.records["silverloop"] if r.scenario == scenario.name]
    assert records, f"{scenario.name} produced no records in the {scenario_set} set"

    decisions = [record.decision.value for record in records]
    assert decisions == list(scenario.expected_decisions)

    # Compared against the decision list, NOT `expected_cases`.
    #
    # Those two were interchangeable only while the repository opened a fresh case every day a
    # concern persisted. They are different quantities: `expected_decisions` is what the ladder
    # decided (a property of `policy.py`, which is all this harness runs), while `expected_cases`
    # is how many rows reach a coordinator's queue (a property of the repository, which this
    # harness has no access to). Asserting one against the other made a repository defect look
    # like a policy expectation.
    coordinator_review_count = sum(
        1 for record in records if record.decision == Decision.COORDINATOR_REVIEW
    )
    assert coordinator_review_count == sum(
        1 for decision in scenario.expected_decisions if decision == Decision.COORDINATOR_REVIEW
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_silverloop_decisions_match_expected(scenario) -> None:
    _assert_parity(scenario, "core")


@pytest.mark.parametrize("scenario", HOLDOUT_SCENARIOS, ids=lambda scenario: scenario.name)
def test_silverloop_holdout_decisions_match_expected(scenario) -> None:
    _assert_parity(scenario, "holdout")
