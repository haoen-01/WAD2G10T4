from pathlib import Path

import pytest

from silverloop.scenarios import run_scenario

SCENARIO_DIRECTORY = Path(__file__).parents[3] / "scenarios"
HOLDOUT_DIRECTORY = SCENARIO_DIRECTORY / "holdout"

SCENARIOS = sorted(SCENARIO_DIRECTORY.glob("*.yaml"))
HOLDOUT_SCENARIOS = sorted(HOLDOUT_DIRECTORY.glob("*.yaml"))


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda path: path.stem)
def test_safety_scenario(path: Path) -> None:
    run_scenario(path)


@pytest.mark.parametrize("path", HOLDOUT_SCENARIOS, ids=lambda path: path.stem)
def test_holdout_scenario(path: Path) -> None:
    """The holdout scenarios run through the real `SqlAlchemyRepository`, exactly like the core
    set. `python -m silverloop.scenarios` globs non-recursively and so does not reach them; this
    test is what keeps them executable and their recorded behaviour honest.
    """
    run_scenario(path)


def test_scenario_suite_is_not_empty() -> None:
    assert len(SCENARIOS) >= 6


def test_holdout_suite_is_present_and_separate() -> None:
    """The holdout set must exist, and must not leak into the core glob -- pooling the two would
    void the point of holding them out.
    """
    assert len(HOLDOUT_SCENARIOS) == 5
    assert {path.stem for path in SCENARIOS}.isdisjoint({path.stem for path in HOLDOUT_SCENARIOS})
