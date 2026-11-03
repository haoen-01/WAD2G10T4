"""What the single stored consent boolean actually means, named per use.

`ConsentEvidenceRow.active` (`repository._consent_active`) is one boolean today, but the codebase
already treats it as covering several different questions depending on where it is read:

  * whether Care+ may **contact** this person on its own initiative (`policy.decide`'s
    consent gate, the context question, the baseline-confirmation question, the coordinator
    review queue -- see `sql_repository._close_open_cases_for_consent`).
  * whether an offer the person **answers themselves** is even reachable
    (`search_activities`, `respond_to_activity`, `state_preference` -- none of these ever call
    `_consent_active`, on purpose: the ladder answers "should we contact this person?", which is
    the wrong question when they contacted us).
  * whether a tap or an enjoyment report gets folded into an **inferred** preference
    (`_apply_activity_decline`, `_apply_activity_enjoyment`), as opposed to an explicit statement
    through `state_preference`, which is never paused.
  * whether the daily wearable reading is still **analysed** into a baseline/signal/attention
    band at all (`_evaluate` calls `analyse_signal` unconditionally; only the resulting decision
    is suppressed).
  * whether ambient public context (rain, public holidays) is fetched for the day being decided
    (`advance`'s `_context_provider.fetch` call, which never checks consent).

This module names those five questions as `ConsentScope` and states, as one pure lookup, what the
one stored boolean means for each of them *today*. See `docs/adr/0001-consent-scope-model.md` for
why the scopes are drawn this way, which ones the single boolean actually gates, and which ones
are a named, deferred gap rather than an oversight.

Nothing here changes what any call site decides. Call sites that already implement one of these
scope's rules route their `consent_active` read through `scope_permitted` so that the mapping
lives in one place; if a scope's rule ever needs to vary independently of the others, only this
function needs to change, one row at a time, once the schema carries more than one boolean.
"""

from __future__ import annotations

from enum import StrEnum


class ConsentScope(StrEnum):
    """The five permissions the ticket asked Care+ to tell apart. See the module docstring."""

    # Contacting the person without being asked: a nudge, a programme suggestion, a coordinator
    # review referral, the context question, the baseline-confirmation question. Gated by the
    # stored boolean -- this is what `policy.decide`'s `consent_active` parameter models.
    PROACTIVE_OUTREACH = "proactive_outreach"

    # Folding a tap or an enjoyment report into an *inferred* dimension preference. Gated, but
    # distinctly from outreach: pausing this leaves the tap itself on the record (see
    # `USER_INITIATED_SEARCH`) and leaves anything the person states outright
    # (`state_preference`) untouched. `_apply_activity_decline` / `_apply_activity_enjoyment`
    # already implement exactly this rule; this scope only names it.
    PREFERENCE_LEARNING = "preference_learning"

    # The person asking Care+ for something, or answering what it showed them: search,
    # "interested" / "not for me", and stating a preference outright. Never gated -- the ladder
    # answers "should we contact this person?", which is the wrong question when they contacted
    # us. Always permitted regardless of the stored boolean.
    USER_INITIATED_SEARCH = "user_initiated_search"

    # Turning ingested wearable readings into a baseline, a signal and an attention band. Never
    # gated today: `_evaluate` computes it unconditionally, because there is no separate control
    # over data ingestion in this system and the computation is what lets a coordinator's
    # already-open case, and the decision to resume outreach on re-consent, stay correct. What is
    # gated is *acting* on it (`PROACTIVE_OUTREACH`) and, on the senior's own surface, *showing*
    # it back to them -- the senior app hides "How things look" while suggestions are off, in the
    # view layer, not here.
    PROACTIVE_MONITORING = "proactive_monitoring"

    # Fetching ambient public context (rain, public holidays) to decide today. Never gated today
    # and carries no person identifier off the process. Named as a scope because a future
    # per-category consent model should cover it (tracked in `docs/WAYFINDER.md` §49); left
    # ungated for now because there is nothing personal in the fetch to protect.
    EXTERNAL_CONTEXT = "external_context"


# Scopes the single stored boolean actually gates. Everything else in `ConsentScope` is always
# permitted regardless of `consent_active`, by decision (see the ADR), not by omission.
_GATED_BY_STORED_BOOLEAN = frozenset(
    {ConsentScope.PROACTIVE_OUTREACH, ConsentScope.PREFERENCE_LEARNING}
)


def scope_permitted(scope: ConsentScope, *, consent_active: bool) -> bool:
    """Whether `scope` is currently permitted, given the one stored consent boolean.

    A pure function of its two arguments so every caller reasons about it the same way, and so a
    future scope-by-scope split (a schema change, deferred -- see the ADR) only ever has to touch
    this one lookup, never the call sites that already read `scope_permitted(...)` today.
    """
    if scope in _GATED_BY_STORED_BOOLEAN:
        return consent_active
    return True
