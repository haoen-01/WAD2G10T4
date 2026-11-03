from __future__ import annotations

from collections import defaultdict

# Evidence weights, in Beta pseudo-counts. One recorded intervention contributes at most one unit
# of evidence, split between alpha ("this option suited them") and beta ("it did not"). Several
# pairs deliberately sum to less than one: the remainder is genuine ignorance, and the honest way
# for a Beta posterior to represent "we do not know" is to not move.
#
# The design decision underneath all of it: ACCEPTANCE IS NOT SUCCESS. A tap on "Yes, tell me
# more" is consent to be shown something and nothing else. Ranking on it would make this a
# click-through optimiser, which is precisely the failure mode the product exists to avoid, so a
# bare acceptance barely moves the posterior. The weight it used to claim is released only when
# the person says what actually happened -- see `_FOLLOW_THROUGH_WEIGHTS`.
_OUTCOME_WEIGHTS: dict[str, tuple[float, float]] = {
    "activity_recovered": (1.0, 0.0),
    "accepted": (0.25, 0.0),
    # The *bare* decline: an answer with no reason attached. A decline that does carry one is
    # resolved through `_DECLINE_REASON_WEIGHTS` instead -- see below.
    "declined": (0.0, 1.0),
    # Silence is ambiguous. An unread phone is not a refusal, so it counts against the candidate
    # at half weight rather than being scored as a no.
    "no_response": (0.0, 0.5),
    # "Maybe later" is an active reply from someone who read the message. It says nothing about
    # whether the option suits them, so it moves nothing in either direction. Before this existed
    # a deferral was filed as `no_response` and penalised almost as hard as a refusal.
    "deferred": (0.0, 0.0),
}

# `OutcomeKind` members that can never be handed to `record`, named rather than given a weight.
#
# `coordinator_resolved` is administrative closure. `record_outcome` refuses it outright
# ("Coordinator outcomes must be recorded through case review") and `review_case` writes a
# `CaseReviewRow` and an audit event, never an `InterventionOutcomeRow` -- so
# `_preference_learners`, which folds outcome rows, cannot see one. It used to sit in
# `_OUTCOME_WEIGHTS` as a deliberate `(0.0, 0.0)`, which read like a chosen ranking weight for a
# path no data takes. Naming it here keeps the exhaustiveness guard over `OutcomeKind` honest
# without inventing policy for an impossible row; if one ever did arrive, `record`'s silent no-op
# is the same zero, reached by the fail-safe rather than by a decision nobody made.
_OUTCOMES_NEVER_REACHED_BY_THE_LEARNER: frozenset[str] = frozenset({"coordinator_resolved"})

# The outcome a `DeclineReason` qualifies. A reason sent alongside anything else is context the
# contract calls "only meaningful alongside `declined`" (`models.OutcomeRequest.reason`) and is
# ignored here rather than allowed to rewrite an acceptance.
_DECLINED = "declined"

# A decline is not one answer. `record_outcome` has always stored the one-tap reason on the
# outcome row, and the deterministic suppression guard has always read it -- a `bad_day` decline
# never counts toward muting a candidate. The posterior that actually ORDERS outreach did not:
# every decline arrived here as a bare `declined` and taught a full unit against the option,
# so "just a bad day" and "I am already getting about" ranked a suggestion down exactly as hard
# as "it is not for me". Applied INSTEAD OF `_OUTCOME_WEIGHTS["declined"]`, never on top of it.
#
# An unrecognised reason falls back to the bare decline weight: a reason this table has not
# considered is still a refusal, and reading it as one of the zero-weight carve-outs would be the
# unsafe direction to guess in.
_DECLINE_REASON_WEIGHTS: dict[str, tuple[float, float]] = {
    # About the day, not the option. "Not today" is the single most common honest answer to a
    # nudge, and three of them in a quiet week used to be enough to bury a perfectly good
    # suggestion under the person's own bad fortnight.
    "bad_day": (0.0, 0.0),
    # About the SENSOR. `ALREADY_ACTIVE` is the person correcting the wearable -- ground truth
    # `policy.py` feeds into data quality, not a verdict on the suggestion. Ranking the option
    # down for it would punish the option for the tracker's mistake.
    "already_active": (0.0, 0.0),
    # The rest are genuinely about this option, and mean exactly what a bare decline means.
    # Written as a reference to that weight rather than as a copied literal so a retune of
    # `declined` cannot leave these silently describing the old scale.
    "not_for_me": _OUTCOME_WEIGHTS[_DECLINED],
    "too_far": _OUTCOME_WEIGHTS[_DECLINED],
    "too_tiring": _OUTCOME_WEIGHTS[_DECLINED],
    "bad_timing": _OUTCOME_WEIGHTS[_DECLINED],
    "prefer_something_else": _OUTCOME_WEIGHTS[_DECLINED],
}

