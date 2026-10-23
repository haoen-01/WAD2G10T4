# Review — adversarial cross-check of audits A / B / C / D

Reviewer: independent Opus-class. Read-only. Worktree `/Users/ianpong/Projects/ismoggers-v2`
(branch `feat/personalisation-ranking-worldmodel-v2`, HEAD `846ad2c`, whose parent is the audited
`010aa96`; no tracked file differs in the modules under review). Nothing was edited, committed or
served; no port was bound.

Probes I wrote and ran myself (`LLM_ENABLED=false ADAPTER_MODE=fixture`, from `apps/api`,
`uv run python …`) live in `scratchpad/audits/review/`:

| script                      | what it settles                                                                                                                                          |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `r1_intent_weight.py`       | B-F5 "the intent soft factor is inert for the top-K", across intents with real INTENSITY mismatches and across a cooldown that straddles a tier boundary |
| `r2_diversity.py`           | whether the rank-3 movement in r1 is `_diversify`; whether a lower-tier promotion occurs naturally on the fixture                                        |
| `r3_f4_construct.py`        | B-F4 reproduced on the **production** weights                                                                                                            |
| `r4_prefs.py`               | A-F1 / B-F7 averaging: 3 likes vs 1 like, like+avoid, pairwise swaps                                                                                     |
| `/tmp/negprobe.py` (inline) | C-C1 negation, extended to the SOCIAL and INTENSITY axes                                                                                                 |

All file:line references are `apps/api/src/silverloop/…` unless prefixed.

---

## 1. Challenge of every P0 and P1

### 1.0 Verdict table

| #   | Report / finding                                                                      | Their severity | My verdict                                                                                   | Severity after review                          |
| --- | ------------------------------------------------------------------------------------- | -------------- | -------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| 1   | A-F1 / B-F7 — one scalar carries sentiment+confidence+count; cross-axis **averaging** | P0 / P1        | **CONFIRMED, reproduced**                                                                    | **P0**                                         |
| 2   | A-F2 / B-F2 / D-§3 — DISTANCE two-bucket; "too far" at 1.2 km teaches _avoid near_    | P0 / P0 / P1   | **CONFIRMED**; one sub-claim downgraded                                                      | **P0**                                         |
| 3   | A-F3 / B-F1 / D-§5 — INTENSITY nominal; `MODERATE` fabricated                         | P0 / P0 / P1   | **CONFIRMED**, and it falsifies another module's stated contract (§6.N3)                     | **P0**                                         |
| 4   | A-F4 / B-F8 / C-C3 — CATEGORY is _format_                                             | P0 / P1 / P1   | **CONFIRMED**                                                                                | **P0**                                         |
| 5   | B-F3 — UNKNOWN on a constrained axis scored as MISMATCH, costs a whole tier           | P0             | **CONFIRMED**; their _fix_ is incomplete (§2.6)                                              | **P0**                                         |
| 6   | B-F4 — diversity swap compares totals, not tiers                                      | P0             | **CONFIRMED, reproduced on production weights**; currently _latent_                          | **P0**, with a sequencing hazard (§6.N1)       |
| 7   | C-C1 — negation inverted, then hard-filtered                                          | P0             | **CONFIRMED and broader than reported** (SOCIAL and INTENSITY also invert)                   | **P0**                                         |
| 8   | B-F5 — "the intent soft factor is inert for the top-K"; delete `intent` and `_tier`   | P1             | **REFUTED as stated** (two reachable counterexamples); the _remedy_ is rejected as sequenced | **P2** cleanup; the ADR-0003 half stays **P1** |
| 9   | B-F5b — ADR 0003's `no_intent_soft` NDCG delta is a dedupe artefact                   | P1             | **ACCEPTED on B's evidence** (not re-run)                                                    | **P1** (doc/ADR correction)                    |
| 10  | A-F6 — "That's right" adds a second row and manufactures a contradiction              | P1             | **CONFIRMED**                                                                                | **P1**                                         |
| 11  | A-F5 — TIMING over-generalises; SOCIAL asserted from "the people"                     | P1             | **CONFIRMED**                                                                                | **P1**                                         |
| 12  | A-F8 — `typical_response_hour` is UTC, shown as local                                 | P1             | **CONFIRMED**                                                                                | **P1**                                         |
| 13  | A-F9 — provenance mislabels (seeded consent → EXPLICIT/HIGH/confirmed)                | P1             | **CONFIRMED**                                                                                | **P1**                                         |
| 14  | A-F7 — goals are stored and never reach ranking/intent/planner                        | P2             | **CONFIRMED by exhaustive grep**                                                             | **P2**                                         |
| 15  | B-F6 — "near me" becomes a hard 1 km cut-off; "walk" unparsed                         | P1             | **CONFIRMED**; partially overlaps C-C2                                                       | **P1**                                         |
| 16  | B-F9 — three environment ontologies                                                   | P1             | **CONFIRMED by reading**                                                                     | **P1**                                         |
| 17  | B-F10 — double counting distance ×4, environment ×4, time ×3                          | P1             | **CONFIRMED**; the "×4" is a count of _code paths_, not of score magnitude                   | **P1**                                         |
| 18  | B-F11 — rain nudge outweighs ten declines; every benchmark case is rainy              | P1             | **ACCEPTED on B's evidence**                                                                 | **P1** (benchmark), **P2** (weights)           |
| 19  | B-F12 — engagement keyed per session, not series                                      | P1             | **CONFIRMED by reading** `_activity_engagement`                                              | **P1**                                         |
| 20  | B-F13 — engagement ignores recency, counts duplicate taps                             | P1             | **CONFIRMED** (dup taps); recency half **downgraded**                                        | **P1** dup / **P2** recency                    |
| 21  | C-C2 — no activity-content axis in `ActivityIntent`                                   | P1             | **CONFIRMED**                                                                                | **P1**                                         |
| 22  | C-C4 — CJK and ≤2-char tokens silently dropped from `unparsed_terms`                  | P1             | **CONFIRMED**                                                                                | **P1**                                         |
| 23  | C-C5 — content words mis-typed as environment/intensity                               | P1             | **CONFIRMED**                                                                                | **P1**                                         |
| 24  | D-§1 — the outreach learner cannot tell "not today" from "not for me"                 | P1             | **CONFIRMED**; their fix has an unflagged side effect (§6.N6)                                | **P1**                                         |
| 25  | D-§2 — enjoyment on an outing that never happened still teaches attributes            | P1             | **CONFIRMED**                                                                                | **P1**                                         |
| 26  | D-§7 — `okay`/`enjoyed` share one row; learning is order-dependent                    | P1             | **CONFIRMED by reading** `preferences.py:415-443`                                            | **P1**                                         |
| 27  | D-§9 — "went and hated it" is scored **positively** with a positive card line         | P1             | **CONFIRMED** (direction); magnitude corrected                                               | **P1**                                         |

### 1.1 CONFIRMED with my own evidence

**#1 — A-F1 / B-F7, the averaging defect.** `preferences._weighted_dimension_score` (`:459-500`)
sums `strength × source_weight` over _matched rows only_ and divides by `Σ source_weight`, so the
denominator grows with the numerator. `r4_prefs.py` on `activity-sheltered-walk-1`:

```
1 stated like (distance=near)              -> 1.0
3 stated likes (near, social, sheltered)   -> 1.0
like(social) + avoid(Group class)          -> 0.0
cross-dim: inferred +0.6 CATEGORY, decline -0.333 DISTANCE -> -0.004
distinct preference_fit across the 29 fixture listings, with 3 stated likes: [1.0]
pairwise order changes vs no preferences at all (empty intent): 0
```

Three of the person's own confirmed statements are a **constant +2.0 offset on every listing** and
change nothing; an AVOID is exactly cancelled by a LIKE on a different axis, and the breakdown then
prints "Nothing learned applies to this listing." (`activity_search.py:727-731` keys the note on
`== 0.0`). The cross-axis `-0.004` shows the `_SOURCE_WEIGHT` tiering, which exists to rank
_evidence classes within one axis_, being used as a mixer _across_ axes. P0 upheld.

One correction to A's framing: "the person's three most confident facts are a constant offset" is
true here because every one of the 29 fixture listings matches at least one of the three axes. The
portable statement of the defect is **match-any == match-all**, and the constant-offset result is
its fixture-specific consequence.

