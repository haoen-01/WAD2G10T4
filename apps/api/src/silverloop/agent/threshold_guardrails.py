"""The full review-threshold guardrail: structure (rules 1-8) plus coordinator-facing wording (9).

`review_threshold.validate_threshold_structure` is pure and lives beside the rules it enforces, so
the evaluation harness and the stage-1 fixed rule can use it without importing this package. This
module adds rule 9 -- the reasoning's length and wording -- which needs the agent package's word
lists. It is the check the calibration agent's loop runs on every proposal, and the check the
repository re-runs on an agent's output before storing it (Transaction B) and before approving it.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date

from silverloop.agent.constants import (
    MAX_THRESHOLD_REASONING_CHARS,
    MIN_THRESHOLD_REASONING_CHARS,
)
from silverloop.agent.guardrails import coordinator_text_violations, fold_for_rules
from silverloop.models import OverrideReason, ReviewThresholdCause
from silverloop.review_threshold import (
    ReviewThreshold,
    ThresholdDecisionFact,
    ThresholdVerdict,
    validate_threshold_structure,
)

VIOLATION_REASONING_LENGTH = (
    f"Reasoning must be between {MIN_THRESHOLD_REASONING_CHARS} and "
    f"{MAX_THRESHOLD_REASONING_CHARS} characters."
)


def reasoning_violations(reasoning: str) -> list[str]:
    """Rule 9 alone: length (measured on what a coordinator reads) and wording."""
    violations: list[str] = []
    readable = len(fold_for_rules(reasoning, join_across_controls=True).strip())
    if readable < MIN_THRESHOLD_REASONING_CHARS or len(reasoning) > MAX_THRESHOLD_REASONING_CHARS:
        violations.append(VIOLATION_REASONING_LENGTH)
    violations.extend(coordinator_text_violations(reasoning))
    return violations


def validate_threshold_output(
    *,
    reasoning: str,
    live: ReviewThreshold,
    proposed: ReviewThreshold | None,
    cause: ReviewThresholdCause | str | None,
    cited_evidence_ids: Sequence[str],
    known_evidence_ids: Collection[str],
    coordinator_reason: OverrideReason | str | None,
    facts: Sequence[ThresholdDecisionFact],
    today: date,
    blocked_values: Collection[ReviewThreshold] | None = None,
    require_cause: bool = True,
) -> ThresholdVerdict:
    """Rules 1-9. Every structural argument means what it means in `validate_threshold_structure`;
    `reasoning` is checked by rule 9 whether or not a change is proposed."""
    structure = validate_threshold_structure(
        live=live,
        proposed=proposed,
        cause=cause,
        cited_evidence_ids=cited_evidence_ids,
        known_evidence_ids=known_evidence_ids,
        coordinator_reason=coordinator_reason,
        facts=facts,
        today=today,
        blocked_values=blocked_values,
        require_cause=require_cause,
    )
    violations = (*structure.violations, *reasoning_violations(reasoning))
    return ThresholdVerdict(approved=not violations, violations=tuple(violations))


__all__ = [
    "VIOLATION_REASONING_LENGTH",
    "reasoning_violations",
    "validate_threshold_output",
]
