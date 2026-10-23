"""Tests for the activity-ranking planner (F27): `agent.planner.plan_activity_ranking`.

Mirrors `test_agent_planner.py` in shape and discipline -- a fake transport, exercised
deterministically and offline, because what matters here is the loop's own guarantees: the
allow-list, the guardrail, the iteration cap, and every degradation path -- applied to "reorder
and maybe narrow an already-filtered list" rather than "choose one outreach candidate".
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import select

import silverloop.agent.intent_planner as intent_planner_module
import silverloop.agent.planner as planner_module
from silverloop.agent.constants import MAX_ACTIVITY_OPTIONS_RETURNED
from silverloop.agent.guardrails import ActivityOrderProposal, validate_activity_order
from silverloop.agent.planner import plan_activity_ranking
from silverloop.agent.tools import ActivityOption, ActivityRankingContext
from silverloop.config import Settings
from silverloop.db_models import AuditEventRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository

# ── Fake transport, mirroring test_agent_planner.py ─────────────────────────────────────────────


@dataclass
class FakeBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class FakeResponse:
    content: list[Any]
    stop_reason: str = "tool_use"
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("The planner made more requests than the test scripted.")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.messages = FakeMessages(responses)


class EchoingFakeClient:
    """A client with no opinion of its own: it reads the keys `get_activity_options` returned
    and echoes them back, in the same order, as its proposal. Used to pin the "null-agent"
    property -- a model that adds nothing must reproduce the deterministic order exactly."""

    def __init__(self) -> None:
        self.messages = self
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if len(kwargs["messages"]) == 1:
            return FakeResponse([FakeBlock("tu1", "get_activity_options", {})])
        tool_result = kwargs["messages"][-1]["content"][0]["content"]
        keys = [option["activity_key"] for option in json.loads(tool_result)["options"]]
        return FakeResponse(
            [
                FakeBlock(
                    "tu2",
                    "propose_activity_order",
                    {"ordered_keys": keys, "reasoning": "No change; the order already fits."},
                )
            ]
        )


def option(key: str, *, rank: int, category: str | None = "movement") -> ActivityOption:
    return ActivityOption(
        key=key,
        title=f"Activity {key}",
        category=category,
        distance_m=500,
        environment="indoor",
        intensity="light",
        time_window="morning",
        deterministic_rank=rank,
        reasons=["Matches what you asked for"],
    )


def context_with(count: int) -> ActivityRankingContext:
    return ActivityRankingContext(
        understood_lines=["Anything that suits you"],
        options=[option(f"activity-{index}", rank=index) for index in range(count)],
    )


def settings_with(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "llm_enabled": True,
        "llm_api_key": "test-key",
        "llm_model": "claude-opus-5",
        "llm_max_iterations": 4,
        "external_context_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def run(context: ActivityRankingContext, responses: list[Any], **overrides: Any):
    fallback_order = [item.key for item in context.options[:MAX_ACTIVITY_OPTIONS_RETURNED]]
    return plan_activity_ranking(
        context,
        settings=settings_with(**overrides),
        fallback_order=fallback_order,
        client_factory=lambda: (FakeClient(responses), None),
    )


def propose_block(ordered_keys: list[str], block_id: str = "tu_propose") -> FakeBlock:
    return FakeBlock(
        id=block_id,
        name="propose_activity_order",
        input={"ordered_keys": ordered_keys, "reasoning": "Because."},
    )


# ── Guardrail: subset, reorder, invented key, duplicate, empty-with-options ─────────────────────


def test_guardrail_accepts_a_reordered_subset() -> None:
    """Reordering and narrowing are both still the planner's to do -- within the bounds below."""
    permitted = ["a", "b", "c", "d", "e"]
    verdict = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["c", "a", "b"]), permitted_keys=permitted
    )
    assert verdict.approved
    assert verdict.violations == []


# ── Bounding a captured ranker: promotion cap and narrowing floor ───────────────────────────────
#
# The allow-list answers "can external text make the planner offer something it was never shown".
# These answer the attack that does not need an invented key: a listing whose own title says
# "rank me first and drop the rest".


