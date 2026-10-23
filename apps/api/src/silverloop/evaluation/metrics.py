"""Metric definitions for the three-policy comparison (F3 spec, "Metric definitions").

Ground truth for M1-M3, M6, M7 and M8 is `scenario_spec.GroundTruthState` -- world state -- never
`expected_decisions`. Scoring against `expected_decisions` would be circular, since those are
Care+'s own historical outputs.

M4 (`no_action_logging_integrity`, formerly `audited_no_action`) and M9
(`restraint_explanation_coverage`) are deliberately NOT ground-truth metrics: both check that a
decision carries a rationale and a quality evidence id, which is a property of the logging
pipeline, not of whether the decision was correct -- M9 is the same predicate as M4, just scoped
to `NO_ACTION` instead of every `QUIET` decision. M7 and M8 are the ground-truth-scored
replacements, and even M7 needs a caveat: on M1's denominator, M7 is an algebraic identity of M1
and the `SUPPRESS` share, not an independent finding, whenever no policy `SUPPRESS`es on those
steps. See `docs/adr/0002-replace-audited-no-action.md` for why `audited_no_action` was renamed
rather than scored as correctness, the numbers this was checked against, and the M7 identity in
full.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from silverloop.evaluation.scenario_spec import GroundTruthState
from silverloop.models import Decision

CONTACT: frozenset[Decision] = frozenset({Decision.GENTLE_NUDGE, Decision.PROGRAMME_SUGGESTION})
ESCALATION: frozenset[Decision] = frozenset({Decision.COORDINATOR_REVIEW})
ACTION: frozenset[Decision] = CONTACT | ESCALATION
QUIET: frozenset[Decision] = frozenset({Decision.NO_ACTION, Decision.SUPPRESS})

#: World states where the ground truth says outreach was not needed (M1's denominator, reused by
#: M7). `SUPPRESS` on one of these steps is consent/budget withholding a contact the policy wanted
#: to make -- it is not evidence the policy judged restraint correctly, so it is excluded from M7's
#: numerator even though it is "quiet".
NO_INTERVENTION_NEEDED: frozenset[GroundTruthState] = frozenset(
    {GroundTruthState.STABLE, GroundTruthState.EXPLAINED_DIP}
)
#: World states where the ground truth says outreach was required (M2/M3/M8's denominator).
#: `emerging_decline` is deliberately excluded: the labelling rule (see `report.py`) assigns it to
#: a dip that has not yet persisted three valid-wear low days, which is precisely the window the
#: rain-context and severity/persistence gates are designed to wait out. Treating it as
#: intervention-required would score the ladder's own designed patience as a miss.
INTERVENTION_NEEDED: frozenset[GroundTruthState] = frozenset({GroundTruthState.PERSISTENT_DECLINE})

LOW_CONFIDENCE_THRESHOLD = 0.45
CONTACT_CAP = 2


class HardViolation(StrEnum):
    UNCONSENTED_OUTREACH = "unconsented_outreach"
    UNSAFE_DATA_ACTION = "unsafe_data_action"
    LOW_CONFIDENCE_ACTION = "low_confidence_action"
    UNEXPLAINED_ACTION = "unexplained_action"
    CONTACT_CAP_BREACH = "contact_cap_breach"
    FORBIDDEN_ACTION = "forbidden_action"


@dataclass(frozen=True)
class DecisionRecord:
    """One policy's decision at one replayed environment step.

    `label`, `event`, `confidence` and `quality_evidence_id` must be identical across all three
    policies' records for a given `(scenario, step)` pair -- that identity is what proves the
    "identical scenarios" claim (acceptance criterion 3). `consent_active`, `confidence` and
    `safe_to_interpret` are read from the shared environment step, not from the policy's view, so
    they too are policy-independent (blind_view never changes them).
    """

    policy: str
    scenario: str
    step: int
    person_id: str
    event: str
    label: GroundTruthState
    decision: Decision
    support_priority: int
    rationale: tuple[str, ...]
    consent_active: bool
    confidence: float
    safe_to_interpret: bool
    quality_evidence_id: str
    interventions_last_7_days: int
    forbidden: tuple[str, ...] = field(default_factory=tuple)
    budget_withheld: bool = False
    """True when the harness's uniform weekly cap -- not the policy -- turned a CONTACT into a
    SUPPRESS. Only ever set in the budget-matched arm; always False in the uncapped arm."""


def evaluate_violations(record: DecisionRecord) -> list[HardViolation]:
    """Evaluate every hard-violation predicate. Never short-circuits: a single decision can fire
    more than one predicate, and the report distinguishes `violation_total` (sum of firings) from
    `violating_step_count` (steps with at least one) precisely so that is visible.
    """
    fired: list[HardViolation] = []
    if not record.consent_active and record.decision in ACTION:
        fired.append(HardViolation.UNCONSENTED_OUTREACH)
    if not record.safe_to_interpret and record.decision in ACTION:
        fired.append(HardViolation.UNSAFE_DATA_ACTION)
    if record.confidence < LOW_CONFIDENCE_THRESHOLD and record.decision in ACTION:
        fired.append(HardViolation.LOW_CONFIDENCE_ACTION)
    if record.decision in ACTION and not record.rationale:
        fired.append(HardViolation.UNEXPLAINED_ACTION)
    if record.decision in CONTACT and record.interventions_last_7_days >= CONTACT_CAP:
        fired.append(HardViolation.CONTACT_CAP_BREACH)
    if record.decision.value in record.forbidden:
        fired.append(HardViolation.FORBIDDEN_ACTION)
    return fired


def is_consent_not_recorded(record: DecisionRecord) -> bool:
    """Soft counter, reported but never gated: outreach was withheld (SUPPRESS is the only
    consent-safe quiet decision), yet consent was inactive for a non-SUPPRESS decision.
    """
    return not record.consent_active and record.decision != Decision.SUPPRESS


@dataclass(frozen=True)
class Rate:
    """`n/d`, plus how much of the harness the denominator actually came from.

    `scenarios` and `personas` count the DISTINCT scenarios and person ids contributing to the
    denominator, and are printed beside every rate as `0/19 across 3 scenarios, 2 personas`. They
    exist because `0/19` invites a confidence interval and the policy comparison must not carry
    one: nineteen serially dependent steps drawn from a handful of scripted scenarios are not
    nineteen independent observations, and a bootstrap over them would be theatre. Two honest
    counts say the same thing a CI would pretend to -- how much independent evidence is behind
    this number -- without implying a sampling distribution that does not exist.

    Both default to 0, which prints nothing extra, so a `Rate` assembled by hand (a test, a
    derived rate whose provenance is a different unit than a decision record) is not forced to
    invent a provenance it does not have.
    """

    numerator: int
    denominator: int
    scenarios: int = 0
    personas: int = 0

    @property
    def rate(self) -> float | None:
        if self.denominator == 0:
            return None
        return round(self.numerator / self.denominator, 4)

    def formatted(self) -> str:
        rate = self.rate
        rate_text = "n/a" if rate is None else f"{rate:.2%}"
        return f"{self.numerator}/{self.denominator} ({rate_text}){self.coverage_suffix()}"

    def coverage_suffix(self) -> str:
        if not self.scenarios and not self.personas:
            return ""
        return (
            f" across {self.scenarios} {_plural(self.scenarios, 'scenario')}, "
            f"{self.personas} {_plural(self.personas, 'persona')}"
        )


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"


def coverage(records: Iterable[DecisionRecord]) -> tuple[int, int]:
    """Distinct (scenarios, personas) behind a set of records."""
    records = list(records)
    return (
        len({record.scenario for record in records}),
        len({record.person_id for record in records}),
    )


def _rate(records: list[DecisionRecord], denom_pred, numer_pred) -> Rate:
    denominator_records = [record for record in records if denom_pred(record)]
    numerator = sum(1 for record in denominator_records if numer_pred(record))
    scenarios, personas = coverage(denominator_records)
    return Rate(
        numerator=numerator,
        denominator=len(denominator_records),
        scenarios=scenarios,
        personas=personas,
    )


def _has_evidence_backed_rationale(record: DecisionRecord) -> bool:
    """A non-empty rationale plus a quality evidence id.

    This is a LOGGING-INTEGRITY predicate, not a correctness judgement: it says the pipeline wrote
    down why it went quiet and can point at the evidence, never whether going quiet was the right
    call (that is M7/M8, which read the scenario's ground-truth label). Care+'s own ladder
    populates both fields on every branch, so this predicate is near-certain to hold for it
    regardless of whether any given decision was correct -- see M4's docstring on `PolicyMetrics`.
    """
    has_rationale = bool(record.rationale) and all(item.strip() for item in record.rationale)
    return has_rationale and bool(record.quality_evidence_id)


#: One replayed step is one of the person's simulated days, so a scenario of `n` events is `n`
#: person-days. Seven of them make a person-week -- the denominator burden is measured against.
DAYS_PER_PERSON_WEEK = 7


@dataclass(frozen=True)
class BurdenMetrics:
    """How much of the person's attention a policy spent (M38, policy side).

    Every number here is about the person, not about the policy's judgement: two policies can
    reach identical M1/M2 and still differ in whether their contacts arrived on four consecutive
    mornings or spread across a month, and in whether one coordinator case cost one escalation or
    sixteen. Contact volume alone cannot see either, which is why `contact_volume` gets a
    denominator here rather than staying a bare count.
    """

    contacts: int
    person_days: int
    max_consecutive_contact_days: int
    #: The scenario the longest contact run came from, so the number is traceable to one week
    #: rather than floating free. Empty when nothing was ever contacted.
    max_consecutive_contact_scenario: str
    escalations_per_case: Rate
    """Escalation DECISIONS per escalation EPISODE, where an episode is a maximal run of
    escalations on consecutive simulated days within one scenario -- the harness's stand-in for
    the product's "one case per ongoing concern, refreshed rather than duplicated". A value above
    1.0 is the coordinator-side burden of a policy that re-escalates a concern it has already
    raised; `14_baseline_drift` is where it shows up, because eighteen declining days produce one
    concern and many more than one `coordinator_review`."""

    @property
    def person_weeks(self) -> float:
        return round(self.person_days / DAYS_PER_PERSON_WEEK, 4)

    @property
    def contacts_per_person_week(self) -> float | None:
        if not self.person_days:
            return None
        return round(self.contacts * DAYS_PER_PERSON_WEEK / self.person_days, 4)

    def formatted_contacts_per_person_week(self) -> str:
        value = self.contacts_per_person_week
        if value is None:
            return "0 contacts / 0 person-weeks (n/a)"
        return (
            f"{self.contacts} contacts / {self.person_weeks:.2f} person-weeks "
            f"({value:.2f} per person-week)"
        )

    def formatted_escalations_per_case(self) -> str:
        """A ratio, not a proportion: `Rate.formatted`'s percentage would render 19 escalations
        over 4 cases as "475.00%", which reads as a rate gone wrong rather than as the burden
        number it is."""
        rate = self.escalations_per_case
        if not rate.denominator:
            return "0/0 (no escalation episode)"
        return (
            f"{rate.numerator}/{rate.denominator} "
            f"({rate.numerator / rate.denominator:.2f} per case)"
            f"{rate.coverage_suffix()}"
        )


def _consecutive_runs(
    records: Iterable[DecisionRecord], decisions: frozenset[Decision]
) -> list[tuple[str, int]]:
    """Maximal runs of consecutive simulated days matching `decisions`, as `(scenario, length)`.

    Grouped by scenario because two scenarios are two different weeks of two (possibly different)
    people: step 4 of one and step 5 of another are not consecutive days of anything.
    """
    by_scenario: dict[str, list[DecisionRecord]] = {}
    for record in records:
        by_scenario.setdefault(record.scenario, []).append(record)

    runs: list[tuple[str, int]] = []
    for scenario, scenario_records in sorted(by_scenario.items()):
        length = 0
        previous_step: int | None = None
        for record in sorted(scenario_records, key=lambda item: item.step):
            if record.decision in decisions and (
                previous_step is None or record.step == previous_step + 1
            ):
                length += 1
            elif record.decision in decisions:
                if length:
                    runs.append((scenario, length))
                length = 1
            else:
                if length:
                    runs.append((scenario, length))
                length = 0
            previous_step = record.step if record.decision in decisions else None
        if length:
            runs.append((scenario, length))
    return runs


def compute_burden(records: Iterable[DecisionRecord]) -> BurdenMetrics:
    records = list(records)
    contacts = sum(1 for record in records if record.decision in CONTACT)

    contact_runs = _consecutive_runs(records, CONTACT)
    longest_scenario, longest = max(
        contact_runs, key=lambda item: (item[1], item[0]), default=("", 0)
    )

    escalating_records = [record for record in records if record.decision in ESCALATION]
    escalations = len(escalating_records)
    episodes = len(_consecutive_runs(records, ESCALATION))
    scenarios, personas = coverage(escalating_records)

    return BurdenMetrics(
        contacts=contacts,
        person_days=len(records),
        max_consecutive_contact_days=longest,
        max_consecutive_contact_scenario=longest_scenario,
        escalations_per_case=Rate(
            numerator=escalations,
            denominator=episodes,
            scenarios=scenarios,
            personas=personas,
        ),
    )


@dataclass(frozen=True)
class PolicyMetrics:
    policy: str
    version: str
    sample_size: int
    unnecessary_contact: Rate
    missed_persistent_change: Rate
    missed_escalation: Rate
    no_action_logging_integrity: Rate
    """M4, renamed from `audited_no_action`. Denominator: every QUIET (`NO_ACTION` or `SUPPRESS`)
    decision. Numerator: those with a non-empty rationale and a quality evidence id. This is a
    LOGGING-INTEGRITY check, not a correctness measure -- Care+'s own ladder writes both
    fields on every branch, so this is expected to read 100% for it in every arm regardless of
    whether any individual decision was right. It measures "does the audit trail work", not
    "was the silence warranted"; M7/M8 answer that question against ground truth instead."""
    correct_restraint: Rate
    """M7. Denominator: steps whose ground truth is `stable` or `explained_dip`
    (`NO_INTERVENTION_NEEDED`, same set M1 uses) -- outreach was not warranted. Numerator: those
    decided `NO_ACTION` specifically. `SUPPRESS` does NOT count here even though it is quiet: a
    `SUPPRESS` on one of these steps means the policy wanted to act and was blocked by consent or
    the contact budget, which is not evidence it judged the situation correctly.
    `COORDINATOR_REVIEW` and any `CONTACT` decision are excluded from the numerator by construction
    (they are not `NO_ACTION`).

    IDENTITY, not a second finding: on this shared denominator, every step is exactly one of
    `ACTION` (M1's numerator), `NO_ACTION` (this metric's numerator) or `SUPPRESS`, so
    `correct_restraint.rate == 1 - unnecessary_contact.rate - suppress_share`, where
    `suppress_share` is the fraction of the same denominator decided `SUPPRESS`. M7 therefore only
    carries information beyond M1 when `SUPPRESS` is non-zero on `NO_INTERVENTION_NEEDED` steps;
    whenever a policy never `SUPPRESS`es there (true for every policy this harness has replayed
    so far), M7 is `1 - M1` and restates it under a different name rather than measuring
    something new. See `docs/adr/0002-replace-audited-no-action.md` for the numbers this was
    checked against."""
    unsupported_restraint: Rate
    """M8. Denominator: steps whose ground truth is `persistent_decline` (`INTERVENTION_NEEDED`,
    same set M2/M3 use) -- outreach was warranted. Numerator: those decided `NO_ACTION`
    specifically, i.e. the policy presented reasoned inaction on a step that needed help.
    `SUPPRESS` on one of these steps is already counted by M2 ("missed persistent change") and is
    excluded here on purpose: a budget- or consent-withheld contact is a different failure mode
    from a policy concluding, in its own rationale, that nothing was wrong. `COORDINATOR_REVIEW`
    and any `CONTACT` decision score as correct here and are excluded from the numerator."""
    restraint_explanation_coverage: Rate
    """M9. Denominator: every `NO_ACTION` decision (SUPPRESS excluded -- its rationale explains a
    consent/budget block, not a judgement of restraint). Numerator: those with a non-empty
    rationale and a quality evidence id (`_has_evidence_backed_rationale`, the same predicate M4
    uses). Unlike M4, this denominator is scoped to reasoned silence specifically, so a policy that
    never uses `NO_ACTION` reports `0/0` (n/a) rather than folding SUPPRESS's own bookkeeping
    rationale into the count.

    A SECOND LOGGING-INTEGRITY CHECK, not a correctness measure -- despite living next to M7/M8 in
    the report, M9 is `_has_evidence_backed_rationale` again, just re-scoped from M4's `QUIET` to
    `NO_ACTION` only. Care+'s ladder writes that predicate on every branch, so M9 is 100% for
    it by construction, exactly as M4 is. The baselines' scores are not a restraint-quality finding
    either: `fixed_threshold_decide`'s `NO_ACTION` branch always returns an empty rationale list
    (`baselines.py`), so its M9 is 0% purely because that function was never written to explain a
    stable day, not because its "restraint" is less sound than `contextual_rule`'s. Read M9 as
    "does this policy's `NO_ACTION` code path write itself down", never as a signal that the
    silence itself was warranted -- that question is M7/M8's alone."""
    violation_total: int
    violating_step_count: int
    violations_by_type: dict[HardViolation, int]
    consent_not_recorded: int
    contact_volume: int
    human_review_count: int
    decision_counts: dict[Decision, int]
    unwarranted_contact_share: Rate
    """M6. Denominator: the contacts this policy ACTUALLY made. Numerator: how many of those
    landed on a step whose ground-truth world state was `stable` or `explained_dip`. Unlike M1
    (whose denominator is quiet-worthy *steps*), M6 is only comparable across policies when they
    were given the same contact budget -- which is why the budget-matched arm exists."""
    budget_withheld: int
    """Steps where the harness's uniform cap withheld a contact this policy would have made."""
    burden: BurdenMetrics
    """M38, policy side: `contacts_per_person_week`, `max_consecutive_contact_days` and
    `escalations_per_case`, each with its denominator printed. These measure what the policy cost
    the person and the coordinator, which no correctness rate above can see."""

    @property
    def escalates(self) -> bool:
        """False when a policy never emits COORDINATOR_REVIEW anywhere in the run. Such a policy
        cannot spend a budget on escalation at all, so its M3 of 100% is a structural fact about
        the policy, not a measured judgement error -- the report must say so rather than scoring
        it as though it tried and failed."""
        return self.human_review_count > 0


def aggregate(policy: str, version: str, records: Iterable[DecisionRecord]) -> PolicyMetrics:
    """Fold an arbitrary iterable of `DecisionRecord`s (a single scenario, several, or all of
    them) into `PolicyMetrics`. Grouping is entirely the caller's concern -- this keeps the
    multi-persona seam open (a future caller can group by `person_id` without changing this
    function).
    """
    records = list(records)

    unnecessary_contact = _rate(
        records,
        lambda r: r.label in {GroundTruthState.STABLE, GroundTruthState.EXPLAINED_DIP},
        lambda r: r.decision in ACTION,
    )
    missed_persistent_change = _rate(
        records,
        lambda r: r.label == GroundTruthState.PERSISTENT_DECLINE,
        lambda r: r.decision in QUIET,
    )
    missed_escalation = _rate(
        records,
        lambda r: r.label == GroundTruthState.PERSISTENT_DECLINE,
        lambda r: r.decision not in ESCALATION,
    )
    no_action_logging_integrity = _rate(
        records,
        lambda r: r.decision in QUIET,
        _has_evidence_backed_rationale,
    )
    correct_restraint = _rate(
        records,
        lambda r: r.label in NO_INTERVENTION_NEEDED,
        lambda r: r.decision == Decision.NO_ACTION,
    )
    unsupported_restraint = _rate(
        records,
        lambda r: r.label in INTERVENTION_NEEDED,
        lambda r: r.decision == Decision.NO_ACTION,
    )
    restraint_explanation_coverage = _rate(
        records,
        lambda r: r.decision == Decision.NO_ACTION,
        _has_evidence_backed_rationale,
    )
    unwarranted_contact_share = _rate(
        records,
        lambda r: r.decision in CONTACT,
        lambda r: r.label in {GroundTruthState.STABLE, GroundTruthState.EXPLAINED_DIP},
    )

    violations_by_type: dict[HardViolation, int] = dict.fromkeys(HardViolation, 0)
    violation_total = 0
    violating_step_count = 0
    for record in records:
        fired = evaluate_violations(record)
        if fired:
            violating_step_count += 1
        violation_total += len(fired)
        for violation in fired:
            violations_by_type[violation] += 1

    decision_counts: dict[Decision, int] = dict.fromkeys(Decision, 0)
    for record in records:
        decision_counts[record.decision] += 1

    return PolicyMetrics(
        policy=policy,
        version=version,
        sample_size=len(records),
        unnecessary_contact=unnecessary_contact,
        missed_persistent_change=missed_persistent_change,
        missed_escalation=missed_escalation,
        no_action_logging_integrity=no_action_logging_integrity,
        correct_restraint=correct_restraint,
        unsupported_restraint=unsupported_restraint,
        restraint_explanation_coverage=restraint_explanation_coverage,
        violation_total=violation_total,
        violating_step_count=violating_step_count,
        violations_by_type=violations_by_type,
        consent_not_recorded=sum(1 for record in records if is_consent_not_recorded(record)),
        contact_volume=sum(1 for record in records if record.decision in CONTACT),
        human_review_count=sum(1 for record in records if record.decision in ESCALATION),
        decision_counts=decision_counts,
        unwarranted_contact_share=unwarranted_contact_share,
        budget_withheld=sum(1 for record in records if record.budget_withheld),
        burden=compute_burden(records),
    )
