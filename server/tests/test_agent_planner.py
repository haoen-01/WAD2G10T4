"""Tests for the outreach planning agent.

The planner is exercised against a fake transport rather than the live API: the behaviour that
matters here is the loop's own discipline -- the allow-list, the guardrail, the iteration cap and
every degradation path -- and that must be provable offline, deterministically, with no API key.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest

from silverloop.agent import (
    ActivityOption,
    ActivityRankingContext,
    AgentProposal,
    CandidateOption,
    HistoryEntry,
    ProgrammeOption,
    ToolContext,
    constants,
    execute_read_tool,
    plan_activity_ranking,
    plan_outreach,
    planner,
    tool_definitions,
    validate_proposal,
)
from silverloop.agent.constants import ITERATION_HARD_CEILING, MIN_MESSAGE_CHARS
from silverloop.agent.guardrails import fold_for_rules
from silverloop.agent.planner import PlannerState
from silverloop.config import Settings
from silverloop.models import Decision, SocialPreference

FALLBACK = ("gentle_nudge:indoor_walk", "Fallback message from the deterministic ranker.")
GOOD_MESSAGE = "Would a short indoor walk feel manageable today? No pressure at all."


# --------------------------------------------------------------------------------------
# Fake transport
# --------------------------------------------------------------------------------------


@dataclass
class FakeBlock:
    """Stands in for a `tool_use` content block."""

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


def propose_block(candidate_key: str, message: str, block_id: str = "tu_propose") -> FakeBlock:
    return FakeBlock(
        id=block_id,
        name="propose_outreach",
        input={"candidate_key": candidate_key, "message": message, "reasoning": "Because."},
    )


def settings_with(**overrides: Any) -> Settings:
    """Settings for a planner run, isolated from the developer's local `.env`."""
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


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(
        decision=Decision.GENTLE_NUDGE,
        display_name="Mdm Lim",
        preferred_language="English / Mandarin",
        context_note="Socially motivated.",
        delta_percent=-28.0,
        sustained_low_days=2,
        confidence=0.82,
        rainy=False,
        holiday=False,
        candidates=[
            CandidateOption("gentle_nudge:indoor_walk", "Gentle movement check-in", 0.5, 2, 1),
            CandidateOption("gentle_nudge:chair_mobility", "Five-minute movement option", 0.7),
        ],
        programmes=[
            ProgrammeOption(
                key="programme:p1",
                name="Morning Tai Chi",
                venue="Blk 123 CC",
                distance_km=0.4,
                next_session="2026-09-06T09:00:00+00:00",
                accessibility=["step-free"],
            )
        ],
        history=[
            HistoryEntry("2026-09-01T12:00:00+00:00", "gentle_nudge", "Gentle check-in", "declined")
        ],
    )


def run(context: ToolContext, responses: list[Any], **overrides: Any):
    return plan_outreach(
        context,
        settings=settings_with(**overrides),
        fallback_choice=FALLBACK,
        client_factory=lambda: (FakeClient(responses), None),
    )


# --------------------------------------------------------------------------------------
# Guardrail: the deterministic security boundary
# --------------------------------------------------------------------------------------


def test_guardrail_approves_a_compliant_proposal(context: ToolContext) -> None:
    verdict = validate_proposal(
        AgentProposal(candidate_key="gentle_nudge:indoor_walk", message=GOOD_MESSAGE),
        permitted_candidate_keys=context.permitted_candidate_keys,
    )
    assert verdict.approved
    assert verdict.violations == []


def test_guardrail_rejects_a_candidate_outside_the_allow_list(context: ToolContext) -> None:
    """The allow-list is what stops the planner inventing or escalating an action."""
    verdict = validate_proposal(
        AgentProposal(candidate_key="coordinator_review:call_family", message=GOOD_MESSAGE),
        permitted_candidate_keys=context.permitted_candidate_keys,
    )
    assert not verdict.approved
    assert any("not permitted" in violation for violation in verdict.violations)


def test_guardrail_rejects_a_programme_from_another_action_class(context: ToolContext) -> None:
    """A gentle nudge cannot become a programme suggestion by wording alone."""
    verdict = validate_proposal(
        AgentProposal(candidate_key="programme:p1", message=GOOD_MESSAGE),
        permitted_candidate_keys=context.permitted_candidate_keys,
    )
    assert not verdict.approved


@pytest.mark.parametrize(
    "message",
    [
        "Your recent decline in health worries us. Would you like to walk today?",
        "We think you may have symptoms worth checking. Would you like to walk?",
        "Please call your doctor about this. Would you like a walk today?",
        "This looks like an emergency. Would you like to walk today?",
    ],
)
def test_guardrail_rejects_clinical_language(context: ToolContext, message: str) -> None:
    verdict = validate_proposal(
        AgentProposal(candidate_key="gentle_nudge:indoor_walk", message=message),
        permitted_candidate_keys=context.permitted_candidate_keys,
    )
    assert not verdict.approved
    assert any("clinical" in violation for violation in verdict.violations)


@pytest.mark.parametrize(
    "message",
    [
        "You must walk today. Would you like to start now?",
        "This is urgent. Would you like a short walk?",
        "You need to respond immediately. Would you like to walk?",
    ],
)
def test_guardrail_rejects_pressure(context: ToolContext, message: str) -> None:
    verdict = validate_proposal(
        AgentProposal(candidate_key="gentle_nudge:indoor_walk", message=message),
        permitted_candidate_keys=context.permitted_candidate_keys,
    )
    assert not verdict.approved
    assert any("pressure" in violation for violation in verdict.violations)


def test_guardrail_rejects_raw_metrics_in_senior_copy(context: ToolContext) -> None:
    """Senior-facing copy never quotes the numbers behind the decision."""
    verdict = validate_proposal(
        AgentProposal(
            candidate_key="gentle_nudge:indoor_walk",
            message="You walked only 1200 steps. Would a short walk feel manageable today?",
        ),
        permitted_candidate_keys=context.permitted_candidate_keys,
    )
    assert not verdict.approved
    assert any("raw number" in violation for violation in verdict.violations)