**#2 — distance.** `preferences.py:102` `_FAR_DISTANCE_M = 2_000`; `:131-134` buckets; `:180`
`_distance_bucket(candidate.distance_m) or "far"` records the _declined listing's own bucket_.
A 1.2 km "too far" therefore writes `distance=near, −0.333`, which penalises every listing under
2 km and leaves every listing over 2 km untouched. Confirmed by reading and by A's, B's and D's
three independent repository runs. Three thresholds do coexist: `intent.py:75` 1000,
`preferences.py:102` 2000, `activity_search.py:596-604` 500/5000, plus the dead
`activity_search.py:95-98 _NEAR_THRESHOLD_M = 1000` whose comment claims it "matches" the learned
bucket (it does not; grep finds no reader). P0 upheld.

_Downgraded sub-claim (A-F2):_ "the **intended** `decline DISTANCE=far` changes 0 pairs under all
three intents, so the learned fact adds nothing the friction factor didn't." That is a property of
this catalogue — its 8 "far" listings already sort last on friction — not a demonstration that a
learned distance preference is redundant with friction. The design conclusion (one owner for
distance) is right; this measurement does not support it. Do not quote the "0 pairs" number in the
ADR as evidence of redundancy.

**#3 — intensity.** `preferences.py:181-186` returns `ActivityIntensity.MODERATE.value` when the
listing carries no intensity. This is the only place the write side invents a catalogue fact, and
it directly violates the brief's "UNKNOWN never silently becomes FALSE/a value". Combined with
D-§4 (`sql_repository._activity_candidate_for_key:2774-2789` builds a `programme:` candidate with
no `intensity`), **every** outreach `too_tiring` writes a fabricated `intensity=moderate`. P0.

**#4 — category is format.** `preferences.py:65` `NOT_FOR_ME → CATEGORY`; `:193-198` and `:241-242`
read `candidate.category` verbatim; the fixture's categories are `Group class` (17 of 29 listings),
`Social group`, `Self-guided`, `Drop-in, self-guided`. `activity_search._diversify:837-877` keys
"variety" on the same field, so a walk + a tai chi + a gardening session count as _identical_ and a
walk + a karaoke count as _different_. `main.py:1015-1019` accepts any 160-char string as a stated
CATEGORY value, so a stated `"Walking"` is storable and can never match anything. P0.

**#5 — UNKNOWN costs a tier.** `_intent_reasons` (`activity_search.py:383-468`) requires each axis
to be _populated and equal_; `_constrained_axes` (`:588-589`) counts every asked axis. So an
unlisted language / social shape / environment lands in the denominator as a miss. Because
`_tier` (`:924-940`) is `intent + repetition` and is the **primary** sort key, no learned like,
history or context can ever lift the unlisted candidate back. Confirmed by reading. P0 — it is the
one place the code makes UNKNOWN behave exactly like FALSE.

**#6 — B-F4, the tier-blind diversity swap. Confirmed and reproduced on the production weights.**
`_diversify:855-875` tests only `third_total - item.breakdown.total > DIVERSITY_SCORE_MARGIN`;
it never reads `_tier`. `r3_f4_construct.py` (four candidates, request = morning + light):

```
diversity=False                                      diversity=True
 #1 g1 Group class  intent=1.0 tier=1.0 total=7.0     #1 g1 Group class  tier=1.0 total=7.0
 #2 g2 Group class  intent=1.0 tier=1.0 total=7.0     #2 g2 Group class  tier=1.0 total=7.0
 #3 g3 Group class  intent=1.0 tier=1.0 total=7.0     #3 s1 Social group tier=0.5 total=7.0 variety=True
 #4 s1 Social group intent=0.5 tier=0.5 total=7.0     #4 g3 Group class  tier=1.0 total=7.0
```

`s1` mismatches the person's stated intensity and is promoted into slot 3 by a stated CATEGORY
preference (+2.0) plus engagement (+1.5) exactly offsetting the intent deficit (3.5). That
contradicts `activity_search.py:106-111`, `_tier`'s own docstring at `:929-937`, and
`docs/architecture.md:428-432`: "no combination of learned preference, history, weather and
distance can lift a weaker match past a fuller one". **`_diversify` is the single hole in the one
invariant the tier exists to enforce.** P0 upheld.

Reachability caveat the lead should have: `r2_diversity.py` swept four intents over the whole
fixture catalogue and found **no** variety promotion at all, let alone a lower-tier one. The
breach needs ≈3.5 units of compensating learned signal, so it is today a _latent_ defect. See
§6.N1 for why that changes the moment B-F5's remedy lands.

**#7 — C-C1, negation. Confirmed, and it is broader than C reported.** Inline probe:

```
'nothing outdoors today'        env=outdoor  unparsed=[]
'not outdoor'                   env=outdoor  unparsed=[]
"I don't want a group class"    soc=social   unparsed=["don't", 'class']   <- NEW
'no chair exercise'             int=light    unparsed=[]                   <- NEW
'not alone'                     soc=solo     unparsed=[]                   <- inverted
'never outdoors'                env=outdoor  unparsed=['never']
```

C documented only the environment inversion and believed the SOLO-before-SOCIAL table order saved
the social case. It does not: without a second "alone" clause, `"I don't want a group class"` sets
`social_preference=SOCIAL`, and `_wrong_company` (`activity_search.py:235-252`) is a **hard** rule
that then excludes every self-guided listing. `"no chair exercise"` sets `intensity=LIGHT` with
`unparsed_terms == []`, so the confirmation card (`ask-silverloop.tsx:299-316`) claims full
understanding of a constraint that is the opposite of what was said. Two hard filters and one soft
factor invert. P0 upheld and widened.

**#10 — A-F6.** `_confirm_dimension_preference` (`sql_repository.py:4834-4840`) selects on
`source == "senior_statement"` only; the `decline_reason`/`inferred` row on the same
`(dimension, value)` is never touched, superseded or consumed. Both rows persist and both render.
On a _reversed_ stance the orphan becomes a system-manufactured contradiction. `:4866` also
increments `observations` when the same statement is repeated, so saying one thing three times is
counted as three pieces of evidence while the world model reports `evidence_count` from that field
(`world_model.py:321`). Confirmed. P1.

**#12 — A-F8.** `sql_repository._typical_response_hour:5943-5952` uses `_as_utc(row.recorded_at).hour`
(docstring says "in UTC"); `world_model.py:424-439` renders it as a plain hour on the senior's
Privacy page while `local_time.py` fixes the product at UTC+8. "Around 3pm" means 11pm. Confirmed. P1.

**#13 — A-F9, consent provenance.** `sql_repository.py:506-515` seeds
`ConsentEvidenceRow(source="synthetic_fixture", actor="system")`; `world_model._interaction_facts:391-407`
hardcodes `source_type=FactSourceType.EXPLICIT`, `source="consent_evidence"`,
`confidence=HIGH`, `confirmed=True` and never reads `ConsentEvidenceRow.source`. A person who did
nothing is shown a confirmed explicit consent. This is **not** a bypassable gate (the gate itself
works, `sql_repository.py:2809-2815`, `4661-4665`), so it does not touch the parked consent-design
question — it is a provenance mislabel and the brief makes provenance an invariant. Confirmed. P1.

**#14 — A-F7, goals.** I grepped every reader of `ActivityGoalRow` / `ActivityGoal` across
`apps/api/src` and `apps/web`. Readers: `sql_repository.list_goals:5363`, `week_plan:5479-5495`
(display + `_gap_prompt:5430`), `world_model.py:334-352` (one fact). Zero hits in
`activity_search.py`, `intent.py`, `preferences.py`, `learning.py` or `agent/*.py`. Confirmed
exactly as A stated: `meet_people`, `less_travel` and `morning_activity` are literal SOCIAL /
DISTANCE / TIMING preferences held in a table the ranker cannot see. P2.

### 1.2 REFUTED or DOWNGRADED

**#8 — B-F5, "`RANKING_WEIGHTS['intent']` is inert for the top-K". REFUTED as stated.**

B's premise is right: after `filter_candidates`, INTENSITY is the only `_INTENT_AXES` member with
no corresponding `_RULES` entry, so it is the only axis on which a survivor can genuinely mismatch.
B's conclusion — that the 7.0 weighted term therefore never moves the top 3 — does not follow, and
two reachable shapes falsify it.

_Counterexample 1 — repetition straddling a tier boundary._ `r1_intent_weight.py` §(c): request =
`intensity=light`; every LIGHT survivor is inside its 14-day cooldown, so LIGHT candidates sit at
`tier = 1.0 + (−1.0) = 0.0` and non-matching candidates at `tier = 0.0 + 0.0 = 0.0` — the same
tier, different `intent_fit`. The weight then decides the whole page:

