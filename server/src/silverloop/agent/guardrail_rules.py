"""Stable names for the guardrail rules, recovered from the violation text already recorded.

Why this is a classifier and not a field
----------------------------------------
`GuardrailVerdict.violations` is a list of prose sentences, written to be read back to the model
as feedback it can act on. That is the right shape for the loop and the wrong shape for a
counter: "which safety rules actually bind in practice" needs a stable key, and prose is not one.

The honest long-term fix is a rule id on each violation at the point it is raised, in
`guardrails.py`. This module is the interim: one table, one function, applied to violations
already stored in the audit trail -- including the ones written before any of this existed, which
a new field could never retrofit.

Its weakness is explicit: a reworded violation silently falls into `RULE_OTHER`. That is why
`tests/test_recorded_client.py` asserts that every violation `guardrails.py` can currently emit
classifies to a named rule. Reword a violation and that test fails, which is the point.
"""

from __future__ import annotations

from typing import Final

RULE_OTHER: Final[str] = "other"

# (distinctive substring, rule name). Ordered; the first match wins. Substrings are chosen to be
# the part of each sentence that carries the rule's identity, not its examples.
_RULE_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    # Outreach (`validate_proposal`)
    ("is not permitted. choose exactly one of", "candidate_not_permitted"),
    ("it must be at least", "message_too_short"),
    ("it must be at most", "message_too_long"),
    ("clinical or emergency language", "clinical_language"),
    ("applies pressure", "pressure"),
    ("involves someone other than the senior", "third_party"),
    ("claims an action has been taken", "asserted_action"),
    ("quotes a raw number", "raw_number"),
    ("gives no visible way to decline", "no_visible_opt_out"),
    ("asks the person to reply, text, call, email or message", "channel_instruction"),
    ("contains an emoji", "emoji"),
    ("copies a data marker", "copied_data_marker"),
    ("claims the person has tried this before", "unsupported_prior_experience"),
    ("implies company, a group, or joining other people", "implied_company"),
    ("carry accessibility meaning", "dropped_accessibility_term"),
    # Activity ranking (`validate_activity_order`)
    ("the proposal offers nothing", "empty_proposal"),
    ("these keys are not permitted", "key_not_permitted"),
    ("duplicate key(s) in the proposal", "duplicate_key"),
    # Neither of the two below may be shortened to a fragment the outreach sentences share: the
    # narrowing sentence also says "at least", which is why its marker is "must be offered" and
    # not anything overlapping "it must be at least" (`message_too_short`).
    ("may gain more than", "over_promotion"),
    ("must be offered", "over_narrowing"),
)

RULE_NAMES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys([name for _, name in _RULE_MARKERS] + [RULE_OTHER])
)


def classify_violation(violation: str) -> str:
    """The rule name a recorded violation belongs to, or `RULE_OTHER`.

    Never raises and never drops: an unrecognised violation is counted under `other` rather than
    vanishing from the total, so `sum(counts.values())` always equals the number of violations.
    """
    lowered = violation.strip().lower()
    for marker, name in _RULE_MARKERS:
        if marker in lowered:
            return name
    return RULE_OTHER


def count_violations_by_rule(violations: object) -> dict[str, int]:
    """Tally an iterable of violation strings by rule name. Non-string members are ignored --
    the input is JSON read back out of an audit row, not a typed object."""
    counts: dict[str, int] = {}
    if not isinstance(violations, list | tuple):
        return counts
    for violation in violations:
        if not isinstance(violation, str):
            continue
        name = classify_violation(violation)
        counts[name] = counts.get(name, 0) + 1
    return counts


__all__ = ["RULE_NAMES", "RULE_OTHER", "classify_violation", "count_violations_by_rule"]