def test_guardrail_rejects_a_message_with_no_way_to_decline(context: ToolContext) -> None:
    verdict = validate_proposal(
        AgentProposal(
            candidate_key="gentle_nudge:indoor_walk",
            message="A gentle indoor walk has been arranged for you this afternoon.",
        ),
        permitted_candidate_keys=context.permitted_candidate_keys,
    )
    assert not verdict.approved
    assert any("decline" in violation for violation in verdict.violations)


@pytest.mark.parametrize("message", ["Too short.", "Walk? " * 200])
def test_guardrail_enforces_length_bounds(context: ToolContext, message: str) -> None:
    verdict = validate_proposal(
        AgentProposal(candidate_key="gentle_nudge:indoor_walk", message=message),
        permitted_candidate_keys=context.permitted_candidate_keys,
    )
    assert not verdict.approved


def test_guardrail_feedback_is_actionable() -> None:
    """A rejection must tell the planner what to fix, or it cannot adapt."""
    verdict = validate_proposal(
        AgentProposal(candidate_key="nope", message="x"),
        permitted_candidate_keys=["gentle_nudge:indoor_walk"],
    )
    feedback = verdict.as_feedback()
    assert feedback.startswith("REJECTED")
    assert "1." in feedback


# --------------------------------------------------------------------------------------
# Guardrail: grounding -- the message may only assert facts the chosen candidate has
#
# Found by live-model probing, 2026-09-09: `gentle_nudge:chair_mobility` is a SOLO, seated
# option. Two of two real runs invented company ("with us"/"joining us"), one dropped "seated"
# for "stretch", and one instructed a reply the senior surface (fixed buttons, no reply channel)
# cannot receive. `guardrails.py` had no rule for any of the three; these pin the fix.
# --------------------------------------------------------------------------------------

_SOLO_SEATED = CandidateOption(
    key="gentle_nudge:chair_mobility",
    title="Five-minute movement option",
    preference_score=0.6,
    social_shape=SocialPreference.SOLO,
    accessibility_terms=("seated",),
)
_SOLO_PLAIN = CandidateOption(
    key="gentle_nudge:indoor_walk",
    title="Gentle movement check-in",
    preference_score=0.5,
    social_shape=SocialPreference.SOLO,
)
_SOCIAL_PROGRAMME = CandidateOption(
    key="programme:p1",
    title="Morning Tai Chi",
    preference_score=0.5,
    social_shape=SocialPreference.SOCIAL,
)


@pytest.mark.parametrize(
    "message",
    [
        # The literal shape of the two real runs the spec reports.
        "Would you like a quick five-minute seated stretch with us today? It's a great way to "
        "get moving with others.",
        "How about joining us for a quick five-minute seated movement session? It's a great way "
        "to move with others.",
        "Would you like to do this together with the group? It is completely optional.",
    ],
)
def test_guardrail_rejects_fabricated_company_for_a_solo_candidate(message: str) -> None:
    verdict = validate_proposal(
        AgentProposal(candidate_key=_SOLO_SEATED.key, message=message),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
    )
    assert not verdict.approved
    assert any("company" in violation for violation in verdict.violations)


def test_guardrail_approves_group_language_for_a_genuinely_social_candidate() -> None:
    """The same phrase is not a violation when it is actually true of the candidate."""
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOCIAL_PROGRAMME.key,
            message="Would you like to join us for Morning Tai Chi this week? No pressure.",
        ),
        permitted_candidate_keys=[_SOCIAL_PROGRAMME.key],
        candidates=[_SOCIAL_PROGRAMME],
    )
    assert verdict.approved, verdict.violations


def test_guardrail_rejects_a_dropped_accessibility_word() -> None:
    """ "Seated" is the fact that makes this candidate the accessible choice; losing it to a
    generic word like "stretch" is exactly the second real defect the spec reports."""
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOLO_SEATED.key,
            message="Would you like a quick five-minute stretch today? Completely optional.",
        ),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
    )
    assert not verdict.approved
    assert any("accessibility" in violation for violation in verdict.violations)


def test_guardrail_approves_when_the_accessibility_word_survives() -> None:
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOLO_SEATED.key,
            message="Would a gentle five-minute seated movement break suit you today? No pressure.",
        ),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
    )
    assert verdict.approved, verdict.violations


def test_guardrail_rejects_an_instruction_to_reply() -> None:
    """The senior surface shows fixed buttons; there is no reply channel to instruct toward."""
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOLO_PLAIN.key,
            message=(
                "Would a short indoor walk feel manageable today? Just reply 'not today' if "
                "now isn't the time."
            ),
        ),
        permitted_candidate_keys=[_SOLO_PLAIN.key],
        candidates=[_SOLO_PLAIN],
    )
    assert not verdict.approved
    assert any("reply channel" in violation for violation in verdict.violations)


def test_guardrail_rejects_an_emoji() -> None:
    message = "Would a short indoor walk feel manageable today? No pressure at all. \U0001f60a"
    verdict = validate_proposal(
        AgentProposal(candidate_key=_SOLO_PLAIN.key, message=message),
        permitted_candidate_keys=[_SOLO_PLAIN.key],
        candidates=[_SOLO_PLAIN],
    )
    assert not verdict.approved
    assert any("emoji" in violation for violation in verdict.violations)


def test_grounding_checks_are_skipped_without_candidate_attributes() -> None:
    """`candidates` is optional so guardrail unit tests that only exercise the fixed-vocabulary
    rules above are not required to also supply candidate metadata -- see the docstring on
    `validate_proposal`. The real planner call site always supplies it (`plan_outreach`).
    """
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOLO_SEATED.key,
            message="Would you like to join us for a walk together? No pressure.",
        ),
        permitted_candidate_keys=[_SOLO_SEATED.key],
    )
    assert verdict.approved, verdict.violations


# --------------------------------------------------------------------------------------
# Guardrail: prior experience -- the rule that could never be satisfied
#
# `_accepted_before` compared the CANDIDATE KEY against the history entry's `title`, and
# `HistoryEntry` had no key to compare instead. A title is a display string
# ("Five-minute movement option"); a key is `gentle_nudge:chair_mobility`. They are never
# equal, so the rule rejected every message mentioning a past experience even when the person
# really had accepted that exact option -- and the system prompt promises the opposite. Every
# false rejection costs a round trip and pushes the run toward `fallback_exhausted`, which then
# reads as "the agent could not do it".
#
# The `key is None` branch was the intended cover for this and was dead: `title` is always set,
# so `key` was never `None`. Dropping it also closes a real over-permission -- had it ever been
# reachable, ANY accepted entry would have licensed a prior-experience claim about ANY candidate.
# --------------------------------------------------------------------------------------