```
weight 7 : top3 = [garden-stretch-1, gardening-1, chair-mobility-1]   (intent 1.0, rep -1.0)
weight 0 : top3 = [evening-walk-1, reading-corner, pool-exercise-1]   (intent 0.0, rep 0.0)
TOP-3 CHANGED: True
```

This is precisely the `(1.0, −1.0)` vs `(0.0, 0.0)` shape B found 13 instances of and dismissed as
"positions 20–50". It is not a tail phenomenon; it is what happens whenever a person declines the
things that match their own request, which is the central scenario of this product.

_Counterexample 2 — via the diversity margin._ `r1` §(b) and `r2` §(i): for `moderate only` and
`light+morning`, zeroing the weight changes the **third** result. `r2` shows why — with the weight
at 0, `_diversify` promotes `reading-corner` (tier 0.0) over `sheltered-walk-1` (tier 1.0), which
it cannot do at weight 7 because the 7-unit inflation puts the tier gap outside the 0.5 margin.

So the correct statement is: _the weighted intent term is redundant with the tier **except** when
`repetition` straddles a tier boundary, and it is currently the only thing keeping `_diversify`'s
tier-blindness latent._ **Severity downgraded P1 → P2**, and B's remedy ("delete `intent` from the
weighted sum and delete `_tier`") is rejected in the form proposed — see §2.5.

B's evidence was an ablation over the 84 evaluation cases. B itself argues (F11, §3.1, "What NOT to
build") that five of the six `QueryTemplate`s cannot see the differences that matter and that every
case is a rainy day. An "inert" conclusion drawn from that dataset is not admissible about the ranker.

**#9 — B-F5b, the ADR-0003 confound.** B's reading of `ablations.py:81-128` (the `no_intent_soft`
arm re-sorts on unadjusted totals without re-running series dedupe, and its own artefact reports
`series_duplication_rate@3 +0.444`) is internally consistent and I accept it without re-running.
This half stays P1, scoped to correcting the ADR 0003 handoff text — _not_ to deleting the factor.

**#20 — B-F13 recency.** The duplicate-tap half is confirmed (`_activity_engagement:4170-4185`
counts every `ActivityOfferResponseRow`; `activity_offer_responses` is deliberately many-per-listing,
`db_models.py:425-434`). The "latest signal wins with recency decay" half introduces two new
untuned constants and is exactly what B-F19 warns against. **Downgraded to P2**; the _correct_
minimal fix is D-§8 (score one response per `(activity_id, day)`) plus D-§9 (a negative verdict
must not read positive), both of which need no new constant.

**#27 — D-§9 magnitude.** D writes "engagement contribution **+0.9**". `_engagement:628-633` gives
`went` a weight of 0.35, so `went=1` alone contributes `0.35 × 1.5 = +0.525`; +0.9 requires an
`interested` tap as well. The finding stands on direction and is if anything under-argued: the
`enjoyed` count is populated only from `PlanEnjoymentRow.enjoyment == Enjoyment.ENJOYED.value`
(`sql_repository.py:4199-4210`), so `okay` and `not_for_me` verdicts are **not counted at all** —
there is no field in `ActivityEngagement` that can hold a negative verdict, and
`_history_reason:659-676` prints "You went to this one before." regardless. P1 upheld.

**C-C1's proposed complement rule — REFUTED.** C proposes that "for `social`/`intensity` the
complement is unambiguous (`not alone` → SOCIAL, `nothing tiring` → LIGHT)". Turning a negation
into a _positive_ value on `social_preference` re-creates the identical failure on a **hard** rule
(`_wrong_company`): "not alone" would then hard-exclude every unlabelled and self-guided listing
from someone who merely said they did not want to be by themselves. Resolution in §3.9: a negation
may only ever produce an **exclusion**, never a positive, on every axis without exception.

---

## 2. Conflicts between the four proposed designs, and the resolution

### 2.1 Storage shape — A's second table vs D's materialised belief vs B's string encoding

_A:_ append-only `preference_observations` + a `ResolvedPreference` that is **never stored**.
_D:_ rebuild observations from the rows that already exist (as Store A already does); keep
`activity_dimension_preferences` as the materialised belief, adding `positive_evidence`,
`negative_evidence`, `pivot`, `direction`.
_B:_ no storage proposal; encode directional facts in the existing `value` string
(`"<=light"`, `"tolerance_m=1400"`, `"hour=8±2"`).

**Resolution: D's storage, A's resolution semantics, B's encoding rejected.**

- Reject B's string encoding outright. `value` is the join key of the unique constraint
  (`db_models.py:341`), the thing `STATED_VALUE_VOCABULARY` closes, what `_candidate_dimension_value`
  compares against, what `FORGET` addresses, and what the Privacy screen renders
  (`view-models.ts:1254`). Encoding a relation into it makes four consumers parse a mini-language.
- Reject A's second table **for now**. Every inferred observation is already reconstructible from
  `activity_offer_responses` (reason, day, activity_id), `intervention_outcomes` (reason),
  `plan_follow_through` and `plan_enjoyment` — that is exactly how `_preference_learners:2024-2075`
  rebuilds Store A. A new table duplicates a write path, needs its own RLS deny policy and its own
  Supabase mirror, and buys only a history UI that A itself says not to build.
- Adopt D's columns, plus **`superseded_by`** (which A-F6 needs and D did not specify), plus
  **`origin_id`** (which D-§12 needs for one-observation-per-origin dedupe). One Alembic revision,
  one idempotent Supabase mirror.
- Adopt A's semantics on top: a pure `preferences.resolve(rows, today, run_id) -> list[ResolvedPreference]`
  that separates sentiment / confidence / evidence_count / weight, and is the only thing
  `activity_search` reads. `ResolvedPreference` is derived per request, never persisted — A is
  right that the read-model discipline (`world_model.build_world_model`) is the pattern to copy.

### 2.2 Distance — ordinal ceiling (A) vs pivot+direction (D) vs monotonic utility (B)

These are the same function with three parameterisations. **Resolution: B's _scoring_, D's _storage_,
A's _aggregation_.**

- **Scoring (B).** One `travel_utility(distance_m, tolerance_m)` is the only place distance is
  scored. It replaces `_friction`, the `near`/`far` learned bucket and (with §3.9) the parser's
  1 km hard default. `u(d) = −clip((d − tolerance_m)/SCALE, 0, 1)` with a **fixed** `SCALE`.
- **Storage (D).** `direction="lower", pivot=1200` on the existing row, because `pivot`/`direction`
  generalise to INTENSITY (and any later ordinal axis) whereas A's `max_comfortable_m` is
  distance-only.
- **Aggregation (A).** `tolerance_m = min(pivot)` over active `DISTANCE/lower` observations,
  defaulting to the friction constant when there are none. Reject an EMA or a quantile (B): a
  smoothing constant with no evaluation is exactly B-F19's own objection.
- Reject A's normalised penalty `−(d − max)/max`: it makes the per-metre penalty inversely
  proportional to the person's own ceiling, so someone with a 500 m ceiling is punished ten times
  harder per metre than someone with 5 km. Reject D's `±25 %` ramp for the same reason.

### 2.3 Taxonomy — C's enums vs B's `content_tags: list[str]` vs A's `activity_kind: list[str]`

**Resolution: C's enums, with A/B's multi-label instinct moved to the family level.**

B's `content_tags: list[str]` and A's `activity_kind: list[str]` re-create the very failure
B-F8 diagnoses (one loosely-typed field, three masters, no agreed semantics). C's
`ActivityType` (single-valued, closed) + `ActivityFamily` (multi-label, closed) + `Format`
(closed) + one alias table in `ontology.py` is the only proposal where a stated value can be
validated, a normalisation test can exist, and the LLM tool enum can be generated from the code.
Take C's fixture mapping table (all 14 programmes) as authored.

_Reject_ C's optional "also write a half-strength `ACTIVITY_FAMILY` observation" in the first slice
— it is a second magnitude knob before any benchmark can see it. Land type-only; family
generalisation is P2 and should be justified by a metric.

### 2.4 Activity content in the intent: soft (C) vs a soft feature (B-F6) vs deleting the soft factor (B-F5)

