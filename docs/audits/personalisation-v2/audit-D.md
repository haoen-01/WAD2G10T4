# Audit D — Outcome / learning semantics

Worktree `/Users/ianpong/Projects/ismoggers-v2` @ 010aa96. Read-only. All numbers below were
produced by three throwaway scripts in this directory (`d_learner.py`, `d_repo.py`, `d_repo2.py`,
outputs in `*.out`), run as `cd apps/api && LLM_ENABLED=false ADAPTER_MODE=fixture uv run python <script>`
against an in-memory SQLite repository with fixture adapters.

Paths abbreviated: `L` = `apps/api/src/silverloop/learning.py`, `P` = `preferences.py`,
`M` = `models.py`, `R` = `sql_repository.py`, `S` = `activity_search.py`, `DB` = `db_models.py`,
`W` = `apps/web/...`.

---

## 0. The signal table — what every outcome touches today

Three independent stores learn from outcomes. None reads from another.

| Store                                                                                                             | Key                                                        | Written by                                                                                                      | Read by                                                                                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **A. Outreach learner** (`PreferenceLearner`, ENGAGEMENT × EXPERIENCE Beta posteriors)                            | outreach `candidate_key` (`gentle_nudge:*`, `programme:*`) | rebuilt from `intervention_outcomes` ⋈ `intervention_follow_through` ⋈ `intervention_enjoyment` (`R:2024-2075`) | `_rank_intervention_candidates` `R:2365-2418`, metrics, planner tool context                                                                                                         |
| **B. Dimension preferences** (`activity_dimension_preferences`, one row per `(person, dimension, value, source)`) | attribute                                                  | `apply_decline` `P:248-312`, `apply_enjoyment` `P:391-456`, `state_preference`                                  | `dimension_score` `P:503-523` (search factor `preference`, weight 2.0), `social_shape_score` `P:526-546` (outreach tie-break, weight 0.0043), world model, senior "Your preferences" |
| **C. Item engagement** (`ActivityEngagement` counts)                                                              | `activity_id`                                              | `activity_offer_responses`, `plan_follow_through`, `plan_enjoyment` per run (`R:4156-4222`)                     | `S:_engagement` (weight 1.5), `S:_repetition` (weight 2.0), `_history_reason`                                                                                                        |

Every signal a person (or the system) can emit, and what it moves:

