"""The evaluator-only Activity Ranker Inspector (`POST /v1/evaluator/ranker/inspect`).

What is pinned here, against the spec's acceptance criteria:

  * the trace describes the product's own ranking -- its top three are search's top three, its
    factors sum to its totals, its sort keys and filter outcomes are the ones the ranker used;
  * inspecting writes nothing, compared row by row across every table;
  * only a demo operator may inspect, an unknown person is a 404 and an unseeded one a 409;
  * no model free text (reasoning, prompts, read-tool arguments, guardrail text, exception text)
    and no words a person stated reach the response, with a scripted planner that tries;
  * previews run through the production learners, and the integrity classifier finds no
    unsupported positive contribution on the fixture catalogue.

No network: the planner transport is always a scripted fake (`client_factory`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop.activity_search import filter_candidates
from silverloop.config import Settings
from silverloop.db_models import Base, PersonRow, ScenarioRunRow
from silverloop.evaluator_presets import HISTORY_PRESETS
from silverloop.main import create_app
from silverloop.models import (
    ActivityIntent,
    ActivityRankingTrace,
    GoalKind,
    PreferenceDimension,
    PreferenceStance,
    RankerInspectRequest,
    SocialPreference,
    TimeWindow,
)
from silverloop.sql_repository import SqlAlchemyRepository

_SETTINGS = dict(
    app_env="test",
    database_url="sqlite+pysqlite:///:memory:",
    silverloop_runtime_profile="offline",
    auth_enabled=False,
    llm_enabled=False,
)

_REQUESTS: tuple[str | None, ...] = (
    None,
    "something near me",
    "something with other people in the morning",
    "indoor light exercise",
    "no walking, my knee",
    "within 800 m",
    "something outdoors this afternoon",
    "tai chi in Mandarin",
)

_PERSONAS = ("mdm-lim", "mr-ravi")


@pytest.fixture
def repo() -> Iterator[SqlAlchemyRepository]:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=Settings(**_SETTINGS))
    instance.create_schema_for_tests()
    for person_id in _PERSONAS:
        instance.reset(person_id=person_id)
    yield instance
    instance.close()


@pytest.fixture
def api(repo: SqlAlchemyRepository) -> Iterator[TestClient]:
    app = create_app(repo, settings=Settings(**_SETTINGS), migrate_on_start=False)
    with TestClient(app) as client:
        yield client


def _inspect(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/v1/evaluator/ranker/inspect", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _trace(payload: dict[str, Any], which: str = "baseline") -> ActivityRankingTrace:
    return ActivityRankingTrace.model_validate(payload[which])


def _snapshot(repository: SqlAlchemyRepository) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, as values -- contents, not counts."""
    with repository.sessions() as session:
        return {
            table.name: sorted(
                (tuple(repr(value) for value in row) for row in session.execute(select(table))),
            )
            for table in Base.metadata.sorted_tables
        }


# ── AC2 / AC3 / AC4: the trace is the product's own ranking ──────────────────────────────────


@pytest.mark.parametrize("person_id", _PERSONAS)
@pytest.mark.parametrize("text", _REQUESTS)
def test_trace_top_three_and_filter_outcomes_are_what_search_returns(
    api: TestClient, repo: SqlAlchemyRepository, person_id: str, text: str | None
) -> None:
    body: dict[str, Any] = {"person_id": person_id}
    if text:
        body["text"] = text
    trace = _trace(_inspect(api, **body))
    search = repo.search_activities(text=text, intent=None, person_id=person_id, actor="test")

    result_ids = [item.candidate.activity_id for item in search.results]
    assert [item.activity_id for item in trace.final_recommendations.top] == result_ids[:3]
    assert trace.llm_rerank.final_order == result_ids
    assert trace.final_recommendations.nothing_matched == search.nothing_matched
    assert trace.parsed_intent.intent.model_dump(exclude={"parsed_by"}) == search.intent.model_dump(
        exclude={"parsed_by"}
    )
    removed = [
        (item.activity_id, item.rule, item.detail)
        for item in trace.filtering.outcomes
        if item.status == "removed"
    ]
    assert removed == [(item.activity_id, item.rule, item.detail) for item in search.filtered_out]
    # The shown reasons are the card's own.
    by_id = {item.activity_id: item for item in trace.scoring.candidates}
    for item in search.results[:3]:
        assert by_id[item.candidate.activity_id].reasons_shown == item.reasons


@pytest.mark.parametrize("preset", [None, "lim-social-nearby"])
def test_factor_contributions_sum_to_totals_and_sort_keys_are_the_ones_sorted_on(
    api: TestClient, preset: str | None
) -> None:
    body: dict[str, Any] = {"person_id": "mdm-lim", "text": "something near me"}
    if preset:
        body["history_preset"] = preset
    payload = _inspect(api, **body)
    # A preset is part of the execution on screen: it is in the baseline, not a variant.
    assert payload["variant"] is None and payload["changes"] is None
    trace = _trace(payload)
    candidates = trace.scoring.candidates
    assert candidates, "the fixture catalogue must keep something for this request"
    for position, item in enumerate(candidates, start=1):
        factors = {factor.name: factor for factor in item.factors}
        assert round(sum(factor.contribution for factor in item.factors), 3) == item.total
        for factor in item.factors:
            assert factor.weight == trace.scoring.weights[factor.name]
            assert -1 <= factor.value <= 1
        assert item.tier == item.sort_key.tier
        if item.request_constrained == 0 or item.request_judged:
            assert item.tier == round(factors["intent"].value + factors["repetition"].value, 3)
        assert item.sort_key.tier == item.tier and item.sort_key.total == item.total
        assert item.sort_key.matched_axes == item.matched_axes
        assert item.sort_key.distance_m == item.distance_m
        assert item.positions.after_sort == position
        beliefs = sum(axis.contribution for axis in item.preference_axes)
        assert abs(beliefs - factors["preference"].value) <= 0.002 * max(
            1, len(item.preference_axes)
        )
    ordering = [
        (
            -item.sort_key.tier,
            -item.sort_key.total,
            -item.sort_key.matched_axes,
            item.sort_key.distance_m if item.sort_key.distance_m is not None else float("inf"),
            item.sort_key.title,
            item.sort_key.start_at.timestamp() if item.sort_key.start_at else float("inf"),
            item.sort_key.activity_id,
        )
        for item in candidates
    ]
    assert ordering == sorted(ordering)
    assert trace.sort.order_before_postprocess == [item.activity_id for item in candidates]