# Applied INSTEAD OF the acceptance weight once the person reports what happened -- never on top
# of it. One intervention, one unit of evidence.
_FOLLOW_THROUGH_WEIGHTS: dict[str, tuple[float, float]] = {
    "completed": (1.0, 0.0),
    "partial": (0.6, 0.4),
    "not_this_time": (0.25, 0.75),
    # "I couldn't today" is not "I won't". A poor fit for this option on the day, ranked down so
    # something else is offered next time, at HALF the weight of a flat refusal: it used to carry
    # the same full unit a `declined` does, which made the one follow-through the product promises
    # is never read as a statement about the person the harshest answer on the list. It is never a
    # capability judgement and is never surfaced as one; see `FollowThrough` in models.py.
    "unable": (0.0, 0.5),
}


# Used for the EXPERIENCE posterior only -- see `PreferenceLearner`'s docstring for why this is
# no longer folded into the same posterior attendance is. Attendance is not enjoyment: before the
# two were split, "went and disliked it" scored exactly like "went and loved it" (both were a bare
# `completed`), and then, once an enjoyment weight superseded the follow-through weight entirely,
# a candidate attended reliably but rated "okay" every time lost its attendance history outright --
# see `docs/adr/0005-engagement-and-experience-as-two-learned-signals.md` for the numbers.
_ENJOYMENT_WEIGHTS: dict[str, tuple[float, float]] = {
    "enjoyed": (1.0, 0.0),
    "okay": (0.5, 0.5),
    "not_for_me": (0.0, 1.0),
}

# The only `FollowThrough` values that mean the person actually did the thing. An enjoyment
# report attached to any other follow-through (`not_this_time`, `unable`, or an unrecognised
# value the client sent anyway) is a fact about attendance recorded under the wrong prompt, not
# evidence about the experience, so it is never folded into the EXPERIENCE posterior -- see
# `record`.
_ATTENDED_FOLLOW_THROUGHS = frozenset({"completed", "partial"})