| Signal                                                                  | Surface                                                                                                                                  | Store A (outreach learner)                                                                                                                         | Store B (dimension)                                                                                                                                                  | Store C (item)                                                                                    | Generalises?                                                      |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `accepted` ("Yes, tell me more")                                        | outreach                                                                                                                                 | ENG +(0.25, 0) → 0.556/0.278 (`L:22`)                                                                                                              | —                                                                                                                                                                    | —                                                                                                 | item                                                              |
| `declined`, **no reason**                                               | outreach                                                                                                                                 | ENG +(0, 1) → 0.333/0.167 (`L:23`)                                                                                                                 | —                                                                                                                                                                    | —                                                                                                 | item                                                              |
| `declined` + `bad_day`                                                  | outreach                                                                                                                                 | **same (0, 1) — reason never reaches learner** (`R:3005-3027`, proven §1)                                                                          | none (`P:66`)                                                                                                                                                        | —                                                                                                 | item                                                              |
| `declined` + `already_active`                                           | outreach                                                                                                                                 | **same (0, 1)** — a data-quality correction is scored as a refusal                                                                                 | none (`P:67`)                                                                                                                                                        | —                                                                                                 | item                                                              |
| `declined` + `not_for_me`                                               | outreach                                                                                                                                 | (0, 1)                                                                                                                                             | CATEGORY avoid `n/(n+2)` **only if candidate resolves with a category** — `programme:*` keys never do (`R:2749-2790`), `gentle_nudge:*` never resolve → nothing (§4) | —                                                                                                 | attribute (search only)                                           |
| `declined` + `too_far`                                                  | outreach / search card                                                                                                                   | (0, 1) / —                                                                                                                                         | DISTANCE avoid **bucket of the declined listing** (`near` if < 2 km, `P:131-134,180`)                                                                                | search: +1 `not_for_me`, cooldown 14 d                                                            | attribute, **wrong direction** (§3)                               |
| `declined` + `too_tiring`                                               | outreach / search card                                                                                                                   | (0, 1) / —                                                                                                                                         | INTENSITY avoid **the declined level**, fallback `moderate` when the listing has none (`P:181-186`)                                                                  | same                                                                                              | attribute, **no direction; fabricated value for programmes** (§5) |
| `declined` + `bad_timing`                                               | outreach / search card                                                                                                                   | (0, 1) / —                                                                                                                                         | TIMING avoid whole `morning`/`afternoon`/`evening` bucket (`P:137-145`)                                                                                              | same                                                                                              | attribute, over-general (§6)                                      |
| `declined` + `prefer_something_else`                                    | outreach / search card                                                                                                                   | (0, 1) / —                                                                                                                                         | none (`P:74`; `_weak_neutral_strength` `P:120-128` is dead code on this path)                                                                                        | same                                                                                              | item                                                              |
| `deferred` ("Maybe later")                                              | outreach                                                                                                                                 | (0, 0) (`L:30`)                                                                                                                                    | —                                                                                                                                                                    | —                                                                                                 | —                                                                 |
| `no_response` (system, after `RESPONSE_WINDOW_DAYS=2`, `R:213,869`)     | outreach                                                                                                                                 | (0, 0.5) → 0.4/0.2 (`L:26`)                                                                                                                        | —                                                                                                                                                                    | —                                                                                                 | item                                                              |
| `coordinator_resolved`                                                  | case review                                                                                                                              | **never written as an outcome row** (`R:5714-5785` writes `CaseReviewRow` + audit only; proven §11); the `(0,0)` table entry `L:21` is unreachable | —                                                                                                                                                                    | —                                                                                                 | —                                                                 |
| `activity_recovered`                                                    | `record_outcome` allows it (`R:2882`) but **nothing in the product emits it** (grep: only the allow-list and the counts filter `R:2106`) | (1, 0) full credit keyed to the candidate if ever sent — contradicts `docs/architecture.md:77-78` "not attributable to the offer"                  | —                                                                                                                                                                    | —                                                                                                 | —                                                                 |
| follow-through `completed`                                              | outreach                                                                                                                                 | replaces acceptance: (1, 0) → 0.667/0.333                                                                                                          | —                                                                                                                                                                    | —                                                                                                 | item                                                              |
| `partial`                                                               | outreach                                                                                                                                 | (0.6, 0.4) → 0.533/0.267                                                                                                                           | —                                                                                                                                                                    | —                                                                                                 | item                                                              |
| `not_this_time`                                                         | outreach                                                                                                                                 | (0.25, 0.75) → 0.417/0.208                                                                                                                         | —                                                                                                                                                                    | —                                                                                                 | item                                                              |
| `unable` (label **"I couldn't today"**, `W/lib/view-models.ts:480`)     | outreach                                                                                                                                 | **(0, 1) — identical to an outright decline** (`L:41`, proven §1)                                                                                  | —                                                                                                                                                                    | —                                                                                                 | item                                                              |
| enjoyment `enjoyed` / `okay` / `not_for_me` after `completed`/`partial` | outreach                                                                                                                                 | EXP (1,0)/(0.5,0.5)/(0,1) (`L:51-55`, `L:131-134`)                                                                                                 | liked aspects only (below)                                                                                                                                           | —                                                                                                 | item + attribute                                                  |
| enjoyment after `not_this_time`/`unable`                                | outreach                                                                                                                                 | EXP untouched (`L:62,131`)                                                                                                                         | **liked aspects still written** (`R:4677-4712` never checks the follow-through value; proven §2)                                                                     | —                                                                                                 | attribute — **from an outing that did not happen**                |
| liked `people`                                                          | either                                                                                                                                   | —                                                                                                                                                  | SOCIAL=`social` +`n/(n+2)` **always**, regardless of listing (`P:380-381`)                                                                                           | —                                                                                                 | attribute                                                         |
| liked `location`                                                        | either                                                                                                                                   | —                                                                                                                                                  | DISTANCE=**bucket of this listing** (`P:382-383`) — "liked where it was" becomes "prefers near"                                                                      | —                                                                                                 | attribute                                                         |
| liked `timing`                                                          | either                                                                                                                                   | —                                                                                                                                                  | TIMING=bucket                                                                                                                                                        | —                                                                                                 | attribute                                                         |
| liked `activity`                                                        | either                                                                                                                                   | —                                                                                                                                                  | CATEGORY=listing category                                                                                                                                            | —                                                                                                 | attribute                                                         |
| enjoyment `not_for_me` with nothing liked                               | either                                                                                                                                   | EXP (0,1) (outreach only)                                                                                                                          | **nothing** — no negative attribute evidence exists (`P:412-413`; proven §9)                                                                                         | C counts `went` +0.35 as positive (`S:631`)                                                       | —                                                                 |
| enjoyment `okay` + liked X after an earlier `enjoyed` + liked X         | either                                                                                                                                   | —                                                                                                                                                  | **collapses** the +0.333 to +0.075 (same `inferred` row, strength recomputed with the capped function, `P:415-417,429-443`; proven §7)                               | —                                                                                                 | —                                                                 |
| search `interested`                                                     | search card                                                                                                                              | —                                                                                                                                                  | —                                                                                                                                                                    | +0.25 each, **unbounded on re-taps** (`S:631`; proven §8)                                         | item                                                              |
| search `not_for_me` (any reason)                                        | search card                                                                                                                              | —                                                                                                                                                  | as above per reason                                                                                                                                                  | `repetition` −1 ×2.0 for 14 d, then `engagement` −0.5 ×1.5 (`S:632-633,647-656`)                  | item + attribute (§10 double count)                               |
| planned `went`                                                          | week                                                                                                                                     | —                                                                                                                                                  | —                                                                                                                                                                    | +0.35; grounds "You went to this one before." (`S:667-668`)                                       | item                                                              |
| planned `did_not_go`                                                    | week                                                                                                                                     | —                                                                                                                                                  | —                                                                                                                                                                    | counted, **not scored** (`S:624-626`)                                                             | —                                                                 |
| planned `cancelled`                                                     | week                                                                                                                                     | —                                                                                                                                                  | —                                                                                                                                                                    | not even counted (`R:4200-4210` only maps `went`/`did_not_go`)                                    | —                                                                 |
| planned enjoyment `enjoyed`                                             | week                                                                                                                                     | —                                                                                                                                                  | liked aspects                                                                                                                                                        | +0.4                                                                                              | item + attribute                                                  |
| planned enjoyment `okay` / `not_for_me`                                 | week                                                                                                                                     | —                                                                                                                                                  | liked aspects (capped for okay)                                                                                                                                      | **nothing; `went` +0.35 stands, "You went…" reason stands** (proven §9)                           | —                                                                 |
| programme unavailable / listing FULL                                    | `respond_to_activity` `R:4283-4287`                                                                                                      | —                                                                                                                                                  | —                                                                                                                                                                    | interest recorded (+0.25 engagement), not planned                                                 | —                                                                 |
| outcome unknown (planned day passed, no report)                         | week                                                                                                                                     | —                                                                                                                                                  | —                                                                                                                                                                    | `awaiting_report=true` (`R:5476`), nothing scored; **no expiry, reportable forever** (proven §12) | —                                                                 |
| senior `prefer`/`avoid` statement                                       | privacy screen                                                                                                                           | —                                                                                                                                                  | `senior_statement` ±1.0, supersedes inferred rows on that dimension (`P:485-493`)                                                                                    | —                                                                                                 | attribute                                                         |

