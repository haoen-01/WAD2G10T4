"""The holdout freeze, for both harnesses.

A holdout that is a directory (or a list of persona briefs) rather than a process is a holdout in
name only. These tests are the process: the bytes are hashed, the hash is committed, and a change
to either is loud. See `silverloop/evaluation/holdout.py` for why the answer to a genuine change
is a new set rather than a quiet edit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from silverloop.evaluation.holdout import (
    FROZEN_DIGEST_FILENAME,
    frozen_label,
    holdout_frozen,
    read_frozen_digest,
)
from silverloop.evaluation.ranking.dataset import (
    HOLDOUT_FROZEN_DIGEST,
    HOLDOUT_PERSONAS,
)
from silverloop.evaluation.ranking.dataset import (
    holdout_digest as ranking_holdout_digest,
)
from silverloop.evaluation.ranking.dataset import holdout_frozen as ranking_holdout_frozen
from silverloop.evaluation.runner import HOLDOUT_DIRNAME, _scenario_digest
from silverloop.evaluation.scenario_spec import discover_scenarios

SCENARIO_DIRECTORY = Path(__file__).parents[3] / "scenarios"
HOLDOUT_DIRECTORY = SCENARIO_DIRECTORY / HOLDOUT_DIRNAME


def _live_digest() -> str:
    return _scenario_digest([scenario.path for scenario in discover_scenarios(HOLDOUT_DIRECTORY)])


def test_holdout_digest_matches_frozen_file() -> None:
    """The five holdout scenarios' bytes still hash to what was committed when the set was frozen.

    If this fails, the question is not "what number do I put in the file" -- it is why the holdout
    changed. The one edit this repo has made (`4d3ddbd`, `h01` step 4's label) moved M1 holdout
    from 2/11 to 3/12, i.e. AGAINST Care+, and is the reason the freeze now exists rather
    than a reason to doubt it.
    """
    frozen = read_frozen_digest(HOLDOUT_DIRECTORY)
    assert frozen is not None, f"{FROZEN_DIGEST_FILENAME} is missing from {HOLDOUT_DIRECTORY}"
    assert frozen == _live_digest(), (
        "the holdout YAML has changed since it was frozen; a genuine change belongs in "
        "scenarios/holdout-v2/ with its own FROZEN_DIGEST, not under the published numbers"
    )
    assert holdout_frozen(HOLDOUT_DIRECTORY, _live_digest()) is True


def test_an_unfrozen_directory_reports_unknown_rather_than_guessing(tmp_path: Path) -> None:
    """A set that has never been frozen is `None`, not `False`: "nobody has run this process" and
    "the bytes have moved" are different findings and the report prints them differently."""
    assert read_frozen_digest(tmp_path) is None
    assert holdout_frozen(tmp_path, "whatever") is None
    assert "unknown" in frozen_label(None)
    assert frozen_label(True) == "true"
    assert "FALSE" in frozen_label(False)


def test_a_changed_holdout_reports_false(tmp_path: Path) -> None:
    (tmp_path / FROZEN_DIGEST_FILENAME).write_text("deadbeef\n", encoding="utf-8")
    assert read_frozen_digest(tmp_path) == "deadbeef"
    assert holdout_frozen(tmp_path, "deadbeef") is True
    assert holdout_frozen(tmp_path, "something-else") is False


def test_the_policy_runner_prints_the_holdout_freeze(capsys: pytest.CaptureFixture[str]) -> None:
    from silverloop.evaluation.runner import main

    assert main([str(SCENARIO_DIRECTORY), "--fail-on-violation", "none"]) == 0
    assert "holdout_frozen: true" in capsys.readouterr().out


def test_ranking_holdout_personas_match_their_frozen_digest() -> None:
    """The ranking benchmark's holdout is four persona briefs in code rather than a directory of
    YAML, so it carries its own frozen digest and the same discipline applies to it."""
    assert len(HOLDOUT_PERSONAS) == 4
    assert ranking_holdout_digest() == HOLDOUT_FROZEN_DIGEST
    assert ranking_holdout_frozen() is True


def test_the_ranking_runner_reports_the_holdout_freeze() -> None:
    from silverloop.evaluation.ranking.report import to_markdown
    from silverloop.evaluation.ranking.runner import run_evaluation

    result = run_evaluation()
    assert result.holdout_frozen is True
    assert result.holdout_digest == HOLDOUT_FROZEN_DIGEST
    assert "holdout_frozen: `true`" in to_markdown(result)