_PRIOR_EXPERIENCE_MESSAGE = (
    "Would you like the seated movement option you enjoyed before? No pressure."
)


def _history(**overrides: Any) -> HistoryEntry:
    fields: dict[str, Any] = {
        "created_at": "2026-09-01T12:00:00+00:00",
        "decision": "gentle_nudge",
        "title": _SOLO_SEATED.title,
        "outcome": "accepted",
        "candidate_key": _SOLO_SEATED.key,
    }
    fields.update(overrides)
    return HistoryEntry(**fields)


def test_guardrail_allows_a_prior_experience_claim_the_history_actually_supports() -> None:
    """The rule's own stated purpose, which it had never once been able to serve."""
    verdict = validate_proposal(
        AgentProposal(candidate_key=_SOLO_SEATED.key, message=_PRIOR_EXPERIENCE_MESSAGE),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
        history=[_history()],
    )

    assert verdict.approved, verdict.violations


def test_guardrail_still_rejects_a_prior_experience_claim_with_no_accepted_outcome() -> None:
    """The false-claim case the rule exists for: offered twice, never answered."""
    verdict = validate_proposal(
        AgentProposal(candidate_key=_SOLO_SEATED.key, message=_PRIOR_EXPERIENCE_MESSAGE),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
        history=[_history(outcome=None), _history(outcome="declined")],
    )

    assert not verdict.approved
    assert any("tried this before" in violation for violation in verdict.violations)


def test_an_acceptance_of_a_different_candidate_does_not_license_the_claim() -> None:
    """Matching on the key rather than on "some accepted entry exists" is the point: a person
    who accepted an indoor walk has said nothing about the chair-mobility option."""
    verdict = validate_proposal(
        AgentProposal(candidate_key=_SOLO_SEATED.key, message=_PRIOR_EXPERIENCE_MESSAGE),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
        history=[_history(candidate_key=_SOLO_PLAIN.key, title=_SOLO_PLAIN.title)],
    )

    assert not verdict.approved
    assert any("tried this before" in violation for violation in verdict.violations)


def test_a_history_entry_with_no_key_recorded_cannot_license_the_claim() -> None:
    """An entry whose evidence carries no `candidate_key` (older rows) is an entry we cannot
    attribute. It must fail closed, not stand in for every candidate at once."""
    verdict = validate_proposal(
        AgentProposal(candidate_key=_SOLO_SEATED.key, message=_PRIOR_EXPERIENCE_MESSAGE),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
        history=[_history(candidate_key=None)],
    )

    assert not verdict.approved
    assert any("tried this before" in violation for violation in verdict.violations)


def test_the_prior_experience_phrases_are_matched_on_word_boundaries() -> None:
    """ "again" was substring-matched while every other rule anchored at `\\b`, so "lean against
    the rail" -- an accessibility instruction, not a claim about the past -- was rejected as one.
    """
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOLO_PLAIN.key,
            message=(
                "Would a short indoor walk suit you today? There is a rail to lean against "
                "along the corridor. No pressure."
            ),
        ),
        permitted_candidate_keys=[_SOLO_PLAIN.key],
        candidates=[_SOLO_PLAIN],
        history=[],
    )

    assert verdict.approved, verdict.violations


def test_a_real_again_is_still_a_prior_experience_claim() -> None:
    """The word-boundary fix must not have turned the rule off."""
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOLO_PLAIN.key,
            message="Would you like to try a short indoor walk again today? No pressure.",
        ),
        permitted_candidate_keys=[_SOLO_PLAIN.key],
        candidates=[_SOLO_PLAIN],
        history=[],
    )

    assert not verdict.approved
    assert any("again" in violation for violation in verdict.violations)


def test_the_prior_experience_fix_loosens_nothing_else() -> None:
    """A supported prior-experience claim still has to pass every other rule. A real acceptance
    is not a licence to invent company for a solo option, drop an accessibility word, apply
    pressure or instruct a reply."""
    supported = [_history()]
    for message, expected in (
        (
            "You enjoyed this seated option before -- join us again today? No pressure.",
            "company",
        ),
        ("You enjoyed that stretch before. Shall we do it again? No pressure.", "accessibility"),
        (
            "You enjoyed this seated option before, so you must do it again right now.",
            "pressure",
        ),
        (
            "You enjoyed this seated option before. Reply 'yes' to do it again, no pressure.",
            "reply channel",
        ),
    ):
        verdict = validate_proposal(
            AgentProposal(candidate_key=_SOLO_SEATED.key, message=message),
            permitted_candidate_keys=[_SOLO_SEATED.key],
            candidates=[_SOLO_SEATED],
            history=supported,
        )
        assert not verdict.approved, message
        assert any(expected in violation for violation in verdict.violations), (message, verdict)


# --------------------------------------------------------------------------------------
# Guardrail: the rules match what the person will READ, not the bytes that carry it
#
# Every rule above matches a vocabulary against the message. None of them normalised it, so the
# whole list was defeated by characters a screen does not render: a zero-width space inside
# "do<ZWSP>ctor", a soft hyphen inside "do<SHY>ctor", or a U+043E Cyrillic small o in "d<o>ctor".
# All three reach the senior reading exactly "doctor" and passed every check.
#
# The fix is `guardrails.fold_for_rules`: NFKC, then drop the default-ignorable and control code
# points, then fold a bounded, named list of Latin confusables. It is applied to the message
# before every rule, including the `must_preserve_words` sentinel check, and to both a
# separator-preserving and a separator-joining form so neither "heart rate" split across a
# newline nor "do<LF>ctor" can slip between them.
# --------------------------------------------------------------------------------------

