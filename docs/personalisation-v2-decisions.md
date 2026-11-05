# Personalisation v2 — canonical domain decisions

Settled before implementation so no module invents a competing version. Each decision names what
it replaces, whether it needs a migration (**MIG**) or a contract change (**CONTRACT**, i.e.
`models.py` → `pnpm client:generate`), and the test that pins it.

## 1. `ActivityCandidate` schema — MIG, CONTRACT

Three added fields, every existing one kept: `activity_type: ActivityType | None`,
`activity_families: list[ActivityFamily]`, `format: Format | None`. `category` stays as a display
badge populated from the format label and is **no longer a learner axis or a diversity key**.
Provenance fields on the listing row: `metadata_source`, `last_verified_at` (nullable). Venue
coordinates stay unpopulated until an adapter fills them; `distance_basis` is stored, not inferred
from nullness.

## 2. Activity taxonomy — new `silverloop/ontology.py`

`ActivityType` (WALKING, TAI_CHI, CHAIR_EXERCISE, STRETCH, DANCE, SWIMMING, GARDENING, ARTS_CRAFTS,
COOKING, GAMES, KARAOKE, LEARNING, VOLUNTEERING, SOCIAL_MEETUP, MINDFULNESS, READING, OTHER),
`ActivityFamily` (MOVEMENT, MIND_BODY, CREATIVE, SOCIAL, LEARNING, NATURE, VOLUNTEERING),
`Format` (GROUP_CLASS, GROUP_ACTIVITY, DROP_IN_GROUP, SELF_GUIDED, ONE_TO_ONE).
`TYPE_FAMILIES` is the multi-label map; `ALIASES` is the one alias table (English, Singlish,
Chinese; longest phrase first) shared by the keyword parser, catalogue normalisation and tests.
Rules: the parser never emits `OTHER`; `OTHER` never matches an intent; an unknown word stays in
`unparsed_terms`; the LLM tool enum is generated from the enum at import; fixture listings carry
hand-authored values and a test proves `normalise(title, description)` reproduces them.

## 3. Programme vs session

A programme (series) is `(provider, title)`; a session is one `activity_id`. No new tables.
`_series_key` is the one definition; affinity, cooldown and dedupe are series-scoped with a
per-session override. One resolver maps an outreach `programme:` key to its catalogue listing so
outreach declines reach the same axes as search declines.

**Amendment (D18) — one series key, and the card headlines the best-ranked session.**
`activity_search.series_key(candidate)` is the one public definition (provider and title, trimmed
and case-folded) and `series_keys_for(candidates)` maps listings to it; dedupe, the engagement
roll-up and the repository all read it. `RankedActivity.series_key` carries it to the client
(**CONTRACT**), so the senior screen groups sessions by the ranker's key instead of its own
title + location key, and a result without a key is never grouped. A grouped card headlines the
first session of its series in the API's order — the best-ranked — so the session "I'm interested"
plans is the one the ranker placed; "Also on" lists the others soonest first. The sort breaks
otherwise-equal sessions by `start_at` (soonest first, undated last), so among equally good sessions
the soonest already leads.

## 4. `PreferenceObservation` (append-only, derived)

A frozen dataclass rebuilt at read time from the rows that already exist (offer responses,
intervention outcomes, plan follow-through and enjoyment, statements, goals): `origin`,
`origin_id`, `kind`, `dimension`, `sentiment` (like/avoid/neutral/retract), `value` (nominal) or
`pivot` + `direction` (ordinal), `scope`, `source_tier`, `weight`, `observed_on_day`, `run_id`,
`expires_on_day`, `evidence_id`, `origin_activity_id`. No new table.

## 5. `ResolvedPreference` (derived, never persisted) — MIG, CONTRACT

`preferences.resolve(rows, today, run_id)` is the only thing the ranker reads. Fields: dimension,
value or pivot+direction, sentiment, categorical confidence, `positive_evidence`,
`negative_evidence`, `evidence_count` (distinct origins), `winning_tier`, `weight ∈ [0, 1]`, scope,
`expires_on_day`, source, run_id, `superseded_by`, `stated_text`, `supporting`, `contradicted_by`.
`strength = (pos − neg)/(pos + neg + 2)`, `confidence = (pos + neg)/(pos + neg + 2)`, exposed
separately. `activity_dimension_preferences` gains `positive_evidence`, `negative_evidence`,
`pivot`, `direction`, `origin_id`, `superseded_by`, `scope` (all nullable; backfilled from
`observations` and the sign of `strength`). `strength`/`observations` are kept.
`PreferenceDimension.CATEGORY` is deprecated: never written, never removed; `ACTIVITY_TYPE` is the
content axis.

## 6. Source hierarchy — CONTRACT

