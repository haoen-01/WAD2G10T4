"""Where the recordings live, what settings the arm runs under, and how one benchmark case
becomes a planner request.

Hermetic settings
-----------------
`Settings` reads `.env` and the process environment. Left to itself, a developer's
`LLM_REQUEST_PROFILE=legacy` would change the system block and the tool schemas, change the
request key, miss every recording and turn a published artifact into a machine-dependent one.
`recorded_settings` therefore passes every request-shaping field explicitly (init arguments
outrank both sources) and disables the dotenv files. Pinned by
`test_ranking_llm_arm.py::test_arm_settings_ignore_the_ambient_environment`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from silverloop.agent.tools import ActivityOption, ActivityRankingContext
from silverloop.config import Settings
from silverloop.evaluation.ranking.dataset import FROZEN_TODAY
from silverloop.evaluation.ranking.runner import CaseResult
from silverloop.evaluation.ranking_llm.scripted_model import SCRIPTED_MODEL_ID
from silverloop.intent import describe_intent
from silverloop.local_time import local_hour

# `apps/api/tests/recordings`. Fixtures live under `tests/` because that is what they are --
# committed, reviewed test data -- and the audit that specified this arm named that location.
RECORDINGS_ROOT = Path(__file__).resolve().parents[4] / "tests" / "recordings"
ACTIVITY_RECORDINGS = RECORDINGS_ROOT / "activity_ranking"
INTENT_RECORDINGS = RECORDINGS_ROOT / "intent"
# The review-threshold calibrator's guided sequence (ADR 0008 stage 3, `threshold_sequence`).
THRESHOLD_RECORDINGS = RECORDINGS_ROOT / "review_threshold"

MAX_ITERATIONS = 4


def recorded_settings(recording_path: Path, *, model: str = SCRIPTED_MODEL_ID) -> Settings:
    """The one `Settings` both the generator and the arm use. See the module docstring."""
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        adapter_mode="fixture",
        external_context_enabled=False,
        llm_enabled=True,
        llm_provider="recorded",
        llm_recording_path=str(recording_path),
        llm_model=model,
        llm_request_profile="modern",
        llm_thinking="adaptive",
        llm_effort="medium",
        llm_max_iterations=MAX_ITERATIONS,
    )


def time_window_of(start_at: Any) -> str:
    """Mirrors `activity_rerank.time_window_of` by value.

    Duplicated rather than imported for the reason `evaluation/ranking/_dimensions.py` gives for
    the same choice: this package must not import the repository layer, and the buckets are a
    three-line vocabulary the production side owns.
    """
    if start_at is None:
        return "any"
    hour = local_hour(start_at)
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def ranking_context(case: CaseResult, ranked: list[Any]) -> ActivityRankingContext:
    """Assemble exactly the context `sql_repository.search_activities` assembles for the planner.

    Field-for-field the same projection (`sql_repository.py`, the `plan_activity_ranking` call in
    `search_activities`): if this drifted, the arm would be measuring a prompt the product never
    sends.
    """
    return ActivityRankingContext(
        understood_lines=describe_intent(case.intent),
        options=[
            ActivityOption(
                key=item.ranked.candidate.activity_id,
                title=item.ranked.candidate.title,
                category=item.ranked.candidate.category,
                distance_m=item.ranked.candidate.distance_m,
                environment=item.ranked.candidate.indoor_outdoor.value,
                intensity=(
                    item.ranked.candidate.intensity.value
                    if item.ranked.candidate.intensity is not None
                    else None
                ),
                time_window=time_window_of(item.ranked.candidate.start_at),
                deterministic_rank=item.ranked.rank,
                reasons=[reason.text for reason in item.ranked.reasons],
            )
            for item in ranked
        ],
    )


ADVERSARIAL_RECORDINGS = RECORDINGS_ROOT / "adversarial"


def adversarial_context() -> ActivityRankingContext:
    """A small, hand-built context used by exactly one fixture: the guardrail-revision recording.

    Deliberately not a benchmark case. The stand-in that produced that fixture is scripted to
    propose a key that was never permitted, and a scripted violation inside the benchmark would
    put a fabricated rejection rate into a published table. It lives here rather than in the test
    so the fixture and the test that replays it are built from the identical request -- a
    context defined twice would key differently and miss.
    """
    return ActivityRankingContext(
        understood_lines=["Anything that suits you"],
        options=[
            ActivityOption(
                key=f"adversarial-{index}",
                title=f"Synthetic option {index}",
                category="movement" if index % 2 else "social",
                distance_m=400 + 100 * index,
                environment="indoor",
                intensity="light",
                time_window="morning",
                deterministic_rank=index + 1,
                reasons=["Matches what you asked for"],
            )
            for index in range(4)
        ],
    )


@dataclass(frozen=True)
class IntentCase:
    """One free-text request for the intent-parse recording.

    The ranking benchmark builds `ActivityIntent`s directly -- it has no free text at all -- so
    these six phrasings were authored to mirror its six query templates one for one. They are
    synthetic sentences written for this fixture, not anything a person said.
    """

    name: str
    template: str
    text: str
    today: date = FROZEN_TODAY


INTENT_CASES: tuple[IntentCase, ...] = (
    IntentCase(
        name="unconstrained",
        template="unconstrained",
        text="Something nice to do, I don't mind what.",
    ),
    IntentCase(
        name="morning_indoors_gentle",
        template="tuesday_morning_indoors_gentle",
        text="Something gentle indoors tomorrow morning please.",
    ),
    IntentCase(
        name="meet_people_nearby",
        template="meet_people_nearby",
        text="I'd like to meet some people, somewhere close to home.",
    ),
    IntentCase(
        name="language_constrained",
        template="language_constrained",
        text="Anything run in Mandarin?",
    ),
    IntentCase(
        name="distance_constrained",
        template="distance_constrained",
        text="Nothing far, my knees are not what they were.",
    ),
    IntentCase(
        name="evening_solitary",
        template="evening_solitary",
        text="Something quiet on my own in the evening.",
    ),
)


__all__ = [
    "ACTIVITY_RECORDINGS",
    "ADVERSARIAL_RECORDINGS",
    "INTENT_CASES",
    "INTENT_RECORDINGS",
    "MAX_ITERATIONS",
    "RECORDINGS_ROOT",
    "THRESHOLD_RECORDINGS",
    "IntentCase",
    "adversarial_context",
    "ranking_context",
    "recorded_settings",
    "time_window_of",
]