_ZERO_WIDTH_SPACE = "\u200b"
_ZERO_WIDTH_JOINER = "\u200d"
_SOFT_HYPHEN = "\u00ad"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        pytest.param(
            f"Your do{_ZERO_WIDTH_SPACE}ctor asked about the seated class. No pressure.",
            "clinical",
            id="zero-width-space-split",
        ),
        pytest.param(
            f"Your do{_ZERO_WIDTH_JOINER}ctor asked about the seated class. No pressure.",
            "clinical",
            id="zero-width-joiner-split",
        ),
        pytest.param(
            f"Your do{_SOFT_HYPHEN}ctor asked about the seated class. No pressure.",
            "clinical",
            id="soft-hyphen-split",
        ),
        pytest.param(
            "Your d\u043ector asked about the seated class. No pressure.",
            "clinical",
            id="cyrillic-o-homoglyph",
        ),
        pytest.param(
            "Your \u0455ymptoms matter. Seated class, no pressure.",
            "clinical",
            id="cyrillic-dze-homoglyph",
        ),
        pytest.param(
            "Your \u03b1mbulance is on the way. Seated class, no pressure.",
            "clinical",
            id="greek-alpha-homoglyph",
        ),
        pytest.param(
            f"Your daught{_ZERO_WIDTH_SPACE}er asked about the seated class. No pressure.",
            "someone other than the senior",
            id="third-party-zero-width",
        ),
        pytest.param(
            "Your d\u0430ughter asked about the seated class. No pressure.",
            "someone other than the senior",
            id="third-party-homoglyph",
        ),
        pytest.param(
            f"You mu{_ZERO_WIDTH_SPACE}st attend the seated class. No pressure.",
            "applies pressure",
            id="pressure-zero-width",
        ),
        pytest.param(
            f"We have bo{_ZERO_WIDTH_SPACE}oked you into the seated class. No pressure.",
            "action has been taken",
            id="asserted-action-zero-width",
        ),
        pytest.param(
            f"Your do\nct{_ZERO_WIDTH_SPACE}or asked about the seated class. No pressure.",
            "clinical",
            id="newline-split",
        ),
    ],
)
def test_invisible_and_confusable_characters_do_not_defeat_a_guardrail_rule(
    message: str, expected: str
) -> None:
    verdict = validate_proposal(
        AgentProposal(candidate_key=_SOLO_SEATED.key, message=message),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
    )
    assert not verdict.approved, message
    assert any(expected in violation for violation in verdict.violations), (message, verdict)


def test_normalisation_does_not_split_a_multi_word_phrase_across_a_line_break() -> None:
    """The separator-preserving form exists for this: deleting every control character outright
    would turn "heart rate" wrapped across a newline into "heartrate" and lose the match."""
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOLO_SEATED.key,
            message="We noticed your heart\nrate. Seated class, no pressure.",
        ),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
    )
    assert not verdict.approved
    assert any("clinical" in violation for violation in verdict.violations)


def test_zero_width_padding_cannot_reach_the_minimum_message_length() -> None:
    """Length is measured on what the person reads. Padding a two-word message out to the
    minimum with invisible characters is an empty message with a long byte count."""
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOLO_SEATED.key,
            message="Seated?" + _ZERO_WIDTH_SPACE * MIN_MESSAGE_CHARS,
        ),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
    )
    assert not verdict.approved
    assert any("at least" in violation for violation in verdict.violations)


def test_the_must_preserve_sentinel_survives_an_invisible_split() -> None:
    """The other direction of the same rule. "se<ZWSP>ated" renders as "seated" on the card, so
    the accessibility word IS preserved and the message must not be rejected for dropping it."""
    verdict = validate_proposal(
        AgentProposal(
            candidate_key=_SOLO_SEATED.key,
            message=(
                f"Would a five-minute se{_ZERO_WIDTH_SPACE}ated movement option suit you today? "
                "No pressure."
            ),
        ),
        permitted_candidate_keys=[_SOLO_SEATED.key],
        candidates=[_SOLO_SEATED],
    )
    assert verdict.approved, verdict.violations


def test_a_clean_message_is_unchanged_by_normalisation() -> None:
    """Plain ASCII copy has to fold to itself, or every rule above is measuring something else."""
    clean = "Would a five-minute seated movement option suit you today? No pressure."
    assert fold_for_rules(clean) == clean
    assert fold_for_rules(clean, join_across_controls=True) == clean


# --------------------------------------------------------------------------------------
# Tool surface
# --------------------------------------------------------------------------------------


def test_every_tool_is_strict_and_closed() -> None:
    """Strict schemas with no extra properties are what keep argument validation at 100%."""
    for tool in tool_definitions():
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False
        assert "required" in tool["input_schema"]


def test_read_tools_return_small_typed_payloads(context: ToolContext) -> None:
    payload, summary, ok = execute_read_tool("get_candidate_options", context)
    assert ok
    assert "gentle_nudge:indoor_walk" in payload
    assert summary == "Returned 2 permitted candidate(s)."

    payload, _, ok = execute_read_tool("list_programme_options", context)
    assert ok
    assert "Morning Tai Chi" in payload

    payload, _, ok = execute_read_tool("get_outreach_history", context)
    assert ok
    assert "declined" in payload


def test_unknown_tool_is_reported_as_a_failed_call(context: ToolContext) -> None:
    _, summary, ok = execute_read_tool("delete_everything", context)
    assert not ok
    assert "Unknown tool" in summary


# --------------------------------------------------------------------------------------
# The loop: plan, act, adapt
# --------------------------------------------------------------------------------------


def test_planner_selects_a_candidate_and_records_evidence(context: ToolContext) -> None:
    result = run(
        context,
        [
            FakeResponse([FakeBlock("tu1", "get_candidate_options", {})]),
            FakeResponse([propose_block("gentle_nudge:chair_mobility", GOOD_MESSAGE)]),
        ],
    )
    assert result.mode == "agent"
    assert result.used_agent
    assert result.selected_candidate_key == "gentle_nudge:chair_mobility"
    assert result.selected_message == GOOD_MESSAGE
    assert result.iterations == 2
    assert result.tool_call_success_rate == 1.0
    assert result.usage.total_tokens > 0
    assert "planner" in result.trace_detail().lower()


def test_planner_adapts_after_a_guardrail_rejection(context: ToolContext) -> None:
    """The heart of the loop: a rejection is fed back and the planner revises."""
    result = run(
        context,
        [
            # First attempt breaks the no-clinical-language rule.
            FakeResponse(
                [
                    propose_block(
                        "gentle_nudge:indoor_walk",
                        "Your symptoms concern us. Would you like a walk today?",
                        block_id="tu_bad",
                    )
                ]
            ),
            # Having been told exactly what was wrong, it fixes the wording.
            FakeResponse([propose_block("gentle_nudge:indoor_walk", GOOD_MESSAGE)]),
        ],
    )
    assert result.mode == "agent"
    assert result.iterations == 2
    assert result.guardrail_rejections, "the rejection must be preserved in the audit record"
    assert result.selected_message == GOOD_MESSAGE
    assert "revision" in result.trace_detail()


