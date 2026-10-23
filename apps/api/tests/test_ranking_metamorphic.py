"""Metamorphic properties of the activity ranker, over the ranking benchmark's own catalogue and
core personas (10 personas x 6 query templates = 60 cases, every property run over all of them).

The policy ladder has had four such properties since `test_evaluation.py:728`; the ranker had
none. A metamorphic test needs no ground truth: it states a relation between two runs
("permuting the input must not change the output"; "saying you avoid something must never raise
it"), which is exactly the kind of claim a graded benchmark cannot make -- and the kind of claim
that survives a change to the labels.

Three conventions, all deliberate:

* Each property is ONE test that folds over all 60 cases and reports every failing
  `(persona, template, activity_id)` in its message, so a failure names the cases rather than
  reducing to a boolean.
* Each property also counts the cases it actually exercised and asserts that count is non-zero, so
  a property cannot pass vacuously because every case was skipped.
* A property that fails TODAY is marked `xfail(strict=True)` with the opportunity-matrix row that
  will fix it. The suite then DOCUMENTS the flaw -- and fails loudly the day the flaw is fixed and
  the marker goes stale -- instead of being quietly weakened until it is green.

Two production passes deliberately move a candidate for reasons unrelated to its score:
`_dedupe_series` defers the second session of a programme below the top three, and `_diversify`
swaps one candidate of another kind into third place. A direction property that ignored them would
be asserting that those passes do not exist, so the properties below compare positions only among
candidates neither pass touched (`Run.untouched`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from silverloop.activity_search import (
    ActivityEngagement,
    RankedScore,
    filter_candidates,
    rank_candidates_with_breakdown,
)
from silverloop.evaluation.ranking.dataset import (
    CATALOGUE,
    CORE_PERSONAS,
    FROZEN_TODAY,
    QUERY_TEMPLATES,
    PersonaBrief,
    QueryTemplate,
)
from silverloop.evaluation.ranking.traces import build_engagement, build_preferences
from silverloop.local_time import at_local
from silverloop.models import (
    ActivityCandidate,
    ActivityEnvironment,
    ActivityIntent,
    ActivityPreferences,
    DimensionPreference,
    IndoorOutdoor,
    PreferenceDimension,
)

CASES: list[tuple[PersonaBrief, QueryTemplate]] = [
    (persona, template) for persona in CORE_PERSONAS for template in QUERY_TEMPLATES
]


def _case(persona: PersonaBrief, template: QueryTemplate) -> str:
    return f"{persona.person_id}/{template.name}"


@dataclass(frozen=True)
class Run:
    """One ranked case: the inputs that produced it, and the order it produced."""

    kept: list[ActivityCandidate]
    intent: ActivityIntent
    preferences: ActivityPreferences
    engagement: dict[str, ActivityEngagement]
    today: date
    rain_forecast: bool
    ranked: list[RankedScore]

    @property
    def order(self) -> list[str]:
        return [item.ranked.candidate.activity_id for item in self.ranked]

    def position(self, activity_id: str) -> int:
        return self.order.index(activity_id)

    def untouched(self) -> set[str]:
        """Candidates neither post-scoring pass moved (see the module docstring)."""
        return {
            item.ranked.candidate.activity_id
            for item in self.ranked
            if not item.breakdown.series_deferred and not item.breakdown.variety_promoted
        }


def build_run(
    persona: PersonaBrief,
    template: QueryTemplate,
    *,
    catalogue: list[ActivityCandidate] | None = None,
    intent: ActivityIntent | None = None,
    preferences: ActivityPreferences | None = None,
    engagement: dict[str, ActivityEngagement] | None = None,
    today: date = FROZEN_TODAY,
    rain_forecast: bool | None = None,
) -> Run:
    """One case, with any single input replaced. The filter runs on the same inputs as the rank,
    so a changed catalogue or date is honoured by both halves of the pipeline."""
    catalogue = list(CATALOGUE) if catalogue is None else catalogue
    intent = template.build_intent(persona) if intent is None else intent
    preferences = build_preferences(persona) if preferences is None else preferences
    engagement = build_engagement(persona) if engagement is None else engagement
    rain = template.rain_forecast if rain_forecast is None else rain_forecast
    kept, _ = filter_candidates(catalogue, intent, today=today)
    ranked = rank_candidates_with_breakdown(
        kept,
        intent,
        preferences,
        rain_forecast=rain,
        engagement=engagement,
        today=today,
    )
    return Run(
        kept=kept,
        intent=intent,
        preferences=preferences,
        engagement=engagement,
        today=today,
        rain_forecast=rain,
        ranked=ranked,
    )


def _stated_avoid(dimension: PreferenceDimension, value: str) -> DimensionPreference:
    """A person saying outright that they do not want something -- the strongest negative signal
    the preference store carries, and the one `dimension_score` lets override inference."""
    return DimensionPreference(
        dimension=dimension,
        value=value,
        strength=-1.0,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=at_local(FROZEN_TODAY, 12, 0),
        stated_text="Not that one, please.",
    )


def _report(failures: list[str], checked: int, *, property_name: str) -> None:
    assert checked > 0, f"{property_name} exercised no case at all"
    assert not failures, f"{property_name} failed on {len(failures)} case(s):\n" + "\n".join(
        failures
    )


# ── Invariance: changing something the ranker must not read changes nothing ────────────────────


def test_permuting_the_candidate_input_order_does_not_change_the_ranking() -> None:
    """The order the catalogue happens to arrive in is not evidence about anything."""
    failures: list[str] = []
    checked = 0
    permutations = {
        "reversed": list(reversed(CATALOGUE)),
        "rotated": [*CATALOGUE[17:], *CATALOGUE[:17]],
    }
    for persona, template in CASES:
        base = build_run(persona, template)
        for name, permuted in permutations.items():
            checked += 1
            other = build_run(persona, template, catalogue=permuted)
            if other.order != base.order:
                differs = next(
                    index
                    for index, (left, right) in enumerate(zip(base.order, other.order, strict=True))
                    if left != right
                )
                failures.append(
                    f"{_case(persona, template)} ({name}): rank {differs + 1} is "
                    f"{base.order[differs]} but {other.order[differs]} after permuting"
                )
    _report(failures, checked, property_name="permutation invariance")


def test_renaming_every_provider_does_not_change_the_ranking() -> None:
    """`provider` is half the series key and appears on the card; it is not a sort key and carries
    no score. Renaming every provider consistently keeps the series groupings identical."""
    renamed = [
        candidate.model_copy(update={"provider": f"Renamed {candidate.provider}"})
        for candidate in CATALOGUE
    ]
    failures: list[str] = []
    for persona, template in CASES:
        if (
            build_run(persona, template).order
            != build_run(persona, template, catalogue=renamed).order
        ):
            failures.append(_case(persona, template))
    _report(failures, len(CASES), property_name="provider-rename invariance")


def test_renaming_every_title_order_preservingly_does_not_change_the_ranking() -> None:
    """`title` IS the ranker's last tie-break -- deliberately, so two otherwise identical listings
    always come out in the same order. The honest property is therefore that a rename which
    preserves the RELATIVE ORDER of titles preserves the ranking: nothing else about a title (its
    length, its words) may move a listing. The premise is asserted before it is relied on.
    """
    titles = sorted({candidate.title for candidate in CATALOGUE})
    assert sorted(f"{title} (Session)" for title in titles) == [
        f"{title} (Session)" for title in titles
    ]
    renamed = [
        candidate.model_copy(update={"title": f"{candidate.title} (Session)"})
        for candidate in CATALOGUE
    ]
    failures: list[str] = []
    for persona, template in CASES:
        if (
            build_run(persona, template).order
            != build_run(persona, template, catalogue=renamed).order
        ):
            failures.append(_case(persona, template))
    _report(failures, len(CASES), property_name="title-rename invariance")


def test_changing_the_location_name_does_not_change_the_ranking() -> None:
    """Distance is scored; the name of the place is not."""
    renamed = [
        candidate.model_copy(
            update={"location": candidate.location.model_copy(update={"name": "Somewhere Else"})}
        )
        for candidate in CATALOGUE
    ]
    failures: list[str] = []
    for persona, template in CASES:
        if (
            build_run(persona, template).order
            != build_run(persona, template, catalogue=renamed).order
        ):
            failures.append(_case(persona, template))
    _report(failures, len(CASES), property_name="location-name invariance")


def test_shifting_the_whole_world_by_a_week_does_not_change_the_ranking() -> None:
    """Move every session, the request's own date, the simulated today and the person's decline
    history forward by exactly seven days -- the same weekday, the same hours, the same gaps. The
    ranker reads dates only as day-of-week, time-of-day and elapsed days, so nothing may move.
    """
    shift = timedelta(days=7)
    shifted_catalogue = [
        candidate.model_copy(
            update={
                "start_at": candidate.start_at + shift if candidate.start_at else None,
                "retrieved_at": candidate.retrieved_at + shift,
            }
        )
        for candidate in CATALOGUE
    ]
    failures: list[str] = []
    for persona, template in CASES:
        base = build_run(persona, template)
        intent = template.build_intent(persona)
        if intent.on_date is not None:
            intent = intent.model_copy(update={"on_date": intent.on_date + shift})
        engagement = {
            activity_id: ActivityEngagement(
                interested=value.interested,
                not_for_me=value.not_for_me,
                went=value.went,
                enjoyed=value.enjoyed,
                last_not_for_me=(
                    value.last_not_for_me + shift if value.last_not_for_me is not None else None
                ),
            )
            for activity_id, value in build_engagement(persona).items()
        }
        other = build_run(
            persona,
            template,
            catalogue=shifted_catalogue,
            intent=intent,
            engagement=engagement,
            today=FROZEN_TODAY + shift,
        )
        if other.order != base.order:
            failures.append(_case(persona, template))
    _report(failures, len(CASES), property_name="+7-day shift invariance")


def test_the_persons_name_and_language_do_not_change_an_unconstrained_ranking() -> None:
    """`display_name` never reaches the ranker at all, and `preferred_language` reaches it only
    through an explicit language constraint. With no such constraint in the request, neither may
    move a listing -- a listing is not a better fit because of who is asking.
    """
    failures: list[str] = []
    checked = 0
    for persona, template in CASES:
        base = build_run(persona, template)
        if base.intent.language is not None:
            continue  # this template asks for the person's language on purpose
        renamed = PersonaBrief(
            person_id=persona.person_id,
            display_name="Someone Else (synthetic)",
            mobility_radius_m=persona.mobility_radius_m,
            tight_mobility_radius_m=persona.tight_mobility_radius_m,
            preferred_language="Tamil",
            stated_tastes=persona.stated_tastes,
            soft_avoids=persona.soft_avoids,
            hard_avoids=persona.hard_avoids,
            trace=persona.trace,
        )
        intent = template.build_intent(renamed)
        assert intent.language is None
        checked += 1
        other = build_run(renamed, template, intent=intent, preferences=base.preferences)
        if other.order != base.order:
            failures.append(_case(persona, template))
    _report(failures, checked, property_name="name/language invariance")


# ── Direction: a signal against something must never promote it ────────────────────────────────


def test_a_stated_avoid_on_a_category_never_raises_a_listing_of_that_category() -> None:
    """The person says, in their own words, that they do not want this kind of thing. Nothing in
    the ranker may read that as a reason to show it sooner."""
    failures: list[str] = []
    checked = 0
    for persona, template in CASES:
        base = build_run(persona, template)
        categories = [
            candidate.category for candidate in base.kept[:6] if candidate.category is not None
        ]
        if not categories:
            continue
        avoided = categories[0]
        preferences = ActivityPreferences(
            person_id=persona.person_id,
            dimensions=[
                *base.preferences.dimensions,
                _stated_avoid(PreferenceDimension.CATEGORY, avoided),
            ],
        )
        checked += 1
        other = build_run(persona, template, preferences=preferences)
        comparable = base.untouched() & other.untouched()
        for candidate in base.kept:
            if candidate.category != avoided or candidate.activity_id not in comparable:
                continue
            before = base.position(candidate.activity_id)
            after = other.position(candidate.activity_id)
            if after < before:
                failures.append(
                    f"{_case(persona, template)}: {candidate.activity_id} ({avoided}) rose from "
                    f"rank {before + 1} to {after + 1} after the person said they avoid {avoided}"
                )
    _report(failures, checked, property_name="stated-avoid direction")


def test_moving_one_listing_further_away_never_raises_it() -> None:
    """Distance costs, on `friction` and on the sort's own tie-break. It never pays."""
    failures: list[str] = []
    checked = 0
    for persona, template in CASES:
        base = build_run(persona, template)
        # A MIDDLE-ranked subject, not the first one: a candidate already at rank 1 can only fall,
        # so testing "never rises" on it would pass whatever the ranker did.
        eligible = [
            item.ranked.candidate
            for item in base.ranked
            if item.ranked.candidate.distance_m is not None
            and item.ranked.candidate.activity_id in base.untouched()
        ]
        subject = eligible[len(eligible) // 2] if eligible else None
        if subject is None or subject.distance_m is None:
            continue
        # Stay inside any distance constraint the request made, so this tests the SCORE rather
        # than re-testing the hard filter.
        ceiling = base.intent.max_distance_m or 10_000
        further = min(subject.distance_m + 700, ceiling)
        if further <= subject.distance_m:
            continue
        catalogue = [
            candidate.model_copy(update={"distance_m": further})
            if candidate.activity_id == subject.activity_id
            else candidate
            for candidate in CATALOGUE
        ]
        other = build_run(persona, template, catalogue=catalogue)
        if subject.activity_id not in other.untouched():
            continue
        checked += 1
        before = base.position(subject.activity_id)
        after = other.position(subject.activity_id)
        if after < before:
            failures.append(
                f"{_case(persona, template)}: {subject.activity_id} rose from rank {before + 1} "
                f"to {after + 1} when it moved from {subject.distance_m} m to {further} m"
            )
    _report(failures, checked, property_name="distance direction")


def test_saying_not_for_me_today_never_raises_that_listing() -> None:
    """Their most recent word about that exact listing. It is the one thing allowed to pull a
    matching listing down a tier, and it must never push one up."""
    failures: list[str] = []
    checked = 0
    for persona, template in CASES:
        base = build_run(persona, template)
        eligible = [
            item.ranked.candidate
            for item in base.ranked
            if item.ranked.candidate.activity_id in base.untouched()
        ]
        subject = eligible[len(eligible) // 2] if eligible else None
        if subject is None:
            continue
        engagement = dict(build_engagement(persona))
        existing = engagement.get(subject.activity_id)
        engagement[subject.activity_id] = ActivityEngagement(
            interested=existing.interested if existing else 0,
            not_for_me=(existing.not_for_me if existing else 0) + 1,
            went=existing.went if existing else 0,
            enjoyed=existing.enjoyed if existing else 0,
            last_not_for_me=FROZEN_TODAY,
        )
        other = build_run(persona, template, engagement=engagement)
        if subject.activity_id not in other.untouched():
            continue
        checked += 1
        before = base.position(subject.activity_id)
        after = other.position(subject.activity_id)
        if after < before:
            failures.append(
                f"{_case(persona, template)}: {subject.activity_id} rose from rank {before + 1} "
                f"to {after + 1} after a 'not for me' today"
            )
    _report(failures, checked, property_name="not-for-me direction")


def test_rain_never_raises_an_outdoor_listing_when_the_environment_was_left_open() -> None:
    failures: list[str] = []
    checked = 0
    for persona, template in CASES:
        dry = build_run(persona, template, rain_forecast=False)
        if dry.intent.environment != ActivityEnvironment.EITHER:
            continue
        wet = build_run(persona, template, rain_forecast=True)
        checked += 1
        comparable = dry.untouched() & wet.untouched()
        for candidate in dry.kept:
            if (
                candidate.indoor_outdoor != IndoorOutdoor.OUTDOOR
                or candidate.activity_id not in comparable
            ):
                continue
            before = dry.position(candidate.activity_id)
            after = wet.position(candidate.activity_id)
            if after < before:
                failures.append(
                    f"{_case(persona, template)}: outdoor {candidate.activity_id} rose from rank "
                    f"{before + 1} to {after + 1} once it was raining"
                )
    _report(failures, checked, property_name="rain direction")


def test_rain_changes_nothing_when_the_person_asked_for_a_specific_environment() -> None:
    """An explicit ask is honoured regardless of the forecast: the rain nudge is a better-fit
    nudge, not a safety override, so with the environment named it must be a complete no-op --
    same order, same totals, same reason lines."""
    failures: list[str] = []
    checked = 0
    for persona, template in CASES:
        dry = build_run(persona, template, rain_forecast=False)
        if dry.intent.environment == ActivityEnvironment.EITHER:
            continue
        checked += 1
        wet = build_run(persona, template, rain_forecast=True)
        if dry.order != wet.order:
            failures.append(f"{_case(persona, template)}: the order moved")
            continue
        for left, right in zip(dry.ranked, wet.ranked, strict=True):
            if left.breakdown.total != right.breakdown.total or [
                reason.text for reason in left.ranked.reasons
            ] != [reason.text for reason in right.ranked.reasons]:
                failures.append(
                    f"{_case(persona, template)}: {left.ranked.candidate.activity_id} changed "
                    "score or reasons"
                )
    _report(failures, checked, property_name="explicit-environment rain no-op")


def test_a_fuller_intent_match_never_ranks_below_a_lesser_one() -> None:
    """The tier invariant, as a property over all 60 cases rather than one hand-built example:
    nothing learned, inferred, promoted for variety or nudged by the weather may lift a candidate
    that matched less of what the person asked for above one that matched more.

    Compared only among candidates no post-scoring pass moved: `_dedupe_series` defers a second
    session of the same programme below the top three by design, which is a statement about the
    slate rather than about the fit.
    """
    failures: list[str] = []
    checked = 0
    for persona, template in CASES:
        run = build_run(persona, template)
        comparable = run.untouched()
        tiers = {
            item.ranked.candidate.activity_id: round(
                sum(
                    factor.value
                    for factor in item.breakdown.factors
                    if factor.name in ("intent", "repetition")
                ),
                3,
            )
            for item in run.ranked
        }
        checked += 1
        for index, item in enumerate(run.ranked):
            activity_id = item.ranked.candidate.activity_id
            if activity_id not in comparable:
                continue
            for later in run.ranked[index + 1 :]:
                later_id = later.ranked.candidate.activity_id
                if later_id not in comparable:
                    continue
                if tiers[later_id] > tiers[activity_id]:
                    failures.append(
                        f"{_case(persona, template)}: {later_id} (tier {tiers[later_id]}) ranks "
                        f"below {activity_id} (tier {tiers[activity_id]})"
                    )
    _report(failures, checked, property_name="tier invariant")