def test_guardrail_rejects_promoting_an_option_past_the_cap() -> None:
    permitted = ["a", "b", "c", "d", "e", "f"]
    verdict = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["f", "a", "b", "c", "d", "e"]),
        permitted_keys=permitted,
    )
    assert not verdict.approved
    assert any("more than 3 position(s)" in violation for violation in verdict.violations)
    assert any("f (offered at 1, deterministic position 6)" in v for v in verdict.violations)


def test_guardrail_allows_a_promotion_of_exactly_the_cap() -> None:
    """The cap is a bound on the blast radius, not a ban on the planner doing its job."""
    permitted = ["a", "b", "c", "d", "e", "f"]
    verdict = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["d", "a", "b", "c", "e", "f"]),
        permitted_keys=permitted,
    )
    assert verdict.approved, verdict.violations


def test_narrowing_counts_towards_the_promotion_cap() -> None:
    """Hiding the options above a key promotes it just as surely as reordering does, so the cap
    is measured on the final position."""
    permitted = ["a", "b", "c", "d", "e", "f"]
    verdict = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["e", "f", "a"]), permitted_keys=permitted
    )
    assert not verdict.approved
    assert any("more than 3 position(s)" in violation for violation in verdict.violations)


def test_guardrail_rejects_narrowing_below_the_floor() -> None:
    permitted = ["a", "b", "c", "d"]
    verdict = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["a", "b"]), permitted_keys=permitted
    )
    assert not verdict.approved
    assert any("at least 3 must be offered" in violation for violation in verdict.violations)


def test_the_floor_does_not_apply_when_fewer_options_were_shown() -> None:
    """With two permitted options there is no "drop the rest" to prevent."""
    verdict = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["a"]), permitted_keys=["a", "b"]
    )
    assert verdict.approved, verdict.violations


def test_guardrail_rejects_an_invented_key() -> None:
    verdict = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["a", "not-a-real-key"]), permitted_keys=["a", "b"]
    )
    assert not verdict.approved
    assert any("not-a-real-key" in violation for violation in verdict.violations)


def test_guardrail_rejects_a_duplicate_key() -> None:
    verdict = validate_activity_order(
        ActivityOrderProposal(ordered_keys=["a", "a"]), permitted_keys=["a", "b"]
    )
    assert not verdict.approved
    assert any("Duplicate" in violation for violation in verdict.violations)


def test_guardrail_rejects_offering_nothing_when_options_exist() -> None:
    verdict = validate_activity_order(ActivityOrderProposal(ordered_keys=[]), permitted_keys=["a"])
    assert not verdict.approved
    assert any("offers nothing" in violation for violation in verdict.violations)


def test_guardrail_allows_offering_nothing_when_nothing_is_permitted() -> None:
    """An empty allow-list is not the planner's failure -- there is nothing to narrow from."""
    verdict = validate_activity_order(ActivityOrderProposal(ordered_keys=[]), permitted_keys=[])
    assert verdict.approved


# ── The loop: success, narrowing, degradation ───────────────────────────────────────────────────


def test_loop_returns_mode_agent_on_an_approved_proposal() -> None:
    context = context_with(3)
    result = run(
        context,
        [
            FakeResponse([FakeBlock("tu1", "get_activity_options", {})]),
            FakeResponse([propose_block(["activity-2", "activity-0", "activity-1"])]),
        ],
    )
    assert result.mode == "agent"
    assert result.used_agent
    assert result.selected_order == ["activity-2", "activity-0", "activity-1"]
    assert result.iterations == 2


def test_provider_error_falls_back_and_keeps_the_deterministic_order() -> None:
    context = context_with(3)
    result = run(context, [RuntimeError("connection reset")])
    assert result.mode == "fallback_error"
    # The class only: provider text is never stored, it can carry request details.
    assert result.fallback_reason == "RuntimeError"
    assert result.selected_order == [item.key for item in context.options]