class PreferenceLearner:
    """Two small transparent weighted Beta-Bernoulli posteriors per key, combined at read time;
    never overrides safety policy.

    ENGAGEMENT answers "would this person choose this option again" -- accept it, follow through
    on it -- from `_OUTCOME_WEIGHTS`/`_FOLLOW_THROUGH_WEIGHTS` exactly as before. EXPERIENCE
    answers "given they attended, was it any good" -- from `_ENJOYMENT_WEIGHTS`, and only when
    `_ATTENDED_FOLLOW_THROUGHS` says they actually attended. `expected_value` is their product,
    i.e. an honest P(attend) x E[enjoy | attend]: an option nobody attends cannot out-rank one
    people attend and enjoy merely because its few reports are glowing, and an option people
    reliably attend is not erased by a lukewarm "okay" the way a single collapsed posterior
    erased it.

    They used to be one posterior, with `enjoyment` superseding `follow_through` on the theory
    that the most informative report supersedes the earlier ones. That is right for "accepted"
    vs. "completed" -- a bare tap really does teach nothing once we know what happened -- but
    wrong for "completed" vs. "enjoyed": attending is not evidence that goes stale the moment a
    verdict on taste arrives, it is a different fact, about a different question, and the product
    needs both answers. A candidate attended every single time it was offered and rated "okay"
    every time used to average out to the same posterior as a candidate never offered at all,
    because `okay`'s (0.5, 0.5) replaced, rather than sat alongside, the (1.0, 0.0) `completed`
    would otherwise have contributed. See
    `docs/adr/0005-engagement-and-experience-as-two-learned-signals.md`.

    A key never reported on for either posterior defaults to Beta(1, 1) x Beta(1, 1) = 0.25 --
    lower than the single learner's 0.5, because "we don't know if they'd attend" and "we don't
    know if they'd enjoy it" are two separate pieces of honest ignorance, and multiplying two
    honest 0.5s is the correct combination of them, not a penalty invented for this change. A key
    with real engagement evidence but no enjoyment report yet still reads its EXPERIENCE factor
    as the neutral 0.5 prior, never a manufactured negative -- reported enjoyment can pull a
    candidate below what its engagement alone would earn it, but the absence of a report never
    can.
    """

    def __init__(self) -> None:
        self._engagement: dict[str, list[float]] = defaultdict(lambda: [1.0, 1.0])
        self._experience: dict[str, list[float]] = defaultdict(lambda: [1.0, 1.0])

    def record(
        self,
        key: str,
        outcome: str,
        follow_through: str | None = None,
        enjoyment: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Fold one intervention's result into the two posteriors for `key`.

        One intervention, at most one unit of ENGAGEMENT evidence and at most one unit of
        EXPERIENCE evidence, each resolved once. `follow_through` supersedes `outcome` for
        ENGAGEMENT exactly as before -- an accepted suggestion that was never acted on cannot keep
        the credit acceptance provisionally gave it. `enjoyment` no longer supersedes anything: it
        contributes to EXPERIENCE only, and only when `follow_through` says the person actually
        attended, so a verdict attached to `not_this_time`/`unable` (a fact about not attending,
        wherever the client happened to collect it) is never read as a taste report.

        `reason` is the optional one-tap `DeclineReason` already stored on the outcome row. It
        qualifies a `declined` outcome and nothing else: it selects the decline's weight from
        `_DECLINE_REASON_WEIGHTS` instead of the bare one, so "just a bad day" and a sensor
        correction stop teaching what a refusal teaches. `reason` never reaches EXPERIENCE, never
        supersedes a `follow_through`, and is ignored outright on any other outcome -- the
        contract calls it "only meaningful alongside `declined`", and a client that attaches
        `bad_day` to an acceptance must not be able to zero that acceptance out.
        """
        engagement_weights = None
        if follow_through:
            engagement_weights = _FOLLOW_THROUGH_WEIGHTS.get(follow_through)
        if engagement_weights is None and outcome == _DECLINED and reason is not None:
            engagement_weights = _DECLINE_REASON_WEIGHTS.get(reason, _OUTCOME_WEIGHTS[_DECLINED])
        if engagement_weights is None:
            engagement_weights = _OUTCOME_WEIGHTS.get(outcome)
        if engagement_weights is not None:
            self._fold(self._engagement, key, engagement_weights)
        # An outcome/follow-through this learner has no weight for is left alone rather than
        # guessed at. Silent no-ops are how a new OutcomeKind stops being learned from without
        # anything failing, so callers should keep `_OUTCOME_WEIGHTS` exhaustive over `OutcomeKind`.

        if enjoyment and follow_through in _ATTENDED_FOLLOW_THROUGHS:
            experience_weights = _ENJOYMENT_WEIGHTS.get(enjoyment)
            if experience_weights is not None:
                self._fold(self._experience, key, experience_weights)

    @staticmethod
    def _fold(scores: dict[str, list[float]], key: str, weights: tuple[float, float]) -> None:
        alpha, beta = scores[key]
        scores[key] = [alpha + weights[0], beta + weights[1]]

    def engagement_value(self, key: str) -> float:
        """P(this person would accept and follow through on this option again)."""
        alpha, beta = self._engagement[key]
        return round(alpha / (alpha + beta), 3)

    def experience_value(self, key: str) -> float:
        """E[enjoyment | attended], honest 0.5 when nobody has reported one yet."""
        alpha, beta = self._experience[key]
        return round(alpha / (alpha + beta), 3)

    def expected_value(self, key: str) -> float:
        """P(attend) x E[enjoy | attend] -- the ranking signal every caller outside this module
        uses. Kept as one number, exactly as before the split, because ranking is the only
        product surface this feeds: see the module-level docstring and the ADR for why the two
        components are not separately exposed beyond this module."""
        engagement_alpha, engagement_beta = self._engagement[key]
        experience_alpha, experience_beta = self._experience[key]
        engagement = engagement_alpha / (engagement_alpha + engagement_beta)
        experience = experience_alpha / (experience_alpha + experience_beta)
        return round(engagement * experience, 3)

    def snapshot(self, keys: list[str]) -> dict[str, float]:
        return {key: self.expected_value(key) for key in keys}


def _single_observation_deltas() -> list[float]:
    """Every `expected_value` movement one `record` call can produce from a fresh key, computed
    from the weight tables themselves rather than picked by hand.

    Enumerates every reachable single observation: a bare outcome (skipping `deferred`, which is
    deliberately zero-weight), a `declined` outcome paired with each `DeclineReason`, an
    `accepted` outcome paired with each follow-through, and an `accepted` outcome paired with
    each attended follow-through (`_ATTENDED_FOLLOW_THROUGHS`) and each enjoyment report -- the
    only combination where a single intervention can move both posteriors at once. A
    follow-through outside `_ATTENDED_FOLLOW_THROUGHS` paired with an enjoyment report is not
    enumerated separately: `record` never lets that combination touch EXPERIENCE, so its delta is
    identical to the same follow-through with no enjoyment at all, already covered above.

    The `declined x reason` arm exists because the reason table is a SECOND source of single-
    observation deltas and the bound below has to see all of them. At today's weights it changes
    nothing (every non-zero reason weight is exactly the bare decline's), but a future reason
    weight smaller than the current minimum would shrink this bound -- and if the enumeration
    could not see it, `SOCIAL_DIMENSION_RANKING_WEIGHT` would quietly become large enough to
    override the very observation that reason recorded, while every existing test kept passing.

    Exists for `sql_repository.SOCIAL_DIMENSION_RANKING_WEIGHT`, see `MIN_SINGLE_OBSERVATION_DELTA`
    below and ADR 0005: the ranking nudge must never be large enough to override what a single
    real observation taught, and that bound has to be re-derived from these tables, not
    hardcoded, so a future retune of the weights cannot silently invalidate it.
    """
    baseline = PreferenceLearner().expected_value("_probe")
    deltas: list[float] = []

    for outcome, weights in _OUTCOME_WEIGHTS.items():
        if weights == (0.0, 0.0):
            continue
        learner = PreferenceLearner()
        learner.record("_probe", outcome)
        deltas.append(learner.expected_value("_probe") - baseline)

    for reason in _DECLINE_REASON_WEIGHTS:
        learner = PreferenceLearner()
        learner.record("_probe", _DECLINED, reason=reason)
        deltas.append(learner.expected_value("_probe") - baseline)

    for follow_through in _FOLLOW_THROUGH_WEIGHTS:
        learner = PreferenceLearner()
        learner.record("_probe", "accepted", follow_through)
        deltas.append(learner.expected_value("_probe") - baseline)

    for follow_through in _ATTENDED_FOLLOW_THROUGHS:
        for enjoyment in _ENJOYMENT_WEIGHTS:
            learner = PreferenceLearner()
            learner.record("_probe", "accepted", follow_through, enjoyment)
            deltas.append(learner.expected_value("_probe") - baseline)

    return [delta for delta in deltas if abs(delta) > 1e-9]


# The smallest-magnitude change any single recorded intervention can produce in `expected_value`,
# from a key with no prior evidence at all. Recomputed from `_OUTCOME_WEIGHTS`/
# `_DECLINE_REASON_WEIGHTS`/`_FOLLOW_THROUGH_WEIGHTS`/`_ENJOYMENT_WEIGHTS` at import time (not
# hardcoded), so a future retune of any weight table keeps this constant correct rather than
# silently stale. See
# `sql_repository.SOCIAL_DIMENSION_RANKING_WEIGHT` and ADR 0005 for what this bounds.
MIN_SINGLE_OBSERVATION_DELTA = min(abs(delta) for delta in _single_observation_deltas())