Signals the taxonomy in the brief names that have **no representation at all**: _asked for more_ (is
`accepted`), _booked_ (the product books nothing — correct), _missed_ on the outreach side (folded
into `not_this_time`), _PROGRAMME_UNAVAILABLE_ as an outcome (it is a note string), _OUTCOME_UNKNOWN_
(implicit `None`).

---

## Findings

### 1. The outreach learner cannot tell "not today" from "not for me" — every decline and `unable` is a full-unit refusal

**Evidence.** `record_outcome` writes the reason to the outcome row (`R:3012-3021`) but
`_preference_learners` selects only `InterventionOutcomeRow.outcome` (`R:2035-2039`) and
`PreferenceLearner.record` has no reason parameter (`L:103-109`). `_OUTCOME_WEIGHTS["declined"] = (0.0, 1.0)`
(`L:23`), `_FOLLOW_THROUGH_WEIGHTS["unable"] = (0.0, 1.0)` (`L:41`).

```
$ uv run python d_repo.py   (section A/B)
gentle_nudge:chair_mobility  reason=bad_day        before=0.25 after=0.167
gentle_nudge:chair_mobility  reason=not_for_me     before=0.25 after=0.167
gentle_nudge:chair_mobility  reason=already_active before=0.25 after=0.167
gentle_nudge:chair_mobility  accepted->unable:     before=0.278 after=0.167 (declined gives 0.167)
```

So "Just a bad day" (`W/lib/view-models.ts:554`), "I am already getting about" (a _sensor
correction_ that `policy.py` treats as data quality, `M:73-76`) and "I couldn't today"
(`view-models.ts:480`) each teach "this option is a poor fit" as hard as "It is not for me".
The `bad_day`/`already_active` carve-out exists only for suppression (`R:3066-3074`) and for the
dimension learner (`P:66-67`), not for the posterior that actually orders outreach.

**Root cause.** The learner's input is the bare `OutcomeKind`; reason is treated as "context, not a
second answer" (`R:2984-2987`) — which is right for the _duplicate guard_ and wrong for the
_weight_.

**Severity.** P1. Three declines on bad days = 0.1 expected value and a suppression trigger is
reason-aware but the ranking is not.

**Substrate.** `InterventionOutcomeRow.reason` is already stored; `_latest_outcome_ids_subquery`
already yields one row per intervention; the amendment path already re-derives the learner.

**Design.** `PreferenceLearner.record(key, outcome, reason=None, follow_through=None, enjoyment=None)`
with a reason-keyed override table:

```python
_DECLINE_REASON_WEIGHTS: dict[str, tuple[float, float]] = {
    "bad_day": (0.0, 0.0),            # about the day
    "already_active": (0.0, 0.0),     # about the sensor
    "prefer_something_else": (0.0, 0.5),
    "bad_timing": (0.0, 0.5),         # about the slot, half a unit against this listing
    "too_far": (0.0, 1.0), "too_tiring": (0.0, 1.0), "not_for_me": (0.0, 1.0),
}
_FOLLOW_THROUGH_WEIGHTS["unable"] = (0.0, 0.5)   # "couldn't today" ≠ "won't"
```

and select `InterventionOutcomeRow.reason` in `_preference_learners`. Keep
`test_every_outcome_kind_has_a_learning_weight` exhaustive over `DeclineReason` too.

**Files.** `L`, `R:_preference_learners`, `apps/api/tests/test_learning_weights.py`,
`test_follow_through_api.py`. **Effort** S.