C-C2 wants `activity_types` added to `_INTENT_AXES` (weight 7, soft, "a single-axis request gives
walks +7.0 and everything else 0, which is already a near-hard ordering"). B-F5 wants
`_INTENT_AXES` and the weighted `intent` term deleted. These are direct opposites.

**Resolution: keep a soft `request_fit` restricted to axes the hard filter does not own.** That is
B's own §2.4 and it is compatible with C-C2, because `activity_types` is by design _not_ a
`_RULES` entry. Concretely `request_fit` scores: `intensity`, `activity_types`, and a soft distance
_phrase_; nothing else. The five hard-filtered axes are honoured by the filter and **not** re-scored
(this is also B-F10's fix and A's "an axis the intent constrains contributes 0 preference score").

### 2.5 The tier — B wants it deleted; nobody else touches it

**Resolution: keep `_tier`; fix `_diversify` instead. This is the one place I rule against B.**

My probe shows `_tier` is the _only_ mechanism enforcing "nothing learned can override a stated
request", and `_diversify` is its single hole (§1.1 #6). Deleting the tier does not fix that hole —
it dissolves the invariant into weight tuning, on a benchmark B itself says cannot see the
differences that matter (F11) and with weights B itself says have no tuning record (F19). The
correct order is: (i) make `_diversify` tier-aware — one line, `tier(item) == tier(third)`;
(ii) fix UNKNOWN so the tier stops being wrong (B-F3); (iii) re-author the benchmark (B §3.1);
(iv) _only then_ revisit whether the weighted `intent` term can go. Under the canonical design the
tier becomes `request_fit_tier + repetition_hold`, computed from the same `Signal` as `request_fit`.

### 2.6 UNKNOWN semantics — all four agree on direction, and all four under-specify the consequence

A ("`None` never matches"), C ("unknown stays in `unparsed_terms`; `OTHER` never matches"),
D ("UNKNOWN never silently becomes a value") and B-F3 ("exclude UNKNOWN from the denominator") point
the same way. But B's fix trades one error for its mirror: excluding UNKNOWN from the denominator
makes an unlisted listing score **identically** to a confirmed match, i.e. UNKNOWN becomes TRUE.

**Resolution (mine; none of the four proposed it):** three-valued `Tri`; UNKNOWN excluded from both
numerator and denominator; **plus a deterministic tie-break on the count of MATCH axes** at equal
fit; **plus** B's disclosure line ("Language not listed") as a permitted fourth reason with
`ReasonBasis.CATALOGUE`. That is the only combination where unknown is never negative _and_ never
free.

### 2.7 Preference utility denominator — A's `max_axes_seen` vs B's `Σ|s_d|` vs D's evidence counts

**Resolution: B's denominator, A's per-axis precedence, D's per-axis strength.**

`preference_utility = Σ_d s_d · m_d / Σ_d |s_d|` over the person's **active preference dimensions**,
where `s_d` is the winning tier's signed strength on axis `d` (§3.6) and
`m_d ∈ {+1 MATCH, −1 MISMATCH on a closed vocabulary only, 0 UNKNOWN}`. Report `coverage =
judged_dims / active_dims` on the breakdown.

Reject A's `/ max_axes_seen` (axes the _candidate_ can be checked on): it makes the score a
function of catalogue completeness rather than of what is known about the person, so a sparsely
described listing scores higher than a fully described identical one. Keep A's per-axis precedence
rule exactly as today, generalised from "stated" to "highest active tier" (§3.7).

### 2.8 Timing — A's `(weekday, hour)` slots vs B's hour kernel vs D's clarification chip

**Resolution: D's chip, gated by A's ≥2-observation rule; reject B's kernel.** A kernel introduces a
width constant with no evaluation and still cannot express "Tuesday clashes with my clinic", which
is the case A-F5 and D-§6 both name. Until a chip answer exists, `bad_timing` writes **item-level
only** (D) — the 14-day cooldown already handles the listing.

### 2.9 `FORGET` vs append-only — a conflict none of the four noticed

`PreferenceStance.FORGET` today deletes every row on that `(dimension, value)`, learned and stated
(`models.py:916-926`, `sql_repository.py:4542-4640`). A's append-only design says "forget = a
retraction observation, never deleted". D's evidence-count design would let the _next_ tap
resurrect the belief from a count the person believed they had erased. **Resolution:** `FORGET`
writes `sentiment=retract` and stamps `superseded_by` on every matching row; readers skip
superseded rows; the Privacy screen shows nothing. This preserves the person's control _and_
prevents resurrection. Flag to the lead: this is a semantics change a senior can observe, and it
needs an ADR line.

### 2.10 Item affinity — B-F12 (series) + B-F13 (recency) vs D-§8 (dedupe) + D-§9 (negative verdicts)

Compatible. Adopt B-F12 (roll up to `_series_key`, per-session override), D-§8 (one scored response
per `(activity_id, day)`) and D-§9 (`not_enjoyed` count; `went` with a `not_for_me` verdict scores
negative and grounds no positive line). Defer B-F13's recency decay to P2.

---

## 3. The canonical design (mandate §6)

Every element below is labelled **[MIG]** if it needs an Alembic revision + Supabase mirror,
**[CONTRACT]** if it changes `models.py` (⇒ `pnpm client:generate` + commit `openapi/silverloop.json`
and `libs/api-client/src/generated`), and S / M / L for effort.

### 3.1 `ActivityCandidate` schema changes — **[MIG] [CONTRACT] — M**

Add three fields; keep every existing one.

```python
activity_type: ActivityType | None = None      # single-valued, closed; None = not labelled
activity_families: list[ActivityFamily] = []   # multi-label, closed, derived from TYPE_FAMILIES
format: Format | None = None                   # replaces `category`'s structural job
# `category: str | None` STAYS, populated from FORMAT_LABEL[format]: badge only (activity-card.tsx:130)
```

`ActivityCandidateRow` (`db_models.py:278-335`) gains `activity_type: str|null`,
`activity_families_json: JSON`, `format: str|null` — all nullable, so the revision is additive and
the offline SQLite path is unaffected. New Supabase mirror `2026xxxx_activity_ontology.sql`,
idempotent, with the RLS deny policy the existing every-ORM-table test requires.
**Replaces:** `category`'s use as a learner axis and as `_diversify`'s key. **Extends:**
`fixtures._Programme` (three explicit hand-authored fields, never inferred in product code).

Also add `series_key: tuple[str, str]` as a _derived_ accessor only (B-F12) — `_series_key` already
computes it; no column, no migration.

### 3.2 Activity taxonomy — new `silverloop/ontology.py` — **[CONTRACT] — M**

Take C's `ActivityType` (17 members incl. `OTHER`), `ActivityFamily` (7), `Format` (5),
`TYPE_FAMILIES: dict[ActivityType, frozenset[ActivityFamily]]` (multi-label), and
`ALIASES: dict[str, ActivityType]` (longest phrase first; EN / Singlish / 中文), verbatim from C's
table, together with C's fixture mapping for all 14 programmes and the 5 outreach keys.

Rules, all from C and all upheld: the parser never emits `OTHER`; `OTHER` never matches an intent;
a word not in `ALIASES` stays in `unparsed_terms`; the alias table never enters an LLM prompt (the
enum in the tool schema is the constraint); the tool enum is **built from the enum at import time**,
not hand-typed (C-C7).
**Replaces:** nothing yet (additive). **New:** a normalisation test that
`normalise(title, description) == programme.activity_type` for every fixture, so the alias table and
the hand labels cannot drift.

### 3.3 Programme vs session — **no migration — S**

Keep both, name the relationship. A _programme_ (series) is `(provider, title)`; a _session_ is one
`activity_id`. `_series_key` already defines it and `_dedupe_series` already uses it. Make it
load-bearing in two more places: `_activity_engagement` rolls counts up to the series with a
per-session override (B-F12), and the cooldown is series-scoped. `_activity_candidate_for_key`
(`sql_repository.py:2749-2790`) and `outreach_detail` (`:3223-3256`) collapse into **one** resolver
that looks the programme up in the catalogue first (D-§4), so an outreach decline can reach the
same attribute axes a search decline reaches.

### 3.4 `PreferenceObservation` (append-only) — **derived, no table — S**

Per §2.1, `PreferenceObservation` is a **pure dataclass rebuilt at read time** from
`activity_offer_responses`, `intervention_outcomes`, `plan_follow_through`, `plan_enjoyment` and the
statement rows — exactly the pattern `_preference_learners:2024-2075` already uses for Store A.

```python
@dataclass(frozen=True)
class PreferenceObservation:
    origin: Literal["offer_response","intervention","plan","senior_statement","goal"]
    origin_id: str                     # unique with `kind` -> one origin, one observation (D-§12)
    kind: Literal["decline","enjoyment","statement","goal","retraction"]
    dimension: PreferenceDimension
    sentiment: Literal["like","avoid","neutral","retract"]
    value: str | None                  # nominal axes
    pivot: float | None                # ordinal axes: metres / intensity index / hour
    direction: Literal["lower","higher"] | None
    scope: TimingScope | DislikeScope | None   # from the clarification chip (§3.11)
    source_tier: SourceTier
    weight: float                      # 1.0 enjoyed, 0.15 okay, 0.5 stale report, ...
    observed_on_day: date              # the PERSON's calendar, the only clock we reason on
    run_id: str | None                 # None for standing statements (ADR 0004 unchanged)
    expires_on_day: date | None
    evidence_id: str
    origin_activity_id: str | None     # excluded from its own scoring (D-§10)
```

**Replaces:** the in-place `strength` recomputation in `apply_decline`/`apply_enjoyment`.
**Extends:** the existing rows, which stay the write path.

### 3.5 `ResolvedPreference` (derived) — **[CONTRACT] — M**

```python
class ResolvedPreference(BaseModel):
    dimension: PreferenceDimension
    value: str | None                  # nominal axes
    pivot: float | None                # ordinal ceiling (metres, intensity index, hour)
    direction: Literal["lower","higher"] | None
    slots: list[tuple[int,int]]        # TIMING, only slots with >= 2 agreeing observations
    sentiment: Literal["like","avoid"]
    confidence: FactConfidence         # categorical; capped MEDIUM unless stated or ratified
    positive_evidence: float           # D-§7
    negative_evidence: float
    evidence_count: int                # DISTINCT origins; a statement repeated == 1 (A-F1)
    winning_tier: SourceTier
    weight: float                      # [0,1] = tier_base x confidence_factor; what the ranker reads
    scope: Scope                       # §3.8
    expires_on_day: date | None
    source: str                        # senior_statement | decline_reason | inferred | goal
    run_id: str | None
    superseded_by: str | None
    stated_text: str | None
    supporting: list[str]              # origin ids
    contradicted_by: list[str]         # lower-tier origins that disagree: shown, never scored
```

`strength = (pos − neg) / (pos + neg + k)` with `k = 2` (D-§13, same curve as today's `n/(n+2)`) and
`confidence = (pos + neg) / (pos + neg + k)` exposed **separately**, so the world model's
`evidence_count`/`confidence` and the ranker's number finally mean the same thing (A-F1's last
paragraph). Order-independence is by construction, which is D-§7's fix.

`activity_dimension_preferences` gains **[MIG]**: `positive_evidence FLOAT`, `negative_evidence FLOAT`,
`pivot FLOAT NULL`, `direction VARCHAR(10) NULL`, `origin_id VARCHAR(80) NULL`,
`superseded_by VARCHAR(80) NULL`, `scope VARCHAR(20) NULL`. Backfill: `positive_evidence =
max(observations·sign,0)`, `negative_evidence = max(−observations·sign,0)`, everything else NULL —
so pre-existing rows resolve exactly as today until new evidence arrives. Do **not** drop or rename
`strength`/`observations` in the same revision; both are read by `world_model.py:318-325` and
`view-models.ts:1141-1150`. `PreferenceDimension.CATEGORY` is **deprecated, never written**, never
removed (`test_dimension_preference_run_scope_migration.py:107` relies on those rows) —
C is right about this.

### 3.6 Source hierarchy — **[CONTRACT] — S**

```python
class SourceTier(IntEnum):            # higher wins the axis outright; never averaged into a lower tier
    DEFAULT           = 0   # friction / catalogue default only
    WEAK_LEARNED      = 1   # 1-2 distinct origins; weight <= 0.35; shown as "just a hint"
    STRONG_LEARNED    = 2   # >= 3 distinct origins agreeing
    STATED_GOAL       = 3   # ActivityGoal, closed vocabulary (A-F7)
    STATED            = 4   # senior_statement, standing
    RATIFIED          = 5   # a statement that consumed an inferred row (A-F6)
    TEMPORARY_STATED  = 6   # statement with expires_on_day >= today
    CURRENT_REQUEST   = 7   # today's ActivityIntent
```

`CURRENT_REQUEST` is **excluded from `preference_utility` entirely**: an axis the person constrained
today is owned by the filter (hard axes) or by `request_fit` (soft axes) and is never re-scored from
history. That is B-F10's and A's shared rule and it removes the intent/preference double count.
Within one axis, only the highest active tier contributes (today's stated-supersedes rule,
generalised); across axes, contributions **sum** with B's denominator (§2.7).

### 3.7 Scope hierarchy — **no new migration beyond §3.5 — S**

`current request > temporary explicit > persistent explicit > strong learned > weak learned >
default`. This is exactly ADR 0004's split, promoted from something derived out of
`source` + `expires_at` in `_preference_inactive` into a first-class `(source_tier, scope,
expires_on_day, run_id)` tuple. Rule kept verbatim from ADR 0004: standing statements carry
`run_id = None` and survive a reset; everything else is run-scoped.

### 3.8 Outcome taxonomy funnel — **derived view, no migration — M**

Adopt D's `OutcomeStage` as a **read-only derived view** over the rows that already exist (the same
discipline as `world_model.build_world_model`):