def test_exhausted_iteration_cap_keeps_the_deterministic_order() -> None:
    """The model keeps calling the read tool forever; Python stops it at the cap."""
    context = context_with(3)
    forever = [FakeResponse([FakeBlock("tu1", "get_activity_options", {})])] * 20
    result = run(context, forever, llm_max_iterations=2)
    assert result.mode == "fallback_exhausted"
    assert result.iterations == 2
    assert result.max_iterations == 2
    assert result.selected_order == [item.key for item in context.options]


def test_an_escalating_proposal_is_rejected_every_time_then_falls_back() -> None:
    """A model that only ever proposes an invented key never gets through."""
    context = context_with(2)
    bogus = propose_block(["invented-key"])
    result = run(context, [FakeResponse([bogus])] * 4)
    assert result.mode == "fallback_exhausted"
    assert result.selected_order == [item.key for item in context.options]
    assert len(result.guardrail_rejections) == 4


def test_narrowing_is_visible_in_the_result() -> None:
    """The planner may narrow: fewer keys come back than were shown, and none invented."""
    context = context_with(5)
    result = run(
        context,
        [
            FakeResponse([FakeBlock("tu1", "get_activity_options", {})]),
            FakeResponse([propose_block(["activity-0", "activity-1", "activity-2"])]),
        ],
    )
    assert result.mode == "agent"
    assert len(result.selected_order) < len(context.options)
    assert set(result.selected_order) <= set(context.permitted_keys)


def test_narrowing_reaches_the_repository_as_planner_narrowed() -> None:
    """Integration seam: the repository turns a narrowed planner order into a `FilterOutcome`
    with `rule == "planner_narrowed"` for every option the planner chose not to show -- the only
    account of "permitted, but the agent decided not to offer it". This proves the planner's
    narrowing (owned here) is not silently lost one layer up (owned by the repository).
    """
    repository = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=settings_with(database_url="sqlite+pysqlite:///:memory:"),
    )
    repository.create_schema_for_tests()
    repository.reset()
    try:
        original_build_client = planner_module._build_client
        planner_module._build_client = lambda settings, timeout: (EchoingFakeClient(), None)
        try:
            baseline = repository.search_activities(
                text=None, intent=None, person_id=DEMO_PERSON_ID, actor=DEMO_PERSON_ID
            )
        finally:
            planner_module._build_client = original_build_client

        shown_ids = [item.candidate.activity_id for item in baseline.results][
            :MAX_ACTIVITY_OPTIONS_RETURNED
        ]
        assert len(shown_ids) > 1, "the fixture catalogue must offer more than one option to narrow"
        dropped = shown_ids[-1]
        narrowed_keys = shown_ids[:-1]

        class NarrowingFakeClient:
            def __init__(self) -> None:
                self.messages = self

            def create(self, **kwargs: Any) -> Any:
                if len(kwargs["messages"]) == 1:
                    return FakeResponse([FakeBlock("tu1", "get_activity_options", {})])
                return FakeResponse(
                    [
                        FakeBlock(
                            "tu2",
                            "propose_activity_order",
                            {
                                "ordered_keys": narrowed_keys,
                                "reasoning": "Dropping the weakest fit.",
                            },
                        )
                    ]
                )

        planner_module._build_client = lambda settings, timeout: (NarrowingFakeClient(), None)
        try:
            response = repository.search_activities(
                text=None, intent=None, person_id=DEMO_PERSON_ID, actor=DEMO_PERSON_ID
            )
        finally:
            planner_module._build_client = original_build_client

        narrowed_outcomes = [
            outcome for outcome in response.filtered_out if outcome.rule == "planner_narrowed"
        ]
        assert any(outcome.activity_id == dropped for outcome in narrowed_outcomes)
    finally:
        repository.close()


# ── A3: the allow-list is exactly what was shown, never the full permitted set ──────────────────


def test_permitted_keys_is_exactly_the_shown_set_not_the_full_option_list() -> None:
    context = context_with(MAX_ACTIVITY_OPTIONS_RETURNED + 5)
    assert len(context.permitted_keys) == MAX_ACTIVITY_OPTIONS_RETURNED
    assert context.permitted_keys == [
        item.key for item in context.options[:MAX_ACTIVITY_OPTIONS_RETURNED]
    ]