def test_rejected_proposal_never_becomes_the_selected_message(context: ToolContext) -> None:
    """A message the gate refused must not survive anywhere in the result."""
    banned = "Your symptoms concern us. Would you like a walk today?"
    result = run(
        context,
        [
            FakeResponse([propose_block("gentle_nudge:indoor_walk", banned, block_id="tu_bad")]),
            FakeResponse([propose_block("gentle_nudge:indoor_walk", GOOD_MESSAGE)]),
        ],
    )
    assert result.selected_message != banned


def test_planner_cannot_escalate_to_an_unpermitted_action(context: ToolContext) -> None:
    """The model asking for a different action class gets rejected, then falls back."""
    escalation = propose_block("coordinator_review:call_family", GOOD_MESSAGE)
    result = run(context, [FakeResponse([escalation])] * 4)
    assert result.mode == "fallback_exhausted"
    assert result.selected_candidate_key == FALLBACK[0]
    assert result.selected_message == FALLBACK[1]
    assert len(result.guardrail_rejections) == 4


def test_iteration_cap_is_enforced_by_the_loop_not_the_model(context: ToolContext) -> None:
    """The model keeps asking for tools forever; Python stops it at the cap."""
    forever = [FakeResponse([FakeBlock("tu1", "get_candidate_options", {})])] * 20
    result = run(context, forever, llm_max_iterations=3)
    assert result.mode == "fallback_exhausted"
    assert result.iterations == 3
    assert result.max_iterations == 3
    assert result.selected_candidate_key == FALLBACK[0]


def test_iteration_cap_is_clamped_to_the_hard_ceiling() -> None:
    """A mis-set environment variable cannot unbound the loop."""
    assert PlannerState(9999).max_iterations == ITERATION_HARD_CEILING
    assert PlannerState(0).max_iterations == 1


# --------------------------------------------------------------------------------------
# Degradation: every failure path returns the deterministic answer
# --------------------------------------------------------------------------------------


def test_disabled_flag_uses_the_deterministic_ranker(context: ToolContext) -> None:
    """`LLM_ENABLED=false` is the offline demo path and must never reach a client."""
    result = plan_outreach(
        context,
        settings=settings_with(llm_enabled=False),
        fallback_choice=FALLBACK,
        client_factory=lambda: pytest.fail("the planner must not build a client when disabled"),
    )
    assert result.mode == "fallback_disabled"
    assert result.selected_candidate_key == FALLBACK[0]
    assert result.selected_message == FALLBACK[1]
    assert result.iterations == 0
    assert result.model is None


def test_unavailable_client_falls_back_with_a_stated_reason(context: ToolContext) -> None:
    result = plan_outreach(
        context,
        settings=settings_with(),
        fallback_choice=FALLBACK,
        client_factory=lambda: (None, "The anthropic SDK is not installed."),
    )
    assert result.mode == "fallback_disabled"
    assert result.fallback_reason == "The anthropic SDK is not installed."


def test_provider_error_falls_back(context: ToolContext) -> None:
    """The audit record names the exception's class and nothing else -- a provider message can
    carry request ids or part of a credential, and `fallback_reason` is an operator surface.
    The text itself goes to the agent log; see `test_agent_integration.py`."""
    result = run(context, [RuntimeError("connection reset")])
    assert result.mode == "fallback_error"
    assert result.fallback_reason == "RuntimeError"
    assert "connection reset" not in (result.fallback_reason or "")
    assert result.selected_candidate_key == FALLBACK[0]


def test_model_refusal_falls_back(context: ToolContext) -> None:
    """A safety refusal arrives as a normal 200 response and must be checked, not indexed."""
    result = run(context, [FakeResponse(content=[], stop_reason="refusal")])
    assert result.mode == "fallback_error"
    assert "refusal" in (result.fallback_reason or "")


def test_turn_without_a_proposal_falls_back(context: ToolContext) -> None:
    result = run(context, [FakeResponse(content=[], stop_reason="end_turn")])
    assert result.mode == "fallback_no_proposal"
    assert result.selected_candidate_key == FALLBACK[0]


# --------------------------------------------------------------------------------------
# Malformed provider responses
#
# Everything the provider returns is untrusted *structure* until proven otherwise. These four
# shapes are exactly the ones `test_activity_planner.py` pins for `plan_activity_ranking`; the
# outreach loop used to raise `TypeError` / `AttributeError` / `ValueError` on each, which
# `_plan_outreach_safely` then caught -- losing the partial trace and the tokens already spent.
# --------------------------------------------------------------------------------------


@dataclass
class MalformedBlock:
    """A content block with no `type`, which the SDK always promises."""

    id: str = "tu_malformed"
    name: str = "get_candidate_options"
    input: dict[str, Any] = field(default_factory=dict)


def test_a_response_with_no_content_degrades_instead_of_raising(context: ToolContext) -> None:
    result = run(context, [FakeResponse(content=None)])  # type: ignore[arg-type]
    assert result.mode == "fallback_error"
    assert result.fallback_reason == "MalformedResponse"
    assert result.selected_candidate_key == FALLBACK[0]


def test_a_response_whose_content_is_not_a_list_degrades_instead_of_raising(
    context: ToolContext,
) -> None:
    result = run(context, [FakeResponse(content={"text": "hello"})])  # type: ignore[arg-type]
    assert result.mode == "fallback_error"
    assert result.fallback_reason == "MalformedResponse"
    assert result.selected_candidate_key == FALLBACK[0]


def test_a_block_without_a_type_is_not_a_tool_use(context: ToolContext) -> None:
    """A block missing `type` is not a `tool_use` block, so this turn simply produced no
    proposal -- the same reading `plan_activity_ranking` takes."""
    result = run(context, [FakeResponse(content=[MalformedBlock()])])
    assert result.mode == "fallback_no_proposal"
    assert result.selected_candidate_key == FALLBACK[0]