```
SHOWN -> ASKED_FOR_MORE -> PLANNED -> ATTENDED(completed|partial) -> VERDICT(enjoyed|okay|not_for_me)
      \-> DECLINED(reason, clarification)   \-> NO_RESPONSE   \-> DEFERRED
                            \-> MISSED(not_this_time|did_not_go)  \-> UNABLE_TODAY
                            \-> CANCELLED  \-> PROGRAMME_UNAVAILABLE  \-> OUTCOME_UNKNOWN
```

One weight table keyed by stage replaces the four parallel ones, so
`test_every_outcome_kind_has_a_learning_weight` becomes exhaustive over the funnel and
`coordinator_resolved` / `activity_recovered` fall out (D-§11). Add D's `_DECLINE_REASON_WEIGHTS`
override (`bad_day`/`already_active` → `(0,0)`; `unable` → `(0,0.5)`) and select
`InterventionOutcomeRow.reason` in `_preference_learners` (D-§1). **See §6.N6 before doing this.**

### 3.9 `ActivityIntent` changes — **[CONTRACT] — M**

```python
activity_types: list[ActivityType] = Field(default_factory=list, max_length=5)          # SOFT
excluded_activity_types: list[ActivityType] = Field(default_factory=list, max_length=5) # HARD
excluded_environments: list[IndoorOutdoor] = Field(default_factory=list, max_length=3)  # HARD
excluded_social: list[SocialPreference] = Field(default_factory=list, max_length=2)     # HARD
distance_is_explicit: bool = False   # True only when the person gave a NUMBER (B-F6)
suggested_types: list[SuggestedType] = Field(default_factory=list, max_length=3)        # server-side only
```

**Negation rule (resolves §2.9 against C):** a negated needle produces an `excluded_*` entry and
**never** a positive value on any axis, including binary ones. `_contains` returns
`Match(needle, negated, start)` after a ≤3-token look-back over `_NEGATORS = ("not","no","nothing",
"nowhere","never","don't","dont","without","cannot","can't","rather not","不要","不想","别")`; a
negated needle is still consumed, so it never lands in `unparsed_terms`, and `describe_intent`
renders it ("Not outdoors").

**Hard vs soft, per field:**

| field                                                                    | hard filter?                              | why                                                                                                                                            |
| ------------------------------------------------------------------------ | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `on_date`, `time_window`, `environment`, `social_preference`, `language` | **hard** (unchanged)                      | already `_RULES`; a mismatch is a real barrier                                                                                                 |
| `max_distance_m`                                                         | **hard only when `distance_is_explicit`** | B-F6: "near me" must not amputate 15 of 29 listings                                                                                            |
| `intensity`                                                              | **soft** (unchanged)                      | the only soft axis today                                                                                                                       |
| `activity_types`                                                         | **soft**                                  | C is right: a hard content filter on 14 programmes makes most requests `nothing_matched`                                                       |
| `excluded_*` (all three)                                                 | **hard**                                  | an exclusion cannot on its own empty the catalogue, and "no walking, my knee" is the one phrasing where showing it anyway is the harmful error |

Also from C: `_WORD = re.compile(r"[a-z']+|[一-鿿]+")` with the `len > 2` filter dropped for CJK runs
(C-C4); `garden`, `park`, `exercise`, `chair`, `seated`, `sitting`, `active`, `workout` move out of
`_OUTDOOR`/`_LIGHT`/`_MODERATE` into `ALIASES` (C-C5); `preferred_language` defaults
`intent.language` softly and disclosed (A-F7).