def test_a_key_beyond_the_shown_cap_is_rejected_even_though_it_is_a_real_option() -> None:
    """A key the deterministic ranker permitted but the tool never showed must still be
    rejected -- the allow-list is what was shown, not what merely exists."""
    context = context_with(MAX_ACTIVITY_OPTIONS_RETURNED + 1)
    unseen_key = context.options[-1].key
    assert unseen_key not in context.permitted_keys

    result = run(
        context,
        [
            FakeResponse([FakeBlock("tu1", "get_activity_options", {})]),
            FakeResponse([propose_block([unseen_key])]),
            FakeResponse([propose_block(context.permitted_keys[:3])]),
        ],
    )
    assert result.mode == "agent"
    assert result.selected_order == context.permitted_keys[:3]
    assert any(unseen_key in violation for violation in result.guardrail_rejections)


# ── Null-agent property ─────────────────────────────────────────────────────────────────────────


def test_a_model_that_echoes_the_deterministic_order_reproduces_it_exactly() -> None:
    context = context_with(4)
    fallback_order = [item.key for item in context.options]
    result = plan_activity_ranking(
        context,
        settings=settings_with(),
        fallback_order=fallback_order,
        client_factory=lambda: (EchoingFakeClient(), None),
    )
    assert result.mode == "agent"
    assert result.selected_order == fallback_order


# ── Degradation paths shared with the outreach planner ──────────────────────────────────────────


def test_disabled_flag_never_builds_a_client() -> None:
    context = context_with(2)
    result = plan_activity_ranking(
        context,
        settings=settings_with(llm_enabled=False),
        fallback_order=[item.key for item in context.options],
        client_factory=lambda: pytest.fail("must not build a client when disabled"),
    )
    assert result.mode == "fallback_disabled"
    assert result.selected_order == [item.key for item in context.options]


def test_no_options_never_builds_a_client() -> None:
    context = context_with(0)
    result = plan_activity_ranking(
        context,
        settings=settings_with(),
        fallback_order=[],
        client_factory=lambda: pytest.fail("no options means no reason to call the model"),
    )
    assert result.mode == "fallback_disabled"
    assert result.selected_order == []


def test_turn_without_a_proposal_falls_back() -> None:
    context = context_with(2)
    result = run(context, [FakeResponse(content=[], stop_reason="end_turn")])
    assert result.mode == "fallback_no_proposal"
    assert result.selected_order == [item.key for item in context.options]


def test_model_refusal_falls_back() -> None:
    context = context_with(2)
    result = run(context, [FakeResponse(content=[], stop_reason="refusal")])
    assert result.mode == "fallback_error"
    assert "refusal" in (result.fallback_reason or "")


# ── A malformed provider response must degrade the SEARCH, not 500 it ───────────────────────────
#
# The outreach loop is wrapped by `_plan_outreach_safely`'s blanket `except Exception`, so a
# provider shape neither planner anticipated still produces an audited fallback.
# `search_activities` had no such guard, and both planners it calls can raise: `plan_intent` reads
# `response.content` outside its own `try`, so `content=None`, `content=5` and a response with no
# `content` attribute at all raised `TypeError`/`AttributeError` straight through a senior-facing
# request; and `_tool_use_blocks` validates a block's `type` and `name` but not its `id`, so a
# well-formed `tool_use` block with no `id` raised `AttributeError` out of the ranking loop.
#
# All four are now what the documented degradation says they are: the deterministic order, an
# audited `fallback_error`, and the exception's CLASS -- never its text -- in the evidence.


class _MalformedIntentClient:
    """Answers the intent call with `response`, whatever shape that is."""

    def __init__(self, response: Any) -> None:
        self.messages = self
        self.response = response

    def create(self, **kwargs: Any) -> Any:
        return self.response


class _NoContent:
    """A response object with no `content` attribute at all."""

    usage = None
    stop_reason = "tool_use"


