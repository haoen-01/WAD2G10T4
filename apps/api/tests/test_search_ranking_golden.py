"""The search audit's `detail.ranking` is pinned: a ranking change must be deliberate and reviewed.

`search_activities` runs `activity_search.rank_with_trace` (filter -> score_and_sort -> dedupe ->
diversify) and reads its inputs through `_ranking_inputs`. "The evaluation artifacts did not
change" only covers the pure ranker over the evaluation harness's own inputs -- not the
repository's read phase (engagement counting, series roll-up, rain, preferences) -- so these
goldens pin the whole search path end to end.

History. Both files were first captured from the code *before* the ranker-inspector refactor
(commit `0fdc84f`) and proved that refactor behaviour-identical. They were then deliberately
regenerated on 2026-09-15 for the recorded-discrepancy fixes, and the diff was reviewed item by
item: every row gained `tier`, `matched_axes` and `coverage` (D2); sessions of one programme now
break ties soonest first, so 90 of 145 cases swap sessions within a programme and none reorders
programmes (D18); preference and engagement values moved where one unclarified "not for me" is now
held back and activity types resolve per value (D7, D17); reason lines follow each factor's
positive contribution (D12, D15); and the scripted planner case labels the tail it never saw
`ranker` (D3). A second, reviewed regeneration the same day (round 2) changed only reason wording --
the catalogue filler line, stated, goal and learned lines naming their source, and senior sentences
phrased without a double hyphen -- and
added the `more_reasons` capture; a checkpoint before any wording change proved that moving extra
lines off the card face left every visible line in place. Regenerate only for a deliberate ranking
change, with
`SILVERLOOP_REGENERATE_SEARCH_GOLDEN=1 uv run pytest tests/test_search_ranking_golden.py`, and
review the diff before accepting it.

The scenario golden covers what the first one does not reach: a variety swap on the search path,
a went-and-enjoyed plan report, same-day repeat taps, an "interested" on a sibling session after
a decline, and a search whose bounded planner (a scripted transport, never the network) is
rejected once, then narrows and reorders.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from silverloop.config import Settings
from silverloop.models import (
    ActivityEnvironment,
    ActivityIntent,
    ActivityOfferResponse,
    DeclineReason,
    Enjoyment,
    GoalKind,
    LikedAspect,
    PlannedFollowThrough,
    PreferenceDimension,
    PreferenceStance,
    SocialPreference,
    TimeWindow,
)
from silverloop.sql_repository import SqlAlchemyRepository

GOLDEN_PATH = Path(__file__).parent / "golden" / "search_detail_ranking.jsonl"
SCENARIO_GOLDEN_PATH = Path(__file__).parent / "golden" / "search_scenarios_golden.jsonl"

_PERSONAS = ("mdm-lim", "mr-ravi", "mdm-siti", "mr-tan", "mdm-devi")

_TEXTS: tuple[str | None, ...] = (
    None,
    "something near me",
    "something with other people in the morning",
    "indoor light exercise",
    "no walking, my knee",
    "within 800 m",
    "something outdoors this afternoon",
)

_CHIPS = ActivityIntent(
    social_preference=SocialPreference.SOCIAL,
    environment=ActivityEnvironment.INDOOR,
    time_window=TimeWindow.ANY,
)


def _search(
    repository: SqlAlchemyRepository,
    person_id: str,
    *,
    text: str | None = None,
    intent: ActivityIntent | None = None,
    label: str,
) -> dict[str, Any]:
    response = repository.search_activities(
        text=text, intent=intent, person_id=person_id, actor="golden"
    )
    event = next(
        event
        for event in repository.list_events(person_id=person_id)
        if event.event_type == "activity_search"
        and event.detail.get("query_id") == response.query_id
    )
    return {
        "label": label,
        "person_id": person_id,
        "ranking": event.detail["ranking"],
        "result_ids": event.detail["result_ids"],
        "filtered_out": [
            {"activity_id": item.activity_id, "rule": item.rule, "detail": item.detail}
            for item in response.filtered_out
        ],
        "reasons": [
            [reason.model_dump(mode="json") for reason in item.reasons] for item in response.results
        ],
        # The lines a card shows only when opened: pinned beside the face so a change to what is
        # moved off the face, or dropped, is as visible in the diff as a change to the face itself.
        "more_reasons": [
            [reason.model_dump(mode="json") for reason in item.more_reasons]
            for item in response.results
        ],
    }


def _offline_repository() -> SqlAlchemyRepository:
    return SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=Settings(
            app_env="test",
            database_url="sqlite+pysqlite:///:memory:",
            silverloop_runtime_profile="offline",
            auth_enabled=False,
            llm_enabled=False,
        ),
    )


def collect_search_rankings() -> list[dict[str, Any]]:
    repository = _offline_repository()
    repository.create_schema_for_tests()
    captured: list[dict[str, Any]] = []
    try:
        for person_id in _PERSONAS:
            repository.reset(person_id=person_id)
            for text in _TEXTS:
                captured.append(
                    _search(repository, person_id, text=text, label=f"live:{text or '<none>'}")
                )
            captured.append(_search(repository, person_id, intent=_CHIPS, label="live:chips"))

            # Stated beliefs and goals, so the preference factor is exercised at every tier.
            today = repository.person_state(person_id=person_id).current_day
            if person_id == "mdm-lim":
                repository.set_goal(GoalKind.MEET_PEOPLE, None, True, "golden", person_id=person_id)
                repository.state_preference(
                    PreferenceDimension.ENVIRONMENT,
                    "indoor",
                    PreferenceStance.PREFER,
                    actor="golden",
                    person_id=person_id,
                )
            if person_id == "mr-ravi":
                repository.state_preference(
                    PreferenceDimension.ACTIVITY_TYPE,
                    "walking",
                    PreferenceStance.AVOID,
                    until=today + timedelta(days=3),
                    actor="golden",
                    person_id=person_id,
                )
                repository.state_preference(
                    PreferenceDimension.INTENSITY,
                    "light",
                    PreferenceStance.PREFER,
                    actor="golden",
                    person_id=person_id,
                )
            for text in _TEXTS:
                captured.append(
                    _search(repository, person_id, text=text, label=f"stated:{text or '<none>'}")
                )

            # Engagement: a reasoned decline, a plain decline and an interest on the first three
            # results of an open search, then the same searches again.
            opened = repository.search_activities(
                text=None, intent=None, person_id=person_id, actor="golden"
            )
            ids = [item.candidate.activity_id for item in opened.results]
            if len(ids) >= 3:
                repository.respond_to_activity(
                    ids[0],
                    ActivityOfferResponse.NOT_FOR_ME,
                    reason=DeclineReason.TOO_FAR,
                    actor="golden",
                    person_id=person_id,
                )
                repository.respond_to_activity(
                    ids[1],
                    ActivityOfferResponse.NOT_FOR_ME,
                    reason=DeclineReason.NOT_FOR_ME,
                    actor="golden",
                    person_id=person_id,
                )
                repository.respond_to_activity(
                    ids[2],
                    ActivityOfferResponse.INTERESTED,
                    query_id=opened.query_id,
                    rank_shown=3,
                    actor="golden",
                    person_id=person_id,
                )
            for text in _TEXTS:
                captured.append(
                    _search(repository, person_id, text=text, label=f"engaged:{text or '<none>'}")
                )

            # Rain, on a later simulated day (the cooldown and wrong_day both move).
            repository.advance("rain_explains_decline", person_id=person_id)
            for text in _TEXTS:
                captured.append(
                    _search(repository, person_id, text=text, label=f"rain:{text or '<none>'}")
                )
    finally:
        repository.close()
    return captured


def test_search_detail_ranking_matches_the_reviewed_golden() -> None:
    # One search per line, so a real difference names the search it happened in.
    rendered = [json.dumps(case, sort_keys=True) for case in collect_search_rankings()]
    if os.environ.get("SILVERLOOP_REGENERATE_SEARCH_GOLDEN") == "1":
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    golden = GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
    assert len(rendered) == len(golden)
    for line, (actual, expected) in enumerate(zip(rendered, golden, strict=True), start=1):
        assert actual == expected, f"search #{line} ({json.loads(expected)['label']}) changed"


# ── Scenarios the first golden does not reach ─────────────────────────────────────────────────


@dataclass
class _Block:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _Response:
    content: list[Any]
    stop_reason: str = "tool_use"
    usage: Any = None


@dataclass
class _ScriptedPlanner:
    """Reads the options, proposes an invented key (rejected), then swaps the first two options
    and leaves out the last one it was shown (approved)."""

    calls: list[int] = field(default_factory=list)

    @property
    def messages(self) -> _ScriptedPlanner:
        return self

    def create(self, **kwargs: Any) -> Any:
        turn = len(self.calls)
        self.calls.append(turn)
        if turn == 0:
            return _Response([_Block("t0", "get_activity_options", {})])
        if turn == 1:
            self.keys = [
                option["activity_key"]
                for option in json.loads(kwargs["messages"][-1]["content"][0]["content"])["options"]
            ]
            return _Response(
                [
                    _Block(
                        "t1",
                        "propose_activity_order",
                        {"ordered_keys": ["invented-key", *self.keys], "reasoning": "r"},
                    )
                ]
            )
        keys = [self.keys[1], self.keys[0], *self.keys[2:-1]]
        return _Response(
            [_Block("t2", "propose_activity_order", {"ordered_keys": keys, "reasoning": "r"})]
        )


def _latest_plan_id(repository: SqlAlchemyRepository, person_id: str, activity_id: str) -> Any:
    week = repository.week_plan(person_id=person_id)
    return next(entry for entry in week.entries if entry.activity.activity_id == activity_id)


def collect_search_scenarios(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    # A variety swap on the search path: a too-tiring "not for me" on one walk, then a walking
    # request, leaves three walks in the top three and a stretch session within the margin.
    repository = _offline_repository()
    repository.create_schema_for_tests()
    try:
        repository.reset(person_id="mdm-lim")
        repository.respond_to_activity(
            "activity-brisk-walk-1",
            ActivityOfferResponse.NOT_FOR_ME,
            reason=DeclineReason.TOO_TIRING,
            actor="golden",
            person_id="mdm-lim",
        )
        walking = ActivityIntent.model_validate({"activity_types": ["walking"]})
        captured.append(_search(repository, "mdm-lim", intent=walking, label="variety:walking"))
        assert any(row["variety_promoted"] for row in captured[-1]["ranking"])

        # Same-day repeat taps: the same decline twice and the same interest twice, one day.
        repository.reset(person_id="mr-ravi")
        for _ in range(2):
            repository.respond_to_activity(
                "activity-evening-social-1",
                ActivityOfferResponse.NOT_FOR_ME,
                reason=DeclineReason.TOO_FAR,
                actor="golden",
                person_id="mr-ravi",
            )
            repository.respond_to_activity(
                "activity-craft-circle-2",
                ActivityOfferResponse.INTERESTED,
                actor="golden",
                person_id="mr-ravi",
            )
        for text in (None, "something near me"):
            captured.append(
                _search(repository, "mr-ravi", text=text, label=f"repeat:{text or '<none>'}")
            )

        # "Interested" on a sibling session after a decline on another session of the programme.
        repository.reset(person_id="mdm-siti")
        repository.respond_to_activity(
            "activity-chair-mobility-1",
            ActivityOfferResponse.NOT_FOR_ME,
            reason=DeclineReason.NOT_FOR_ME,
            actor="golden",
            person_id="mdm-siti",
        )
        repository.respond_to_activity(
            "activity-chair-mobility-2",
            ActivityOfferResponse.INTERESTED,
            actor="golden",
            person_id="mdm-siti",
        )
        chair = ActivityIntent.model_validate({"activity_types": ["chair_exercise"]})
        captured.append(_search(repository, "mdm-siti", label="sibling:<none>"))
        captured.append(_search(repository, "mdm-siti", intent=chair, label="sibling:chair"))

    finally:
        repository.close()

    # A planned outing reported as went and enjoyed, once its day has passed. Its own database:
    # catalogue sessions anchor to the furthest active person's day, so a second persona's
    # listings can fall outside the week being planned.
    repository = _offline_repository()
    repository.create_schema_for_tests()
    try:
        repository.reset(person_id="mdm-lim")
        opened = repository.search_activities(
            text=None, intent=None, person_id="mdm-lim", actor="golden"
        )
        planned = None
        for rank, item in enumerate(opened.results, start=1):
            answer = repository.respond_to_activity(
                item.candidate.activity_id,
                ActivityOfferResponse.INTERESTED,
                query_id=opened.query_id,
                rank_shown=rank,
                actor="golden",
                person_id="mdm-lim",
            )
            if answer.planned:
                planned = item.candidate.activity_id
                break
        assert planned is not None
        entry = _latest_plan_id(repository, "mdm-lim", planned)
        for _ in range(10):
            if repository.person_state(person_id="mdm-lim").current_day > entry.day:
                break
            repository.advance("recovery", person_id="mdm-lim")
        repository.record_planned_follow_through(
            entry.plan_id, PlannedFollowThrough.WENT, None, "golden", person_id="mdm-lim"
        )
        repository.record_planned_enjoyment(
            entry.plan_id,
            Enjoyment.ENJOYED,
            [LikedAspect.PEOPLE, LikedAspect.ACTIVITY],
            "golden",
            person_id="mdm-lim",
        )
        for text in (None, "something near me"):
            captured.append(
                _search(repository, "mdm-lim", text=text, label=f"enjoyed:{text or '<none>'}")
            )
    finally:
        repository.close()

    # A search with the bounded planner on, over a scripted transport (never the network).
    import silverloop.agent.planner as planner_module

    planner = _ScriptedPlanner()
    monkeypatch.setattr(planner_module, "_build_client", lambda settings, timeout: (planner, None))
    llm = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=Settings(
            app_env="test",
            database_url="sqlite+pysqlite:///:memory:",
            auth_enabled=False,
            llm_enabled=True,
            llm_api_key="test-key",
            llm_model="claude-opus-5",
            llm_max_iterations=4,
            external_context_enabled=False,
        ),
    )
    llm.create_schema_for_tests()
    try:
        llm.reset(person_id="mdm-lim")
        response = llm.search_activities(
            text=None, intent=ActivityIntent(), person_id="mdm-lim", actor="golden"
        )
        event = next(
            event
            for event in llm.list_events(person_id="mdm-lim")
            if event.event_type == "activity_search"
            and event.detail.get("query_id") == response.query_id
        )
        agent = event.detail["agent"]
        captured.append(
            {
                "label": "planner:scripted",
                "person_id": "mdm-lim",
                "ranking": event.detail["ranking"],
                "result_ids": event.detail["result_ids"],
                "response_result_ids": [item.candidate.activity_id for item in response.results],
                "selected_by": [item.selected_by for item in response.results],
                "ranks": [item.rank for item in response.results],
                "filtered_out": [
                    {"activity_id": item.activity_id, "rule": item.rule, "detail": item.detail}
                    for item in response.filtered_out
                ],
                "planner_mode": event.detail["planner_mode"],
                "planner_agreed_with_ranker": event.detail["planner_agreed_with_ranker"],
                "planner_contested": event.detail["planner_contested"],
                "snapshot_stale": event.detail["snapshot_stale"],
                "agent": {
                    key: agent[key]
                    for key in (
                        "mode",
                        "iterations",
                        "rejected_proposal_count",
                        "guardrail_violation_count",
                        "guardrail_rejections",
                        "fallback_reason",
                    )
                },
            }
        )
    finally:
        llm.close()
    return captured


def test_search_scenarios_match_the_reviewed_golden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered = [json.dumps(case, sort_keys=True) for case in collect_search_scenarios(monkeypatch)]
    if os.environ.get("SILVERLOOP_REGENERATE_SEARCH_GOLDEN") == "1":
        SCENARIO_GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCENARIO_GOLDEN_PATH.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    golden = SCENARIO_GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
    assert len(rendered) == len(golden)
    for line, (actual, expected) in enumerate(zip(rendered, golden, strict=True), start=1):
        assert actual == expected, f"scenario #{line} ({json.loads(expected)['label']}) changed"