`SourceTier`: DEFAULT < WEAK_LEARNED (1–2 origins, weight ≤ 0.35) < STRONG_LEARNED (≥ 3 agreeing)
< STATED_GOAL < STATED < RATIFIED (a statement that consumed an inferred row) < TEMPORARY_STATED
< CURRENT_REQUEST. Within one axis only the highest active tier contributes; across axes
contributions sum. `CURRENT_REQUEST` never enters preference utility: an axis the person
constrained today belongs to the filter (hard) or request fit (soft).

**Amendment (D17, D20).** "Within one axis" is now "within one resolution group": per
axis for TIMING, ENVIRONMENT, SOCIAL, DISTANCE and INTENSITY; per (axis, value) for ACTIVITY_TYPE
and the deprecated CATEGORY. Same-value conflicts settle by tier (higher wins, lower shown via
`contradicted_by`; equal tiers cancel). A goal-derived belief resolves under its own key
`goal:{dimension}:{value}`, never a statement's. See ADR 0006, first amendment.

**Second-round amendment — distance statements with no number.** DISTANCE lines with a
pivot (learned ceilings and floors) resolve per axis as above. A DISTANCE row with no pivot
resolves in one of two groups of its own, by lean: `(DISTANCE, "unpivoted_near")` for `near`
liked, `far` avoided and the `LESS_TRAVEL` goal; `(DISTANCE, "unpivoted_far")` for `far` liked or
`near` avoided. So a statement with no number no longer out-tiers a learned ceiling, and a
far-leaning statement can neither widen the distance nor silence a stated or goal "near". A winning
near-leaning belief at a stated tier (STATED_GOAL, STATED, RATIFIED or TEMPORARY_STATED) narrows
the travel tolerance to `min(tolerance, preferences.NEARBY_RADIUS_M)` (1000 m) after the learned
lines; a far-leaning one is never read at any tier (inspector `never_widens`), so the
`LESS_TRAVEL` goal beside a stated "far" keeps the 1 km cap. `preferences.belief_in_effect` is the
one definition of a belief the ranker reads, and the world model's `in_effect` uses it: a
far-leaning or learned no-number DISTANCE belief is never in effect. `GoalKind.LESS_TRAVEL` now
maps to `(DISTANCE, "near")`. See ADR 0006, second-round amendment.

## 7. Scope hierarchy

current request > temporary explicit > persistent explicit > strong learned > weak learned >
default. ADR 0004's run-scoping stands: standing statements carry `run_id = None` and survive a
reset; everything else is run-scoped. Temporary statements carry `expires_on_day` on the person's
calendar.

**FORGET** becomes a retraction: it stamps `superseded_by` on every matching row instead of
deleting, readers skip superseded rows, the Privacy screen shows nothing, and the next tap cannot
resurrect the belief. (Observable change; recorded in ADR 0006.)

## 8. Outcome taxonomy

A derived funnel view, no migration:
`SHOWN → ASKED_FOR_MORE → PLANNED → ATTENDED(completed|partial) → VERDICT(enjoyed|okay|not_for_me)`;
side exits `DECLINED(reason, clarification)`, `NO_RESPONSE`, `DEFERRED`, `MISSED(not_this_time|
did_not_go)`, `UNABLE_TODAY`, `CANCELLED`, `PROGRAMME_UNAVAILABLE`, `OUTCOME_UNKNOWN`.
Administrative closure is never enjoyment. Enjoyment requires an attending follow-through.
Engagement and experience stay two posteriors (ADR 0005); outreach weights become reason-aware
and `_single_observation_deltas` enumerates reason × outcome so the social tie-break bound stays
structural.

## 9. `ActivityIntent` — CONTRACT

Added: `activity_types` (soft, ≤5), `excluded_activity_types`, `excluded_environments`,
`excluded_social` (all hard), `distance_is_explicit` (true only when a number was given),
`suggested_types` (server-side, for the confirm card). Negation: a ≤3-token negator look-back
produces an `excluded_*` entry and **never** a positive value on any axis; the negated needle is
consumed and rendered ("Not outdoors"). Tokeniser accepts CJK runs; content words leave the axis
tables for the alias table; `preferred_language` is a disclosed soft default.

## 10. Hard vs soft constraints — the rule

> A hard rule exists only where a mismatch is a barrier the person cannot cross (a distance they
> gave as a number, a day, a time window, an environment, company, capacity, language) or where
> they explicitly excluded something. Everything else is soft. A hard rule is never re-scored
> softly; a soft axis is never promoted to a filter.

