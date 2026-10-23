# ADR 0006 — Preference resolution, ordinal axes, and `forget` as a retraction

Status: **Accepted** (2026-09-15, lead decision: built on
`feat/personalisation-ranking-worldmodel-v2` and `feat/activity-ranker-inspector`, and amended
twice after the Activity Ranker Inspector made its consequences visible — see the two amendments at
the end. Proposed 2026-09-13.)
Date: 2026-09-13
Supersedes nothing. Amends ADR 0004 (run scoping) in one place: `forget`.
Related: `docs/personalisation-v2-decisions.md` §5–§7, §10–§12;
`docs/audits/personalisation-v2/review-core.md` §2.1, §2.2, §2.6–§2.10, §6 N3–N7.

## Context

`activity_dimension_preferences.strength` was one signed scalar carrying three different facts at
once: which way a belief leans, how much evidence sits behind it, and how confident that makes it.
Four independent audits found four separate defects that all trace back to that one conflation, and
to the same shortcut on the write side — recording a _label_ for something the person expressed as
a _number_.

The four, in the words of what a person would notice:

1. Someone states three preferences in plain words. All three are read, all three match every
   listing in the catalogue, and the order does not change — because the score summed matched rows
   only and divided by their own weights, so matching one was arithmetically identical to matching
   three. The card then printed "Nothing learned applies to this listing" whenever a like and an
   avoid happened to cancel.
2. Someone says a 1.2 km walk is too far. The system records `distance = near, −0.333` — the
   bucket the listing fell in — and from then on demotes everything within 2 km of their home and
   leaves everything beyond it untouched. It learned the opposite of what they said.
3. Someone says a session was too tiring. The listing carries no intensity, so the write side
   substitutes `moderate`: a fact nobody asserted, about a level the listing never claimed, and one
   that contradicts the catalogue row the belief was derived from.
4. Someone says "not for me" to a morning walk. `category` holds a _format_ label, so this teaches
   a dislike of every other "Group class" — tai chi, gardening, a pool session — nine unrelated
   programmes from one tap.

## Decision

### 1. A resolver, not a scalar

`preferences.resolve(rows, today, run_id) -> list[ResolvedPreference]` is the only thing the ranker
reads about a person. It is **derived per request and never persisted**, the same read-model
discipline `world_model.build_world_model` already keeps: a second store of the same belief is a
second thing that can be wrong.

Evidence is counted on both sides (`positive_evidence`, `negative_evidence`), and the two numbers
people actually mean are derived from them separately:

```
strength   = (pos − neg) / (pos + neg + 2)     which way it leans
confidence = (pos + neg) / (pos + neg + 2)     how much sits behind it
```

Both are order-independent by construction, which is what fixes "it was fine" after "I loved it"
erasing the endorsement while the same two reports in the other order kept it. `0.0` can finally be
told apart from "two things that disagree": `coverage` and `evidence_count` travel beside it.

`evidence_count` counts **distinct origins**. A person saying one thing three times is one person
saying it.

### 2. `SourceTier` wins an axis; it never averages into one

`DEFAULT < WEAK_LEARNED < STRONG_LEARNED < STATED_GOAL < STATED < RATIFIED < TEMPORARY_STATED <
CURRENT_REQUEST`. Within one axis only the highest active tier contributes. The per-source weight
table that used to blend them existed to rank evidence _classes within_ an axis and was being used
as a mixer _across_ them, so a guess could halve something a person said in plain words.

`CURRENT_REQUEST` never enters preference utility at all. An axis the person constrained _today_
belongs to the hard filter or to `request_fit`; scoring it again from history is a double count,
and it lets what was learned last month argue with what was asked for this morning.

### 3. Ordinal axes

DISTANCE and INTENSITY carry a `pivot` and a `direction` rather than a value from a list. "Too far
at 1.2 km" is a ceiling; "too tiring at moderate" is a rung. `tolerance_m` starts at the 500 m
default, a floor (somewhere further the person enjoyed getting to) may raise it, and `min(pivot)`
over the active ceilings then caps it — the tightest thing a person has said is the one that
binds, and a ceiling only ever narrows: "1.2 km was too far" is a complaint about 1.2 km, not a
discovery that everything nearer is free (read as the tolerance itself, it made a 2 km listing
cheaper because the person had complained). Rejected: an
exponentially-smoothed or quantile tolerance (a smoothing constant with no evaluation behind it),
and a penalty normalised by the person's own ceiling (it punishes someone with a 500 m limit ten
times harder per metre than someone with a 5 km one, which is a claim about their mobility that no
evidence here supports).

