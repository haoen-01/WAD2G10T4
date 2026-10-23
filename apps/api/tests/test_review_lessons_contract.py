"""`review_lessons.classify_review` precedence and wording (docs/calibration-trust-spec.md, A).

A2 extends this with the receipt; the classification grid and the import boundary are pinned here
because the contract depends on them.
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path

import pytest

from silverloop.agent.guardrails import coordinator_text_violations
from silverloop.models import (
    CaseStatus,
    ContextGapCategory,
    HumanAction,
    OverrideReason,
    ReviewLesson,
    ReviewLessonKind,
    ReviewLessonReason,
)
from silverloop.review_lessons import LESSON_SUMMARIES, classify_review, tally_context_gaps

_SOURCE = Path(__file__).resolve().parents[1] / "src" / "silverloop"


def _expected(
    status: CaseStatus,
    reviewer: str,
    action: HumanAction | None,
    reason: OverrideReason | None,
    late: bool | None,
) -> tuple[ReviewLessonKind, ReviewLessonReason]:
    """The spec's precedence, written independently of the implementation."""
    if reviewer == "system":
        return ReviewLessonKind.TEACHES_NOTHING, ReviewLessonReason.SYSTEM_CLOSURE
    if late:
        return ReviewLessonKind.COUNTS_TOWARD_REVIEW_SETTING, ReviewLessonReason.REACHED_TOO_LATE
    if (
        status == CaseStatus.RESOLVED
        and action == HumanAction.OVERRIDE
        and reason == OverrideReason.NOT_A_CONCERN
    ):
        return ReviewLessonKind.COUNTS_TOWARD_REVIEW_SETTING, ReviewLessonReason.NOT_A_CONCERN
    if action == HumanAction.OVERRIDE and reason == OverrideReason.KNOWN_CONTEXT:
        return ReviewLessonKind.RECORDS_CONTEXT_GAP, ReviewLessonReason.KNOWN_CONTEXT
    nothing = ReviewLessonKind.TEACHES_NOTHING
    if action is None or (action == HumanAction.OVERRIDE and reason is None):
        return nothing, ReviewLessonReason.NO_STRUCTURED_CHOICE
    if action == HumanAction.AGREE:
        return nothing, ReviewLessonReason.AGREED
    if action == HumanAction.HOLD:
        return nothing, ReviewLessonReason.ON_HOLD
    return nothing, {
        OverrideReason.DATA_DOUBT: ReviewLessonReason.DATA_DOUBT,
        OverrideReason.RECENT_CONTACT: ReviewLessonReason.RECENT_CONTACT,
        OverrideReason.OTHER: ReviewLessonReason.OTHER_REASON,
        OverrideReason.NOT_A_CONCERN: ReviewLessonReason.NOT_RESOLVED,
    }[reason]  # type: ignore[index]


@pytest.mark.parametrize(
    ("status", "reviewer", "action", "reason", "late"),
    list(
        itertools.product(
            list(CaseStatus),
            ["coordinator", "system"],
            [None, *HumanAction],
            [None, *OverrideReason],
            [None, False, True],
        )
    ),
)
def test_classification_follows_the_spec_precedence_across_the_grid(
    status: CaseStatus,
    reviewer: str,
    action: HumanAction | None,
    reason: OverrideReason | None,
    late: bool | None,
) -> None:
    lesson = classify_review(
        review_id="review-1",
        status=status,
        reviewer=reviewer,
        human_action=action,
        override_reason=reason,
        reached_too_late=late,
    )
    assert (lesson.kind, lesson.reason) == _expected(status, reviewer, action, reason, late)
    assert lesson.summary == LESSON_SUMMARIES[lesson.reason]


def test_reached_too_late_wins_over_known_context() -> None:
    lesson = classify_review(
        review_id="review-1",
        status=CaseStatus.RESOLVED,
        reviewer="coordinator",
        human_action=HumanAction.OVERRIDE,
        override_reason=OverrideReason.KNOWN_CONTEXT,
        reached_too_late=True,
        context_gap_category=ContextGapCategory.AWAY,
    )
    assert lesson.kind == ReviewLessonKind.COUNTS_TOWARD_REVIEW_SETTING
    assert lesson.reason == ReviewLessonReason.REACHED_TOO_LATE


@pytest.mark.parametrize(
    ("action", "reason", "late"),
    list(itertools.product([None, *HumanAction], [None, *OverrideReason], [None, False, True])),
)
def test_a_category_is_reported_only_beside_a_known_context_override(
    action: HumanAction | None, reason: OverrideReason | None, late: bool | None
) -> None:
    """A stored row carrying a category beside any other choice (written before the repository
    refused it, or by hand) never reads as known context Care+ missed."""
    lesson = classify_review(
        review_id="review-1",
        status=CaseStatus.RESOLVED,
        reviewer="coordinator",
        human_action=action,
        override_reason=reason,
        reached_too_late=late,
        context_gap_category=ContextGapCategory.AWAY,
    )
    allowed = action == HumanAction.OVERRIDE and reason == OverrideReason.KNOWN_CONTEXT
    assert lesson.context_gap_category == (ContextGapCategory.AWAY if allowed else None)
    assert (lesson.kind == ReviewLessonKind.RECORDS_CONTEXT_GAP) == (allowed and not late)
    if not allowed:
        assert tally_context_gaps([lesson]).total == 0


def test_every_lesson_summary_passes_the_coordinator_wording_rules() -> None:
    assert set(LESSON_SUMMARIES) == set(ReviewLessonReason)
    for reason, summary in LESSON_SUMMARIES.items():
        assert coordinator_text_violations(summary) == [], reason


def test_the_tally_counts_context_gap_lessons_by_category_in_enum_order() -> None:
    def gap(category: ContextGapCategory | None, late: bool = False) -> ReviewLesson:
        return classify_review(
            review_id="r",
            status="resolved",
            reviewer="coordinator",
            human_action="override",
            override_reason="known_context",
            reached_too_late=late,
            context_gap_category=category,
        )

    lessons = [
        gap(ContextGapCategory.OTHER_KNOWN),
        gap(None),
        gap(ContextGapCategory.AWAY),
        gap(ContextGapCategory.AWAY),
        gap(ContextGapCategory.AWAY, late=True),  # counts toward the setting instead
    ]
    tally = tally_context_gaps(lessons)
    assert tally.total == 4
    assert [(item.category, item.count) for item in tally.by_category] == [
        (ContextGapCategory.AWAY, 2),
        (ContextGapCategory.OTHER_KNOWN, 1),
        (None, 1),
    ]
    assert coordinator_text_violations(tally.disclosure) == []


@pytest.mark.parametrize("package", ["policy.py", "review_threshold.py", "agent"])
def test_no_decision_path_imports_review_lessons(package: str) -> None:
    target = _SOURCE / package
    files = [target] if target.is_file() else sorted(target.rglob("*.py"))
    assert files
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [
                    f"{node.module}.{alias.name}" for alias in node.names
                ]
            assert not any("review_lessons" in name for name in names), path
