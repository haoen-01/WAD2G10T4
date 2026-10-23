"""The follow-through funnel over an authored `outcomes:` block (M38, policy side).

`OutcomeKind.ACCEPTED` means "show me more" and nothing else. The product is careful about that
distinction everywhere it records one; the policy harness was not measuring it at all, so a
policy that produced twenty taps and no attendance scored identically to one that produced two
attendances. This module closes that gap on the harness side:

    offered -> responded{accepted, declined, deferred, no_response}
            -> followed{completed, partial, not_this_time, unable}
            -> enjoyed{enjoyed, okay, not_for_me}

Every stage is `n/d` of the stage before it, plus `silence_rate = no_response / offered`.

**What the `outcomes:` block is, and why it is not circular.** One entry per event, authored in
the scenario YAML beside `labels:` and `world:`. It says what THIS PERSON does if they are
contacted on THIS DAY -- a counterfactual fact about the person, in the same spirit as the latent
world, not a record of what any policy did. A step nobody contacted simply never enters the
denominator, which is why the funnel is computed per policy: a quieter policy offers less and is
measured on less, and the `n/d` says so.

The block is optional and today only two scenarios carry one, so these denominators are small.
The report says that rather than printing a confident rate over six offers.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from silverloop.evaluation.metrics import CONTACT, DecisionRecord, Rate, coverage
from silverloop.evaluation.outcomes import ATTENDED, AuthoredOutcome
from silverloop.models import Enjoyment, OutcomeKind


@dataclass(frozen=True)
class Funnel:
    """Each stage as `n/d` of the previous one, never as a share of the top."""

    offered: int
    """Contacts this policy actually made on a step that authors an outcome. Steps with no
    authored outcome are excluded from every stage: an unauthored day is missing data, and
    counting it as silence would invent a refusal."""
    unauthored_offers: int
    """Contacts made on a step with no authored outcome. Printed so `offered` is never mistaken
    for "every contact this policy made"."""
    responded: Rate
    accepted: Rate
    declined: Rate
    deferred: Rate
    no_response: Rate
    followed: Rate
    attended: Rate
    enjoyment_recorded: Rate
    enjoyed: Rate
    scenarios: int
    personas: int

    @property
    def silence_rate(self) -> Rate:
        return self.no_response


def _rate(numerator: int, denominator: int) -> Rate:
    """A stage rate carries no per-stage coverage.

    The denominator of a later stage is an earlier stage's numerator, not a set of steps, so
    "across 2 scenarios" would describe the offers rather than the stage and would keep printing
    a coverage next to `0/0`. The funnel states its coverage once, for the offers it was built
    from, on `Funnel.scenarios` / `Funnel.personas`.
    """
    return Rate(numerator=numerator, denominator=denominator)


def compute_funnel(
    records: Iterable[DecisionRecord],
    outcomes: dict[tuple[str, int], AuthoredOutcome],
) -> Funnel:
    """Fold one policy's ledger against the authored outcomes.

    `outcomes` is keyed by `(scenario, step)` -- the same key the ledger carries -- so the join
    never depends on ordering.
    """
    contacted = [record for record in records if record.decision in CONTACT]
    offers = [
        (record, outcomes[(record.scenario, record.step)])
        for record in contacted
        if (record.scenario, record.step) in outcomes
    ]
    unauthored = len(contacted) - len(offers)
    scenarios, personas = coverage(record for record, _ in offers)

    offered = len(offers)
    replies = [outcome for _, outcome in offers if outcome.response != OutcomeKind.NO_RESPONSE]
    accepted = [outcome for _, outcome in offers if outcome.response == OutcomeKind.ACCEPTED]
    followed = [outcome for outcome in accepted if outcome.follow_through is not None]
    attended = [outcome for outcome in followed if outcome.follow_through in ATTENDED]
    with_enjoyment = [outcome for outcome in attended if outcome.enjoyment is not None]
    enjoyed = [outcome for outcome in with_enjoyment if outcome.enjoyment == Enjoyment.ENJOYED]

    def count(response: OutcomeKind) -> int:
        return sum(1 for _, outcome in offers if outcome.response == response)

    return Funnel(
        offered=offered,
        unauthored_offers=unauthored,
        responded=_rate(len(replies), offered),
        accepted=_rate(len(accepted), offered),
        declined=_rate(count(OutcomeKind.DECLINED), offered),
        deferred=_rate(count(OutcomeKind.DEFERRED), offered),
        no_response=_rate(count(OutcomeKind.NO_RESPONSE), offered),
        followed=_rate(len(followed), len(accepted)),
        attended=_rate(len(attended), len(followed)),
        enjoyment_recorded=_rate(len(with_enjoyment), len(attended)),
        enjoyed=_rate(len(enjoyed), len(with_enjoyment)),
        scenarios=scenarios,
        personas=personas,
    )


def authored_outcomes(
    scenario_name: str, outcomes: Sequence[AuthoredOutcome | None] | None
) -> dict[tuple[str, int], AuthoredOutcome]:
    """Index one scenario's block by `(scenario, step)`; steps are 1-based, as the ledger's are."""
    if not outcomes:
        return {}
    return {
        (scenario_name, index + 1): outcome
        for index, outcome in enumerate(outcomes)
        if outcome is not None
    }


__all__ = [
    "Funnel",
    "authored_outcomes",
    "compute_funnel",
]