### 4. One owner per signal

`travel_utility(distance_m, tolerance_m) = −clip((d − tolerance)/SCALE, 0, 1)` is **the only place
distance is scored**. It absorbs the learned ceiling by moving where the cost starts, not by adding
a term. `_friction`, the learned near/far bucket and the dead `_NEAR_THRESHOLD_M` are gone.
`environment_compatibility(ask, listing) -> Tri` is the one environment rule, shared by the filter,
the preference reader, the rain nudge and the evaluation harness — three copies used to coexist and
disagree about whether "sheltered" counted as indoors, so a listing could be filtered in on one
reading and scored out on another.

`ACTIVITY_TYPE` replaces `CATEGORY` as the content axis and as the diversity key.

### 5. UNKNOWN is neither a penalty nor free

`Tri = MATCH | MISMATCH | UNKNOWN`; `None` on either side is UNKNOWN, never MISMATCH. UNKNOWN is
excluded from the numerator **and** the denominator of every fit — it used to land in the
denominator as a miss, and because the tier is the primary sort key nothing learned, no history and
no weather could lift that listing back. Excluding it from the denominator alone would trade that
error for its mirror (an unanswerable listing scoring exactly like a confirmed match), so the count
of matched axes is a sort key after the weighted total.

Consequence worth stating plainly: a listing that answers fewer of the asks but contradicts none of
them can now outrank one that answers all of them and contradicts one. That is the ratio semantics
working as intended — a mismatch is a "no", an unlisted field is not — and `coverage` is reported so
the difference is visible rather than inferred.

### 6. `forget` becomes a retraction — **an observable change**

`PreferenceStance.FORGET` used to delete every row on a `(dimension, value)`. It now stamps
`superseded_by`: readers skip the row, the Privacy screen shows nothing, and the response still
carries `preference: null` and `removed_rows`.

To the person, nothing changes: they tap "Forget this" and the belief is gone. Two things change
behind it. The record of what Care+ once believed, and of them striking it out, is no longer
quietly rewritten — and the next observation on that key starts a fresh belief from zero rather
than resurrecting a count they believed they had erased, which is a hole the evidence-count model
would otherwise have opened.

A person can still forget the fresh belief. Retraction is not a mute.

### 7. Ratification consumes rather than duplicates

"That's right" on an inferred belief stamps `superseded_by` on the inferred row and records what it
consumed in `origin_id` (which is what puts the statement at `RATIFIED`). It used to write a second
row beside the first and touch neither, so both rendered — and on a reversed stance the orphan
became a contradiction the system had manufactured against a belief the person had just agreed with.

### 8. What is kept

- The six factor names and every `RANKING_WEIGHTS` value. No retune until the benchmark can see
  format-vs-content, dry days and soft distance (review §7).
- `strength` and `observations` as stored columns: `world_model.py` and the Privacy screen read
  them, and a revision that dropped them would be a contract change smuggled inside a storage one.
- `PreferenceDimension.CATEGORY` as a deprecated member — never written, never removed, still
  readable and still forgettable. A person must be able to delete a belief this product already
  holds about them.
- ADR 0004's run-scoping rule, unchanged.
- ADR 0005's bound: `social_shape_score` stays in [-1, 1] _structurally_, because it returns
  `ResolvedPreference.strength` through the same arithmetic `preference_utility` uses and that
  field is a Pydantic `Field(ge=-1, le=1)`.

## Consequences

**Migration.** One additive Alembic revision (`e1c9a5d70b42`) and one idempotent Supabase mirror.
Every column is nullable; the backfill splits `observations` by the sign of `strength`, so every
pre-existing belief resolves to exactly the strength it already had and nothing changes meaning at
the moment it runs.

**Benchmark.** The headline numbers move slightly and within their confidence intervals. They are
not the evidence for this change and should not be read as such: five of the six query templates
cannot see format-versus-content, every case is a rainy day, and soft distance is unexercised. The
evidence is the twelve named defects and the tests that pin each one. Re-authoring the benchmark
(review P1.10) gates any weight change.

**What is deferred.** `ActivityFamily` half-strength generalisation; recency decay on item
affinity; a multiplicative `context_suitability`; retiring the weighted `intent` term and `_tier`.
`GoalKind.GET_OUT_MORE` and `LESS_TRAVEL` are **not** folded into preferences: the first names a
frequency rather than a kind, and the second names a direction with no number in it — and DISTANCE
is ordinal now, so mapping it would mean inventing a pivot nobody said, which is the fabrication
this whole change exists to remove.