def test_filter_outcomes_match_filter_candidates_one_rule_per_removal(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    trace = _trace(_inspect(api, person_id="mr-ravi", text="something outdoors this afternoon"))
    catalogue = repo.list_activities()
    kept, removed = filter_candidates(catalogue, trace.parsed_intent.intent, today=trace.today)
    assert [item.activity_id for item in trace.filtering.outcomes] == [
        item.activity_id for item in catalogue
    ]
    assert [item.activity_id for item in trace.filtering.outcomes if item.status == "kept"] == [
        item.activity_id for item in kept
    ]
    assert [
        (item.activity_id, item.rule, item.detail)
        for item in trace.filtering.outcomes
        if item.status == "removed"
    ] == [(item.activity_id, item.rule, item.detail) for item in removed]
    assert sum(trace.filtering.by_rule.values()) == trace.filtering.removed_count == len(removed)
    assert list(trace.filtering.rules_in_order)[0] == "excluded_activity_type"


# ── AC5: never writes ─────────────────────────────────────────────────────────────────────────


def test_inspecting_writes_nothing_in_any_table(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    # Give the person real state first, so a write path would have something to touch.
    opened = repo.search_activities(text=None, intent=None, person_id="mdm-lim", actor="test")
    first = opened.results[0].candidate.activity_id
    repo.respond_to_activity(
        first, "not_for_me", reason="too_far", actor="test", person_id="mdm-lim"
    )
    repo.set_goal(GoalKind.MEET_PEOPLE, None, True, "test", person_id="mdm-lim")
    repo.state_preference(
        PreferenceDimension.ENVIRONMENT,
        "indoor",
        PreferenceStance.PREFER,
        actor="t",
        person_id="mdm-lim",
    )
    repo.advance("rain_explains_decline", person_id="mdm-lim")
    before = _snapshot(repo)

    _inspect(api, person_id="mdm-lim")
    _inspect(
        api,
        person_id="mdm-lim",
        text="something near me",
        history_preset="lim-social-nearby",
        run_planner=True,
        counterfactual={
            "request": {"time_window": "morning"},
            "world_model": {"travel_ceiling_m": 300, "temporary_avoid_activity_type": "walking"},
            "world": {"rain": False, "mark_full": [first]},
        },
        feedback={"activity_id": first, "response": "not_for_me", "reason": "too_far"},
    )
    _inspect(
        api,
        person_id="mdm-lim",
        feedback={
            "activity_id": first,
            "response": "enjoyment",
            "enjoyment": "enjoyed",
            "liked": ["people", "location"],
        },
    )
    _inspect(api, person_id="mdm-lim", feedback={"activity_id": first, "response": "interested"})
    _inspect(
        api, person_id="mdm-lim", history_preset="lim-social-nearby", compare_preset_to_live=True
    )
    assert api.get("/v1/evaluator/ranker/presets").status_code == 200

    assert _snapshot(repo) == before


# ── AC6: access ───────────────────────────────────────────────────────────────────────────────


_JWT_SECRET = "ranker-inspector-test-secret-0123456789"
_SUPABASE_URL = "https://project.supabase.co"


def _bearer(role: str) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": "user-001",
            "iss": _SUPABASE_URL + "/auth/v1",
            "aud": "authenticated",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "app_metadata": {"role": role},
        },
        _JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_only_a_demo_operator_may_inspect(repo: SqlAlchemyRepository) -> None:
    repo.upsert_person_link("user-001", "mdm-lim", "test")
    settings = Settings(
        **{**_SETTINGS, "auth_enabled": True},
        supabase_url=_SUPABASE_URL,
        supabase_jwt_secret=_JWT_SECRET,
    )
    client = TestClient(
        create_app(repo, settings=settings, migrate_on_start=False), raise_server_exceptions=False
    )
    body = {"person_id": "mdm-lim"}
    for role in ("senior", "coordinator"):
        assert (
            client.post(
                "/v1/evaluator/ranker/inspect", json=body, headers=_bearer(role)
            ).status_code
            == 403
        )
        assert client.get("/v1/evaluator/ranker/presets", headers=_bearer(role)).status_code == 403
    assert client.post("/v1/evaluator/ranker/inspect", json=body).status_code == 401
    operator = _bearer("demo_operator")
    assert (
        client.post("/v1/evaluator/ranker/inspect", json=body, headers=operator).status_code == 200
    )
    assert client.get("/v1/evaluator/ranker/presets", headers=operator).status_code == 200


def test_unknown_person_is_404_and_a_person_without_an_active_run_is_409(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    assert api.post("/v1/evaluator/ranker/inspect", json={"person_id": "nobody"}).status_code == 404
    with repo.sessions.begin() as session:
        for run in session.scalars(
            select(ScenarioRunRow).where(ScenarioRunRow.person_id == "mr-ravi")
        ):
            run.active = False
        assert session.get(PersonRow, "mr-ravi") is not None
    assert (
        api.post("/v1/evaluator/ranker/inspect", json={"person_id": "mr-ravi"}).status_code == 409
    )


@pytest.mark.parametrize(
    "body",
    [
        {"person_id": "mdm-lim", "surprise": True},
        {"person_id": "mdm-lim", "counterfactual": {"world": {"sunshine": True}}},
        {"person_id": "mdm-lim", "counterfactual": {"request": {"on_date": "2026-01-01"}}},
        {"person_id": "mdm-lim", "history_preset": "no-such-preset"},
        {"person_id": "mdm-lim", "history_preset": "ravi-knee-quiet"},
        {"person_id": "mdm-lim", "feedback": {"activity_id": "nope", "response": "interested"}},
        {
            "person_id": "mdm-lim",
            "feedback": {
                "activity_id": "activity-karaoke-1",
                "response": "interested",
                "reason": "too_far",
            },
        },
        {"person_id": "mdm-lim", "counterfactual": {"world": {"mark_full": ["nope"]}}},
    ],
)
def test_requests_outside_the_allow_list_are_refused(api: TestClient, body: dict[str, Any]) -> None:
    assert api.post("/v1/evaluator/ranker/inspect", json=body).status_code == 422


# ── AC7 / AC8: the planner stage, scripted, with no model text leaking ───────────────────────


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
class _Scripted:
    responses: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def messages(self) -> _Scripted:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


_SECRETS = (
    "REASONING_SECRET",
    "READ_ARGUMENT_SECRET",
    "INVENTED_KEY_SECRET",
    "UNPARSED_MODEL_SECRET",
    "EXCEPTION_TEXT_SECRET",
    "STATED_TEXT_SECRET",
)


def _llm_repo() -> SqlAlchemyRepository:
    instance = SqlAlchemyRepository(
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
    instance.create_schema_for_tests()
    instance.reset()
    return instance


def _assert_no_model_text(payload: str) -> None:
    for secret in _SECRETS:
        assert secret not in payload
    for forbidden in (
        "agent_reasoning",
        '"reasoning"',
        '"proposal"',
        "These keys are not permitted",
        "REJECTED by the deterministic safety gate",
        "deterministic filter and ranker have ALREADY",
        "Guardrail rejected",
        '"summary"',
        '"arguments"',
        "stated_text",
    ):
        assert forbidden not in payload


def test_a_rejected_proposal_then_an_approved_one_is_traced_without_any_model_text() -> None:
    repository = _llm_repo()
    try:
        repository.state_preference(
            PreferenceDimension.SOCIAL,
            "social",
            PreferenceStance.PREFER,
            stated_text="STATED_TEXT_SECRET",
            actor="test",
        )
        repository.set_goal(GoalKind.MORNING_ACTIVITY, None, True, "test")
        before = _snapshot(repository)
        plain = repository.inspect_ranker(RankerInspectRequest(person_id="mdm-lim"))
        window = plain.baseline.llm_rerank.deterministic_window
        assert plain.baseline.llm_rerank.status == "not_run_in_preview"
        assert len(window) >= 4

        reordered = [window[1], window[0], *window[2:]]
        planner = _Scripted(
            [
                _Response([_Block("t1", "get_activity_options", {"note": "READ_ARGUMENT_SECRET"})]),
                _Response(
                    [
                        _Block(
                            "t2",
                            "propose_activity_order",
                            {
                                "ordered_keys": ["INVENTED_KEY_SECRET", *window],
                                "reasoning": "REASONING_SECRET one",
                            },
                        )
                    ]
                ),
                _Response(
                    [
                        _Block(
                            "t3",
                            "propose_activity_order",
                            {"ordered_keys": reordered, "reasoning": "REASONING_SECRET two"},
                        )
                    ]
                ),
            ]
        )
        intent_client = _Scripted(
            [
                _Response(
                    [
                        _Block(
                            "i1",
                            "record_intent",
                            {
                                "time_window": "morning",
                                "unparsed_terms": ["UNPARSED_MODEL_SECRET", "please"],
                            },
                        )
                    ]
                )
            ]
        )
        response = repository.inspect_ranker(
            RankerInspectRequest(person_id="mdm-lim", text="something please", run_planner=True),
            planner_client_factory=lambda: (planner, None),
            intent_client_factory=lambda: (intent_client, None),
        )
        stage = response.baseline.llm_rerank
        assert response.baseline.parsed_intent.intent_mode == "agent"
        assert response.baseline.parsed_intent.parser.value == "llm"
        assert response.baseline.parsed_intent.unparsed_terms == ["please"]
        assert response.baseline.parsed_intent.unparsed_terms_withheld == 1
        assert response.baseline.parsed_intent.language_model_supplied_ungrounded is False
        assert stage.status == "agent" and stage.ran and stage.transport == "live"
        assert stage.provider == "anthropic"
        assert stage.iterations == 3
        assert stage.guardrail_rule_counts == {"key_not_permitted": 1}
        assert stage.rejected_proposal_count == 1
        assert [(call.tool_name, call.ok, call.unknown_key_count) for call in stage.tool_calls] == [
            ("get_activity_options", True, 0),
            ("propose_activity_order", False, 1),
            ("propose_activity_order", True, 0),
        ]
        assert stage.tool_calls[0].proposed_keys == []
        assert stage.tool_calls[1].proposed_keys == window
        # The intent planner read "morning", so the planner window is the morning search's.
        assert stage.final_order[:2] == [
            stage.deterministic_window[1],
            stage.deterministic_window[0],
        ]
        top = response.baseline.final_recommendations.top
        assert top[0].selected_by == "agent"
        assert {movement.activity_id: movement.final_rank for movement in stage.movements}[
            stage.deterministic_window[0]
        ] == 2
        _assert_no_model_text(response.model_dump_json())
        assert _snapshot(repository) == before
    finally:
        repository.close()


def test_an_exhausted_planner_and_a_provider_error_fall_back_to_the_deterministic_order() -> None:
    repository = _llm_repo()
    try:
        invalid = [
            _Response(
                [
                    _Block(
                        f"t{n}",
                        "propose_activity_order",
                        {"ordered_keys": ["INVENTED_KEY_SECRET"], "reasoning": "REASONING_SECRET"},
                    )
                ]
            )
            for n in range(4)
        ]
        exhausted = repository.inspect_ranker(
            RankerInspectRequest(person_id="mdm-lim", run_planner=True),
            planner_client_factory=lambda: (_Scripted(list(invalid)), None),
        )
        stage = exhausted.baseline.llm_rerank
        assert stage.status == "fallback_exhausted" and stage.iterations == 4
        assert stage.final_order == exhausted.baseline.post_processing.variety.order_after
        assert stage.guardrail_rule_counts["key_not_permitted"] == 4
        assert all(
            item.selected_by == "ranker" for item in exhausted.baseline.final_recommendations.top
        )
        _assert_no_model_text(exhausted.model_dump_json())

        errored = repository.inspect_ranker(
            RankerInspectRequest(person_id="mdm-lim", run_planner=True),
            planner_client_factory=lambda: (
                _Scripted([RuntimeError("EXCEPTION_TEXT_SECRET with a credential")]),
                None,
            ),
        )
        stage = errored.baseline.llm_rerank
        assert stage.status == "fallback_error"
        assert stage.fallback_error_class == "RuntimeError"
        assert stage.final_order == errored.baseline.post_processing.variety.order_after
        _assert_no_model_text(errored.model_dump_json())
    finally:
        repository.close()


def test_with_the_llm_off_the_stage_says_so_and_recorded_transport_is_labelled(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    trace = _trace(_inspect(api, person_id="mdm-lim", run_planner=True, text="near me"))
    assert trace.llm_rerank.status == "fallback_disabled"
    assert trace.llm_rerank.ran is False and trace.llm_rerank.planner_enabled is False
    assert trace.parsed_intent.intent_mode == "fallback_disabled"
    assert trace.llm_rerank.window_size == 10
    assert (trace.llm_rerank.max_promotion, trace.llm_rerank.min_shown_after_narrowing) == (3, 3)

    recorded = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=Settings(
            app_env="test",
            database_url="sqlite+pysqlite:///:memory:",
            auth_enabled=False,
            llm_enabled=True,
            llm_provider="recorded",
            llm_recording_path="/nonexistent/recording.json",
        ),
    )
    recorded.create_schema_for_tests()
    recorded.reset()
    try:
        response = recorded.inspect_ranker(
            RankerInspectRequest(
                person_id="mdm-lim",
                run_planner=True,
                counterfactual={"world": {"rain": True}},
            )
        )
        assert response.baseline.llm_rerank.transport == "recorded"
        assert response.baseline.llm_rerank.status == "fallback_disabled"  # no recording on disk
        assert response.variant is not None
        assert response.variant.llm_rerank.recording_may_miss is True
        assert response.baseline.llm_rerank.recording_may_miss is False
        # A preset baseline is not the live state either, so a recording may miss it too.
        with_preset = recorded.inspect_ranker(
            RankerInspectRequest(
                person_id="mdm-lim", run_planner=True, history_preset="lim-social-nearby"
            )
        )
        assert with_preset.variant is None
        assert with_preset.baseline.llm_rerank.recording_may_miss is True
    finally:
        recorded.close()


# ── AC9 / AC10 at the API: post-processing and unknown metadata ──────────────────────────────


def test_series_dedupe_is_recorded_on_the_fixture_catalogue(api: TestClient) -> None:
    trace = _trace(_inspect(api, person_id="mdm-lim", text="something near me"))
    dedupe = trace.post_processing.series_dedupe
    deferred = {item.activity_id for item in dedupe.deferred}
    flagged = {item.activity_id for item in trace.scoring.candidates if item.series_deferred}
    assert deferred == flagged
    for item in dedupe.deferred:
        assert item.to_position > 3
        holder = next(c for c in trace.scoring.candidates if c.activity_id == item.series_holder_id)
        mover = next(c for c in trace.scoring.candidates if c.activity_id == item.activity_id)
        assert (holder.title, holder.provider) == (mover.title, mover.provider)
    top = trace.final_recommendations.top
    assert any(item.selection_stage == "series_dedupe" for item in top) == dedupe.changed


def test_unknown_candidate_metadata_stays_unknown_in_axis_outcomes(api: TestClient) -> None:
    trace = _trace(
        _inspect(
            api,
            person_id="mdm-lim",
            intent={"time_window": "morning", "intensity": "light", "language": "Tamil"},
        )
    )
    candidates = {item.activity_id: item for item in trace.scoring.candidates}
    reading = candidates["activity-reading-corner"]  # no start time, no intensity
    outcomes = {axis.axis: axis.outcome for axis in reading.request_axes}
    assert outcomes["time_window"] == "unknown"
    assert outcomes["intensity"] == "unknown"
    assert outcomes["language"] == "match"
    assert outcomes["environment"] == "not_applicable"
    unknown_fields = {item.field: item.activity_ids for item in trace.catalogue_unknowns}
    assert "activity-reading-corner" in unknown_fields["start_at"]
    assert "activity-karaoke-1" in unknown_fields["intensity"]

    trace = _trace(_inspect(api, person_id="mdm-lim", intent={"language": "Tamil"}))
    candidates = {item.activity_id: item for item in trace.scoring.candidates}
    stretch = candidates["activity-garden-stretch-1"]  # no language listed: kept, and unknown
    assert {axis.axis: axis.outcome for axis in stretch.request_axes}["language"] == "unknown"
    removed = {item.activity_id: item.rule for item in trace.filtering.outcomes}
    assert removed["activity-karaoke-1"] == "inaccessible"  # English/Mandarin/Hokkien only
    assert removed["activity-garden-stretch-1"] is None


# ── AC11 and the learning preview ─────────────────────────────────────────────────────────────


def test_a_too_far_preview_holds_the_series_back_and_adds_a_distance_ceiling(
    api: TestClient,
) -> None:
    payload = _inspect(api, person_id="mdm-lim")
    baseline = _trace(payload)
    declined = baseline.final_recommendations.top[0].activity_id
    declined_candidate = next(c for c in baseline.scoring.candidates if c.activity_id == declined)

    payload = _inspect(
        api,
        person_id="mdm-lim",
        feedback={"activity_id": declined, "response": "not_for_me", "reason": "too_far"},
    )
    variant = _trace(payload, "variant")
    before = {c.activity_id: c for c in baseline.scoring.candidates}
    after = {c.activity_id: c for c in variant.scoring.candidates}
    series = [c for c in after.values() if c.programme_key == declined_candidate.programme_key]
    for session in series:
        repetition = {f.name: f.contribution for f in session.factors}["repetition"]
        assert repetition == -2.0
        assert {f.name: f.contribution for f in before[session.activity_id].factors}[
            "repetition"
        ] == 0.0
    assert after[declined].positions.final > before[declined].positions.final
    assert declined not in [item.activity_id for item in variant.final_recommendations.top]

    distance = [
        fact
        for fact in variant.person_context.facts
        if fact.dimension is PreferenceDimension.DISTANCE and fact.direction == "lower"
    ]
    assert len(distance) == 1 and distance[0].pivot == float(declined_candidate.distance_m)
    assert distance[0].changed_by_preview and distance[0].used_in_scoring
    assert not [
        f for f in baseline.person_context.facts if f.dimension is PreferenceDimension.DISTANCE
    ]
    changes = payload["changes"]
    assert {"kind": "fact_added", "fact_key": distance[0].fact_key} in [
        {"kind": change["kind"], "fact_key": change["fact_key"]} for change in changes
    ]
    assert any(
        change["kind"] == "factor_delta"
        and change["activity_id"] == declined
        and change["factor"] == "repetition"
        and change["delta"] == -2.0
        for change in changes
    )
    preview = variant.applied.learning_preview
    assert preview is not None and preview.teaches_dimension and preview.consent_active
    assert preview.facts_before == baseline.person_context.facts
    assert preview.engagement_before is None
    assert preview.engagement_after is not None and preview.engagement_after.in_cooldown


def test_interested_teaches_no_dimension_and_enjoyment_counts_a_visit(api: TestClient) -> None:
    target = "activity-craft-circle-1"
    interested = _trace(
        _inspect(
            api, person_id="mdm-lim", feedback={"activity_id": target, "response": "interested"}
        ),
        "variant",
    )
    preview = interested.applied.learning_preview
    assert preview is not None and not preview.teaches_dimension
    assert preview.engagement_after is not None and preview.engagement_after.series.interested == 1
    assert not [fact for fact in interested.person_context.facts if fact.changed_by_preview]

    enjoyed = _trace(
        _inspect(
            api,
            person_id="mdm-lim",
            feedback={
                "activity_id": target,
                "response": "enjoyment",
                "enjoyment": "enjoyed",
                "liked": ["people"],
            },
        ),
        "variant",
    )
    preview = enjoyed.applied.learning_preview
    assert preview is not None and preview.teaches_dimension
    assert preview.engagement_after is not None
    assert (preview.engagement_after.series.went, preview.engagement_after.series.enjoyed) == (1, 1)
    social = [f for f in enjoyed.person_context.facts if f.dimension is PreferenceDimension.SOCIAL]
    assert social and social[0].value == "social" and social[0].changed_by_preview

    okay = _trace(
        _inspect(
            api,
            person_id="mdm-lim",
            feedback={"activity_id": target, "response": "enjoyment", "enjoyment": "okay"},
        ),
        "variant",
    )
    assert okay.applied.learning_preview is not None
    after = okay.applied.learning_preview.engagement_after
    assert after is not None and (
        after.series.went,
        after.series.enjoyed,
        after.series.not_enjoyed,
    ) == (1, 0, 0)


def test_a_same_day_repeat_decline_teaches_nothing_new(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    target = "activity-evening-social-1"
    repo.respond_to_activity(target, "not_for_me", reason="too_far", actor="t", person_id="mdm-lim")
    trace = _trace(
        _inspect(
            api,
            person_id="mdm-lim",
            feedback={"activity_id": target, "response": "not_for_me", "reason": "too_far"},
        ),
        "variant",
    )
    preview = trace.applied.learning_preview
    assert preview is not None and preview.duplicate_same_day and not preview.teaches_dimension


# ── Counterfactuals ───────────────────────────────────────────────────────────────────────────


def test_world_and_request_counterfactuals_change_what_they_say(api: TestClient) -> None:
    payload = _inspect(
        api,
        person_id="mdm-lim",
        counterfactual={
            "request": {
                "social_preference": "solo",
                "max_distance_m": 1000,
                "distance_is_explicit": True,
            },
            "world": {"rain": True, "mark_full": ["activity-garden-stretch-1"]},
        },
    )
    baseline, variant = _trace(payload), _trace(payload, "variant")
    assert baseline.parsed_intent.intent.social_preference is SocialPreference.EITHER
    assert variant.parsed_intent.intent.social_preference is SocialPreference.SOLO
    assert (
        variant.retrieval.rain_forecast is True
        and variant.retrieval.rain_source == "counterfactual"
    )
    outcomes = {item.activity_id: item for item in variant.filtering.outcomes}
    assert outcomes["activity-garden-stretch-1"].rule == "full"
    assert outcomes["activity-brisk-walk-1"].rule == "too_far"
    assert variant.filtering.by_rule.get("wrong_company", 0) > 0
    assert all(
        change["kind"] != "filter_status_changed" or change["activity_id"]
        for change in payload["changes"]
    )


def test_a_travel_ceiling_applies_below_the_tolerance_and_reports_no_effect_above_it(
    api: TestClient,
) -> None:
    applied = _trace(
        _inspect(
            api, person_id="mdm-lim", counterfactual={"world_model": {"travel_ceiling_m": 300}}
        ),
        "variant",
    )
    assert [(e.control, e.effect) for e in applied.applied.world_model_effects] == [
        ("travel_ceiling_m", "applied")
    ]
    assert applied.person_context.travel_tolerance_m == 300
    assert applied.person_context.travel_tolerance_basis == "learned_ceiling"

    no_effect = _trace(
        _inspect(
            api, person_id="mdm-lim", counterfactual={"world_model": {"travel_ceiling_m": 2000}}
        ),
        "variant",
    )
    effect = no_effect.applied.world_model_effects[0]
    assert (effect.effect, effect.no_effect_reason) == ("no_effect", "not_below_tolerance")
    assert no_effect.person_context.travel_tolerance_m == 500


def test_a_temporary_avoid_wins_its_axis_until_its_day(api: TestClient) -> None:
    variant = _trace(
        _inspect(
            api,
            person_id="mdm-lim",
            counterfactual={"world_model": {"temporary_avoid_activity_type": "stretch"}},
        ),
        "variant",
    )
    facts = [
        f
        for f in variant.person_context.facts
        if f.fact_key == "activity_type:stretch:senior_statement"
    ]
    assert len(facts) == 1
    fact = facts[0]
    assert fact.provenance == "temporary" and fact.tier == "temporary_stated"
    assert fact.used_in_scoring and fact.expires_on_day == variant.today + timedelta(days=6)
    stretch = [
        c
        for c in variant.scoring.candidates
        if c.activity_type is not None and c.activity_type.value == "stretch"
    ]
    assert stretch and all({f.name: f.value for f in c.factors}["preference"] < 0 for c in stretch)


# ── Presets, person context and integrity ─────────────────────────────────────────────────────


def test_presets_endpoint_lists_the_scripted_histories_and_controls(api: TestClient) -> None:
    body = api.get("/v1/evaluator/ranker/presets").json()
    ids = {preset["preset_id"] for preset in body["presets"]}
    assert {"lim-social-nearby", "ravi-knee-quiet"} <= ids
    assert "walking" in body["controls"]["activity_types"]
    assert "other" not in body["controls"]["activity_types"]
    assert {person["person_id"] for person in body["people"]} == set(_PERSONAS)


def test_the_two_personas_rank_the_same_request_differently_with_their_presets(
    api: TestClient,
) -> None:
    lim = _trace(
        _inspect(
            api, person_id="mdm-lim", text="something near me", history_preset="lim-social-nearby"
        )
    )
    ravi = _trace(
        _inspect(
            api, person_id="mr-ravi", text="something near me", history_preset="ravi-knee-quiet"
        )
    )
    lim_top = [item.activity_id for item in lim.final_recommendations.top]
    ravi_top = [item.activity_id for item in ravi.final_recommendations.top]
    assert lim_top != ravi_top
    # And live state alone ranks them identically (D8), which is why the presets exist.
    lim_live = _trace(_inspect(api, person_id="mdm-lim", text="something near me"))
    ravi_live = _trace(_inspect(api, person_id="mr-ravi", text="something near me"))
    assert [i.activity_id for i in lim_live.final_recommendations.top] == [
        i.activity_id for i in ravi_live.final_recommendations.top
    ]
    for trace in (lim, ravi):
        scripted = trace.applied.history_preset
        assert scripted is not None and scripted.events
        assert all(event.origin_id.startswith("scripted:") for event in scripted.events)
        assert trace.person_context.facts
        assert all(fact.provenance == "scripted_history" for fact in trace.person_context.facts)
        assert trace.preview is True and trace.saved is False
        assert trace.variant == "baseline"
    assert lim_live.preview is False and lim_live.applied.history_preset is None


def test_person_context_reports_why_a_fact_was_not_used(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    repo.set_goal(GoalKind.MEET_PEOPLE, None, True, "t", person_id="mdm-lim")
    repo.state_preference(
        PreferenceDimension.SOCIAL,
        "social",
        PreferenceStance.PREFER,
        actor="t",
        person_id="mdm-lim",
    )
    repo.respond_to_activity(
        "activity-evening-social-1",
        "not_for_me",
        reason="bad_timing",
        actor="t",
        person_id="mdm-lim",
    )
    trace = _trace(_inspect(api, person_id="mdm-lim", intent={"social_preference": "social"}))
    by_key = {fact.fact_key: fact for fact in trace.person_context.facts}
    stated = by_key["social:social:senior_statement"]
    assert stated.provenance == "person_said" and stated.not_used_reason == "constrained_by_request"
    goal = [f for f in trace.person_context.facts if f.provenance == "goal"]
    assert goal and goal[0].not_used_reason == "not_winning_tier"
    held = [f for f in trace.person_context.facts if f.status == "recorded_not_applied"]
    assert held and held[0].dimension is PreferenceDimension.TIMING
    assert held[0].not_applied_reason == "held_back_item_level"
    assert trace.person_context.consent_active is True
    assert "stated_text" not in json.dumps(trace.model_dump(mode="json"))


def test_unknown_axes_are_measured_by_re_ranking(api: TestClient) -> None:
    trace = _trace(_inspect(api, person_id="mdm-lim", intent={"time_window": "morning"}))
    axes = {axis.dimension: axis for axis in trace.person_context.unknown_axes}
    assert PreferenceDimension.TIMING not in axes  # constrained by the request
    assert PreferenceDimension.SOCIAL in axes
    for axis in axes.values():
        assert axis.tested_values
        assert set(axis.changing_values) <= set(axis.tested_values)
        assert axis.changes_top_three == bool(axis.changing_values)
    assert any(axis.changes_top_three for axis in axes.values())


def _integrity_payloads(client: TestClient) -> list[ActivityRankingTrace]:
    traces: list[ActivityRankingTrace] = []
    chips = [
        {"social_preference": "social"},
        {"environment": "indoor", "time_window": "morning"},
        {"activity_types": ["tai_chi", "walking"], "intensity": "moderate"},
        {"language": "Tamil"},
    ]
    for person_id in _PERSONAS:
        presets = [None, *[p.preset_id for p in HISTORY_PRESETS if p.person_id == person_id]]
        for preset in presets:
            for rain in (False, True):
                bodies: list[dict[str, Any]] = [{"text": text} for text in _REQUESTS if text]
                bodies += [{"intent": chip} for chip in chips] + [{}]
                for extra in bodies:
                    body: dict[str, Any] = {"person_id": person_id, **extra}
                    if preset:
                        body["history_preset"] = preset
                    body["counterfactual"] = {"world": {"rain": rain}}
                    payload = _inspect(client, **body)
                    traces.append(_trace(payload))
                    traces.append(_trace(payload, "variant"))
    return traces


def test_no_shown_positive_contribution_is_unsupported_on_the_fixture_catalogue(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    # Real engagement too, so the HISTORY basis is exercised.
    repo.respond_to_activity(
        "activity-craft-circle-1", "interested", actor="t", person_id="mdm-lim"
    )
    traces = _integrity_payloads(api)
    assert len(traces) > 100
    findings = [finding for trace in traces for finding in trace.integrity.findings]
    _assert_cards_explain_exactly_what_they_can(traces)
    unsupported = [f for f in findings if f.classification == "unsupported"]
    assert unsupported == []
    assert any(f.classification == "grounded" for f in findings)
    for trace in traces:
        integrity = trace.integrity
        assert integrity.unsupported == 0
        shown = {item.activity_id for item in trace.final_recommendations.top}
        assert {f.activity_id for f in integrity.findings} <= shown
        for candidate in trace.scoring.candidates:
            assert (candidate.integrity is not None) == (candidate.activity_id in shown)


def test_web_grouping_is_reported_for_the_first_three_cards(api: TestClient) -> None:
    trace = _trace(
        _inspect(
            api,
            person_id="mdm-lim",
            intent=ActivityIntent(time_window=TimeWindow.ANY).model_dump(mode="json"),
        )
    )
    cards = trace.final_recommendations.web_cards
    assert len(cards) == 3
    assert len({(card.title, card.location_name) for card in cards}) == 3
    final = trace.llm_rerank.final_order
    for card in cards:
        assert card.headline_activity_id in card.member_ids
        assert set(card.member_ids) <= set(final)


# ── Review follow-ups ─────────────────────────────────────────────────────────────────────────


def test_a_model_supplied_language_is_kept_where_it_filtered_and_flagged_when_ungrounded() -> None:
    """The LLM's `language` is the one model-written value the trace keeps, because the filter,
    the reason lines and `understood` used it verbatim. Anywhere else it must not appear."""
    repository = _llm_repo()
    secret = "LANGUAGE_SECRET_XYZ"

    def intent_client(language: str) -> _Scripted:
        return _Scripted(
            [
                _Response(
                    [
                        _Block(
                            "i1",
                            "record_intent",
                            {"language": language, "unparsed_terms": ["UNPARSED_MODEL_SECRET"]},
                        )
                    ]
                )
            ]
        )

    def silent_planner() -> _Scripted:
        return _Scripted([_Response([], stop_reason="end_turn")])

    try:
        ungrounded = repository.inspect_ranker(
            RankerInspectRequest(
                person_id="mdm-lim", text="something in the morning", run_planner=True
            ),
            planner_client_factory=lambda: (silent_planner(), None),
            intent_client_factory=lambda: (intent_client(secret), None),
        ).baseline
        parsed = ungrounded.parsed_intent
        assert parsed.intent_mode == "agent" and parsed.intent.language == secret
        assert parsed.language_model_supplied_ungrounded is True
        assert parsed.unparsed_terms == [] and parsed.unparsed_terms_withheld == 1
        removed = [o for o in ungrounded.filtering.outcomes if o.rule == "inaccessible"]
        assert removed and all(secret in (o.detail or "") for o in removed)

        payload = ungrounded.model_dump(mode="json")
        payload["parsed_intent"]["intent"]["language"] = None
        payload["parsed_intent"]["understood"] = []
        for axis in payload["parsed_intent"]["axes"]:
            if axis["axis"] == "language":
                axis["values"] = []
        for outcome in payload["filtering"]["outcomes"]:
            outcome["detail"] = None
        for candidate in payload["scoring"]["candidates"]:
            candidate["reasons_shown"] = []
            candidate["more_reasons"] = []
            candidate["reasons_before_composition"] = []
        assert secret not in json.dumps(payload)
        _assert_no_model_text(json.dumps(payload))

        grounded = repository.inspect_ranker(
            RankerInspectRequest(person_id="mdm-lim", text="tai chi in Tamil", run_planner=True),
            planner_client_factory=lambda: (silent_planner(), None),
            intent_client_factory=lambda: (intent_client("Tamil"), None),
        ).baseline
        assert grounded.parsed_intent.intent.language == "Tamil"
        assert grounded.parsed_intent.language_model_supplied_ungrounded is False
    finally:
        repository.close()


def test_a_preset_folded_into_a_live_belief_keeps_its_live_provenance(
    api: TestClient,
) -> None:
    live = api.post(
        "/v1/activities/activity-evening-social-1/response",
        json={"response": "not_for_me", "reason": "too_far"},
    )
    assert live.status_code == 200, live.text
    payload = _inspect(
        api, person_id="mdm-lim", history_preset="lim-social-nearby", compare_preset_to_live=True
    )
    baseline, variant = _trace(payload), _trace(payload, "variant")
    assert baseline.applied.history_preset is None and variant.applied.history_preset is not None

    key = "distance:lower:decline_reason"
    before = next(f for f in baseline.person_context.facts if f.fact_key == key)
    assert (before.provenance, before.scripted_contribution) == ("learned", False)
    assert before.positive_evidence == 1.0

    merged = next(f for f in variant.person_context.facts if f.fact_key == key)
    assert merged.provenance == "learned" and merged.scripted_contribution is True
    assert merged.positive_evidence == 3.0  # one live "too far" and two scripted ones
    assert merged.pivot == 850.0

    scripted_only = next(
        f for f in variant.person_context.facts if f.fact_key == "social:social:inferred"
    )
    assert scripted_only.provenance == "scripted_history" and scripted_only.scripted_contribution


def test_an_unknown_person_is_404_even_with_a_preset_and_other_failures_are_500(
    repo: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    from silverloop import ranker_inspector
    from silverloop.models import ActivityIntent as Intent

    client = TestClient(
        create_app(repo, settings=Settings(**_SETTINGS), migrate_on_start=False),
        raise_server_exceptions=False,
    )
    url = "/v1/evaluator/ranker/inspect"
    assert (
        client.post(
            url, json={"person_id": "nobody", "history_preset": "lim-social-nearby"}
        ).status_code
        == 404
    )
    assert (
        client.post(url, json={"person_id": "nobody", "history_preset": "no-such"}).status_code
        == 404
    )
    assert (
        client.post(
            url,
            json={
                "person_id": "mdm-lim",
                "counterfactual": {"world_model": {"temporary_avoid_activity_type": "other"}},
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            url,
            json={
                "person_id": "mdm-lim",
                "counterfactual": {
                    "world_model": {
                        "temporary_avoid_activity_type": "walking",
                        "temporary_avoid_until": "2000-01-01",
                    }
                },
            },
        ).status_code
        == 422
    )

    def validation_error(*args: Any, **kwargs: Any) -> Any:
        Intent.model_validate({"max_distance_m": -1})

    def key_error(*args: Any, **kwargs: Any) -> Any:
        raise KeyError("a defect, not a person")

    for failure in (validation_error, key_error):
        monkeypatch.setattr(ranker_inspector, "inspect", failure)
        assert client.post(url, json={"person_id": "mdm-lim"}).status_code == 500


def test_the_travel_ceiling_and_cooldown_come_from_the_executed_scoring(api: TestClient) -> None:
    trace = _trace(
        _inspect(
            api,
            person_id="mdm-lim",
            intent={"social_preference": "social"},
            history_preset="lim-social-nearby",
        )
    )
    facts = {fact.fact_key: fact for fact in trace.person_context.facts}
    assert facts["distance:lower:decline_reason"].used_in_scoring
    assert facts["social:social:inferred"].not_used_reason == "constrained_by_request"
    walked = {
        axis.fact_key
        for candidate in trace.scoring.candidates
        for axis in candidate.preference_axes
    }
    used = {key for key, fact in facts.items() if fact.used_in_scoring}
    assert walked == used - {"distance:lower:decline_reason"}
    for candidate in trace.scoring.candidates:
        if candidate.engagement is not None:
            repetition = {f.name: f.value for f in candidate.factors}["repetition"]
            assert candidate.engagement.in_cooldown == (repetition == -1.0)


@pytest.mark.parametrize("prior", ["none", "learned_decline", "standing_prefer"])
def test_a_temporary_avoid_counterfactual_matches_what_the_put_endpoint_stores(
    api: TestClient, repo: SqlAlchemyRepository, prior: str
) -> None:
    from silverloop.local_time import at_local
    from silverloop.preferences import resolve
    from silverloop.ranker_inspector import confirm_statement_in_memory, row_key

    person = "mdm-lim"
    if prior == "learned_decline":
        response = api.post(
            "/v1/activities/activity-garden-stretch-1/response",
            json={"response": "not_for_me", "reason": "not_for_me"},
        )
        assert response.status_code == 200
    elif prior == "standing_prefer":
        response = api.put(
            f"/v1/people/{person}/activity-preferences/activity_type/stretch",
            json={"stance": "prefer"},
        )
        assert response.status_code == 200
    with repo.sessions() as session:
        run_id = repo._active_run(session, person).run_id
    today = repo.person_state(person_id=person).current_day
    until = today + timedelta(days=3)
    before = repo.activity_preferences(person_id=person)
    goals = repo.list_goals(person_id=person)
    preview = confirm_statement_in_memory(
        list(before.dimensions),
        PreferenceDimension.ACTIVITY_TYPE,
        "stretch",
        strength=-1.0,
        expires_at=at_local(until, 23, 59),
        now=at_local(today, 12, 0),
    )

    stored = api.put(
        f"/v1/people/{person}/activity-preferences/activity_type/stretch",
        json={"stance": "avoid", "until": until.isoformat()},
    )
    assert stored.status_code == 200, stored.text
    after = repo.activity_preferences(person_id=person)

    def statement(rows: list[Any]) -> Any:
        return next(
            row
            for row in rows
            if row.dimension is PreferenceDimension.ACTIVITY_TYPE
            and row.value == "stretch"
            and row.source == "senior_statement"
            and row.superseded_by is None
        )

    fields = (
        "strength",
        "source",
        "confirmed",
        "observations",
        "expires_at",
        "positive_evidence",
        "negative_evidence",
        "superseded_by",
        "stated_text",
        "pivot",
        "direction",
        "scope",
    )
    real, mirrored = statement(after.dimensions), statement(preview)
    assert {f: getattr(mirrored, f) for f in fields} == {f: getattr(real, f) for f in fields}
    assert (mirrored.origin_id is None) == (real.origin_id is None)
    assert (mirrored.origin_id is None) == (prior != "learned_decline")
    assert sorted(row_key(r) for r in preview if r.superseded_by is None) == sorted(
        row_key(r) for r in after.dimensions
    )

    def resolved(rows: list[Any]) -> list[dict[str, Any]]:
        return sorted(
            (r.model_dump(mode="json") for r in resolve(rows, today, run_id, goals=goals)),
            key=lambda r: (r["dimension"], r["value"] or "", r["source"]),
        )

    assert resolved(preview) == resolved(list(after.dimensions))
    # And once the time box lapses, the tier the row falls to (STATED, or RATIFIED when it consumed
    # a learned row) matches too -- which is what the `origin_id` rule decides.
    from silverloop.preferences import observation_for

    lapsed = until + timedelta(days=1)
    real_tier = observation_for(statement(after.dimensions), today=lapsed).source_tier
    assert observation_for(statement(preview), today=lapsed).source_tier == real_tier
    assert real_tier.name == ("RATIFIED" if prior == "learned_decline" else "STATED")


@pytest.mark.parametrize("llm_enabled", [False, True])
def test_a_request_nothing_survives_is_no_candidates_as_search_records_it(
    llm_enabled: bool,
) -> None:
    repository = (
        _llm_repo()
        if llm_enabled
        else SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=Settings(**_SETTINGS))
    )
    if not llm_enabled:
        repository.create_schema_for_tests()
        repository.reset()
    try:
        intent = {"on_date": "2030-01-01", "social_preference": "social"}
        for run_planner in (False, True):
            trace = repository.inspect_ranker(
                RankerInspectRequest(person_id="mdm-lim", intent=intent, run_planner=run_planner),
                planner_client_factory=lambda: pytest.fail("no candidates: no planner call"),
            ).baseline
            assert trace.final_recommendations.nothing_matched
            assert trace.llm_rerank.status == "no_candidates" and not trace.llm_rerank.ran
        search = repository.search_activities(
            text=None, intent=ActivityIntent.model_validate(intent), person_id="mdm-lim", actor="t"
        )
        event = next(
            e
            for e in repository.list_events()
            if e.event_type == "activity_search" and e.detail["query_id"] == search.query_id
        )
        assert search.nothing_matched and event.detail["planner_mode"] == "no_candidates"
    finally:
        repository.close()


# ── Baseline includes the preset; the variant is the preview alone ───────────────────────────


def test_with_a_preset_the_changes_are_the_previews_effect_alone(api: TestClient) -> None:
    declined = "activity-craft-circle-1"
    feedback = {"activity_id": declined, "response": "not_for_me", "reason": "too_far"}
    payload = _inspect(
        api, person_id="mdm-lim", history_preset="lim-social-nearby", feedback=feedback
    )
    baseline, variant = _trace(payload), _trace(payload, "variant")
    on_screen = _trace(_inspect(api, person_id="mdm-lim", history_preset="lim-social-nearby"))

    # The baseline is exactly the preset execution on screen.
    assert baseline.variant == "baseline" and baseline.preview
    assert baseline.applied.history_preset is not None
    assert baseline.applied.counterfactual is None and baseline.applied.learning_preview is None
    assert baseline.llm_rerank.final_order == on_screen.llm_rerank.final_order
    assert baseline.person_context.facts == on_screen.person_context.facts
    # The variant keeps the preset and adds the preview.
    assert variant.applied.history_preset == baseline.applied.history_preset
    preview = variant.applied.learning_preview
    assert preview is not None and preview.facts_before == baseline.person_context.facts

    # Every change is the feedback's: the preset's own facts never appear as added.
    changes = payload["changes"]
    scripted_only = {
        f.fact_key for f in baseline.person_context.facts if f.provenance == "scripted_history"
    }
    assert scripted_only
    touched = {c["fact_key"] for c in changes if c["kind"].startswith("fact_")}
    assert not touched & (scripted_only - {"distance:lower:decline_reason"})
    ceiling = [c for c in changes if c["fact_key"] == "distance:lower:decline_reason"]
    # The preset already held a ceiling (its tightest scripted "too far", 2.8 km); the preview's
    # 850 m "too far" folds into that same belief and tightens it.
    assert [c["kind"] for c in ceiling] == ["fact_changed"]
    assert (ceiling[0]["baseline_pivot"], ceiling[0]["variant_pivot"]) == (2800.0, 850.0)
    assert {"pivot", "evidence"} <= set(ceiling[0]["changed_fields"])
    assert "value" not in ceiling[0]["changed_fields"]
    from silverloop.ranker_inspector import FACT_CHANGE_FIELDS

    for change in changes:
        if change["kind"] == "fact_changed":
            assert change["changed_fields"]
            assert set(change["changed_fields"]) <= set(FACT_CHANGE_FIELDS)
        else:
            assert change["changed_fields"] == []
    # The decline holds back the whole programme; the session in the top three carries the delta
    # (with equal scores the sooner session is the one ranked first).
    assert any(
        c["kind"] == "factor_delta"
        and c["activity_id"].startswith("activity-craft-circle-")
        and c["factor"] == "repetition"
        for c in changes
    )

    # And against live state the same preview would also report the preset's facts as new.
    against_live = _inspect(
        api, person_id="mdm-lim", history_preset="lim-social-nearby", compare_preset_to_live=True
    )["changes"]
    assert {c["fact_key"] for c in against_live if c["kind"] == "fact_added"} >= scripted_only


def test_compare_preset_to_live_needs_a_preset_and_no_preview(api: TestClient) -> None:
    url = "/v1/evaluator/ranker/inspect"
    feedback = {"activity_id": "activity-craft-circle-1", "response": "interested"}
    for body in (
        {"person_id": "mdm-lim", "compare_preset_to_live": True},
        {
            "person_id": "mdm-lim",
            "history_preset": "lim-social-nearby",
            "compare_preset_to_live": True,
            "feedback": feedback,
        },
        {
            "person_id": "mdm-lim",
            "history_preset": "lim-social-nearby",
            "compare_preset_to_live": True,
            "counterfactual": {"world": {"rain": True}},
        },
    ):
        response = api.post(url, json=body)
        assert response.status_code == 422, body
        assert "compare_preset_to_live" in response.json()["detail"]
    # Unknown person is still checked first.
    assert (
        api.post(url, json={"person_id": "nobody", "compare_preset_to_live": True}).status_code
        == 404
    )


def test_a_counterfactual_alone_diffs_against_live_state(api: TestClient) -> None:
    payload = _inspect(api, person_id="mdm-lim", counterfactual={"world": {"rain": True}})
    baseline, variant = _trace(payload), _trace(payload, "variant")
    assert baseline.preview is False and baseline.applied.history_preset is None
    assert variant.preview is True and variant.applied.history_preset is None
    assert baseline.retrieval.rain_source == "simulation_context"


def test_scoring_carries_the_rankers_descriptions_engagement_weights_and_top_n(
    api: TestClient,
) -> None:
    from silverloop.activity_search import (
        ENGAGEMENT_WEIGHTS,
        RANKING_FACTOR_DESCRIPTIONS,
        RANKING_WEIGHTS,
    )

    scoring = _trace(_inspect(api, person_id="mdm-lim")).scoring
    assert scoring.factor_descriptions == RANKING_FACTOR_DESCRIPTIONS
    assert set(scoring.factor_descriptions) == set(scoring.weights) == set(RANKING_WEIGHTS)
    assert scoring.engagement_weights == ENGAGEMENT_WEIGHTS
    assert scoring.top_n == 3


def test_transport_is_off_when_the_planner_is_disabled(api: TestClient) -> None:
    trace = _trace(_inspect(api, person_id="mdm-lim", history_preset="lim-social-nearby"))
    assert trace.llm_rerank.transport == "off"
    assert trace.llm_rerank.provider == "anthropic"
    assert (
        trace.llm_rerank.planner_enabled is False and trace.llm_rerank.recording_may_miss is False
    )


def test_person_context_says_where_travel_starts_to_cost(api: TestClient) -> None:
    def friction_is_charged_from(trace: ActivityRankingTrace, starts_m: int) -> None:
        for candidate in trace.scoring.candidates:
            value = {f.name: f.value for f in candidate.factors}["friction"]
            if candidate.distance_m is None:
                continue
            expected = (
                0.0
                if candidate.distance_m <= starts_m
                else round(-min(1.0, (candidate.distance_m - starts_m) / 4500), 3)
            )
            assert value == expected, candidate.activity_id

    live = _trace(_inspect(api, person_id="mdm-lim", text="something near me"))
    context = live.person_context
    # "near me" implies 1 km, which does not narrow the 500 m default.
    assert (context.travel_cost_starts_m, context.travel_cost_start_basis) == (500, "default")
    assert context.asked_radius_m == 1000
    friction_is_charged_from(live, 500)

    explicit = _trace(_inspect(api, person_id="mdm-lim", text="within 800 m")).person_context
    assert (explicit.travel_cost_starts_m, explicit.asked_radius_m) == (500, None)

    # A far outing enjoyed for its location raises the tolerance; "near me" then narrows it.
    payload = _inspect(
        api,
        person_id="mdm-lim",
        text="something near me",
        feedback={
            "activity_id": "activity-brisk-walk-1",
            "response": "enjoyment",
            "enjoyment": "enjoyed",
            "liked": ["location"],
        },
    )
    variant = _trace(payload, "variant")
    assert variant.person_context.travel_tolerance_m == 4600
    assert variant.person_context.travel_tolerance_basis == "learned_floor"
    assert (
        variant.person_context.travel_cost_starts_m,
        variant.person_context.travel_cost_start_basis,
    ) == (1000, "asked_radius")
    friction_is_charged_from(variant, 1000)


def test_axis_outcomes_on_the_trace_carry_their_unknown_reason(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    repo.state_preference(
        PreferenceDimension.ACTIVITY_TYPE,
        "walking",
        PreferenceStance.PREFER,
        actor="t",
        person_id="mdm-lim",
    )
    trace = _trace(_inspect(api, person_id="mdm-lim", intent={"time_window": "morning"}))
    by_id = {c.activity_id: c for c in trace.scoring.candidates}
    walking = [a for a in by_id["activity-sheltered-walk-1"].preference_axes]
    assert [(a.outcome, a.unknown_reason) for a in walking] == [("match", None)]
    crafts = by_id["activity-reading-corner"]
    assert [(a.outcome, a.unknown_reason) for a in crafts.preference_axes] == [
        ("unknown", "mismatch_not_counted")
    ]
    time_axis = {a.axis: a for a in crafts.request_axes}["time_window"]
    assert (time_axis.outcome, time_axis.unknown_reason) == ("unknown", "listing_silent")
    for candidate in trace.scoring.candidates:
        for axis in [*candidate.request_axes, *candidate.preference_axes]:
            assert (axis.unknown_reason is None) == (axis.outcome != "unknown")


def _assert_cards_explain_exactly_what_they_can(traces: list[ActivityRankingTrace]) -> None:
    """D15/D12/D11 across real traces: no line without a positive factor; every card's face holds
    at most three lines and its face plus `more_reasons` is exactly the eligible set (after a swap
    too, VARIETY included); `reasons_suppressed` is `len(more_reasons)`; a promoted card shows
    VARIETY; a card with no more positive bases than slots shows a line for every one on its
    face; and no final card has a positive factor that is unexplained."""
    from silverloop.activity_search import REASON_BASIS_FACTOR, eligible_reasons
    from silverloop.models import ActivityReason, ReasonBasis

    variety = ActivityReason(
        text="Something a bit different from the others.", basis=ReasonBasis.VARIETY
    )
    checked = 0
    for trace in traces:
        assert trace.integrity.reason_without_positive_factor == 0
        assert trace.integrity.unsupported == 0
        assert trace.integrity.on_expand == sum(
            1 for f in trace.integrity.findings if f.classification == "on_expand"
        )
        for candidate in trace.scoring.candidates:
            contributions = {f.name: f.contribution for f in candidate.factors}
            before = list(candidate.reasons_before_composition)
            if candidate.variety_promoted:
                before.append(variety)
                assert any(r.basis is ReasonBasis.VARIETY for r in candidate.reasons_shown)
            eligible = eligible_reasons(before, contributions)
            assert len(candidate.reasons_shown) <= 3
            # Senior-facing sentences are written with commas, never " -- " (design review).
            assert all(
                "--" not in r.text for r in [*candidate.reasons_shown, *candidate.more_reasons]
            )
            card = [*candidate.reasons_shown, *candidate.more_reasons]
            assert sorted(card, key=repr) == sorted(eligible, key=repr)
            assert candidate.reasons_suppressed == len(candidate.more_reasons)
            assert candidate.reasons_suppressed == len(eligible) - len(candidate.reasons_shown)
            positive = {
                basis
                for basis, factor in REASON_BASIS_FACTOR.items()
                if contributions[factor] > 0 and any(r.basis is basis for r in eligible)
            }
            slots = 3 - (1 if candidate.variety_promoted else 0)
            if len(positive) <= slots:
                assert positive <= {r.basis for r in candidate.reasons_shown}
            checked += 1
    assert checked > 1000


def test_rain_and_a_morning_request_no_longer_lift_a_listing_that_says_nothing(
    api: TestClient,
) -> None:
    """D13 acceptance: the undated reading corner used to take the unjudged intent credit and sit
    in the top three of a rainy "something in the morning"."""
    payload = _inspect(
        api,
        person_id="mdm-lim",
        text="something in the morning",
        counterfactual={"world": {"rain": True}},
    )
    variant = _trace(payload, "variant")
    top = [item.activity_id for item in variant.final_recommendations.top]
    assert "activity-reading-corner" not in top
    assert {programme for programme in (t.split("-")[1] for t in top)} == {
        "chair",
        "sheltered",
        "pool",
    }
    reading = next(
        c for c in variant.scoring.candidates if c.activity_id == "activity-reading-corner"
    )
    assert {f.name: f.contribution for f in reading.factors}["intent"] == 0.0
    assert reading.tier == reading.sort_key.tier == 1.0
    assert variant.integrity.unsupported == 0


def test_card_headlines_are_the_rankers_top_three_across_default_traces(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    """D18 acceptance: the screen folds sessions by `series_key` and headlines the best-ranked
    one, so over default traces (LLM off) the three card headlines are the ranker's top three."""
    for person_id in ("mdm-siti", "mr-tan", "mdm-devi"):
        repo.reset(person_id=person_id)
    people = ("mdm-lim", "mr-ravi", "mdm-siti", "mr-tan", "mdm-devi")
    texts = (
        None,
        "something near me",
        "something with other people in the morning",
        "indoor light exercise",
        "no walking, my knee",
        "within 800 m",
        "something outdoors this afternoon",
        "tai chi in Mandarin",
        "gentle exercise",
        "something to do on my own",
    )
    folded: set[tuple[str, str | None]] = set()
    for person_id in people:
        for text in texts:
            body: dict[str, Any] = {"person_id": person_id}
            if text:
                body["text"] = text
            trace = _trace(_inspect(api, **body))
            final = trace.final_recommendations
            top = [item.activity_id for item in final.top]
            headlines = [card.headline_activity_id for card in final.web_cards]
            series = {c.activity_id: (c.provider, c.title) for c in trace.scoring.candidates}
            # Every card headlines the best-ranked session of its programme, in ranker order.
            firsts = list(dict.fromkeys(series[key] for key in trace.llm_rerank.final_order))[:3]
            assert [series[key] for key in headlines] == firsts
            for card in final.web_cards:
                assert card.member_ids[0] == card.headline_activity_id
            if len({series[key] for key in top}) == len(top) == 3:
                assert headlines == top and final.web_grouping_changes_top_three is False
            else:
                # Fewer distinct programmes than slots (the series dedupe only reorders when
                # there are more than three results): the screen folds them, and says so.
                assert final.web_grouping_changes_top_three is True
                folded.add((person_id, text))
    # Exactly these fold, and nothing else: an afternoon outdoors keeps only two programmes on the
    # fixture catalogue (the garden stretch's two sessions and one gardening session).
    assert folded == {(person_id, "something outdoors this afternoon") for person_id in people}


# ── D4 / D5: the planner stage reports the run's own transport and every rule code ────────────


def test_the_planner_stage_reads_provider_and_transport_from_the_run() -> None:
    from datetime import UTC, datetime

    from silverloop.agent.planner import ActivityPlanRun
    from silverloop.models import TraceIntentPlanner
    from silverloop.ranker_inspector import LlmConfig, run_llm_stage

    repository = _llm_repo()
    try:
        trace = repository.inspect_ranker(RankerInspectRequest(person_id="mdm-lim")).baseline
        by_id = {c.activity_id: c for c in trace.scoring.candidates}
        from silverloop.models import RankedActivity

        catalogue = {c.activity_id: c for c in repository.list_activities()}
        ranked = [
            RankedActivity(
                candidate=catalogue[key], rank=position, reasons=by_id[key].reasons_shown
            )
            for position, key in enumerate(trace.llm_rerank.final_order, start=1)
        ]
    finally:
        repository.close()

    def run_with(provider: str | None, transport: str | None) -> Any:
        def plan(context: Any, order: list[str]) -> ActivityPlanRun:
            return ActivityPlanRun(
                evidence_id="agent-test",
                agent_version="v",
                mode="fallback_disabled",
                provider=provider,
                transport=transport,  # type: ignore[arg-type]
                started_at=datetime.now(UTC),
                max_iterations=4,
                selected_order=order,
            )

        return run_llm_stage(
            ranked,
            ["anything"],
            run_planner=True,
            config=LlmConfig(enabled=True, provider="anthropic", model="m", max_iterations=4),
            plan=plan,
            differs_from_live=True,
            intent_planner=TraceIntentPlanner(ran=False, mode="chips"),
        ).trace

    replayed = run_with("recorded", "recorded")
    assert (replayed.provider, replayed.transport, replayed.recording_may_miss) == (
        "recorded",
        "recorded",
        True,
    )
    never_requested = run_with(None, None)
    assert (never_requested.provider, never_requested.transport) == ("anthropic", "off")
    assert never_requested.recording_may_miss is False


def test_promotion_and_narrowing_rejections_surface_as_rule_codes() -> None:
    repository = _llm_repo()
    try:
        window = repository.inspect_ranker(
            RankerInspectRequest(person_id="mdm-lim")
        ).baseline.llm_rerank.deterministic_window
        assert len(window) == 10
        planner = _Scripted(
            [
                _Response([_Block("t1", "get_activity_options", {})]),
                # The last option to first place: a promotion past MAX_PROMOTION.
                _Response(
                    [
                        _Block(
                            "t2",
                            "propose_activity_order",
                            {"ordered_keys": [window[-1], *window[:-1]], "reasoning": "r"},
                        )
                    ]
                ),
                # Two of ten: narrowing below MIN_SHOWN_AFTER_NARROWING.
                _Response(
                    [
                        _Block(
                            "t3",
                            "propose_activity_order",
                            {"ordered_keys": window[:2], "reasoning": "r"},
                        )
                    ]
                ),
                _Response(
                    [
                        _Block(
                            "t4",
                            "propose_activity_order",
                            {"ordered_keys": window, "reasoning": "r"},
                        )
                    ]
                ),
            ]
        )
        stage = repository.inspect_ranker(
            RankerInspectRequest(person_id="mdm-lim", run_planner=True),
            planner_client_factory=lambda: (planner, None),
        ).baseline.llm_rerank
        assert stage.status == "agent" and stage.rejected_proposal_count == 2
        assert stage.guardrail_rule_counts == {"over_promotion": 1, "over_narrowing": 1}
        assert (stage.provider, stage.transport) == ("anthropic", "live")
    finally:
        repository.close()


# ── D17 / D20: fact keys come from the resolver; ACTIVITY_TYPE resolves per value ────────────


def test_goal_and_per_activity_type_facts_resolve_on_the_resolvers_own_keys(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    repo.set_goal(GoalKind.MEET_PEOPLE, None, True, "t", person_id="mdm-lim")
    repo.state_preference(
        PreferenceDimension.SOCIAL, "social", PreferenceStance.AVOID, actor="t", person_id="mdm-lim"
    )
    repo.state_preference(
        PreferenceDimension.ACTIVITY_TYPE,
        "arts_crafts",
        PreferenceStance.PREFER,
        actor="t",
        person_id="mdm-lim",
    )
    # Three widened "not for me"s on stretch sessions: a strong learned avoid of that one type.
    for activity_id in (
        "activity-garden-stretch-1",
        "activity-garden-stretch-2",
        "activity-evening-stretch-1",
    ):
        response = api.post(
            f"/v1/activities/{activity_id}/response",
            json={
                "response": "not_for_me",
                "reason": "not_for_me",
                "clarification": "this_activity_type",
            },
        )
        assert response.status_code == 200, response.text

    payload = _inspect(
        api,
        person_id="mdm-lim",
        counterfactual={"world_model": {"temporary_avoid_activity_type": "walking"}},
        feedback={
            "activity_id": "activity-evening-stretch-2",
            "response": "enjoyment",
            "enjoyment": "enjoyed",
            "liked": ["activity"],
        },
    )
    baseline, variant = _trace(payload), _trace(payload, "variant")
    facts = {fact.fact_key: fact for fact in variant.person_context.facts}
    # Keys are unique: no two facts collapse onto one name.
    assert len(facts) == len(variant.person_context.facts)

    # D20: a goal and a statement on the same value are two keys, contradicting each other only.
    goal, stated = facts["goal:social:social"], facts["social:social:senior_statement"]
    assert (goal.provenance, goal.tier, goal.used_in_scoring) == ("goal", "stated_goal", False)
    assert goal.not_used_reason == "not_winning_tier"  # SOCIAL resolves over the whole axis
    assert (stated.provenance, stated.used_in_scoring) == ("person_said", True)
    assert goal.contradicted_by == ["social:social:senior_statement"]
    assert stated.contradicted_by == ["goal:social:social"]

    # D17: a temporary avoid of walking no longer silences beliefs about other kinds of activity.
    walking = facts["activity_type:walking:senior_statement"]
    arts = facts["activity_type:arts_crafts:senior_statement"]
    stretch_avoid = facts["activity_type:stretch:decline_reason"]
    assert (walking.provenance, walking.used_in_scoring) == ("temporary", True)
    assert arts.used_in_scoring and arts.winning and arts.not_used_reason is None
    assert stretch_avoid.used_in_scoring and stretch_avoid.tier == "strong_learned"
    # ... and on the same type, not_winning_tier means a stronger belief about that very type.
    stretch_like = facts["activity_type:stretch:inferred"]
    assert stretch_like.changed_by_preview and not stretch_like.used_in_scoring
    assert stretch_like.not_used_reason == "not_winning_tier"
    assert stretch_like.contradicted_by == ["activity_type:stretch:decline_reason"]

    # Every used belief is one scoring actually walked, keyed identically on the candidates.
    walked = {axis.fact_key for c in variant.scoring.candidates for axis in c.preference_axes}
    assert walked == {key for key, fact in facts.items() if fact.used_in_scoring}
    assert "goal:social:social" in {f.fact_key for f in baseline.person_context.facts}


# ── A second item-level answer about the same programme widens nothing, in previews too ──────


def _pure_state(repository: SqlAlchemyRepository, **overrides: Any) -> Any:
    from datetime import date

    from silverloop.ranker_inspector import InspectionState

    fields: dict[str, Any] = dict(
        person_id="mdm-lim",
        display_name="Mdm Lim",
        run_id="run-test",
        today=date(2026, 9, 15),
        catalogue=repository.list_activities(),
        dimensions=[],
        goals=[],
        offers=[],
        follow_through=[],
        verdicts=[],
        rain_forecast=False,
        consent_active=True,
    )
    fields.update(overrides)
    return InspectionState(**fields)


def _type_facts(state: Any) -> list[tuple[str | None, str]]:
    return [
        (p.value, p.sentiment)
        for p in state.preferences().resolved
        if p.dimension is PreferenceDimension.ACTIVITY_TYPE
    ]


def test_a_feedback_preview_on_the_same_programme_as_a_held_back_row_applies_nothing(
    repo: SqlAlchemyRepository,
) -> None:
    """The repository fills `origin_series` for the origins stored rows name; a preview on a
    sibling session of that programme teaches nothing new, and one on a different programme of
    the same kind is the second answer that widens."""
    from silverloop.models import (
        ClarificationScope,
        DeclineReason,
        DimensionPreference,
        RankerFeedbackKind,
        RankerFeedbackPreview,
    )
    from silverloop.ranker_inspector import apply_feedback

    catalogue = {c.activity_id: c for c in repo.list_activities()}
    from silverloop.activity_search import series_key

    chair = catalogue["activity-chair-mobility-1"]
    held = DimensionPreference(
        dimension=PreferenceDimension.ACTIVITY_TYPE,
        value="chair_exercise",
        strength=-0.333,
        source="decline_reason",
        confirmed=False,
        observations=1,
        updated_at=chair.retrieved_at,
        negative_evidence=1.0,
        scope=ClarificationScope.THIS_ONE,
        origin_id="offer-response-live",
    )
    state = _pure_state(
        repo, dimensions=[held], origin_series={"offer-response-live": series_key(chair)}
    )
    assert _type_facts(state) == []

    def preview(activity_id: str) -> Any:
        return apply_feedback(
            state,
            RankerFeedbackPreview(
                activity_id=activity_id,
                response=RankerFeedbackKind.NOT_FOR_ME,
                reason=DeclineReason.NOT_FOR_ME,
            ),
            duplicate_same_day=False,
        )

    sibling = preview("activity-chair-mobility-2")
    assert sibling.teaches_dimension is False
    assert sibling.state.dimensions == [held]
    assert _type_facts(sibling.state) == []

    other_programme = preview("activity-seated-strength-1")
    assert series_key(catalogue["activity-seated-strength-1"]) != series_key(chair)
    assert other_programme.teaches_dimension is True
    assert _type_facts(other_programme.state) == [("chair_exercise", "avoid")]


def test_a_preset_decline_then_a_preview_on_the_same_programme_applies_nothing(
    repo: SqlAlchemyRepository,
) -> None:
    """A scripted origin names its programme before it is folded, so a preview on top of the
    preset reads it exactly as a stored origin."""
    from silverloop.evaluator_presets import HistoryPreset, ScriptedEvent
    from silverloop.models import DeclineReason, RankerFeedbackKind, RankerFeedbackPreview
    from silverloop.ranker_inspector import apply_feedback, apply_history_preset

    preset = HistoryPreset(
        preset_id="test-chair",
        person_id="mdm-lim",
        title="test",
        events=(
            ScriptedEvent(
                kind="not_for_me",
                programme_key="chair-mobility",
                days_ago=3,
                reason=DeclineReason.NOT_FOR_ME,
            ),
            # The same programme again, scripted: still one opinion about that class.
            ScriptedEvent(
                kind="not_for_me",
                programme_key="chair-mobility",
                days_ago=1,
                reason=DeclineReason.NOT_FOR_ME,
            ),
        ),
    )
    scripted, _ = apply_history_preset(_pure_state(repo), preset)
    assert len(scripted.origin_series) == 2
    assert [row.negative_evidence for row in scripted.dimensions] == [1.0]
    assert _type_facts(scripted) == []

    outcome = apply_feedback(
        scripted,
        RankerFeedbackPreview(
            activity_id="activity-chair-mobility-3",
            response=RankerFeedbackKind.NOT_FOR_ME,
            reason=DeclineReason.NOT_FOR_ME,
        ),
        duplicate_same_day=False,
    )
    assert outcome.teaches_dimension is False
    assert _type_facts(outcome.state) == []


def test_inspecting_a_same_programme_preview_after_a_live_decline_shows_no_new_fact(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    from silverloop.models import ActivityOfferResponse, DeclineReason

    repo.respond_to_activity(
        "activity-chair-mobility-1",
        ActivityOfferResponse.NOT_FOR_ME,
        reason=DeclineReason.NOT_FOR_ME,
        actor="test",
        person_id="mdm-lim",
    )
    feedback = {
        "activity_id": "activity-chair-mobility-2",
        "response": "not_for_me",
        "reason": "not_for_me",
    }
    payload = _inspect(api, person_id="mdm-lim", feedback=feedback)
    variant = _trace(payload, "variant")
    preview = variant.applied.learning_preview
    assert preview is not None and preview.duplicate_same_day is False
    assert preview.teaches_dimension is False
    applied = [
        f.fact_key
        for f in variant.person_context.facts
        if f.dimension is PreferenceDimension.ACTIVITY_TYPE and f.status == "applied"
    ]
    assert applied == []

    # The same preview on a different chair-exercise programme is the second answer that widens.
    feedback["activity_id"] = "activity-seated-strength-1"
    widened = _trace(_inspect(api, person_id="mdm-lim", feedback=feedback), "variant")
    assert widened.applied.learning_preview is not None
    assert widened.applied.learning_preview.teaches_dimension is True
    assert [
        f.fact_key
        for f in widened.person_context.facts
        if f.dimension is PreferenceDimension.ACTIVITY_TYPE and f.status == "applied"
    ] == ["activity_type:chair_exercise:decline_reason"]


# ── DISTANCE statements with no number: why one is or is not used ─────────────────────────────


def test_distance_facts_say_why_they_were_not_used_and_never_deprecated_axis(
    repo: SqlAlchemyRepository,
) -> None:
    from datetime import UTC, datetime

    from silverloop.models import DimensionPreference
    from silverloop.ranker_inspector import trace_facts

    now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)

    def row(value: str, strength: float, source: str, **extra: Any) -> DimensionPreference:
        return DimensionPreference(
            dimension=PreferenceDimension.DISTANCE,
            value=value,
            strength=strength,
            source=source,  # type: ignore[arg-type]
            confirmed=source == "senior_statement",
            observations=1,
            updated_at=now,
            positive_evidence=1.0 if strength > 0 else 0.0,
            negative_evidence=1.0 if strength < 0 else 0.0,
            **extra,
        )

    def reasons(rows: list[DimensionPreference]) -> dict[str, tuple[bool, str | None]]:
        state = _pure_state(repo, dimensions=rows)
        return {
            f"{fact.value}:{fact.sentiment}:{fact.tier}": (
                fact.used_in_scoring,
                fact.not_used_reason,
            )
            for fact in trace_facts(state, ActivityIntent(), state.preferences())
            if fact.dimension is PreferenceDimension.DISTANCE
        }

    assert reasons([row("near", 1.0, "senior_statement")]) == {"near:like:stated": (True, None)}
    assert reasons([row("far", -1.0, "senior_statement")]) == {"far:avoid:stated": (True, None)}
    assert reasons([row("far", 1.0, "senior_statement")]) == {
        "far:like:stated": (False, "never_widens")
    }
    assert reasons([row("near", -1.0, "senior_statement")]) == {
        "near:avoid:stated": (False, "never_widens")
    }
    assert reasons([row("near", 0.5, "inferred")]) == {
        "near:like:weak_learned": (False, "no_distance_line")
    }
    temporary_far = row(
        "far", 1.0, "senior_statement", expires_at=datetime(2026, 9, 20, tzinfo=UTC)
    )
    # A higher-tier "far" neither silences the "near" (it resolves apart) nor is ever read.
    assert reasons([row("near", 1.0, "senior_statement"), temporary_far]) == {
        "near:like:stated": (True, None),
        "far:like:temporary_stated": (False, "never_widens"),
    }
    # Two near-leaning statements still settle by tier.
    temporary_near = row(
        "near", 1.0, "senior_statement", expires_at=datetime(2026, 9, 20, tzinfo=UTC)
    )
    assert reasons([row("far", -1.0, "senior_statement"), temporary_near]) == {
        "far:avoid:stated": (False, "not_winning_tier"),
        "near:like:temporary_stated": (True, None),
    }
    # A far-leaning statement outranked by another far-leaning one is still `never_widens`.
    assert reasons([row("near", -1.0, "senior_statement"), temporary_far]) == {
        "near:avoid:stated": (False, "never_widens"),
        "far:like:temporary_stated": (False, "never_widens"),
    }
    for rows in (
        [row("far", 1.0, "senior_statement")],
        [row("near", 0.5, "inferred")],
        [row("lower", 0.333, "decline_reason", pivot=650.0, direction="lower")],
    ):
        assert all(reason != "deprecated_axis" for _, reason in reasons(rows).values())


def test_the_person_context_reports_the_nearby_radius_and_a_stated_near(
    api: TestClient, repo: SqlAlchemyRepository
) -> None:
    from silverloop.preferences import NEARBY_RADIUS_M

    baseline = _trace(_inspect(api, person_id="mdm-lim")).person_context
    assert baseline.nearby_radius_m == NEARBY_RADIUS_M == 1000
    repo.state_preference(
        PreferenceDimension.DISTANCE,
        "near",
        PreferenceStance.PREFER,
        actor="test",
        person_id="mdm-lim",
    )
    stated = _trace(_inspect(api, person_id="mdm-lim")).person_context
    assert stated.nearby_radius_m == NEARBY_RADIUS_M
    near = [f for f in stated.facts if f.dimension is PreferenceDimension.DISTANCE]
    assert [(f.value, f.used_in_scoring, f.not_used_reason) for f in near] == [("near", True, None)]
    assert stated.travel_tolerance_m == min(baseline.travel_tolerance_m, NEARBY_RADIUS_M)
    if baseline.travel_tolerance_m >= NEARBY_RADIUS_M:
        assert stated.travel_tolerance_basis == "stated_near"
    else:
        assert stated.travel_tolerance_basis == baseline.travel_tolerance_basis