| Field                                                                    | Hard?                                 |
| ------------------------------------------------------------------------ | ------------------------------------- |
| `on_date`, `time_window`, `environment`, `social_preference`, `language` | hard (unchanged)                      |
| `max_distance_m`                                                         | hard only when `distance_is_explicit` |
| `intensity`, `activity_types`, a distance phrase                         | soft (request fit)                    |
| `excluded_*`                                                             | hard                                  |

A distance _phrase_ ("close by", "near home") is spent twice on purpose and charged once: its
implied radius is a request-fit axis (does this listing sit inside what was asked, which moves
the tier) and the same radius narrows the travel tolerance for that one request to
`min(learned tolerance, asked radius)` inside `travel_utility`, which is where the gap is costed.
It never widens a learned ceiling, and a number still filters rather than costs.

**Second-round amendment — a standing "near" is soft in the same way.** A stated or goal
"near" with no number (see §6, round 2) is not a hard rule either: it narrows the tolerance to
`preferences.NEARBY_RADIUS_M`, the same 1000 m radius a "near me" phrase implies (`intent.py`
imported the constant until the search route and its parser were removed), and is costed only in `travel_utility` (basis `stated_near` when it binds).
It never removes a listing and never widens a learned ceiling; a far-leaning statement ("far"
liked, "near" avoided) changes nothing and cannot cancel a stated or goal "near".

## 11. Missing-data semantics

`Tri = MATCH | MISMATCH | UNKNOWN`; `None` on either side is UNKNOWN, never MISMATCH. UNKNOWN is
excluded from both numerator and denominator of every fit; at equal fit the candidate with more
MATCH axes wins the tie-break, so unknown is never negative and never free; UNKNOWN is disclosed
as a catalogue reason line ("Language not listed"). Every write-side fallback is deleted: no
fabricated `moderate`, no `or "far"`, no unconditional `social`. Clarification chips (optional,
skippable): `bad_timing → TimingScope{time_of_day, weekday, this_slot}`; `not_for_me →
DislikeScope{this_activity_type, this_format, this_venue, this_one}`; enjoyment
`not_for_me → DislikedAspect{people, location, activity, timing, pace, environment}`. Unclarified
means item-level only. Accessibility is never inferred from behaviour.

**Amendment (D7) — what "unclarified" means for each reason.** An unclarified answer is
item-level and held back from the resolved set until a second agreeing answer arrives
(`preferences._is_held_back`; since round 2, below, a repeat answer about the same programme as
the belief's latest origin adds nothing):

- `not_for_me` with no chip is recorded `THIS_ONE` (it used to resolve at once, so one tap on a
  walk became a standing dislike of every walk). The `this_activity_type` chip widens it
  immediately; `this_one`, `this_venue` and `this_format` teach no activity-type belief at all.
- `bad_timing` with no chip is recorded `THIS_SLOT`; `time_of_day` and `weekday` widen it.
- **Ordinal exception:** `too_far` and `too_tiring` carry no item-level scope and are never held
  back. They write a ceiling at the listing's own distance or intensity straight away, because
  they are a statement about that number, not about the kind of thing.

**Second-round amendment — a repeat answer about the same programme adds nothing.** An
unclarified `THIS_ONE` or `THIS_SLOT` answer adds evidence only when it is about a different
programme (`activity_search.series_key`) from the programme of the belief's latest origin, whatever
the belief's evidence count or scope. The same listing declined again on another day, a sibling
session, or an outreach decline followed by a search decline on the same programme leaves a
held-back belief held back and `preferences_updated` empty; the same repeat after the belief has
widened (by agreement or by a chip) adds nothing either. A different programme with the same type
or time slot counts and widens a held-back belief. A chip still widens at once. A row with no known
origin programme (no `origin_id`, or none the repository can resolve) keeps the first-round rule,
where distinct origins count. Only the latest origin is stored, so alternating programmes (river,
park, river) still count each answer — a documented, bounded approximation. No schema change: the
repository resolves origin ids to programmes read-only (`sql_repository._origin_series`). See ADR
0006, second-round amendment.

## 12. Candidate score architecture

```
eligible = hard rules (7 today + exclusion rules)
features = extract(candidate)                          # one place; Tri comparisons only
utility  = w_r·request_fit + w_p·preference_utility + w_a·item_affinity
         + w_c·context_suitability + w_t·travel_utility
tier     = request_fit_tier + repetition_hold           # kept
order    = (−tier, −utility, −matched_axes, distance, title)
then     = series dedupe → tier-aware diversify → bounded LLM rerank (promotion cap) → top-K
```

One responsibility per signal: distance is _costed_ only in `travel_utility` (absorbing the
learned tolerance, narrowed to the radius a phrase asked for today; the request-fit axis only says
whether a listing sits inside what was asked and never charges for the gap); environment is filtered once and nudged once by rain only when the person left it
open; an axis constrained today contributes 0 preference utility. The six existing factor names
and `RANKING_WEIGHTS` values are kept in this pass; weights are not retuned until the re-authored
benchmark can see dry days, soft distance and format-vs-content.

**Amendment (D1, D11–D13, D15, D18) — as built.**

- **Sort key**, in order: `tier` (descending), weighted `total` (descending), `matched_axes`
  (descending), `distance_m` (ascending, unknown last), `title`, `start_at` (ascending, undated
  last), `activity_id`. `activity_search.SortKey.ordering()` is the one definition and
  `sort_key_for(candidate, breakdown)` builds it; series dedupe runs before the variety check.
- **Tier is not the intent value.** `ScoreBreakdown.tier` is recorded by scoring as
  `round(tier_fit + repetition, 3)`. A listing that states none of the constrained axes gets
  intent credit `0.0` but tier fit `1.0` (ADR 0006 amendment, §5), so it keeps its tier without
  unexplained score.
- **Reason composition** (`_compose_reasons`): only a line whose factor contributed positively is
  eligible (intent, preference, history→engagement, context); a VARIETY line is always kept; then
  one line per remaining basis, largest positive contribution first; free slots take further lines
  in basis order; lines display in basis order. With more than three positive bases the smallest
  contributor is left off by design and counted, so `reasons_suppressed` always equals eligible
  minus shown — including on a card the variety check promoted.

**Second-round amendment — nothing is left off; the rest is shown on expand.** "Left off by
design" above is superseded. `_compose_reasons` returns the kept lines and the rest: the card face
shows at most three (`RankedActivity.reasons`) and every other eligible line is carried in
`RankedActivity.more_reasons` (**CONTRACT**) and shown when the card is opened, so `reasons` and
`more_reasons` together are every eligible line and `reasons_suppressed == len(more_reasons)`. A
variety rebuild composes over `[*reasons, *more_reasons, VARIETY]`; the planner still reads only
`reasons`. The inspector's integrity class `capped` is renamed `on_expand`. A PREFERENCE line's
clause follows the belief's tier, comma-phrased — "{subject}, which you said you like." (stated,
ratified), "{subject}, as you asked for the time being." (temporary), "{subject}, which is one of
your goals." (goal) — and only learned beliefs are worded as something from before. The catalogue
filler is the bare label ("Group class."), and the senior card hides "Why this may suit you" when
the face would hold only that filler. On the senior card the details disclosure reads "More details
and reasons" when `more_reasons` is not empty. See ADR 0006, second-round amendment.

