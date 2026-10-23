"""The authored `outcomes:` block: what a person does if they are contacted on a given day.

A leaf module, exactly as `world.py` is. It carries the SCHEMA the scenario loader needs and
nothing that measures anything, so `scenario_spec` can parse an `outcomes:` block without
reaching `metrics` -- `funnel.py`, which does the measuring, imports both.

The block is a counterfactual fact about the PERSON, one optional entry per event, in the same
spirit as the latent world: it says what they would do if contacted that day, never what any
policy did. That is what keeps the follow-through funnel from scoring Care+ against its own
output. A day the scenario does not author is `null`, and stays missing data rather than becoming
silence.
"""

from __future__ import annotations

from dataclasses import dataclass

from silverloop.models import Enjoyment, FollowThrough, OutcomeKind

#: The responses a person can give to one piece of outreach in this harness.
#: `ACTIVITY_RECOVERED` and `COORDINATOR_RESOLVED` are administrative closures, never a reply, so
#: they are not authorable here -- the product makes the same distinction.
AUTHORABLE_RESPONSES = frozenset(
    {
        OutcomeKind.ACCEPTED,
        OutcomeKind.DECLINED,
        OutcomeKind.DEFERRED,
        OutcomeKind.NO_RESPONSE,
    }
)

#: Follow-through values that mean the person actually attended something. Enjoyment is only
#: meaningful after one of these: administrative closure is never enjoyment.
ATTENDED = frozenset({FollowThrough.COMPLETED, FollowThrough.PARTIAL})


class OutcomeSpecError(ValueError):
    """Raised when a scenario's `outcomes:` block fails structural validation."""


@dataclass(frozen=True)
class AuthoredOutcome:
    """What the person does if contacted on one replayed day.

    `follow_through` is only meaningful after `ACCEPTED`, and `enjoyment` only after an attending
    `follow_through`. Both are validated rather than tolerated, so an authored funnel cannot
    describe someone enjoying an activity they declined.
    """

    response: OutcomeKind
    follow_through: FollowThrough | None = None
    enjoyment: Enjoyment | None = None


_OUTCOME_KEYS = frozenset({"response", "follow_through", "enjoyment"})


def coerce_outcome(raw: object, *, where: str) -> AuthoredOutcome | None:
    """Parse one `outcomes:` entry. `null` means "not authored for this day" and is legal."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise OutcomeSpecError(f"{where}: each 'outcomes' entry must be a mapping or null")
    unknown = sorted(set(raw) - _OUTCOME_KEYS)
    if unknown:
        raise OutcomeSpecError(
            f"{where}: unknown outcome key(s) {', '.join(unknown)}; "
            f"expected any of: {', '.join(sorted(_OUTCOME_KEYS))}"
        )
    if "response" not in raw:
        raise OutcomeSpecError(f"{where}: 'outcomes' entry is missing required key 'response'")

    try:
        response = OutcomeKind(raw["response"])
    except ValueError as exc:
        allowed = ", ".join(sorted(member.value for member in AUTHORABLE_RESPONSES))
        raise OutcomeSpecError(
            f"{where}: unknown response {raw['response']!r}; expected one of: {allowed}"
        ) from exc
    if response not in AUTHORABLE_RESPONSES:
        allowed = ", ".join(sorted(member.value for member in AUTHORABLE_RESPONSES))
        raise OutcomeSpecError(
            f"{where}: {response.value!r} is an administrative closure, not a reply; "
            f"expected one of: {allowed}"
        )

    follow_through: FollowThrough | None = None
    if raw.get("follow_through") is not None:
        if response != OutcomeKind.ACCEPTED:
            raise OutcomeSpecError(
                f"{where}: 'follow_through' is only meaningful after 'accepted', "
                f"not after {response.value!r}"
            )
        try:
            follow_through = FollowThrough(raw["follow_through"])
        except ValueError as exc:
            allowed = ", ".join(member.value for member in FollowThrough)
            raise OutcomeSpecError(
                f"{where}: unknown follow_through {raw['follow_through']!r}; "
                f"expected one of: {allowed}"
            ) from exc

    enjoyment: Enjoyment | None = None
    if raw.get("enjoyment") is not None:
        if follow_through not in ATTENDED:
            raise OutcomeSpecError(
                f"{where}: 'enjoyment' requires an attending follow_through "
                f"({', '.join(sorted(item.value for item in ATTENDED))}); "
                "administrative closure is never enjoyment"
            )
        try:
            enjoyment = Enjoyment(raw["enjoyment"])
        except ValueError as exc:
            allowed = ", ".join(member.value for member in Enjoyment)
            raise OutcomeSpecError(
                f"{where}: unknown enjoyment {raw['enjoyment']!r}; expected one of: {allowed}"
            ) from exc

    return AuthoredOutcome(response=response, follow_through=follow_through, enjoyment=enjoyment)


__all__ = [
    "ATTENDED",
    "AUTHORABLE_RESPONSES",
    "AuthoredOutcome",
    "OutcomeSpecError",
    "coerce_outcome",
]
