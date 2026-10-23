"""Offline probes over a replayed run's `PersonWorldModel` and the facts that feed ranking (M38).

`WorldModelQuality` already counts explicit / inferred / confirmed / temporary / stale /
expired_excluded / contradicted facts. Those answer "is the model larger?". None of them answers
the question that matters for a memory feature: **is any of this remembered thing actually used,
and when it is used, does it change anything?** A model can grow indefinitely while every fact in
it is decoration.

Two probe families, both pure functions:

- `probe_world_model(snapshots)` -- counts over an ordered sequence of snapshots of one person's
  model. A sequence rather than a single snapshot because `corrected` and `rejected` are
  transitions: a fact whose value changed under the same key, and an inferred fact a later
  statement reversed. Neither is visible in a snapshot.
- `probe_fact_contribution(cases)` -- **leave-one-out** over the dimension preferences that back
  the person's learned facts, re-running the production ranker
  (`activity_search.rank_candidates_with_breakdown`) once per fact per case. Removing a fact and
  re-ranking is a measurement of contribution, not a judgement of truth, which is why calling
  production ranking here is read-only in the sense that matters: nothing is written, no
  permission is widened, and the ranker is not being scored against a label it helped produce.

Module boundary: like the rest of `silverloop.evaluation`, this file imports no repository, no
`config` and no agent. A `PersonWorldModel` is passed IN by the caller -- the test builds one
through the real repository and hands it over -- so the probes stay reproducible and the harness
stays database-free.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from silverloop.activity_search import (
    ActivityEngagement,
    RankedScore,
    rank_candidates_with_breakdown,
)
from silverloop.models import (
    ActivityCandidate,
    ActivityIntent,
    ActivityPreferences,
    FactSourceType,
    PersonFact,
    PersonWorldModel,
)

#: The sources that count as the person speaking for themselves. A value change under one of
#: these is a CORRECTION; a value change between two inferred readings is just the learner moving.
STATED_SOURCE_MARKERS = ("senior_statement", "statement", "ratified")

DEFAULT_TOP_K = 3

#: The one `ScoreFactor` a dimension preference can move. Named here so "was this fact read at
#: all" is a question about a specific factor rather than about the total, which every other
#: factor also moves.
PREFERENCE_FACTOR = "preference"


def _is_stated(fact: PersonFact) -> bool:
    if fact.source_type == FactSourceType.EXPLICIT:
        return True
    return any(marker in fact.source for marker in STATED_SOURCE_MARKERS)


@dataclass(frozen=True)
class WorldModelProbe:
    """Counts, never rates -- the same discipline `WorldModelQuality` keeps."""

    facts: int
    explicit: int
    inferred: int
    confirmed: int
    stale: int
    contradictions: int
    single_evidence: int
    corrected: int
    """Facts whose `value` changed under the same `key` and whose later reading came from the
    person's own words. This is the model being put right, and it is the one transition a
    memory feature must be able to show a person happening."""
    rejected: int
    """Facts that existed as INFERRED and whose value was then reversed by a statement -- the
    learner was contradicted, not merely updated. A subset of `corrected` by construction; both
    are reported because "the model was corrected 3 times" and "3 of those corrections overturned
    something we had guessed" are different sentences."""
    total_evidence: int
    snapshots: int

    @property
    def avg_evidence_count(self) -> float | None:
        if not self.facts:
            return None
        return round(self.total_evidence / self.facts, 4)


def probe_world_model(snapshots: Sequence[PersonWorldModel]) -> WorldModelProbe:
    """Counts over an ordered sequence of one person's world-model snapshots.

    The final snapshot supplies the static counts (what the model IS); the sequence supplies
    `corrected` and `rejected` (what the model DID). An empty sequence probes to all zeros rather
    than raising: a run that never built a model is a legitimate, reportable outcome.
    """
    if not snapshots:
        return WorldModelProbe(
            facts=0,
            explicit=0,
            inferred=0,
            confirmed=0,
            stale=0,
            contradictions=0,
            single_evidence=0,
            corrected=0,
            rejected=0,
            total_evidence=0,
            snapshots=0,
        )

    latest = snapshots[-1]
    corrected_keys: set[str] = set()
    rejected_keys: set[str] = set()
    previous: dict[str, PersonFact] = {}
    for snapshot in snapshots:
        for fact in snapshot.facts:
            earlier = previous.get(fact.key)
            if earlier is not None and earlier.value != fact.value and _is_stated(fact):
                corrected_keys.add(fact.key)
                if earlier.source_type == FactSourceType.INFERRED:
                    rejected_keys.add(fact.key)
            previous[fact.key] = fact

    quality = latest.quality
    return WorldModelProbe(
        facts=quality.facts,
        explicit=quality.explicit,
        inferred=quality.inferred,
        confirmed=quality.confirmed,
        stale=quality.stale,
        contradictions=quality.contradictions,
        single_evidence=quality.single_evidence,
        corrected=len(corrected_keys),
        rejected=len(rejected_keys),
        total_evidence=sum(fact.evidence_count for fact in latest.facts),
        snapshots=len(snapshots),
    )