## 13. World-model confidence semantics — CONTRACT (fields only)

`FactConfidence` stays categorical. `evidence_count` counts distinct origins. Learned facts cap
at MEDIUM; stated, ratified and temporary-stated facts may be HIGH. Staleness is measured on the
person's calendar. Consent facts read the evidence row's `source` (a seeded fixture is FIXTURE,
MEDIUM, unconfirmed). The fixture biography is described to any model as fixture, never as a
coordinator's words. Response hours use `local_hour`.

## 14. Context provenance

Rain and public holidays stay the two context sources; each carries provenance and freshness.
The simulator's `weather_turns` no longer mutates availability; it produces a replan offer with
reason `weather`.

## 15. Replanning semantics

Server-owned `ReplanOffer(offer_id, run_id, person_id, plan_id, reason ∈ {full, cancelled,
weather}, alternative_id, offered_at, resolved_at, resolution ∈ {accepted, declined, expired,
no_alternative})`. `advance()` writes the offer in the same transaction as the invalidation;
`replace` sets `replaced_reason`/`replaced_by_plan_id` on the old row and audits `replanned`;
replaced rows leave `awaiting_report`. Nothing is replaced silently.

## 16. Ranking metrics and benchmark

Persona-clustered paired bootstrap everywhere, `n_clusters` in every header, per-persona table,
stated/inferred-only strata. Headline: `NDCG@1`, `HitRate@3(rel=3)`, `slate_ndcg@3` over
`discriminable_cases`; graded `NDCG@3` in the technical table. Floors: random, catalogue order,
`intent_filter+static`. Arms: factor-contribution-zeroing per factor, per-preference-dimension,
`no_diversity` as the baseline for every `diversity=False` arm, `cold_start`, `first_signal`,
`trace_prefix:k`, `llm_recorded`. Policy harness: additive `world:` latent block, second label
column, agreement rate reported. Holdout frozen by digest.

## 17. LLM role

Unchanged in kind: parse intent to the same enums, rerank the deterministic top-N within the
permitted set under a promotion cap, word an outreach proposal under the guardrail. New: a
recorded-response provider so every role is measurable offline; provider errors logged by class
only; catalogue text fenced in every payload.

## 18. Consent

Parked (ADR 0001, Deferred). Existing gates unchanged.