### 3.10 Hard vs soft constraints — the rule, stated once

> **A hard rule exists only where a mismatch is a barrier the person cannot cross (distance they
> gave as a number, a day, a time window, an environment, company, capacity, language) or where
> they explicitly excluded something. Everything else is soft. A hard rule is never re-scored
> softly; a soft axis is never promoted to a filter.**

This single sentence resolves B-F10 (double counting), B-F6 (vague phrase → hard cut-off),
C-C2 (content soft) and C-C1 (exclusions hard), and it belongs in `activity_search.py`'s module
docstring and `docs/architecture.md`.

### 3.11 Missing-data semantics — **no migration — S**

```python
class Tri(Enum): MATCH; MISMATCH; UNKNOWN
def compare(feature_value, ask_or_pref_value) -> Tri   # None on EITHER side -> UNKNOWN, never MISMATCH
```

- UNKNOWN is excluded from **both** numerator and denominator of every fit (B-F3).
- At equal fit, the candidate with more MATCH axes wins the tie-break (**my addition**, §2.6), so
  UNKNOWN is never negative and never free.
- UNKNOWN is disclosed as a permitted fourth reason line with `ReasonBasis.CATALOGUE`
  ("Language not listed"); it is never a score.
- **Every write-side fallback is deleted**: `_declined_value`'s `MODERATE` (`preferences.py:181-186`),
  its `or "far"` (`:180`), and `_enjoyed_value`'s unconditional `SOCIAL` (`:380-381`). D and A both
  ask for this and it is the cleanest expression of the invariant.
- Clarification chips (D-§D), all optional and skippable: `bad_timing` →
  `TimingScope{time_of_day, weekday, this_slot}`; `not_for_me` →
  `DislikeScope{this_activity_type, this_format, this_venue, this_one}`; `not_for_me` enjoyment →
  `DislikedAspect{people, location, activity, timing, pace, environment}`. Unclarified ⇒ item-level
  observation only. **[MIG]**: nullable `clarification` column on `activity_offer_responses` and
  `intervention_outcomes` (both append-only; an added nullable column is compatible).

### 3.12 Candidate score architecture — one responsibility per signal

```
eligible   = hard rules (7 today + 3 exclusion rules)        # §3.10
features   = extract(candidate)                              # ONE place; Tri comparisons only
utility    = context_suitability
             x ( w_r * request_fit          # soft asks only: intensity, activity_types, soft distance
               + w_p * preference_utility   # axes the request did NOT constrain; coverage reported
               + w_a * item_affinity        # this series, with a per-session override
               + w_t * travel_utility )     # the ONLY place distance is scored
tier       = request_fit_tier + repetition_hold              # KEPT (see 2.5)
order      = (-tier, -utility, -match_axis_count, distance, title)
then       = series dedupe -> tier-aware diversify -> bounded LLM rerank -> top-K
```

**How the existing six factors map:**

| today              | becomes                                                                                 | note                                                         |
| ------------------ | --------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `intent` (7.0)     | `request_fit` (soft axes only) **+ `tier`**                                             | the hard axes stop being re-scored; the tier survives        |
| `preference` (2.0) | `preference_utility` with B's denominator + `coverage`                                  | axes constrained today contribute 0                          |
| `engagement` (1.5) | `item_affinity`, series-scoped, day-deduped, negative verdicts counted                  | D-§8, D-§9, B-F12                                            |
| `repetition` (2.0) | `repetition_hold: bool` → a post-sort demotion to the tail, series-scoped               | what the docstring already describes                         |
| `context` (1.5)    | `context_suitability ∈ [0.5, 1.0]`, multiplicative, rain ∧ outdoor ∧ env-not-asked only | B-F11; no bonus for being indoors                            |
| `friction` (1.0)   | `travel_utility(distance_m, tolerance_m)`                                               | absorbs the learned DISTANCE ceiling; kills the double count |

`_NEAR_THRESHOLD_M` (`activity_search.py:95-98`, dead, false comment) is **deleted**.
`_ENVIRONMENT_COMPATIBLE`, `preferences._environment_value` and the rain branch collapse into one
`environment_compatibility(ask, listing) -> Tri` with `covered = indoor|sheltered` (B-F9), which
`evaluation/ranking/_grounding.py` and `_dimensions.py` import instead of duplicating.

### 3.13 World-model confidence semantics — **[CONTRACT] — S**

- `FactConfidence` stays **categorical** — A is right that exposing a probability is the wrong move.
- `evidence_count` = **distinct origins**. A statement repeated three times is `1`
  (`sql_repository.py:4866` stops incrementing when value + stated_text are unchanged).
- A fact from `RATIFIED`/`STATED`/`TEMPORARY_STATED` may be HIGH; anything learned is capped at
  MEDIUM regardless of count.
- `stale` is computed from `run.current_day − observed_on_day`, i.e. the **person's calendar**,
  the same clock expiry already uses (A-F10). One clock, product-wide.
- `_typical_response_hour` uses `local_hour` and is suppressed on a simulated run (A-F8).
- Consent facts read `ConsentEvidenceRow.source`: `synthetic_fixture ⇒ FactSourceType.FIXTURE`,
  confidence MEDIUM, `confirmed=False` (A-F9).
- `contradicted_by` on `ResolvedPreference` replaces `world_model._mark_contradictions`, and a
  ratified statement removes the contradiction the system manufactures today (A-F6).

### 3.14 What stays exactly as it is

- The **hard-filter-before-any-model** order, `FilterOutcome`'s named rules, and the fact that the
  planner may rank but never author a candidate.
- `learning.py`'s two-posterior split and ADR 0005's `expected_value = P(attend) × E[enjoy|attend]`.
- The **pure-module** discipline: `preferences.py` and `activity_search.py` import nothing from
  `policy.py`; `dimension_score` returns a float, never a `Decision`.
- ADR 0004's run-scoping rule and the `c2725d7de5df` migration.
- `PREFERENCE_LEARNING` consent gating of all inference (`sql_repository.py:2809-2815`, `4661-4665`).
- `NO_ACTION` as a first-class audited result; the senior surface showing no scores or counts.
- `_dedupe_series`, `ScoreBreakdown` as operator-only, the bounded `validate_activity_order`
  subset check, `snapshot_stale` discarding a reorder.
- `PreferenceStance.PREFER/AVOID/FORGET` as the senior's controls (semantics of FORGET amended per §2.9).
- The offline SQLite + fixture + LLM-off path: every migration above is additive and nullable.

---

## 4. Minimum test set that pins the corrected semantics

Mapped to the design element each one pins. New tests unless marked _(amend)_.

**Preference resolution (§3.5, §3.6, §2.7) — `tests/test_preferences.py`**

1. `test_three_confirmed_likes_outscore_one_confirmed_like` — A-F1/B-F7; the exact `r4` case.
2. `test_an_avoid_on_one_axis_is_not_cancelled_by_a_like_on_another` — the group-class-vs-solo case.
3. `test_stating_the_same_preference_twice_is_one_piece_of_evidence` — A-F1, `evidence_count == 1`.
4. `test_okay_then_enjoyed_and_enjoyed_then_okay_resolve_identically` — D-§7 order-independence.
5. `test_a_higher_tier_supersedes_rather_than_averages_on_the_same_axis` _(amend the existing
   `test_without_a_statement_inferred_rows_still_average_by_source_tier`)_.
6. `test_coverage_is_reported_and_an_unjudgeable_axis_is_excluded_from_both_sides` — §3.11.

**Ordinal axes (§3.1 distance, §3.5 pivot/direction)** 7. `test_too_far_at_1200m_ranks_a_500m_listing_above_a_1600m_one` — A-F2/B-F2/D-§3. 8. `test_a_second_too_far_at_900m_lowers_the_tolerance_to_900` — `min(pivot)`, not an EMA. 9. `test_travel_utility_is_monotonic_in_distance_and_is_the_only_distance_term` — B-F10. 10. `test_too_tiring_on_a_light_listing_never_promotes_a_moderate_one` — A-F3/B-F1. 11. `test_too_tiring_on_a_listing_with_no_intensity_records_nothing` — the `MODERATE` fabrication. 12. `test_one_bad_timing_teaches_no_dimension_and_two_on_the_same_slot_do` — A-F5/D-§6.