@dataclass(frozen=True)
class RankingCase:
    """One search the person actually made, replayed offline so a fact can be removed from it."""

    case_id: str
    candidates: tuple[ActivityCandidate, ...]
    intent: ActivityIntent
    preferences: ActivityPreferences
    rain_forecast: bool = False
    engagement: Mapping[str, ActivityEngagement] = field(default_factory=dict)
    today: date | None = None


@dataclass(frozen=True)
class FactContribution:
    """The leave-one-out split, as `n/d` over (fact, case) pairs.

    `facts_explanation_only` is the honest measure of decorative memory: the fact was read, it
    reached a reason line the person was shown, and removing it changed nothing about what they
    were shown. A memory feature whose facts are overwhelmingly explanation-only is telling people
    it remembers them without letting that memory cost it anything.
    """

    pairs: int
    facts_consulted: int
    facts_that_changed_top_k: int
    facts_explanation_only: int
    cases: int
    top_k: int

    @property
    def facts_never_read(self) -> int:
        return self.pairs - self.facts_consulted


def _top_k_ids(ranked: Sequence[RankedScore], top_k: int) -> tuple[str, ...]:
    return tuple(item.ranked.candidate.activity_id for item in ranked[:top_k])


def _top_k_reasons(ranked: Sequence[RankedScore], top_k: int) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(sorted(reason.text for reason in item.ranked.reasons)) for item in ranked[:top_k]
    )


def _preference_contributions(ranked: Sequence[RankedScore]) -> dict[str, float]:
    contributions: dict[str, float] = {}
    for item in ranked:
        for factor in item.breakdown.factors:
            if factor.name == PREFERENCE_FACTOR:
                contributions[item.ranked.candidate.activity_id] = factor.contribution
    return contributions


def probe_fact_contribution(
    cases: Sequence[RankingCase], *, top_k: int = DEFAULT_TOP_K
) -> FactContribution:
    """One `rank_candidates_with_breakdown` call per fact per case, plus one baseline per case.

    For each (case, dimension preference) pair:

    - **consulted** -- removing the preference moves any candidate's `preference` factor. If it
      does not, the ranker never read the fact for this case at all.
    - **changed_top_k** -- removing it changes the SET of activity ids in the top K. Set, not
      order: a swap the person would never notice is not a contribution.
    - **explanation_only** -- the top-K reason lines change but the top-K set does not. The fact
      was shown to the person and cost nothing.

    Comparing whole reason lines rather than string-matching a preference value into them keeps
    this independent of how any reason happens to be worded.
    """
    pairs = 0
    consulted = 0
    changed = 0
    explanation_only = 0

    for case in cases:
        baseline = rank_candidates_with_breakdown(
            list(case.candidates),
            case.intent,
            case.preferences,
            rain_forecast=case.rain_forecast,
            engagement=case.engagement,
            today=case.today,
        )
        baseline_ids = _top_k_ids(baseline, top_k)
        baseline_reasons = _top_k_reasons(baseline, top_k)
        baseline_contributions = _preference_contributions(baseline)

        for index in range(len(case.preferences.dimensions)):
            pairs += 1
            without = case.preferences.model_copy(
                update={
                    "dimensions": [
                        dimension
                        for position, dimension in enumerate(case.preferences.dimensions)
                        if position != index
                    ]
                }
            )
            ablated = rank_candidates_with_breakdown(
                list(case.candidates),
                case.intent,
                without,
                rain_forecast=case.rain_forecast,
                engagement=case.engagement,
                today=case.today,
            )
            was_read = _preference_contributions(ablated) != baseline_contributions
            moved_set = _top_k_ids(ablated, top_k) != baseline_ids
            moved_reasons = _top_k_reasons(ablated, top_k) != baseline_reasons

            if was_read:
                consulted += 1
            if moved_set:
                changed += 1
            elif moved_reasons:
                explanation_only += 1

    return FactContribution(
        pairs=pairs,
        facts_consulted=consulted,
        facts_that_changed_top_k=changed,
        facts_explanation_only=explanation_only,
        cases=len(cases),
        top_k=top_k,
    )


__all__ = [
    "DEFAULT_TOP_K",
    "FactContribution",
    "RankingCase",
    "WorldModelProbe",
    "probe_fact_contribution",
    "probe_world_model",
]