def test_a_tool_use_whose_input_is_not_a_dict_degrades_instead_of_raising(
    context: ToolContext,
) -> None:
    """`dict(block.input or {})` raised `ValueError` on a string. Treating a non-dict input as
    no arguments at all lets the guardrail rule on the empty proposal and the loop carry on."""
    bad = FakeBlock(id="tu1", name="propose_outreach", input="ordered_keys=everything")  # type: ignore[arg-type]
    result = run(context, [FakeResponse(content=[bad])] * 4)
    assert result.mode == "fallback_exhausted"
    assert result.selected_candidate_key == FALLBACK[0]
    assert result.guardrail_rejections, "the empty proposal must be rejected, not accepted"


def test_a_malformed_turn_keeps_the_trace_and_token_spend_of_the_turns_before_it(
    context: ToolContext,
) -> None:
    """The whole point of degrading inside the loop rather than raising out of it: the run that
    failed still reports what it did and what it cost."""
    result = run(
        context,
        [
            FakeResponse(content=[FakeBlock("tu1", "get_candidate_options", {})]),
            FakeResponse(content=None),  # type: ignore[arg-type]
        ],
    )
    assert result.mode == "fallback_error"
    assert result.fallback_reason == "MalformedResponse"
    assert result.iterations == 2
    assert [call.tool_name for call in result.tool_calls] == ["get_candidate_options"]
    # Two responses were consumed, and both carried usage.
    assert result.usage.input_tokens == 200
    assert result.usage.output_tokens == 100


def test_empty_candidate_list_falls_back_without_calling_the_model() -> None:
    empty = ToolContext(
        decision=Decision.GENTLE_NUDGE,
        display_name="Mdm Lim",
        preferred_language="English",
        context_note=None,
        delta_percent=-10.0,
        sustained_low_days=1,
        confidence=0.9,
        rainy=False,
        holiday=False,
        candidates=[],
    )
    result = plan_outreach(
        empty,
        settings=settings_with(),
        fallback_choice=FALLBACK,
        client_factory=lambda: pytest.fail("no candidates means no reason to call the model"),
    )
    assert result.mode == "fallback_disabled"


# --------------------------------------------------------------------------------------
# Request shape and audit record
# --------------------------------------------------------------------------------------


def test_request_is_cacheable_and_bounded(context: ToolContext) -> None:
    """System prompt and tool list form a stable cached prefix on every iteration."""
    client = FakeClient(
        [
            FakeResponse([FakeBlock("tu1", "get_candidate_options", {})]),
            FakeResponse([propose_block("gentle_nudge:indoor_walk", GOOD_MESSAGE)]),
        ]
    )
    plan_outreach(
        context,
        settings=settings_with(),
        fallback_choice=FALLBACK,
        client_factory=lambda: (client, None),
    )
    first, second = client.messages.calls
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["system"] == second["system"], "the cached prefix must not change between turns"
    assert first["tools"] == second["tools"], "reordering tools would invalidate the cache"
    assert first["model"] == "claude-opus-5"
    assert first["thinking"] == {"type": "adaptive"}
    assert first["max_tokens"] > 0


def test_evidence_record_is_complete_and_states_the_boundary(context: ToolContext) -> None:
    result = run(
        context,
        [
            FakeResponse([FakeBlock("tu1", "get_candidate_options", {})]),
            FakeResponse([propose_block("gentle_nudge:indoor_walk", GOOD_MESSAGE)]),
        ],
    )
    evidence = result.as_evidence()
    for key in (
        "agent_evidence_id",
        "agent_version",
        "mode",
        "model",
        "started_at",
        "iterations",
        "max_iterations",
        "tool_calls",
        "tool_call_success_rate",
        "guardrail_violation_count",
        "rejected_proposal_count",
        "usage",
        "total_tokens",
        "trace_detail",
        "boundary",
    ):
        assert key in evidence, f"{key} missing from the audit record"
    assert "cannot change consent" in evidence["boundary"]


def test_brief_never_leaks_raw_numbers_into_the_message(context: ToolContext) -> None:
    """The planner sees the figures but is told they must not appear in the copy."""
    from silverloop.agent.planner import _brief

    brief = _brief(context)
    assert "must never appear in the message" in brief
    assert "Mdm Lim" in brief


def test_the_brief_calls_the_persistence_count_what_it_counts(context: ToolContext) -> None:
    """`analytics._sustained_low_days` walks backwards over days that passed the wear-time gate
    and skips the rest, so the number is a run of READABLE days, not of calendar ones. The brief
    described it as "lower day(s)", which overstates how much evidence sits behind the figure;
    the coordinator-facing case summary already says "valid-wear day(s)", and one number
    described two ways to two audiences has to be described the same way."""
    from silverloop.agent.planner import _brief

    brief = _brief(context)
    assert f"{context.sustained_low_days} lower valid-wear day(s)" in brief
    assert f"{context.sustained_low_days} lower day(s)" not in brief


def test_the_brief_names_where_the_weather_came_from(context: ToolContext) -> None:
    """Simulated rain keeps the recorded wording; live rain says it is a current NEA reading; an
    unavailable live lookup tells the planner to assume nothing about the weather."""
    from dataclasses import replace

    from silverloop.agent.planner import _brief

    simulated = _brief(replace(context, rainy=True))
    assert "it is raining" in simulated
    assert "live NEA reading" not in simulated

    live = _brief(replace(context, rainy=True, weather_source="live"))
    assert "it is raining (a current live NEA reading)" in live

    unavailable = _brief(replace(context, rainy=False, weather_source="unavailable"))
    assert "live weather is unavailable, so assume nothing about it" in unavailable
    assert "it is raining" not in unavailable

    dry = _brief(context)
    assert "raining" not in dry and "live weather" not in dry


def test_the_brief_describes_the_profile_note_as_the_fixture_text_it_is(
    context: ToolContext,
) -> None:
    """`context_note` is a persona biography from `fixtures.py` -- `world_model.py` labels it
    `FIXTURE` and the Privacy page shows it as such. Telling the model the same string was
    "written by a coordinator" gave one piece of text two provenances, and attributed synthetic
    copy to a named role: Mr Ravi's note reads "has disclosed knee discomfort", which as a
    coordinator's observation is a health disclosure about a real person and is not one.
    """
    from silverloop.agent.planner import SYSTEM_PROMPT, _brief

    brief = _brief(context)
    assert "written by a coordinator" not in brief
    assert "coordinator" not in brief.lower()
    assert "synthetic" in brief.lower() and "fixture" in brief.lower()
    assert "not this person's own words" in brief
    # The system prompt must not restate the note as established fact either.
    assert "is a fact about that person" not in SYSTEM_PROMPT