> **Superseded 2026-09-15 (second-round amendment) for `LESS_TRAVEL`.** It now maps to DISTANCE
> `near` with no pivot, and a stated "near" narrows travel tolerance to a named radius
> (`preferences.NEARBY_RADIUS_M`) without inventing a pivot — see "DISTANCE statements with no
> number" below. `GET_OUT_MORE` is still not folded in.

## Amendment — 2026-09-15: resolution groups, tier versus credit, goal resolver keys

Recorded after the Activity Ranker Inspector made three consequences of this ADR visible
(`docs/ranker-inspector-spec.md` D13, D17, D20). Additive: the decisions above stand except where
this section narrows them.

### §2 narrowed — a tier wins a _resolution group_, not always a whole axis

"Within one axis only the highest active tier contributes" was applied per dimension everywhere.
On ACTIVITY_TYPE that was wrong: one temporary "no walks this week" out-tiered, and so silenced, a
standing "I like arts and crafts" and every learned "not for me" on any other kind of activity.

`preferences._resolution_group(observation)` now decides the set within which a tier wins:

- **Per axis** — TIMING, ENVIRONMENT and SOCIAL (the axes where a mismatch is evidence: morning is
  not afternoon), and the ordinal axes DISTANCE and INTENSITY (every belief is a line on one scale,
  and the tightest winning line must bind the others).
- **Per (axis, value)** — ACTIVITY_TYPE and the deprecated CATEGORY. Saying something about one
  kind of activity says nothing about another, which is also why a different type is UNKNOWN rather
  than a mismatch (§5).

Two beliefs on the **same** value still settle by tier: the higher wins and the lower is shown
through `contradicted_by`; at equal tiers both win and, leaning opposite ways, cancel.
`ResolvedPreference.winning_tier` is the winning tier of the belief's own group.

### §5 extended — the tier is not the intent credit

A listing that states none of the axes the request constrained (every one UNKNOWN) used to earn a
full request fit: `intent` contributed its whole weight, and the card had no honest "as you asked"
line to show for it. Excluding UNKNOWN from both sides of the fit (§5) is kept; what changes is that
the one number was doing two jobs.

- **Credit** (the `intent` factor value, weighted into the total): `matched / judged` when anything
  was judged; `0.0` when axes were constrained but nothing could be judged; `0.0` when nothing was
  constrained.
- **Tier fit** (the first sort key): the same ratio when anything was judged; `1.0` when axes were
  constrained but nothing could be judged, so an unanswerable listing is not demoted below one that
  answers and mismatches; `0.0` when nothing was constrained.
- `ScoreBreakdown.tier = round(tier_fit + repetition.value, 3)` is recorded on the breakdown and is
  what the sort, the ablations and the audit read. It is no longer "the intent value plus
  repetition", and the `unjudged_request_fit` "silent by design" class is gone because there is no
  longer unexplained intent credit to be silent about.

### Goal resolver keys

A goal and a statement on the same value used to share one resolver key
(`dimension:value:senior_statement`), so a stated "avoid" beside a goal for that value was
reported contradicting itself. A goal-derived observation is now named
`goal:{dimension}:{value}` (`preferences.goal_key`) in `supporting` and `contradicted_by`; no
stored row's key can collide with it. `world_model._mark_contradictions` maps a goal key to its
`goal:{kind}` fact and says "your own words say otherwise" only when the other side is a
statement — a goal is a choice from a list, not the person's own words.

### Which answers count toward widening — superseded

_Superseded the same day by the second-round amendment below ("A repeat answer about the same
programme is not a second answer")._ As first amended, agreement was counted by distinct origin (one
recorded response), so a second unclarified "not for me" on the very same session, given on another
day, widened the belief to the whole activity type or time slot; counting per programme was recorded
as a follow-up that seemed to need a schema change. It did not: see below.

### Which side of a contradiction applies

`PersonFact.contradiction_outcome` (`this_applies`, `other_applies`, `neither_applies`,
`undecided`) and `PersonFact.in_effect` are computed in `world_model._mark_contradictions` from
the resolver's own `tier == winning_tier`, so a surface never ranks fact kinds itself.
`neither_applies` covers an axis-resolved dimension where a higher-tier belief on a different value
makes both contradicting beliefs unused.

## Amendment — 2026-09-15 (second round): programmes, distance, reasons on expand, wording

