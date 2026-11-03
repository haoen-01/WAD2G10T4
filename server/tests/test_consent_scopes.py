"""`consent_scopes.py` pins the decision in `docs/adr/0001-consent-scope-model.md`.

One stored boolean, five different questions. These tests fix which of the five the boolean
actually gates today, so a future change to `scope_permitted` has to fail a test to happen by
accident.
"""

from __future__ import annotations

import pytest

from silverloop.consent_scopes import ConsentScope, scope_permitted

# The two scopes the ADR decided the stored boolean gates.
GATED_SCOPES = (ConsentScope.PROACTIVE_OUTREACH, ConsentScope.PREFERENCE_LEARNING)

# The three scopes the ADR decided are always permitted, regardless of the stored boolean.
UNGATED_SCOPES = (
    ConsentScope.USER_INITIATED_SEARCH,
    ConsentScope.PROACTIVE_MONITORING,
    ConsentScope.EXTERNAL_CONTEXT,
)


def test_every_scope_is_classified() -> None:
    """No scope is silently unaccounted for by the two lists above."""
    assert set(GATED_SCOPES) | set(UNGATED_SCOPES) == set(ConsentScope)
    assert set(GATED_SCOPES).isdisjoint(UNGATED_SCOPES)


@pytest.mark.parametrize("scope", GATED_SCOPES)
def test_gated_scopes_follow_the_stored_boolean(scope: ConsentScope) -> None:
    assert scope_permitted(scope, consent_active=True) is True
    assert scope_permitted(scope, consent_active=False) is False


@pytest.mark.parametrize("scope", UNGATED_SCOPES)
def test_ungated_scopes_are_always_permitted(scope: ConsentScope) -> None:
    assert scope_permitted(scope, consent_active=True) is True
    assert scope_permitted(scope, consent_active=False) is True