# ── Provider selection: Amazon Bedrock ────────────────────────────────────────────────────
# Both providers expose the identical Messages surface, so these tests assert only the two
# things that actually differ -- which client class is constructed, and which model id is
# pinned. Everything downstream (the loop, the guardrail, every degradation path) is covered by
# the tests above and is provider-agnostic by construction.


def test_bedrock_provider_builds_the_mantle_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """`AnthropicBedrockMantle`, not the legacy `AnthropicBedrock` InvokeModel client."""
    captured: dict[str, Any] = {}

    class FakeMantle:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    module = types.SimpleNamespace(AnthropicBedrockMantle=FakeMantle, Anthropic=object)
    monkeypatch.setitem(sys.modules, "anthropic", module)

    client, reason = planner._build_client(
        settings_with(llm_provider="bedrock", llm_aws_region="ap-southeast-1", llm_api_key=""),
        timeout=20.0,
    )

    assert reason is None
    assert isinstance(client, FakeMantle)
    assert captured["aws_region"] == "ap-southeast-1"
    assert captured["max_retries"] == 1


def test_bedrock_without_a_region_defers_to_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank region is not an error: AWS_REGION or an active profile may still resolve it."""
    captured: dict[str, Any] = {}

    class FakeMantle:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    module = types.SimpleNamespace(AnthropicBedrockMantle=FakeMantle, Anthropic=object)
    monkeypatch.setitem(sys.modules, "anthropic", module)

    client, reason = planner._build_client(
        settings_with(llm_provider="bedrock", llm_aws_region="", llm_api_key=""),
        timeout=20.0,
    )

    assert reason is None
    assert isinstance(client, FakeMantle)
    assert "aws_region" not in captured


def test_bedrock_degrades_when_the_sdk_has_no_mantle_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An SDK too old to serve Bedrock must fall back, never raise into application start-up."""
    module = types.SimpleNamespace(Anthropic=object)
    monkeypatch.setitem(sys.modules, "anthropic", module)

    client, reason = planner._build_client(
        settings_with(llm_provider="bedrock", llm_aws_region="us-east-1", llm_api_key=""),
        timeout=20.0,
    )

    assert client is None
    assert reason is not None
    assert "AnthropicBedrockMantle" in reason


def test_bedrock_client_construction_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    class ExplodingMantle:
        def __init__(self, **kwargs: Any) -> None:
            raise RuntimeError("no credentials")

    module = types.SimpleNamespace(AnthropicBedrockMantle=ExplodingMantle, Anthropic=object)
    monkeypatch.setitem(sys.modules, "anthropic", module)

    client, reason = planner._build_client(
        settings_with(llm_provider="bedrock", llm_aws_region="us-east-1", llm_api_key=""),
        timeout=20.0,
    )

    assert client is None
    assert reason is not None
    assert "Bedrock client" in reason


def test_model_ids_are_pinned_per_provider() -> None:
    """Bedrock ids carry an `anthropic.` prefix and are written out, never derived by surgery."""
    assert constants.default_model_id("anthropic") == constants.DEFAULT_MODEL_ID
    assert constants.default_model_id("bedrock") == constants.BEDROCK_DEFAULT_MODEL_ID
    assert constants.BEDROCK_DEFAULT_MODEL_ID.startswith("anthropic.")
    # An unrecognised provider must not produce an empty or invented id.
    assert constants.default_model_id("something-else") == constants.DEFAULT_MODEL_ID


# ── Guardrail: bypasses found by adversarial probing, 2026-09-05 ──────────────────────────
# Each string below was APPROVED by the guardrail before these rules existed. They are kept
# verbatim as regression pins: the copy rules are the security boundary, so a rule that silently
# stops matching is the failure mode that matters most.

_PERMITTED = {"gentle_nudge:indoor_walk"}


def _verdict(message: str):
    return validate_proposal(
        AgentProposal(candidate_key="gentle_nudge:indoor_walk", message=message, reasoning="probe"),
        permitted_candidate_keys=_PERMITTED,
    )


@pytest.mark.parametrize(
    "message",
    [
        # Unconsented caregiver contact -- a named product boundary with no rule behind it.
        "You have not moved much in three days. Shall I ask your daughter to check on you?",
        "Your carer has been informed. Would you like to join the walking group?",
        "A caregiver will call you tomorrow. Fancy a short walk? No pressure.",
        # Coercion the fixed phrase list did not cover.
        "Please respond today or a coordinator will visit. Would you like a walk?",
    ],
)
def test_guardrail_rejects_probed_bypasses(message: str) -> None:
    assert _verdict(message).approved is False


@pytest.mark.parametrize(
    "message",
    [
        # "nursery" is not "nurse"; "no booking required" is reassurance, not pressure. Both
        # were rejected by substring matching.
        "Would you like to join the nursery garden group? No pressure.",
        "Join the sheltered walk, no booking required. Completely optional.",
        # Copy the product actually wants to send.
        "Would a gentle five-minute seated stretch feel manageable today? Completely optional.",
        "Would you like to join the walking group this week? No pressure.",
    ],
)
def test_guardrail_approves_legitimate_copy(message: str) -> None:
    verdict = _verdict(message)
    assert verdict.approved is True, verdict.violations


@pytest.mark.parametrize(
    "message",
    [
        "Your symptoms suggest you should see a doctor. Would you like a walk?",
        "This could mean your condition is deteriorating. Fancy a walk? No pressure.",
        "Our fall detection noticed something. Would you like a walk?",
        "Your diagnosis suggests rest. Would you like a walk?",
    ],
)
def test_guardrail_still_rejects_clinical_language_and_its_inflections(message: str) -> None:
    """Whole-word matching must not weaken the clinical rule -- stems keep matching suffixes."""
    assert _verdict(message).approved is False