Recorded when the items the first amendment left open were closed (`docs/WAYFINDER.md`,
"Remaining-item fixes — delivered 2026-09-15 (round 2)"). Additive: the decisions and the first
amendment stand except where this section narrows them. No schema change.

### A repeat answer about the same programme is not a second answer

An unclarified item-level answer — "not for me" with no chip (`THIS_ONE`) or "bad timing" with no
chip (`THIS_SLOT`) — is held back until a second one agrees (`preferences._is_held_back`). An
item-level answer now adds evidence only when it is about a **different programme**
(`activity_search.series_key`: provider and title) from the programme of the belief's **latest
origin**. The rule is the same for ACTIVITY_TYPE and TIMING.

`preferences.apply_decline` takes the answer's `series` and an `origin_series` map (origin id →
programme), and `_fold` leaves the belief unchanged — no evidence added, no widening — when the new
answer is item-level, the row is not restarting after a retraction or a consuming statement, and
`origin_series[row.origin_id]` is the new answer's `series`. The rule does not depend on how much
evidence the belief already holds or on its scope: a repeat item-level answer about the latest
origin's programme adds nothing even after the belief has widened, including a belief a chip
widened. So:

- The same listing declined twice, unclarified, on different days: still held back, and
  `preferences_updated` is empty.
- A sibling session of the same programme: the same.
- An outreach decline on a programme, then a search decline on that programme's listing: the same.
  An outreach `programme:` key resolves to its catalogue listing's programme, or to the programme
  key itself when no listing matches.
- A different programme with the same activity type or time slot: counts, and widens a held-back
  belief as before.
- A belief that has already widened (by agreement or by a chip): a further unclarified answer about
  its latest origin's programme adds no evidence.
- A clarification chip (`time_of_day`, `weekday`, `this_activity_type`) is not item-level, so it
  still widens at once and adds that answer's evidence, on any programme.
- No `series`, or an origin whose programme cannot be found (a legacy row with no `origin_id`):
  the first-round behaviour, where distinct origins count.
- A retry of the same response (same origin) never counts twice, and a legacy ACTIVITY_TYPE
  decline row with `scope = NULL` is read as `this_one` — both unchanged.

**A bounded approximation.** The row stores only its latest `origin_id`, so the comparison is with
the latest origin's programme, not with every programme the belief has seen. Alternating
programmes — river walk, park walk, river walk — still count each answer, because by the third the
latest origin is the park walk. Remembering every origin's programme would need a stored set per
row; the approximation errs toward counting an answer, and only when the person has genuinely
answered about more than one programme.

Why no schema change: the row keeps its single `origin_id`, and the repository resolves origin ids
to programmes read-only when it applies an answer (`sql_repository._origin_series`, by id lookup
through the offer response's listing or the intervention's candidate key, never by parsing an id's
prefix; `_series_for_candidate_key` for the new answer). The Ranker Inspector's feedback preview
and scripted histories register their synthetic origins' programmes
(`ranker_inspector.InspectionState.origin_series`) before folding, so a preview on the same
programme applies no new fact, exactly as the product would. The evaluation's trace replay passes
each event's programme; no persona repeats a decline on one programme, and its artifacts did not
move.

### DISTANCE statements with no number

A stated "near" (`prefer near`, or `avoid far`) carries no pivot. It used to resolve in the same
per-axis group as the learned ceilings, so its tier silenced them while it contributed nothing
itself: `travel_tolerance_m` reads only lines with a pivot.

- **Two groups of their own, by lean.** `_resolution_group` puts a DISTANCE row with no pivot in
  `(DISTANCE, "unpivoted_near")` when it leans near (`near` liked, `far` avoided, the
  `LESS_TRAVEL` goal) and in `(DISTANCE, "unpivoted_far")` when it leans far (`far` liked, `near`
  avoided). Lines with a pivot still resolve per axis (first amendment). A statement with no number
  no longer out-tiers a learned ceiling, and a far-leaning statement, which is never read, cannot
  out-tier and so silence a near-leaning one.