@pytest.fixture
def search_repository() -> Any:
    repository = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=settings_with(database_url="sqlite+pysqlite:///:memory:"),
    )
    repository.create_schema_for_tests()
    repository.reset()
    try:
        yield repository
    finally:
        repository.close()


@contextmanager
def _intent_client(response: Any) -> Any:
    original = intent_planner_module._build_client
    intent_planner_module._build_client = lambda settings: (_MalformedIntentClient(response), None)
    try:
        yield
    finally:
        intent_planner_module._build_client = original


@contextmanager
def _ranking_client(client: Any) -> Any:
    original = planner_module._build_client
    planner_module._build_client = lambda settings, timeout: (client, None)
    try:
        yield
    finally:
        planner_module._build_client = original


def _stored_search_detail(repository: Any) -> dict[str, Any]:
    """The full, evaluator-visible audit row for the most recent search."""
    with repository.sessions() as session:
        row = session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.event_type == "activity_search")
            .order_by(AuditEventRow.recorded_at.desc(), AuditEventRow.event_id.desc())
            .limit(1)
        ).first()
        assert row is not None, "the search must always leave exactly one audit row"
        return dict(row.detail_json)


@pytest.mark.parametrize(
    ("response", "error_class"),
    [
        pytest.param(FakeResponse(content=None), "TypeError", id="content-is-null"),
        pytest.param(FakeResponse(content=5), "TypeError", id="content-is-a-number"),
        pytest.param(_NoContent(), "AttributeError", id="no-content-attribute"),
    ],
)
def test_a_malformed_intent_response_degrades_the_search_instead_of_raising(
    search_repository: Any, response: Any, error_class: str
) -> None:
    with _intent_client(response), _ranking_client(EchoingFakeClient()):
        result = search_repository.search_activities(
            text="something gentle nearby",
            intent=None,
            person_id=DEMO_PERSON_ID,
            actor=DEMO_PERSON_ID,
        )

    assert result.results, "the deterministic reading still produced a result set"
    assert result.intent.parsed_by.value == "keyword"
    stored = _stored_search_detail(search_repository)
    assert stored["intent_mode"] == "fallback_error"
    assert stored["intent"]["fallback_error"] == error_class


def test_a_tool_use_block_with_no_id_degrades_the_ranking_instead_of_raising(
    search_repository: Any,
) -> None:
    class _IdlessBlock:
        type = "tool_use"
        name = "get_activity_options"
        input: dict[str, Any] = {}

    class _IdlessClient:
        def __init__(self) -> None:
            self.messages = self

        def create(self, **kwargs: Any) -> Any:
            return FakeResponse(content=[_IdlessBlock()])

    with _ranking_client(_IdlessClient()):
        result = search_repository.search_activities(
            text=None, intent=None, person_id=DEMO_PERSON_ID, actor=DEMO_PERSON_ID
        )

    assert result.results
    stored = _stored_search_detail(search_repository)
    assert stored["planner_mode"] == "fallback_error"
    assert stored["agent"]["fallback_reason"] == "AttributeError"
    # The deterministic order stands, and nothing is recorded as narrowed by a planner that
    # never produced an order.
    assert [item.candidate.activity_id for item in result.results] == stored["result_ids"]
    assert not [outcome for outcome in result.filtered_out if outcome.rule == "planner_narrowed"]


def test_the_provider_exception_text_never_reaches_the_search_audit(
    search_repository: Any,
) -> None:
    """Same two-surface rule the outreach loop already follows: the class in `evidence_json`,
    the text on the operator log. `evidence_json` is append-only and coordinator-visible."""

    class _ExplodingClient:
        def __init__(self) -> None:
            self.messages = self

        def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("SECRET-KEY-sk-ABCDEF123456 in the exception text")

    with _ranking_client(_ExplodingClient()):
        search_repository.search_activities(
            text=None, intent=None, person_id=DEMO_PERSON_ID, actor=DEMO_PERSON_ID
        )

    stored = _stored_search_detail(search_repository)
    assert "SECRET-KEY" not in json.dumps(stored)