def test_bedrock_passes_explicit_credentials_including_a_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temporary STS credentials must reach the client; `.env` never exports them itself."""
    captured: dict[str, Any] = {}

    class FakeMantle:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    module = types.SimpleNamespace(AnthropicBedrockMantle=FakeMantle, Anthropic=object)
    monkeypatch.setitem(sys.modules, "anthropic", module)

    client, reason = planner._build_client(
        settings_with(
            llm_provider="bedrock",
            llm_aws_region="ap-southeast-1",
            llm_aws_access_key_id="AKIAEXAMPLE",
            llm_aws_secret_access_key="secret",
            llm_aws_session_token="session",
            llm_api_key="",
        ),
        timeout=20.0,
    )

    assert reason is None
    assert isinstance(client, FakeMantle)
    assert captured["aws_access_key"] == "AKIAEXAMPLE"
    assert captured["aws_secret_key"] == "secret"
    assert captured["aws_session_token"] == "session"


def test_bedrock_refuses_half_a_credential_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    """Half a pair would silently fall through to the ambient chain as a different identity."""
    module = types.SimpleNamespace(AnthropicBedrockMantle=object, Anthropic=object)
    monkeypatch.setitem(sys.modules, "anthropic", module)

    client, reason = planner._build_client(
        settings_with(
            llm_provider="bedrock",
            llm_aws_region="ap-southeast-1",
            llm_aws_access_key_id="AKIAEXAMPLE",
            llm_aws_secret_access_key="",
            llm_api_key="",
        ),
        timeout=20.0,
    )

    assert client is None
    assert reason is not None
    assert "incomplete" in reason


# --------------------------------------------------------------------------------------
# Activity ranking: which provider and transport a run used
#
# An evaluator reading a ranking run must never infer from the environment whether the order came
# from a live model or a replayed recording. `provider`/`transport` are stated on the run whenever
# a client was requested, and absent when none was.
# --------------------------------------------------------------------------------------


def _activity_context(count: int) -> ActivityRankingContext:
    return ActivityRankingContext(
        understood_lines=["Anything that suits you"],
        options=[
            ActivityOption(
                key=f"activity-{index}",
                title=f"Activity {index}",
                category="movement",
                distance_m=500,
                environment="indoor",
                intensity="light",
                time_window="morning",
                deterministic_rank=index,
                reasons=["Matches what you asked for"],
            )
            for index in range(count)
        ],
    )


def _activity_proposal(keys: list[str]) -> FakeBlock:
    return FakeBlock(
        id="tu_propose",
        name="propose_activity_order",
        input={"ordered_keys": keys, "reasoning": "Because."},
    )


def test_an_approved_activity_run_states_a_live_provider() -> None:
    context = _activity_context(2)
    order = [option.key for option in context.options]
    result = plan_activity_ranking(
        context,
        settings=settings_with(llm_provider="anthropic"),
        fallback_order=order,
        client_factory=lambda: (FakeClient([FakeResponse([_activity_proposal(order)])]), None),
    )
    assert result.mode == "agent"
    assert (result.provider, result.transport) == ("anthropic", "live")
    evidence = result.as_evidence()
    assert (evidence["provider"], evidence["transport"]) == ("anthropic", "live")


def test_a_bedrock_activity_run_is_live_too() -> None:
    context = _activity_context(2)
    result = plan_activity_ranking(
        context,
        settings=settings_with(llm_provider="bedrock"),
        fallback_order=[option.key for option in context.options],
        client_factory=lambda: (FakeClient([RuntimeError("boom")]), None),
    )
    assert result.mode == "fallback_error"
    assert (result.provider, result.transport) == ("bedrock", "live")


def test_a_recorded_activity_run_states_the_recorded_transport_even_when_unavailable() -> None:
    """A client was requested and turned out unavailable: the run still says what was asked
    for, so a missing recording is never mistaken for a disabled planner."""
    context = _activity_context(2)
    result = plan_activity_ranking(
        context,
        settings=settings_with(llm_provider="recorded"),
        fallback_order=[option.key for option in context.options],
        client_factory=lambda: (None, "LLM_PROVIDER=recorded requires LLM_RECORDING_PATH."),
    )
    assert result.mode == "fallback_disabled"
    assert (result.provider, result.transport) == ("recorded", "recorded")
    evidence = result.as_evidence()
    assert (evidence["provider"], evidence["transport"]) == ("recorded", "recorded")


@pytest.mark.parametrize(
    ("overrides", "count"),
    [({"llm_enabled": False, "llm_provider": "recorded"}, 2), ({"llm_provider": "recorded"}, 0)],
    ids=["planner_disabled", "nothing_to_rank"],
)
def test_an_activity_run_that_never_requested_a_client_names_no_provider(
    overrides: dict[str, Any], count: int
) -> None:
    context = _activity_context(count)
    result = plan_activity_ranking(
        context,
        settings=settings_with(**overrides),
        fallback_order=[option.key for option in context.options],
        client_factory=lambda: pytest.fail("no client may be requested here"),
    )
    assert result.mode == "fallback_disabled"
    assert result.provider is None
    assert result.transport is None
    evidence = result.as_evidence()
    assert "provider" in evidence and evidence["provider"] is None
    assert "transport" in evidence and evidence["transport"] is None


# --------------------------------------------------------------------------------------
# Activity ranking prompt: claims the deterministic layer actually keeps
# --------------------------------------------------------------------------------------


def test_the_activity_prompt_claims_only_the_distance_filter_that_exists() -> None:
    """The filter removes a listing only beyond a distance the person gave as a number; a
    learned "too far" moves the order, it removes nothing. Telling the model otherwise invited it
    to assume every far option was already gone."""
    prompt = planner.SYSTEM_PROMPT_ACTIVITY
    assert "removed anything too far" not in prompt
    assert "beyond a distance the person gave as a number" in " ".join(prompt.split())
    assert "nearer options are already favoured" in " ".join(prompt.split())


@pytest.mark.parametrize(("count", "returned"), [(3, 3), (10, 10), (14, 10)])
def test_the_activity_brief_says_how_many_options_the_model_will_see(
    count: int, returned: int
) -> None:
    from silverloop.agent.planner import _activity_brief

    brief = _activity_brief(_activity_context(count))
    assert f"{count} option(s) passed the deterministic filter" in brief
    assert f"get_activity_options returns the first {returned}" in brief
    assert "anything after those keeps its default place" in brief
    assert returned == min(count, constants.MAX_ACTIVITY_OPTIONS_RETURNED)