**Taxonomy (§3.2, §3.1) — `tests/test_ontology.py` (new) + `test_activity_search.py`** 13. `test_every_fixture_programme_normalises_to_its_hand_labelled_activity_type` — the anti-drift test. 14. `test_not_for_me_on_a_walk_leaves_chair_mobility_unchanged_and_demotes_the_other_walks` — A-F4/B-F8/C-C3. 15. `test_diversity_keys_on_activity_type_not_on_format` — a walk + a tai chi are _different_. 16. `test_a_stated_activity_type_outside_the_enum_is_rejected_with_422` — closes `main.py:1015-1019`.

**Intent (§3.9) — `tests/test_intent.py`** 17. `test_a_negated_needle_never_sets_the_positive_value` — **property test over every needle in
every table**: for all `n`, `parse(f"not {n}")` never yields the value `n` maps to. This is the
only form that catches the SOCIAL and INTENSITY inversions I found beyond C's report. 18. `test_nothing_outdoors_excludes_outdoor_rather_than_requiring_it` — C-C1, end to end through
`filter_candidates`. 19. `test_i_dont_want_a_group_class_does_not_hard_filter_the_self_guided_listings` — my §6.N2. 20. `test_a_walk_parses_to_an_activity_type_and_leaves_unparsed_terms_empty` — C-C2. 21. `test_cjk_content_words_reach_unparsed_terms_or_an_activity_type` — C-C4 (`散步`, `唱歌`). 22. `test_gardening_sets_an_activity_type_and_not_an_environment` — C-C5. 23. `test_near_me_never_hard_filters_a_1200m_listing_but_within_800m_does` — B-F6, both halves.

**Ranking invariants (§3.12, §2.5) — `tests/test_activity_search.py`** 24. `test_diversity_never_promotes_a_lower_tier_candidate` — **B-F4; build exactly `r3_f4_construct.py`.** 25. `test_an_unlisted_field_never_lowers_the_request_fit` — B-F3. 26. `test_at_equal_fit_the_candidate_with_more_matched_axes_ranks_first` — my UNKNOWN tie-break (§2.6). 27. `test_an_axis_the_request_constrains_is_not_rescored_from_history` — B-F10, the double count. 28. `test_a_stated_request_still_outranks_every_learned_preference_combined` _(amend — it must keep
passing after §3.12; this is the regression gate on the whole redesign)_. 29. `test_rain_never_lifts_an_indoor_listing_above_a_better_fit_on_a_dry_day` — B-F11.

**Outcome / affinity (§3.3, §3.8) — `test_activity_responses.py`, `test_follow_through_api.py`, `test_learning_weights.py`** 30. `test_a_not_for_me_on_one_session_holds_back_the_whole_programme` — B-F12. 31. `test_repeated_interested_taps_on_one_day_count_once` — D-§8. 32. `test_a_listing_the_person_attended_and_disliked_is_never_promoted_with_a_positive_line` — D-§9. 33. `test_enjoyment_cannot_be_recorded_without_an_attending_follow_through` — D-§2 (API, 4xx). 34. `test_declined_bad_day_leaves_the_posterior_at_the_prior_while_not_for_me_does_not` — D-§1. 35. `test_min_single_observation_delta_enumerates_every_decline_reason_weight` — **my §6.N6**; this
is the test that stops the social nudge silently collapsing. 36. `test_no_preference_dimension_is_ever_derived_from_accessibility_tags` — D-§E, safety. 37. `test_a_confirmed_statement_leaves_exactly_one_row_on_that_dimension_and_value` — A-F6 (API).

**World model — `test_world_model.py`** 38. `test_a_seeded_consent_reads_as_fixture_not_explicit` — A-F9. 39. `test_a_response_recorded_at_0700_utc_reads_as_3pm` — A-F8. 40. `test_staleness_is_measured_on_the_persons_calendar` — A-F10.

**Evaluation — `test_ranking_evaluation.py`** 41. `test_evaluation_helpers_import_the_production_feature_extractor` _(amend the existing
`test_evaluation_helpers_agree_with_the_production_helpers_they_duplicate` — stop duplicating
2000 m and the buckets in `_dimensions.py`; import them)_. 42. `test_directional_consistency` — after `TOO_TIRING` at level L, no candidate below L loses rank. 43. `test_preference_coverage_is_monotonic` — adding a confirmed like never lowers a matching candidate.

**Scenarios — `scenarios/*.yaml`** 44. One new scenario: `too_far_at_1200m_teaches_a_ceiling.yaml`. No existing scenario touches these
tables, so this is additive.

---

## 5. Implementation order — coherent vertical slices, with shared-file touch points

The four shared files are `models.py`, `db_models.py`, `sql_repository.py`, `main.py` and
`alembic/versions/` + `infra/supabase/migrations/`. **Serialise anything that touches `models.py`**
— every such change forces `pnpm client:generate` and a commit of `openapi/silverloop.json` +
`libs/api-client/src/generated`, and two concurrent branches will conflict there every time.
Two owners can run in parallel only where the "shared files" column is empty.

### P0 — correctness / invariant repair

| #        | Slice                                                                                                                                | Tests         | Shared files                                                | Effort | Parallel?                      |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------- | ----------------------------------------------------------- | ------ | ------------------------------ |
| **P0.1** | **Tier-aware `_diversify`** (`tier(item) == tier(third)`)                                                                            | 24            | none                                                        | **S**  | yes — do this first and alone  |
| **P0.2** | **Negation + tokeniser + content words out of the axis tables** (C-C1, C-C4, C-C5)                                                   | 17-19, 21-22  | `models.py` (`excluded_*`)                                  | **M**  | no (contract)                  |
| **P0.3** | **Tri-valued comparison + UNKNOWN out of the denominator + the match-axis tie-break**; delete every write-side fallback              | 6, 11, 25, 26 | `models.py` (`ScoreBreakdown` note)                         | **M**  | no (contract)                  |
| **P0.4** | **Preference resolution**: `resolve()`, B's denominator, tier hierarchy, evidence counts, `superseded_by`, ratification              | 1-6, 37       | `models.py`, `db_models.py`, `sql_repository.py`, **[MIG]** | **L**  | no                             |
| **P0.5** | **Ordinal axes**: `pivot`/`direction`, `travel_utility` absorbs `_friction` and the learned ceiling, `_NEAR_THRESHOLD_M` deleted     | 7-10, 27      | `models.py`, **same [MIG] as P0.4**                         | **M**  | **fold into P0.4's migration** |
| **P0.6** | **Taxonomy**: `ontology.py`, three candidate columns, `NOT_FOR_ME → ACTIVITY_TYPE`, `_diversify` keys on type, `CATEGORY` deprecated | 13-16         | `models.py`, `db_models.py`, `fixtures.py`, **[MIG]**       | **M**  | no                             |

P0.4 + P0.5 must be **one** Alembic revision and **one** Supabase mirror. P0.6 is a second,
independent revision on a different table — it can follow immediately but not concurrently
(`db_models.py` conflict). P0.1 is genuinely standalone: **land it first, because it removes the
sequencing hazard in §6.N1 before anything touches the weights.**

### P1 — high value

| #         | Slice                                                                                                                                                                                   | Tests            | Shared files                                              | Effort |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | --------------------------------------------------------- | ------ |
| **P1.1**  | `activity_types` / `excluded_activity_types` in `ActivityIntent`; soft `request_fit` axis; LLM tool enum generated from the enum                                                        | 20, 23           | `models.py`, `agent/intent_planner.py`                    | **M**  |
| **P1.2**  | `distance_is_explicit`; "near me" stops hard-filtering                                                                                                                                  | 23               | `models.py`, `intent.py`                                  | **S**  |
| **P1.3**  | Series-scoped affinity + day-dedupe + negative verdicts (`not_enjoyed`)                                                                                                                 | 30-32            | `sql_repository.py`, `models.py`                          | **M**  |
| **P1.4**  | Attendance gate on enjoyment + the web gate at `senior-view.tsx:476`                                                                                                                    | 33               | `sql_repository.py`, `main.py`, web                       | **S**  |
| **P1.5**  | Reason-aware outreach weights + `_single_observation_deltas` enumeration (**§6.N6**)                                                                                                    | 34, 35           | `learning.py`, `sql_repository.py`                        | **S**  |
| **P1.6**  | One `_candidate_for_key` resolver shared by `outreach_detail` and the decline learner                                                                                                   | 14               | `sql_repository.py`                                       | **S**  |
| **P1.7**  | Timing clarification chip + the ≥2-observation rule                                                                                                                                     | 12               | `models.py`, **[MIG]** (nullable `clarification` ×2), web | **M**  |
| **P1.8**  | World-model repairs: consent provenance, `local_hour`, calendar staleness, `either` phrasing, `view-models.ts:1250-1254`                                                                | 38-40            | `world_model.py`, `sql_repository.py`, web                | **S**  |
| **P1.9**  | One `environment_compatibility` shared by filter, preference and rain                                                                                                                   | (amend existing) | `activity_search.py`, `preferences.py`, `evaluation/`     | **S**  |
| **P1.10** | **Re-author the benchmark on the production schema** (vary `rain_forecast`, add a soft-distance and a content template, personas with directional declines), then re-run every ablation | 41-43            | `evaluation/ranking/*`                                    | **L**  |