**Test.** `declined+bad_day` leaves `expected_value` at the prior; `declined+not_for_me` does not;
`unable` moves less than `declined`.

### 2. An enjoyment report on an outing that never happened still teaches attribute preferences

**Evidence.** `record_enjoyment` requires only _some_ follow-through (`R:4696-4699`) and calls
`_apply_activity_enjoyment` unconditionally (`R:4707-4709`). The web prompt claims otherwise
(`W/components/senior/enjoyment-prompt.tsx:12-14`: "only ever shown once `follow_through` is
`'completed'` or `'partial'` — see `senior-view.tsx`") but `senior-view.tsx:474-477` selects
`interventions.find((item) => item.follow_through && !item.enjoyment)` — so after "Not this time"
the person is asked "How was it?".

```
$ d_repo.py section C
programme:aac-chair-mobility accepted -> not_this_time -> enjoyment enjoyed liked=[people,location,timing]
status=200 preferences_updated=[('social','social',0.333), ('distance','near',0.333), ('timing','evening',0.333)]
candidate score=0.208  (EXPERIENCE untouched, DIMENSIONS moved)
```

ADR 0005 (`docs/adr/0005:114-120`) explicitly notes the API "does not currently forbid" this and
fixed it only for the EXPERIENCE posterior. The senior then sees "Care+ learned: you seem to
prefer activities with other people" (`W/lib/view-models.ts:1291-1294`) about something they did
not attend.

**Root cause.** Attendance precondition enforced in one consumer (`L:131`) not at the write
(`R:record_enjoyment`) nor in the web gate.

**Severity.** P1 (correctness of provenance: an attribute fact "inferred" from a non-event).

**Design.** In `record_enjoyment`: `if follow_through not in ("completed","partial"): raise ValueError("How it went can only be recorded once you have said you went.")` — mirroring `record_planned_enjoyment` (`R:4471-4474`). In `senior-view.tsx:476` gate on
`item.follow_through === 'completed' || item.follow_through === 'partial'`. Doc/code disagreement
to fix: `enjoyment-prompt.tsx:14` vs `senior-view.tsx:476`; `docs/api.md:177` ("enjoyment reported
before follow-through exists") should say "before an attending follow-through".

**Files.** `R`, `W/components/senior-view.tsx`, `docs/api.md`, `test_follow_through_api.py`. **Effort** S.

### 3. "Too far" learns _avoid near_ (confirms lead's flaw; senior-visible)

**Evidence.** `_distance_bucket` (`P:131-134`): `far` iff ≥ 2000 m. `_declined_value` records the
_declined listing's_ bucket (`P:180`). Fixture programme is 700 m; the walk listing 1.2 km.

```
$ d_learner.py §5
TOO_FAR at 1.2 km -> bucket: near ; stored [('distance','near',-0.333)]
dimension_score 300 m listing: -0.333 | 3000 m listing: 0.0
$ d_repo.py section D
programme:aac-chair-mobility reason=too_far -> [('distance','near','decline_reason',-0.333,1)]  (distance_m=700)
```

Senior copy after that tap: `summarizeDeclineLearning` → "Care+ will lean away from
**activities nearer home**" (`W/lib/view-models.ts:1244-1247,1302-1305`); Privacy screen
`describe_preference` → 'For distance, this person tends to avoid "near"' (`P:549-574`, proven).
Meanwhile the _client_ already does the right thing, ephemerally: `declineReasonIntentPatch`
(`W/lib/view-models.ts:1037-1040`) sets `max_distance_m = 0.6 × distance` — directional, but lost
on the next typed search and never persisted.

**Root cause.** DISTANCE is a categorical dimension with two buckets; a decline stores a _value_
where the person asserted a _direction_ (`P:169-178` docstring says "the direction the decline
itself asserted" but stores a bucket).

**Severity.** P1.

**Design.** See §Architecture: `DirectionalObservation(dimension=DISTANCE, pivot_m=1200, direction="lower")`.
Read side: `dimension_score` contributes `−strength` to candidates with `distance_m ≥ pivot`, `0`
below, ramping over ±500 m. Same shape for INTENSITY (ordered `light < moderate`) and price when it
exists. Persist the client patch server-side as the same observation so "next search" and "next
outreach" agree.

**Files.** `P` (new `_directional_score`), `M` (`DimensionPreference` gains optional `pivot: float|None`, `direction: Literal["lower","higher"]|None`), `DB`+Alembic+Supabase mirror (two nullable columns), `W` (drop or mirror the client patch). **Effort** M.

**Test.** `too_far` at 1200 m: 300 m listing score ≥ 0, 3000 m listing score < 0; also pins the
senior sentence ("further from home").

### 4. Outreach declines almost never reach the dimension learner; when they do, half the axes are silently absent

**Evidence.** `_activity_candidate_for_key` (`R:2749-2790`) returns `None` for `gentle_nudge:*`
and, for `programme:*`, a stripped `ActivityCandidate` with no `category`, `intensity`,
`indoor_outdoor`, `social_shape` — even though `outreach_detail` (`R:3223-3256`) resolves the very
same programme by title to a full catalogue `ActivityCandidateRow` carrying `intensity=light`,
`category="Group class"`.

```
$ d_repo.py sections D/E
programme:aac-chair-mobility reason=not_for_me -> dims=[]   (detail activity: intensity=light, category=Group class)
gentle_nudge:chair_mobility  reason=too_tiring -> dims=[]
```

So on the outreach surface only `too_far` and `bad_timing` ever generalise; `not_for_me` is item-only.

**Root cause.** Two resolvers for one key; the learner uses the poorer one.

**Severity.** P2 (missed learning rather than wrong learning — except it combines with §5).

**Design.** Single `_candidate_for_key` used by both `outreach_detail` and `_apply_activity_decline`,
resolving `programme:*` through the catalogue row first and falling back to the programme row.
Give `InterventionCandidate` for `gentle_nudge:*` a static attribute profile
(`intensity=light, environment=indoor, social_shape` already present) so `too_tiring` on a nudge
can at least record a directional INTENSITY observation.

**Files.** `R`. **Effort** S. **Test.** `programme:*` + `not_for_me` writes CATEGORY.

### 5. "Too tiring" fabricates `intensity=moderate` and records no direction

**Evidence.** `_declined_value` INTENSITY fallback (`P:181-186`) writes `MODERATE` when the listing
carries none. With §4, every programme decline hits the fallback:

```
$ d_repo.py section D
programme:aac-chair-mobility reason=too_tiring -> [('intensity','moderate','decline_reason',-0.333,1)]
   (the catalogue row for this programme says intensity=light)
$ d_learner.py §6
too_tiring on a LIGHT listing teaches avoid light; moderate untouched (no "prefer lower")
```

**Root cause.** A contextual fallback that invents a catalogue fact, plus categorical INTENSITY.

**Severity.** P1 — violates "UNKNOWN never silently becomes a value" and the fabricated value
contradicts the listing.

**Design.** Remove the fallback (return `None` like TIMING/CATEGORY do); record
`DirectionalObservation(INTENSITY, pivot=<declined level or None>, direction="lower")`. When
the level is unknown the observation still says "lower than _this listing_" and matches via the
listing id, not a value.

**Files.** `P:_declined_value`, `test_preferences.py::test_too_tiring_moves_intensity_and_too_far_does_not`. **Effort** S.

### 6. "Wrong time" over-generalises to a whole 5-12 h window (confirms lead)

**Evidence.** `_timing_bucket` (`P:137-145`): three buckets. `d_learner.py §7`: `bad_timing` on
09:00 → `morning` avoid; an 11:30 listing scores −0.333, 13:00 scores 0. A "Tuesday 9 am clashes
with my clinic" cannot be expressed; a person who declines two morning slots for different reasons
reads as "avoids mornings" (`describe_preference`).

**Severity.** P2.

**Design.** Structured clarification chip after `bad_timing`: "That time of day" / "That day of the
week" / "Just this one" (`TimingClarification` enum, optional, skippable) → observation with
`scope: time_of_day | weekday | slot`. Only `time_of_day` writes the bucket row. Until clarified,
`bad_timing` writes nothing attribute-level (item cooldown already handles the listing).

**Files.** `M` (enum + `ActivityResponseRequest.timing_scope`), `P`, `W/senior/decline-reason-prompt.tsx`. **Effort** M.

### 7. `okay` and `enjoyed` share one `inferred` row: an "okay" _erases_ prior enjoyment; an "enjoyed" _promotes_ a prior okay

**Evidence.** `apply_enjoyment` matches on `(dimension, value, source="inferred")` and recomputes
`strength = strength_for(observations)` with the function of the _latest_ report (`P:415-417,429-443`).

```
enjoyed once:           [('Group class', 0.333, 1)]
then okay (+activity):  [('Group class', 0.075, 2)]   <- enjoyed evidence collapsed to the okay cap
okay then enjoyed:      [('Group class', 0.5, 2)]     <- the okay now counts as a full enjoyed observation
```

**Root cause.** Strength is derived from a count, not from positive/negative evidence counts; the
verdict is not stored on the row.

**Severity.** P1 (order-dependent, non-monotone learning; the same two reports give 0.075 or 0.5).

**Design.** This is the core case for **evidence counts with a prior** (§Architecture):
`positive_evidence`, `negative_evidence` (floats) per `(dimension, value, source)`,
`strength = (pos − neg) / (pos + neg + PRIOR)`, `okay` contributes `+0.15`, `enjoyed` `+1`,
`not_for_me` (with a "what didn't work" aspect) `−1`. Order-independent by construction.

**Files.** `P`, `DB` (+2 float columns; `observations` kept as `pos+neg` for display), Alembic +
`infra/supabase/migrations`, `test_preferences.py`. **Effort** M.

### 8. Re-tapping "I'm interested" is unbounded positive evidence

**Evidence.** `_activity_engagement` counts every `ActivityOfferResponseRow` (`R:4170-4185`);
`_engagement` adds `0.25 × interested` (`S:631`).
`d_repo2.py §H`: three taps on the same listing → engagement contribution 0 → **1.125** (the whole
`engagement` weight), while `plan_activity` correctly de-duplicated to one week entry.
`test_interested_twice_is_one_plan_and_two_responses` pins the _storage_ but not the _scoring_.

**Severity.** P2 (an accidental double-tap already out-weighs a real `went`).

**Design.** Score per distinct `(activity_id, recorded_on_day)` or cap `interested` at 1 per plan;
prefer counting _plans_ (`plan_id is not None`) rather than responses.

**Files.** `R:_activity_engagement`, `S:_engagement`. **Effort** S.

### 9. "Went and hated it" ≠ "went and loved it" is only true in Store A; Stores B and C conflate them

**Evidence.**

- Store A: `d_learner.py §3` loved 0.444 / hated 0.222 / silent 0.333 — distinct. But
  hated (0.222) still ranks **above** an outright decline (0.167) and above no-response (0.2); 3×
  hated (0.16) > 3× declined (0.10). ADR 0005 accepted this (option B) and lists option C as the
  one-line alternative (`docs/adr/0005:56-69, 297-301`).
- Store B: `NOT_FOR_ME` with nothing liked writes nothing (`P:412-413`; `d_learner.py §9`,
  `d_repo2.py §I dims=[]`). There is no negative `LikedAspect`; the only negative attribute path is
  a _decline_. So a person who attends and dislikes gardening teaches the search ranker nothing
  about gardening, while a person who declines it from the card teaches −0.333 on its category.
- Store C: `d_repo2.py §I` — `went` + `not_for_me`: engagement contribution **+0.9**, card reason
  "You went to this one before." (`S:667-668`). `did_not_go` is deliberately unscored
  (`S:624-626`) and `cancelled` is not even counted (`R:4200-4210`).

**Severity.** P1 for Store C (a listing the person hated is _promoted_ on their next search with a
positive reason); P2 for Store B.

**Design.** `ActivityEngagement` gains `not_enjoyed: int`; `_engagement` scores
`went_enjoyed +0.75`, `went_okay +0.35`, `went_not_for_me −0.5`; `_history_reason` never grounds a
positive line on a `went` whose verdict is `not_for_me`. Add `DislikedAspect` (same four values plus
`pace`, `environment`) to `EnjoymentRequest` so `not_for_me` can write negative attribute evidence
through the same observation record.

**Files.** `S`, `R:_activity_engagement`, `M`, `P`, `W/senior/enjoyment-prompt.tsx`. **Effort** M.

### 10. One "not for me: too far" tap is charged three-to-four times against the same listing

**Evidence.** `d_learner.py §11`, listing X at 1.2 km: `preference −0.666` (attribute row × 2.0)

- `repetition −2.0` (14 d) + later `engagement −0.75`, and the client patches
  `max_distance_m` to 720 m so X is hard-filtered by intent on the next chip search
  (`W/lib/view-models.ts:1037-1040`, `ask-silverloop.tsx:200-204`). The `P:19-24` docstring argues
  no double-count because stores are orthogonal — true for _what_ they claim, false for _what X pays_.
  Also `d_repo2.py §K`: one `not_for_me` on "Sheltered Morning Walk" (category `Group class`) puts
  −0.666 on 15 of 27 listings (gardening, chair mobility, evening stretch) — the format-as-category
  flaw the lead named, confirmed.

**Severity.** P2 (ranking, not safety; but it makes a single tap the dominant signal in the table).

**Design.** Define the attribute factor as _evidence about other listings_: exclude the listing
that produced the observation from `dimension_score` for that observation (store `origin_activity_id`
on the observation), and stop the client intent patch once §3's directional observation is
server-side. Category needs a content taxonomy (`activity_kind`: walk / tai chi / gardening /
craft / …) separate from `format` (group class / self-guided) — that is the catalogue's problem
(Audit on catalogue), but `NOT_FOR_ME` should map to `activity_kind`, not `category`.

**Effort** M.

### 11. `coordinator_resolved` and `activity_recovered` are phantom outcomes

**Evidence.** `review_case` writes `CaseReviewRow` and an audit event with
`outcome="coordinator_resolved"` (`R:5758-5770`) but never an `InterventionOutcomeRow`;
`d_repo2.py` (corrected call, `reviewer_note`): resolve → 200, `outcome=coordinator_resolved`,
intervention outcomes unchanged, scores unchanged. `L:16-21` and
`test_a_coordinator_closing_a_case_moves_nothing` test a path no data takes. `activity_recovered`
(1.0, 0.0) is accepted by `record_outcome` (`R:2882`) but no caller emits it; if one ever did it
would credit the _candidate_ with a full success — `docs/architecture.md:77-78` says it "is not
attributable to the offer".

**Severity.** P2 (correct today by accident; the docs and tests describe a mechanism that does not exist).

**Design.** Either remove both from `_OUTCOME_WEIGHTS`/`OutcomeKind` or key `activity_recovered` to
the _decision_ learner only (`decision_learner`, `R:2067`) and never the candidate learner.
Administrative closure must never be enjoyment — today it is not, because it is nothing.

**Effort** S.

### 12. Backdated and stale reports teach with full weight; duplicates are blocked only per row

**Evidence.**

- `d_repo2.py §J`: a plan reported `went` + `enjoyed` **25 days** after its day → 200/200, dims
  written, plan no longer visible on `/week`. `record_planned_follow_through` checks only
  `plan.day >= run.current_day` (`R:4403-4406`).
- `apply_decline` has no dedupe (`d_learner.py §8`: same candidate twice at the same instant →
  observations 2, −0.5). The HTTP layer dedupes outreach outcomes (`R:2900-2931`) and plan rows
  (unique constraints `DB:173,472,492,517`) but `activity_offer_responses` is deliberately
  many-per-listing (`DB:425-434`), so a double-tap on a search card is two attribute observations.
  `test_a_double_tap_racing_to_the_same_row_is_a_conflict_not_a_crash` covers the _race_, not the
  sequential re-tap.
- Store A's join (`R:2054-2064`) is safe only because of the unique constraints; nothing in
  `_preference_learners` would notice a second row.

**Severity.** P2.

**Design.** `PreferenceObservation.recorded_on_day` + `origin` (`activity_id`/`intervention_id`/`plan_id`)
with a unique `(person, origin, kind)` so one origin yields at most one observation per kind;
reports older than `REPORT_WINDOW_DAYS` (e.g. 14 simulated days) are recorded with
`confidence=low` and weight 0.5 rather than refused (refusing loses the person's word).

**Effort** S–M.

### 13. Confidence and evidence count are display-only; the learners have none

**Evidence.** `world_model._inferred_confidence` maps `observations ≥ 3 → MEDIUM` (`world_model.py:48,143-151`)
and `evidence_count=preference.observations` (`:321`) — but `dimension_score` multiplies
`strength × source weight` (`P:494-496`) with no confidence term, and one observation already
sits at −0.333 (a third of the way to certain). The lead's "n/(n+2) overlearns" is confirmed:
three `not_for_me` on group classes = −0.6 on every group class (`d_learner.py §4`).

**Severity.** P2.

**Design.** Bayesian shrinkage: `strength = (pos − neg) / (pos + neg + k)` with `k = 2` gives the
same curve, but expose `confidence = (pos+neg)/(pos+neg+k)` separately and let the _weight_ of a
row in `_weighted_dimension_score` be `source_weight × confidence`, so one tap moves a listing by
≈ 0.11 × 2.0, not 0.333 × 2.0.

**Effort** S.

### 14. Documentation disagrees with code (record, not fix)

- `docs/architecture.md:64-70` says `activity_dimension_preferences` "carries no `run_id`", reset
  clears it, migration "filed for the next phase" — `DB:336-411` has `run_id`, ADR 0004 shipped it,
  `202609130012_dimension_preference_run_scope.sql` exists.
- `enjoyment-prompt.tsx:12-14` vs `senior-view.tsx:474-477` (§2).
- `docs/architecture.md:55-56` "administrative closures carry a zero weight" — they carry no row (§11).
- `P:169-178` docstring "record the direction the decline itself asserted" — records a bucket (§3).
- `docs/api.md:272-274` "`not_for_me` … moves that dimension exactly as an outreach decline does" —
  an outreach `not_for_me` never moves CATEGORY (§4).

---

## Proposed learning-semantics architecture

### A. One outcome funnel, one enum

Replace the four parallel vocabularies (`OutcomeKind`, `FollowThrough`, `PlannedFollowThrough`,
`ActivityOfferResponse`, `Enjoyment`) with one **`OutcomeStage`** recorded per _origin_
(intervention or plan or offer response), keeping the existing tables as the write path:

```
SHOWN → ASKED_FOR_MORE → PLANNED → ATTENDED (completed | partial) → ENJOYED (enjoyed | okay | not_for_me)
      ↘ DECLINED(reason, clarification)   ↘ NO_RESPONSE   ↘ DEFERRED
                                  ↘ MISSED (not_this_time | did_not_go)  ↘ UNABLE_TODAY
                                  ↘ CANCELLED  ↘ PROGRAMME_UNAVAILABLE  ↘ OUTCOME_UNKNOWN (day passed, no report)
```

`OutcomeStage` is a **derived view** (`world_model.py` style: read-only, assembled from the rows
that already exist) — no migration for the funnel itself. The learner weight tables become one
table keyed by stage, so `test_every_outcome_kind_has_a_learning_weight` covers the whole funnel
and `coordinator_resolved`/`activity_recovered` fall out (§11).

### B. `PreferenceObservation` — the unit of attribute learning

```python
class PreferenceObservation(BaseModel):
    observation_id: str
    person_id: str; run_id: str
    origin: Literal["offer_response", "intervention", "plan", "senior_statement"]
    origin_id: str                                  # unique with kind
    stage: OutcomeStage                             # what was said
    dimension: PreferenceDimension
    value: str | None                               # categorical evidence
    direction: Literal["lower", "higher"] | None    # ordered dimensions
    pivot: float | None                             # the listing's own value (m, level index, $)
    sentiment: Literal["positive", "negative", "neutral"]
    weight: float                                   # 1.0 enjoyed, 0.15 okay, 0.5 stale, …
    recorded_on_day: date
    source_tier: Literal["senior_statement", "decline_reason", "inferred"]
```

`activity_dimension_preferences` stays as the **materialised belief** (one row per
`(person, dimension, value|direction, source)`), gaining `positive_evidence`, `negative_evidence`,
`pivot`, `direction`; `strength` and `confidence` are recomputed from those on every write. This
keeps `dimension_score`, world model, Privacy screen and `forget` unchanged in shape.

### C. Directional dimensions

`DISTANCE`, `INTENSITY`, `PRICE` (when catalogue carries it), `DURATION` are ordered. A decline
writes `direction="lower", pivot=listing value`; a liked `location` writes `direction=None,
value=bucket` _only if_ the person confirms via a clarification chip ("Because it was close by" /
"Because of the place itself") — otherwise `LOCATION` should not touch DISTANCE at all (today it
does, `P:382`). Read side: `_directional_score(candidate_value, pivot, direction, strength)` with
a ±25 % ramp, contributing only to listings _on the wrong side_ of the pivot.

### D. Structured clarification

- `bad_timing` → `TimingScope {time_of_day, weekday, this_slot}` (§6).
- `not_for_me` → `DislikeScope {this_activity_kind, this_format, this_venue, this_one}`; only
  `this_activity_kind` generalises, and to `activity_kind`, not `category`.
- `not_for_me` enjoyment → `DislikedAspect {people, location, activity, timing, pace, environment}`.
  `pace` and `environment` are candidate-specific (they need `intensity`/`indoor_outdoor` on the
  listing) and write directional / categorical negatives respectively.

All chips optional; an unclarified reason writes the _item_ observation only.

### E. What must not be inferred

- **Accessibility**: `accessibility_tags`, `unable`, `too_tiring` must never write a "needs
  seated"/"cannot walk" belief. `unable` stays item-level (§1) and never maps to a dimension —
  keep `DECLINE_REASON_DIMENSIONS` free of any capability axis; add a test that no
  `PreferenceDimension` value is ever derived from `accessibility_tags`.
- Health framing: nothing in observations may reference steps/HR; `TOO_TIRING` is a preference for
  gentler _listings_, phrased that way on every surface.
- Social: never inferred from a decline (`P:75-76` already) — keep.
- Silence (`NO_RESPONSE`, `OUTCOME_UNKNOWN`) never writes an attribute observation.

### F. What the current tables already support vs. needs migration

| Need                                        | Today                                 | Migration?                                                                                                                                                                                         |
| ------------------------------------------- | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Funnel view (`OutcomeStage`)                | derivable from existing rows          | no                                                                                                                                                                                                 |
| Reason-aware outreach weights (§1)          | `intervention_outcomes.reason` exists | no                                                                                                                                                                                                 |
| Attendance gate on enjoyment (§2)           | rows exist                            | no (code)                                                                                                                                                                                          |
| Positive/negative evidence counts (§7, §13) | `observations` only                   | **yes**: 2 float columns on `activity_dimension_preferences` (Alembic + `infra/supabase/migrations/2026…_dimension_evidence.sql`)                                                                  |
| Directional observations (§3, §5)           | none                                  | **yes**: `direction`, `pivot` nullable columns (same migration)                                                                                                                                    |
| Observation log with origin (§12)           | audit events only (JSON)              | **yes** if queryable: new `preference_observations` table; **no** if rebuilt from `activity_offer_responses`/`intervention_outcomes`/`plan_*` like Store A is — recommended: rebuild, no new table |
| Clarification chips (§6, D)                 | none                                  | **yes**: nullable `clarification` column on `activity_offer_responses` and `intervention_outcomes` (append-only tables — a new column is compatible with the triggers)                             |
| `not_enjoyed` engagement count (§9)         | `plan_enjoyment.enjoyment` exists     | no                                                                                                                                                                                                 |
| Content taxonomy `activity_kind` (§10)      | none                                  | catalogue column — belongs to the catalogue audit                                                                                                                                                  |

---

## What NOT to build

- A single unified learner that merges Stores A, B, C. The three answer different questions
  (this option / this kind / this listing); fix their vocabularies and gates, not their separation.
- An LLM-inferred preference from free text or notes. Notes stay on their rows (`note_present`
  only); inference stays deterministic and shown back.
- Time-decay on outreach posteriors. With ≤ 5 candidates and a handful of observations per demo
  run, decay would only add a knob; stale-report _weighting_ (§12) is enough.
- A negative `LikedAspect` on `okay`. "It was fine" is neutral; only `not_for_me` gets a dislike chip.
- Enjoyment or attendance for `gentle_nudge:*` as _attribute_ evidence beyond intensity direction
  — a five-minute seated movement teaches nothing about venues, timing or company.
- Coordinator resolution as any learning input. It should stay a case-state transition
  (drop it from `OutcomeKind` rather than wiring it in).
- Surfacing `engagement_value`/`experience_value`, confidence or evidence counts to the senior.
  Seniors see sentences ("Care+ will lean away from …"); counts go to `/evidence` only.
- Fixing the client-side `declineReasonIntentPatch` in isolation — it is the right semantics in the
  wrong layer; delete it once §3 lands server-side rather than making it smarter.
