"""The review-setting calibration evaluation (`silverloop.evaluation.calibration`).

Pins the authored sequences, the simulated coordinators, determinism, the no-network agent arm, the
import boundary, the committed artifacts, and -- the point of the evaluation -- that a dismissive
coordinator's loosenings stay contained by the floor and the shadow check.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from silverloop.evaluation.calibration.metrics import CAP_REASON, episode_outcomes, episode_summary
from silverloop.evaluation.calibration.profiles import PROFILES, counts_toward_loosening, judge
from silverloop.evaluation.calibration.report import (
    JSON_FILENAME,
    MARKDOWN_FILENAME,
    check_artifacts,
    to_json_document,
    to_markdown,
)
from silverloop.evaluation.calibration.runner import (
    ARMS,
    CalibrationResult,
    DayRecord,
    RunTrace,
    run_calibration_evaluation,
    run_one,
)
from silverloop.evaluation.calibration.sequences import (
    CALIBRATION_SEQUENCES,
    CALIBRATION_SEQUENCES_DIGEST,
    SEQUENCE_LENGTH_DAYS,
    AuthoredDay,
    CalibrationSequence,
    Episode,
    sequences_digest,
)
from silverloop.models import CaseStatus, HumanAction, OverrideReason
from silverloop.review_threshold import SHADOW_GRACE_DAYS

DOCS_EVALUATION = Path(__file__).parents[3] / "docs" / "evaluation"

# Changing an authored day or label changes this. Update it only in a reviewed change that says
# why the sequences moved -- never to make a containment check pass.
PINNED_SEQUENCES_DIGEST = "bcb0eb272d3d590cbfb9d3f882bf680d65c64f5bf81b873e8e2b8b4acf0b1f30"


@pytest.fixture(scope="module")
def result() -> CalibrationResult:
    return run_calibration_evaluation()


@pytest.fixture(scope="module")
def document(result: CalibrationResult) -> dict[str, Any]:
    return to_json_document(result)


def _cell(document: dict[str, Any], arm: str, profile: str) -> dict[str, Any]:
    [cell] = [
        item for item in document["cells"] if item["arm"] == arm and item["profile"] == profile
    ]
    return cell


# --- Sequences ---------------------------------------------------------------------------------


def test_sequences_digest_is_pinned() -> None:
    assert CALIBRATION_SEQUENCES_DIGEST == PINNED_SEQUENCES_DIGEST
    assert sequences_digest() == PINNED_SEQUENCES_DIGEST


def test_sequences_are_well_formed_and_cover_what_the_evaluation_needs() -> None:
    assert len(CALIBRATION_SEQUENCES) >= 2
    assert len({sequence.sequence_id for sequence in CALIBRATION_SEQUENCES}) == len(
        CALIBRATION_SEQUENCES
    )
    labels: set[str] = set()
    floor_episodes = 0
    moderate_review_worthy = 0
    for sequence in CALIBRATION_SEQUENCES:
        assert [day.day for day in sequence.days] == list(range(1, SEQUENCE_LENGTH_DAYS + 1))
        previous_end = 0
        for episode in sequence.episodes:
            assert previous_end < episode.start_day <= episode.end_day <= SEQUENCE_LENGTH_DAYS
            previous_end = episode.end_day
            labels.add(episode.label)
            if episode.review_worthy:
                assert episode.should_reach_by_day is not None
                assert episode.start_day <= episode.should_reach_by_day <= episode.end_day
                if sequence.reaches_floor(episode):
                    floor_episodes += 1
                else:
                    moderate_review_worthy += 1
            else:
                assert episode.should_reach_by_day is None
                assert not sequence.reaches_floor(episode)
                # Benign means brief: a benign episode never lasts longer than four days.
                assert episode.end_day - episode.start_day + 1 <= 4
        # Outside every episode, an ordinary day is never low.
        for day in sequence.days:
            if sequence.episode_on(day.day) is None:
                assert day.steps_fraction >= 0.9
    assert {"benign_swing", "genuine_decline", "severe_decline"} <= labels
    assert floor_episodes >= 1
    assert moderate_review_worthy >= 1


# --- Profiles ----------------------------------------------------------------------------------


def test_profiles_are_the_documented_rules() -> None:
    benign = Episode("b", "benign_swing", 1, 3, review_worthy=False, should_reach_by_day=None)
    worthy = Episode("w", "genuine_decline", 10, 20, review_worthy=True, should_reach_by_day=13)
    for episode, day in ((benign, 3), (worthy, 12), (worthy, 15), (None, 30)):
        dismissive = judge("dismissive", episode, day)
        assert (dismissive.status, dismissive.human_action, dismissive.override_reason) == (
            CaseStatus.RESOLVED,
            HumanAction.OVERRIDE,
            OverrideReason.NOT_A_CONCERN,
        )
        assert counts_toward_loosening(dismissive)
        cautious = judge("over_cautious", episode, day)
        assert cautious.status is CaseStatus.ACKNOWLEDGED
        assert cautious.human_action is HumanAction.AGREE
        assert cautious.reached_too_late is True
        assert not counts_toward_loosening(cautious)

    assert counts_toward_loosening(judge("accurate", benign, 3))
    assert counts_toward_loosening(judge("accurate", None, 30))
    on_time = judge("accurate", worthy, 13)
    late = judge("accurate", worthy, 14)
    assert (on_time.human_action, on_time.reached_too_late) == (HumanAction.AGREE, False)
    assert (late.human_action, late.reached_too_late) == (HumanAction.AGREE, True)


# --- Determinism, network and import boundary --------------------------------------------------


def test_a_run_is_deterministic() -> None:
    sequence = CALIBRATION_SEQUENCES[0]
    first = run_one("agent", "dismissive", sequence)
    second = run_one("agent", "dismissive", sequence)
    assert asdict(first) == asdict(second)


def test_the_agent_arm_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[Any] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        attempts.append(args)
        raise AssertionError("the calibration evaluation opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    trace = run_one("agent", "dismissive", CALIBRATION_SEQUENCES[0])
    assert attempts == []
    calibrations = [item for item in trace.proposals if item.output_kind != "write_up"]
    assert calibrations
    # The scripted stand-in actually answered: no output fell back for a transport failure.
    assert all(item.proposer == "agent" for item in calibrations)
    assert all(item.agent_mode == "agent" for item in calibrations)


def test_importing_the_package_loads_no_repository_config_or_agent() -> None:
    script = (
        "import sys; import silverloop.evaluation; "
        "assert 'silverloop.evaluation.calibration' not in sys.modules; "
        "import silverloop.evaluation.calibration, silverloop.evaluation.calibration.sequences, "
        "silverloop.evaluation.calibration.profiles, silverloop.evaluation.calibration.metrics, "
        "silverloop.evaluation.calibration.runner, silverloop.evaluation.calibration.report; "
        "forbidden = {'silverloop.sql_repository', 'silverloop.db_models', "
        "'silverloop.main', 'silverloop.config', 'silverloop.agent', "
        "'silverloop.agent.planner', 'anthropic', 'openai', 'boto3'}; "
        "loaded = forbidden & set(sys.modules); "
        "assert not loaded, loaded; "
        "print('OK')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1] / "src",
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout


# --- Report ------------------------------------------------------------------------------------


def test_report_covers_every_arm_and_profile_and_is_labelled_synthetic(
    document: dict[str, Any], result: CalibrationResult
) -> None:
    assert document["synthetic"] is True
    assert "SYNTHETIC" in document["disclosure"]
    assert "NOT A MODEL" in document["disclosure"]
    assert document["sequences_digest"] == PINNED_SEQUENCES_DIGEST
    assert {(cell["arm"], cell["profile"]) for cell in document["cells"]} == {
        (arm, profile) for arm in ARMS for profile in PROFILES
    }
    for cell in document["cells"]:
        assert len(cell["by_sequence"]) == len(CALIBRATION_SEQUENCES)
        assert (cell["containment"] is None) == (cell["arm"] == "starting_setting")
    assert "SYNTHETIC" in to_markdown(result)


def test_report_carries_no_ids_or_wall_clock_times(result: CalibrationResult) -> None:
    text = json.dumps(to_json_document(result)) + to_markdown(result)
    for pattern in (
        r"\b(review|case|run|decision|threshold|proposal|wearable|metric|audit)_[0-9a-f]{8,}",
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",
        r"\b2026-\d{2}-\d{2}\b",
    ):
        assert re.search(pattern, text) is None, pattern


def test_committed_artifacts_are_current(result: CalibrationResult) -> None:
    assert (DOCS_EVALUATION / JSON_FILENAME).exists()
    assert (DOCS_EVALUATION / MARKDOWN_FILENAME).exists()
    assert check_artifacts(result, DOCS_EVALUATION), (
        "docs/evaluation/review-calibration.* is stale; run "
        "`uv run python -m silverloop.evaluation.calibration --out ../../docs/evaluation`"
    )


def test_cli_check_without_out_is_a_usage_error() -> None:
    from silverloop.evaluation.calibration.__main__ import main

    assert main(["--check"]) == 2


# --- Coverage: an unresolved case keeps an episode in front of the coordinator ------------------


def _trace(days: list[tuple[int, bool, bool]]) -> RunTrace:
    trace = RunTrace(arm="fixed_rule", profile="accurate", sequence_id="coverage")
    trace.days = [
        DayRecord(
            day=day,
            decision="no_action",
            gate="within_range",
            delta_percent=0.0,
            sustained_low_days=0,
            case_opened=opened,
            case_unresolved=unresolved,
            live_severity_pct=40,
            live_persistence_days=3,
        )
        for day, opened, unresolved in days
    ]
    return trace


def _coverage_sequence() -> CalibrationSequence:
    authored = tuple(AuthoredDay(day, 1.0, 14.0, False) for day in range(1, 11))
    return CalibrationSequence(
        sequence_id="coverage",
        title="coverage",
        description="coverage",
        days=authored,
        episodes=(
            Episode("first", "genuine_decline", 1, 4, True, 3),
            Episode("second", "genuine_decline", 6, 9, True, 7),
        ),
    )


def test_an_episode_spanned_by_a_still_unresolved_case_is_retained_not_missed() -> None:
    sequence = _coverage_sequence()
    # One case opens on day 2 and is acknowledged; it is still unresolved through day 8, so the
    # second episode's declining days refresh it and no new case opens.
    starting = _trace([(day, day == 2, 2 <= day <= 8) for day in range(1, 11)])
    # In this arm the case opens on day 3 and is resolved at once; nothing covers day 6 or 7, and
    # an acknowledged case opened on day 8 covers day 8 onwards.
    arm = _trace([(day, day in (3, 8), day >= 8) for day in range(1, 11)])

    outcomes = {item.episode_id: item for item in episode_outcomes(arm, starting, sequence)}
    reference = {item.episode_id: item for item in episode_outcomes(starting, starting, sequence)}

    assert reference["second"].cases_opened == 0
    assert reference["second"].first_case_day is None
    assert reference["second"].first_covered_day == 6
    assert reference["second"].late is False
    assert episode_summary(list(reference.values()))["review_worthy_missed"] == 0

    assert (outcomes["first"].first_covered_day, outcomes["first"].delay_days) == (3, 1)
    assert outcomes["second"].first_case_day == 8
    assert outcomes["second"].first_covered_day == 8
    assert outcomes["second"].starting_first_covered_day == 6
    assert outcomes["second"].delay_days == 2
    assert outcomes["second"].late is True
    summary = episode_summary(list(outcomes.values()))
    assert (summary["review_worthy_retained"], summary["review_worthy_missed"]) == (2, 0)
    assert summary["review_worthy_late"] == 1
    assert summary["max_delay_days"] == 2


def test_a_resolved_case_before_an_episode_does_not_cover_it() -> None:
    sequence = _coverage_sequence()
    trace = _trace([(day, day == 2, False) for day in range(1, 11)])
    outcomes = {item.episode_id: item for item in episode_outcomes(trace, trace, sequence)}
    assert outcomes["second"].first_covered_day is None
    assert episode_summary(list(outcomes.values()))["review_worthy_missed"] == 1


def test_the_runner_records_unresolved_cases(result: CalibrationResult) -> None:
    """A case the simulated coordinator acknowledges is still unresolved at the end of the day it
    opened; a dismissive coordinator resolves every case that day, so their runs record none."""
    acknowledged_somewhere = False
    for trace in result.traces:
        by_day = {day.day: day for day in trace.days}
        for review in trace.reviews:
            if review.status == CaseStatus.ACKNOWLEDGED.value:
                acknowledged_somewhere = True
                assert by_day[review.opened_day].case_unresolved, (trace.arm, trace.sequence_id)
        if trace.profile == "dismissive":
            assert not any(day.case_unresolved for day in trace.days), trace.sequence_id
    assert acknowledged_somewhere


# --- Containment -------------------------------------------------------------------------------


@pytest.mark.parametrize("arm", ["fixed_rule", "agent"])
def test_a_dismissive_coordinator_is_contained(document: dict[str, Any], arm: str) -> None:
    cell = _cell(document, arm, "dismissive")
    starting = {
        run["sequence_id"]: run
        for run in _cell(document, "starting_setting", "dismissive")["by_sequence"]
    }
    # The arm really did loosen: containment of a setting that never moved would prove nothing.
    assert cell["totals"]["threshold"]["approved_looser"] > 0
    for run in cell["by_sequence"]:
        episodes = run["episodes"]
        reference = starting[run["sequence_id"]]["episodes"]
        assert episodes["review_worthy_missed"] <= reference["review_worthy_missed"], run[
            "sequence_id"
        ]
        if episodes["max_delay_days"] is not None:
            assert episodes["max_delay_days"] <= SHADOW_GRACE_DAYS, run["sequence_id"]
        assert episodes["floor_episodes_opened"] == episodes["floor_episodes"], run["sequence_id"]
        for outcome in run["episode_outcomes"]:
            if outcome["reaches_floor"]:
                assert outcome["first_case_day"] is not None, outcome["episode_id"]
        calibrator = run["calibrator"]
        assert calibrator["calibration_skips"].get(CAP_REASON, 0) == 0
        assert calibrator["calibration_discards"].get(CAP_REASON, 0) == 0
    assert cell["containment"]["holds"] is True


def test_the_weekly_cap_never_binds_in_any_cell(document: dict[str, Any]) -> None:
    """The cap counts wall-clock time, which a sixty-day run in seconds cannot honour; the
    sequences are authored to stay under it, and this proves they do."""
    for cell in document["cells"]:
        assert cell["totals"]["calibrator"]["weekly_cap_skips"] == 0, (cell["arm"], cell["profile"])


def test_the_evaluation_exercises_the_floor_and_the_shadow_check(document: dict[str, Any]) -> None:
    """Containment is only meaningful if the guarantees were actually reached for."""
    routes: dict[str, int] = {"floor": 0, "shadow_check": 0}
    for arm in ("fixed_rule", "agent"):
        cell_routes = _cell(document, arm, "dismissive")["totals"]["workload"]["cases_by_route"]
        for route in routes:
            routes[route] += cell_routes[route]
    assert routes["floor"] > 0
    assert routes["shadow_check"] > 0