- **It narrows, and only through a named radius.** `preferences.NEARBY_RADIUS_M = 1000` is the one
  radius "near" means, shared with the intent parser's "near me" phrase. `travel_beliefs` also
  returns winning near-leaning unpivoted beliefs at a stated tier (STATED_GOAL, STATED, RATIFIED,
  TEMPORARY_STATED), and `travel_tolerance_m` applies them after the floors and ceilings:
  `min(tolerance, NEARBY_RADIUS_M)`. A learned 650 m ceiling stays 650 m; a learned 2 km floor
  comes down to 1 km; the 500 m default is untouched. `travel_tolerance_basis` (and the inspector's
  `travel_cost_start_basis`) reads `stated_near` when that step binds — the radius is at or below
  the tolerance it replaces — and `travel_utility`'s note says so. No pivot is invented: the radius
  is a named constant, not a number attributed to the person.
- **It never widens.** A far-leaning statement has no effect on the tolerance at any tier —
  widening from words with no number in them would be the fabrication §3 exists to prevent — and,
  resolving apart, it cannot silence a stated or goal "near" either. A person with the
  `LESS_TRAVEL` goal who also says they like going further keeps the 1 km cap until they stop the
  goal.
- **What the inspector and the world model report.** A far-leaning statement is
  `not_used_reason = never_widens` at any tier; an outranked near-leaning one is
  `not_winning_tier`; a learned DISTANCE row with no pivot (the retired near/far bucket) is
  `no_distance_line`. DISTANCE is never reported `deprecated_axis`; it is a live axis.
  `preferences.belief_in_effect` is the one definition of "the ranker reads this belief": it wins
  its group, and on DISTANCE with no number it is also a stated near-leaning belief. The world
  model's `PersonFact.in_effect` reads it, so a far-leaning or learned no-number DISTANCE belief is
  never shown as in effect.
- `GoalKind.LESS_TRAVEL` maps to `(DISTANCE, "near")` at `STATED_GOAL` and behaves exactly like a
  stated "near". This supersedes the Consequences sentence above for `LESS_TRAVEL`.

### Reasons beyond three are shown when the card is opened

`activity_search._compose_reasons` returns the lines it keeps and the rest. The card face still
shows at most three (`RankedActivity.reasons`); every other eligible line is carried in
`RankedActivity.more_reasons` and shown when the card is opened: the senior card's details
disclosure reads "More details and reasons" when there are extra reasons, and lists them under
"More reasons it may suit you". No eligible line is left off: `reasons` and `more_reasons`
together are every eligible line (VARIETY included), and `reasons_suppressed == len(more_reasons)`.
A variety rebuild composes over `[*reasons, *more_reasons, VARIETY]`, so the face of a card that
was not promoted is unchanged. The bounded planner still sees only `reasons`.

In the inspector trace, `CandidateTrace.more_reasons` is read from the final entry; the integrity
class `capped` is renamed `on_expand` (`IntegrityClass`, and `TraceIntegrity.on_expand`) and means
the factor's line is in `more_reasons`; the classifier and the inverse check read only
`reasons_shown` and `more_reasons`; `TraceVarietySwap.more_reasons_after` replaces
`reasons_dropped`; and `reasons_before_composition` is the scoring-time list before composition and
before any variety rebuild. This supersedes "left off by design" (decisions §12 amendment;
`docs/ranker-inspector-spec.md` D12).

### A stated belief is worded as stated

A PREFERENCE line is a subject (`activity_search._preference_subject`: what about the listing
matches) followed by a clause chosen by the belief's own tier, which is its winning tier. Lines are
comma-phrased; none uses a dash.

| Tier                         | Line                                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| STATED, RATIFIED             | "{subject}, which you said you like."                                                                                                                                                                                                                                                                                                                                              |
| TEMPORARY_STATED             | "{subject}, as you asked for the time being."                                                                                                                                                                                                                                                                                                                                      |
| STATED_GOAL                  | "{subject}, which is one of your goals."                                                                                                                                                                                                                                                                                                                                           |
| WEAK_LEARNED, STRONG_LEARNED | environment "{label}, which you've liked before."; intensity "{label}, which has suited you before."; intensity ceiling "{label}, easier than an activity you found too tiring."; social "With other people, which you've enjoyed before." or "Something to do on your own, which has suited you before."; activity type "{Label}, which you've enjoyed before."; timing unchanged |

A stated, ratified, temporary or goal line never says "before": the person told Care+, and
nothing was inferred from their past. Two neighbouring lines follow the same style: the rain line
(CONTEXT) is "{label}, a better fit with rain around today.", and the catalogue filler is the
catalogue's own label alone ("Group class."). The filler no longer says "near you": it is shown
whatever the listing's distance, so it cannot claim nearness. When the card face would hold only
the filler, the senior card hides its "Why this may suit you" heading and list, because the label
only restates what the card already shows.