**P1.10 gates everything numeric.** Do not touch `RANKING_WEIGHTS` or the ADR 0003 handoff until the
benchmark can see format-vs-content, dry days and soft distance.

### P2 — enhancement

Goals folded in as `STATED_GOAL` (A-F7, test 18-analogue); `preferred_language` as a soft intent
default; `ActivityFamily` half-strength generalisation; multiplicative `context_suitability` +
weight sweep + an ADR; LLM rerank displacement bound and a richer payload (B-F16); `suggested_types`
chip (C-C2); outreach cold-start rotation (B-F15); replanning seeded with the original's type
(B-F17); dropping `describe_preference`, the dead `PREFER_SOMETHING_ELSE` branch and `confirmed`;
the four doc/code corrections (A-F12, B-F20, D-§14); context answers feeding tomorrow's suppression.

### P3 — research

Retiring `_tier` and the weighted `intent` term (only after P1.10 and only with a paired-NDCG diff
listing every changed top-3); A's separate `preference_observations` table if a history surface is
ever wanted; recency decay on item affinity; attribute-prior cold start for outreach; an intent
phrasing corpus with a recorded-response fake and an opt-in `live_llm` mark (C-C6).

---

## 6. Findings none of the four reports made

**N1 — The 7.0 intent weight is the only thing keeping B-F4 latent, so B's own F5 remedy makes the
invariant breach routine.** `r2_diversity.py`: with the production weights no variety promotion
occurs at all on the fixture; with `RANKING_WEIGHTS["intent"] = 0`, `_diversify` promotes
`reading-corner` (tier 0.0) over `sheltered-walk-1` (tier 1.0) on a `light+morning` request. A tier
gap currently implies a total gap of at least `7/constrained_axes ≥ 1.17` (or `2.0` from
`repetition`), comfortably outside the `0.5` margin; remove the term and the gap collapses to the
margin's own scale. **Serialisation consequence: P0.1 (tier-aware diversify) must land before any
change to `RANKING_WEIGHTS` or `_tier`.** None of the four reports connected F4 and F5, and B
proposes them as independent items in the same redesign.

**N2 — Negation inverts the SOCIAL hard filter, and the INTENSITY case reports full understanding.**
C's probe covered environment and concluded the SOLO-before-SOCIAL table order rescued the social
case. It does not: `"I don't want a group class"` → `social_preference=SOCIAL` →
`_wrong_company` (`activity_search.py:235-252`, a `_RULES` entry) hard-excludes every self-guided
listing. And `"no chair exercise"` → `intensity=LIGHT` with `unparsed_terms == []`, so the
confirmation card claims full understanding. This is why test 17 must be a **property test over
every needle in every table**, not the three hand-written cases C proposes.

**N3 — Two modules each rely on the other's discipline and neither holds.**
`sql_repository._activity_candidate_for_key:2758-2762` states as its contract that for a
`programme:` key "the environment, social, **intensity** and category axes simply stay silent
instead of learning something nobody said". `preferences._declined_value:181-186` fabricates
`ActivityIntensity.MODERATE`. So every outreach `too_tiring` writes a fact the resolver's own
docstring promises it cannot write — and, per D-§4, the same programme resolves through
`outreach_detail:3223-3256` to a catalogue row that says `intensity=light`, i.e. the stored belief
**contradicts** the listing it was derived from. D found the fabrication; nobody noticed it
falsifies a second module's stated invariant, which is what makes it a P0 rather than a tidy-up.

**N4 — B-F3's fix creates the mirror error.** Excluding UNKNOWN from the denominator makes an
unlisted listing score identically to a confirmed match, i.e. UNKNOWN becomes TRUE — the same class
of error the finding exists to remove. Needs the match-axis-count tie-break (§2.6, test 26). All
four reports assert "unknown never negative"; none noticed that "unknown never positive" also has
to be stated.

**N5 — `FORGET` is unreconciled with every proposed evidence model.** Today it deletes rows
(`models.py:916-926`). A's append-only design contradicts it; D's evidence counts would let the next
tap resurrect a belief the person believed erased; B and C do not mention it. Resolution in §2.9
(`sentiment=retract` + `superseded_by`), and it needs an ADR line because a senior can observe the
change.

**N6 — D-§1 mechanically perturbs the constant that bounds A's and B's outreach tie-break, and the
failure is silent.** `SOCIAL_DIMENSION_RANKING_WEIGHT = MIN_SINGLE_OBSERVATION_DELTA / 4`
(`sql_repository.py:255`), and `MIN_SINGLE_OBSERVATION_DELTA = min(abs(delta) for delta in
_single_observation_deltas())` (`learning.py:213`) is recomputed at import from the weight tables —
deliberately, "so a future retune of the weights cannot silently invalidate it"
(`learning.py:179-183`). `_single_observation_deltas` enumerates `_OUTCOME_WEIGHTS`,
`_FOLLOW_THROUGH_WEIGHTS` and `_ENJOYMENT_WEIGHTS` — it has **no knowledge of a reason-keyed table**.
D-§1 adds `_DECLINE_REASON_WEIGHTS`. D's specific numbers happen to be safe (the smallest new
`|delta|` is `0.05`, above today's minimum of `0.0167` from the `partial` variants), but any future
reason weight below `(0, 0.35)` would shrink the bound, and any reason weight the enumeration does
not see makes ADR 0005's "enforced by construction rather than by a hand-picked constant" false in
the **unsafe** direction — while `test_social_nudge_cannot_override_a_single_real_acceptance` keeps
passing. Fix: extend `_single_observation_deltas()` to enumerate `declined × reason` in the same
change (test 35). Nobody linked D's outreach-weight work to A's and B's preference-weight work
through this constant.

**N7 — `social_shape_score` inherits every change to the preference resolver and its bound is
derived from `strength`'s Pydantic range.** `preferences.social_shape_score:526-546` calls
`_weighted_dimension_score` and the ADR 0005 bound argument (`sql_repository.py:236-240`) rests
explicitly on `social_shape_score ∈ [-1, 1]` "because `DimensionPreference.strength` is a Pydantic
`Field(ge=-1, le=1)`". A, B and D all replace that scalar. Whatever `resolve()` returns must keep
`ResolvedPreference.weight` Pydantic-bounded to `[0, 1]` and `social_shape_score` bounded to
`[-1, 1]`, or the bound stops being structural. Cheap to honour, invisible to break.

---

## 7. What NOT to build — consolidated, with the four reports' lists reconciled

Adopt every "what NOT to build" item in A, B, C and D **except** the following, which I overrule:

- **B: "delete `_tier`."** Keep it (§2.5). Revisit at P3 with a re-authored benchmark.
- **C: "for `social`/`intensity` the complement of a negation is unambiguous."** Negation produces
  exclusions only, never positives, on every axis (§3.9).
- **A: a separate `preference_observations` table.** Rebuild instead (§2.1); revisit only if a
  history surface is actually wanted.
- **B: `content_tags: list[str]`** and **A: `activity_kind: list[str]`.** Use C's closed enums (§2.3).
- **B: an EMA/quantile distance tolerance** and **A: the `−(d−max)/max` penalty** and **D: the ±25 %
  ramp.** One fixed scale, `tolerance = min(pivot)` (§2.2).
- **B: an hour-of-day kernel for timing.** Chip + ≥2 rule (§2.8).
- **B: recency decay on item affinity in the first pass.** Day-dedupe first; decay is P2 (§2.10).

And two additions of my own:

- **Do not change any `RANKING_WEIGHTS` value before the benchmark is re-authored (P1.10).** Five of
  six templates cannot see the differences that matter, and `weights_digest` pins whatever is chosen
  into a committed artefact.
- **Do not land P0.4, P0.5 and P0.6 as three migrations.** P0.4+P0.5 are one revision on
  `activity_dimension_preferences`; P0.6 is one revision on `activity_candidates`. Each needs its
  hand-mirrored idempotent Supabase file and its RLS deny policy, and the existing
  "every ORM table has a deny policy" test will fail until both are written.
