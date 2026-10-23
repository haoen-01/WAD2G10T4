# Audit A — Preference / World Model

Worktree `/Users/ianpong/Projects/ismoggers-v2` @ `010aa96`. Read-only. Two throwaway scripts were run
(SQLite, `LLM_ENABLED=false`, `ADAPTER_MODE=fixture`); their full output sits beside this file:

- `a_ranking_experiment.py` / `a_ranking_experiment_output.txt` — pure ranking: fixture catalogue
  (29 candidates) ranked under 3 intents × 27 single-fact `ActivityPreferences`.
- `a_repo_behaviour.py` / `a_repo_behaviour_output.txt` — repository on SQLite: fresh world model,
  a 1.2 km "too far", "That's right", reversed stance, forget, dead stated values, repeat statements.

All line numbers are `apps/api/src/silverloop/...` unless prefixed.

---

## 0. What already exists (do not rebuild)

| Substrate                                                                                                                                          | Where                                                                                    | Status                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Typed dimension preference with `source` tier, `strength`, `observations`, `confirmed`, `expires_at`, `stated_text`, `first_observed_at`, `run_id` | `models.py:887-909`, `db_models.py:336-423`                                              | Solid. Unique `(person, dimension, value, source)`.                                                                       |
| Learners that fold declines and liked-aspects into dimensions, pure, never gate                                                                    | `preferences.py:248-312`, `391-456`                                                      | Solid, well-tested (`tests/test_preferences.py`, 46 tests).                                                               |
| Stated > inferred **precedence, not averaging** on a dimension                                                                                     | `preferences.py:459-500`                                                                 | Done.                                                                                                                     |
| One read helper shared by score and "why this fits" line                                                                                           | `preferences.py:219-245`, `activity_search.py:322-380`                                   | Done.                                                                                                                     |
| Expiry on the simulated calendar; run-scoping with standing statements exempt (ADR 0004)                                                           | `sql_repository.py:3732-3799`, migration `c2725d7de5df` + Supabase mirror `202609130012` | Done.                                                                                                                     |
| Consent gate on inference (`PREFERENCE_LEARNING`)                                                                                                  | `sql_repository.py:2809-2815`, `4663-4667`                                               | Done; cannot be bypassed by a stated preference (statements are the person's, not inferred).                              |
| Senior controls: prefer / avoid (until) / forget, with own words                                                                                   | `sql_repository.py:4542-4640`, `main.py:1005-1040`, `senior/your-preferences.tsx`        | Done.                                                                                                                     |
| Proposed memory held until agreed; terminal, replayed, run-scoped                                                                                  | `db_models.py:534-561`, `sql_repository.py:4896-4997`                                    | Done — but has exactly **one** producer (see F12).                                                                        |
| Read-only world model with provenance, categorical confidence, evidence count, expiry, `contradicts`, `stale`, `gaps`, quality counts              | `world_model.py` (pure), `sql_repository.py:5218-5361`                                   | Done.                                                                                                                     |
| Senior surface (count-free) and evaluator surface (full envelope)                                                                                  | `senior/what-silverloop-knows.tsx`, `silverloop/personal-world-model.tsx`                | Done.                                                                                                                     |
| Ranking evaluation harness with `no_preferences` ablation                                                                                          | `evaluation/ranking/`, `docs/evaluation/ranking-evaluation.md:88-98`                     | Done: core NDCG@3 −0.117 [−0.158, −0.078] without preferences, so the factor is load-bearing _on that synthetic dataset_. |

The gap is not missing machinery; it is that the machinery encodes the wrong _shape_ of belief
(categorical buckets, one signed scalar per bucket, in-place overwrite) and several stored fields
have no reader.

---

## Findings

### F1 — `strength = ±n/(n+2)` conflates sentiment, confidence and evidence count into one scalar; averaging then makes 3 matches == 1 match and lets a like cancel an avoid — **P0**

**Evidence.**

- `preferences.py:82,114-117,349-354`: magnitude is `n/(n+2)`; sign is the only sentiment. One tap
  = 0.333, ten = 0.833. A stated PREFER/AVOID is hard-set to ±1.0 with `observations=1`
  (`sql_repository.py:4834-4856`).
- `preferences.py:479-500`: matched rows are **weight-averaged** (`weighted_total / weight_sum`).
  Experiment: `1 stated match -> 1.0; 3 stated matches -> 1.0; prefer+avoid both match -> 0.0`
  (`a_ranking_experiment_output.txt`, "averaging check"). With three stated PREFERs (near, social,
  indoor) **all 29 catalogue candidates score exactly +2.00 and the order does not change at all
  (0 pairwise swaps under every intent)** — the person's three most confident facts are a constant
  offset.
- "stated PREFER social + AVOID Group class": every Group-class listing (all are social) nets 0.0,
  every Social-group listing +2.0, every solo listing 0.0 — the AVOID never pushes a Group class
  below a solo self-guided listing. The avoid is neutralised by the like.
- Ten "not for me" declines on Group class → −0.833; one stated avoid → −1.0. A single utterance
  outranks ten observations _by construction_, which is the intended precedence; but the world
  model then reports `confidence=HIGH, evidence_count=1` for the statement and `MEDIUM, n=10` for
  the observations (`world_model.py:143-150, 318-321`) — the scalar and the envelope disagree about
  what "evidence" is.
- `sql_repository.py:4866`: saying the same thing three times increments `observations` to 3 and
  the world model shows `n=3` ("3x identical PREFER social" in `a_repo_behaviour_output.txt`).
  Repetition of one statement is counted as three pieces of evidence.

**Root cause.** `DimensionPreference.strength` is the only number the ranker reads
(`activity_search.py:726`), so it has to carry direction, certainty and count at once; the
averaging in `_weighted_dimension_score` was written for a single-row case and never revisited when
multiple axes could match.

**Severity.** P0 correctness: a person's own stated facts can be inert (constant offset) or
mutually cancelling, and the stored number is presented as two different things on two surfaces.

**Proposed design.** Separate the three quantities and stop averaging across axes:

```python
class ResolvedPreference(BaseModel):          # derived, per (dimension, value)
    dimension: PreferenceDimension
    value: str
    sentiment: Literal["like", "avoid", "neutral"]   # direction only
    confidence: FactConfidence                       # from tier + independent evidence
    evidence_count: int                              # DISTINCT observations (dedupe repeats)
    winning_tier: SourceTier                         # current_request > temporary_stated > stated > strong_learned > weak_learned
    weight: float                                    # bounded [0,1], from tier + confidence, NEVER from repetition of one utterance
```

Scoring: `preference_fit = clamp(Σ_axes sign(sentiment) · weight_axis / max_axes_seen, -1, 1)` —
a _sum over axes_ normalised by the number of axes the candidate can be checked on, so three
matching likes beat one, and an avoid on one axis is not erased by a like on another. Keep
per-axis precedence exactly as today.

**Files.** `preferences.py` (`_weighted_dimension_score`, new `resolve()`), `models.py` (new
`ResolvedPreference`, keep `DimensionPreference` as the stored row), `activity_search.py:726`,
`tests/test_preferences.py`, `evaluation/ranking/` (re-run; digests change).

**Effort.** M. **Pin with:** a test that three stated likes rank a triple-match above a single-match;
a test that AVOID(category) + PREFER(social) ranks the group class _below_ a solo listing that
matches neither; a test that `state_preference` twice yields `evidence_count == 1`.

---

### F2 — DISTANCE is a two-bucket categorical (`near` < 2000 m ≤ `far`): "too far" at 1.2 km learns _avoid near_; the intended lesson is inert on this catalogue — **P0**

**Evidence.**

- `preferences.py:102,131-134`: `_FAR_DISTANCE_M = 2_000`; `_declined_value` buckets the declined
  candidate's _own_ distance. Repo run: `'too far' on activity-evening-stretch-1 (1200 m) taught
distance=near strength=-0.333`. Then `dimension_score` for the 500 m listing = −0.333, for the
  4 600 m listing = 0.0 (`a_ranking_experiment_output.txt`, "The 1.2 km 'too far' lesson").
- Ranking: the mis-bucketed `decline DISTANCE=near` changes **134 pairwise orders** and puts
  tai-chi (2.1 km), pool (2.8 km), karaoke (3.4 km) in the top 3 under the empty intent. The
  _intended_ `decline DISTANCE=far` changes **0 pairs under all three intents** — the 8 "far"
  listings already sit last on `friction` (`activity_search.py:596-604`), so the learned fact adds
  nothing the friction factor didn't. That is the double count the lead suspected: distance is
  penalised by friction (weight 1.0), by the learned preference (weight 2.0) and by intent
  (`max_distance_m` hard filter, weight 7.0 soft), all against different thresholds.
- Three different "near" thresholds coexist: `intent.py:75` `_NEARBY_DEFAULT_M = 1000`,
  `activity_search.py:95-98` `_NEAR_THRESHOLD_M = 1000` (**defined, unused**, and its comment claims
  it "matches" the learned bucket), `preferences.py:102` `_FAR_DISTANCE_M = 2000`,
  `evaluation/ranking/_dimensions.py:32` duplicates 2000 by hand. `activity_search.py:596-604`
  friction uses 500 m / 5 000 m.

**Root cause.** Distance is an ordinal quantity stored as a nominal label; the decline names a
_threshold_ ("this was too far") but the bucket records a _class_.

**Severity.** P0: the single most concrete product requirement ("too far must teach something
different from just not today", `preferences.py:5-6`) teaches the opposite of what was said on
every listing between 0 and 2 km, which is 21 of 29 fixture listings.

**Proposed design.** An ordinal preference with a learned ceiling, not a class:

```python
# stored observation (append-only, see §Canonical)
PreferenceObservation(dimension=DISTANCE, kind="too_far", numeric_value=1200, ...)
# resolved
ResolvedDistancePreference(max_comfortable_m: int | None, confidence, evidence_count)
```

`max_comfortable_m = min over "too_far" observations` (optionally the k-th smallest for
robustness), raised by "liked the location" observations at ≥ that distance. `dimension_score`
for DISTANCE becomes a smooth penalty `-(d - max)/max` clamped to [−1, 0] for `d > max`, 0
otherwise. Retire `_FAR_DISTANCE_M`, delete the dead `_NEAR_THRESHOLD_M`, and make the friction
factor the _default_ comfort ceiling that the learned ceiling overrides (one threshold, one
penalty), which also removes the double count.

**Files.** `preferences.py` (`_distance_bucket`, `_declined_value`, `_candidate_dimension_value`),
`activity_search.py:95-98, 596-604`, `models.py` (DISTANCE value becomes a number or a
`{"max_m": …}` token), `world_model.py:130-131` phrase, `evaluation/ranking/_dimensions.py`.

**Effort.** M. **Pin with:** "too_far at 1200 m ranks the 500 m listing _above_ the 1600 m one";
"too_far at 1200 then 900 lowers the ceiling to 900"; "no learned distance ⇒ friction alone".

---

### F3 — INTENSITY "too tiring" learns _avoid this level_, not _prefer lower_; on the fixture it promotes the harder classes — **P0**

**Evidence.** `preferences.py:181-186` records the candidate's own `intensity` (fallback
`MODERATE`). Experiment: `decline INTENSITY=light` penalises 20/29 listings and the top 3 become
`evening-walk-1` (moderate), `reading-corner` (unknown), `pool-exercise-1` (moderate). A person who
said a _light_ class was too tiring is shown _moderate_ classes first — the recommendation moves
in the wrong direction. Note also that `_declined_value` guesses `MODERATE` when the listing has no
intensity (`preferences.py:183-186`), so "too tiring" on karaoke (intensity `None`) teaches "avoid
moderate" from a fabricated value — the one place the write side invents data.

**Root cause.** Same as F2: `ActivityIntensity` is ordinal (light < moderate) but stored nominal.

**Proposed design.** `ResolvedIntensityPreference(max_level: ActivityIntensity | None, …)`, where
"too_tiring" at level L sets `max_level = level_below(L)` (or `None`/"nothing suits" if L is
already the lowest, recorded as a gap not a preference). Score: 0 for ≤ max, −1 for > max, and
**unknown intensity is skipped, never guessed**. Remove the `MODERATE` fallback.

**Files.** `preferences.py:181-186, 236`, `models.py:592-596` (add an ordering helper),
`world_model.py:132-133`. **Effort.** S. **Pin with:** "too_tiring on light ⇒ every moderate
listing ranks below every light one"; "too_tiring on a listing with intensity None teaches nothing".

---

### F4 — CATEGORY is _format_, not _content_; "not for me" on a walk penalises tai chi, karaoke and gardening — **P0**

**Evidence.** `preferences.py:65,193-198,241-242` use `candidate.category` verbatim. Fixture
categories: `Group class` ×8 programmes (17 sessions), `Social group` ×3, `Self-guided` ×2,
`Drop-in, self-guided` ×1 (`fixtures.py:399,434,…`). Experiment: `decline CATEGORY=Group class`
demotes 17 of 29 listings (chair mobility, sheltered walk, tai chi, gardening, pool, brisk walk…).
Stated `CATEGORY=Walking` is accepted (`a_repo_behaviour_output.txt`) and can never match anything.
The world model phrase `"Leans towards walking activities"` is therefore a stored belief with zero
effect.

**Root cause.** The catalogue has no content taxonomy; the learner borrowed the only label it had.

**Proposed design.** Add `activity_kind: list[str]` (controlled vocabulary: `walk`, `tai_chi`,
`strength`, `stretch`, `swim`, `gardening`, `craft`, `singing`, `reading`, `social_meal`…) to
`ActivityCandidate`/`_Programme`, keep `category` as _format_. `NOT_FOR_ME` moves
`PreferenceDimension.KIND` (new) on each of the listing's kinds; `LikedAspect.ACTIVITY` likewise.
Keep `CATEGORY` (format) as a separate, explicitly-named axis, or drop it. `STATED_VALUE_VOCABULARY[KIND]`
becomes the controlled list so "Walking" is rejected or normalised to `walk`.

**Files.** `fixtures.py:_Programme`, `models.py:ActivityCandidate`, `db_models.py:ActivityCandidateRow`
(+ Alembic + Supabase mirror), `preferences.py`, `activity_search.py:_preference_reason`,
`world_model.py`, `intent.py` (parse "walk"/"tai chi" → `kinds`). **Effort.** M (schema).
**Pin with:** "not_for_me on sheltered-walk demotes evening-walk and brisk-walk but not chair
mobility"; "stated kind outside the vocabulary is 422".

---

### F5 — TIMING generalises one session to a whole time-of-day; `SocialPreference.SOCIAL` is asserted from "the people" with no listing support — **P1**

**Evidence.** `preferences.py:137-145` three buckets from the candidate's start hour; "bad timing"
on a 9:30 Monday class teaches "avoid morning" for 12/29 listings (experiment: 80 swaps). The
decline reason carries no information about _which_ aspect of timing (day-of-week, hour, clash
with a routine). `preferences.py:380-381`: `LikedAspect.PEOPLE` writes `SOCIAL=social` regardless
of `social_shape` — the one write-side fallback that asserts a listing attribute the listing did
not declare. Also `_gaps` (`world_model.py:513-515`) already says "No weekday or weekend pattern is
learned", i.e. the product knows this is a guess.

**Proposed design.** Record `PreferenceObservation(kind="bad_timing", weekday=…, hour=…)` and
resolve only when ≥2 observations agree on the same slot (or the person states it). Make the
decline chip ask one follow-up option: "wrong time of day / wrong day / clashes with something".
For SOCIAL: only write when `social_shape` is populated; otherwise store as an observation with
`value=None` and let the resolver ignore it.

**Files.** `preferences.py:137-145, 380-381`, `models.py:DeclineReason` (sub-reason).
**Effort.** S–M. **Pin with:** "one bad_timing teaches nothing; two on the same weekday-hour do".

---

### F6 — "That's right" does not convert the inferred row; it adds a second row, both persist and both render — **P1**

**Evidence.** `senior/your-preferences.tsx:186-220` calls `stateActivityPreference(dim, value,
stance)`; the API `_confirm_dimension_preference` (`sql_repository.py:4805-4877`) only touches the
`senior_statement` row. Repo run "after That's right": **2 rows** — `decline_reason −0.333` and
`senior_statement −1.000` — and the world model shows two facts for one belief
(`preference:distance:near:decline_reason`, `…:senior_statement`). The UI comment at
`your-preferences.tsx:41-46` claims the confirm "turn[s] an inferred/decline_reason row into a
senior_statement one"; it does not. Local state hides the old card until the next fetch, when both
come back with "That's right" offered again on the inferred one. The counterpart is worse: after a
_reversed_ stance the orphan inferred row is now a **contradiction** with the person's own words
(`a_repo_behaviour_output.txt` "after reversed stance": `contradictions: 1`) — a contradiction the
system manufactured by not consuming its own evidence.

**Root cause.** No notion of "an observation was _ratified_ by a statement"; rows are independent.

**Proposed design.** `PreferenceStance.CONFIRM` (or `PREFER/AVOID` with `ratifies=<preference_id>`)
that (a) writes the statement, (b) marks the observation rows on that `(dimension, value)` as
`superseded_by=<statement_id>` (append-only: never deleted), (c) carries their `observations` into
the statement's `evidence_count` as _supporting_ evidence. Readers list only unsuperseded rows.

**Files.** `models.py:916-940`, `sql_repository.py:4542-4640, 4805-4877`, `db_models.py` (nullable
`superseded_by`), `your-preferences.tsx`. **Effort.** S. **Pin with:** an API test that after
`prefer` on a `(dim,value)` with an inferred row, `GET activity-preferences` returns **one** row.

---

### F7 — Stored but read nowhere / dead paths — **P2**

Grepped every reader (`grep -rn` over `apps/api/src`, `apps/web`, `apps/e2e`):

| Item                                                                              | Where written                           | Readers outside the writer                                                                                                            | Verdict                                                                                                                                                                                           |
| --------------------------------------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `describe_preference`                                                             | `preferences.py:549-574`                | only `tests/test_preferences.py:404-431`                                                                                              | dead in product                                                                                                                                                                                   |
| `_weak_neutral_strength`, `_NEUTRAL_EVIDENCE_CAP` for declines                    | `preferences.py:87,120-128,278-282`     | unreachable: `DECLINE_REASON_DIMENSIONS[PREFER_SOMETHING_ELSE] is None` (`:74`) returns at `:269-270` before `strength_for` is chosen | dead branch (the cap is still live for `Enjoyment.OKAY` via `_capped_positive_strength`)                                                                                                          |
| `_NEAR_THRESHOLD_M`                                                               | `activity_search.py:95-98`              | none                                                                                                                                  | dead constant with a false comment                                                                                                                                                                |
| `ActivityGoal` (`get_out_more`, `meet_people`, `morning_activity`, `less_travel`) | `sql_repository.py:5373-5427`           | `world_model.py:334-352` (a fact), `_gap_prompt` `sql_repository.py:5430-5438` (any goal ⇒ one fixed sentence)                        | **never reaches ranking, intent or the planner**; `meet_people`/`less_travel`/`morning_activity` are literal SOCIAL/DISTANCE/TIMING preferences stored in a table the ranker cannot see           |
| `DimensionPreference.confirmed`                                                   | set True on every statement             | ranking: no; `world_model.py:319,325`; `describe_preference`                                                                          | redundant with `source == senior_statement` (always co-varies)                                                                                                                                    |
| `first_observed_at`                                                               | `sql_repository.py:3853,3866,4853,4869` | `world_model.py:322` only                                                                                                             | display only; fine                                                                                                                                                                                |
| `stated_text`                                                                     | `4875`                                  | `world_model.py:300-301`, `your-preferences.tsx:268`                                                                                  | display only; fine                                                                                                                                                                                |
| `PersonaProfile.age`, `background`                                                | `fixtures.py`                           | world model identity facts; `context_note` also into the outreach planner prompt (`agent/planner.py:557-566`)                         | age: nowhere else (correct). `context_note`: see F11                                                                                                                                              |
| `preferred_language`                                                              | fixture                                 | world model, planner prompt                                                                                                           | never defaults `ActivityIntent.language` (`sql_repository.py:3895-3960`) — a person whose profile says Mandarin gets no language preference in search                                             |
| `ProposedMemory`                                                                  | `context_question.py:127-157`           | one producer: answer `not_feeling_it` + note containing "alone/by myself/on my own"                                                   | the entire proposed-memory mechanism is reachable from exactly one keyword match on one optional free-text field of one question that only appears on a `GENTLE_NUDGE`/`PROGRAMME_SUGGESTION` day |
| `ContextQuestionAnswerRow.value` (resting/away/other_plans/…)                     | `sql_repository.py:5027-5037`           | world model context fact (momentary)                                                                                                  | never feeds policy, ranking or the next day's decision — "I'm away" changes nothing tomorrow                                                                                                      |

**Proposed design.** Delete `describe_preference`, `_NEAR_THRESHOLD_M`, the dead
`PREFER_SOMETHING_ELSE` branch. Fold goals into the resolver as a `stated` tier source (F1's
`SourceTier.STATED_GOAL`): `meet_people ⇒ SOCIAL like`, `less_travel ⇒ DISTANCE ceiling = current
friction near`, `morning_activity ⇒ TIMING like morning`. Default `intent.language` from
`preferred_language` when the person did not say otherwise (soft, disclosed as a reason). Wire
context answers `away`/`resting` into tomorrow's `asked_recently`-style suppression of the _same_
outreach (still a policy question; report only).

**Effort.** S each. **Pin with:** "a `meet_people` goal changes the order" (today it provably does not).

---

### F8 — `typical_response_hour` is a UTC wall-clock hour shown to a Singapore reader as "3pm" — **P1**

**Evidence.** `sql_repository.py:5943-5958`: `_as_utc(row.recorded_at).hour`, docstring says "in
UTC". `world_model.py:424-439` renders it via `_hour_phrase` on the senior's Privacy page
(`what-silverloop-knows.tsx` renders every fact statement). `local_time.py:20` fixes the project at
UTC+8; every other hour in the product goes through `local_hour`. So "Tends to reply around 3pm"
means 11pm to the reader. It is also wall-clock while the demo advances simulated days in minutes,
so in a demo it measures the operator's working hours, not the persona's.

**Proposed design.** Use `local_hour(row.recorded_at)`; label the fact as wall-clock-derived and
exclude it under a simulated run (`run.simulated` or `ADAPTER_MODE=fixture`), or drop it from the
senior surface until real timestamps exist. **Files.** `sql_repository.py:5950`, `world_model.py:427`.
**Effort.** S. **Pin with:** a test that a response recorded at 07:00 UTC reads "3pm".

---

### F9 — Provenance mislabels: seeded consent is `explicit/confirmed`; the fixture biography is told to the LLM as "written by a coordinator"; a stated `either` is narrated as "more active" — **P1**

**Evidence.**

- Consent: `sql_repository.py:509-513` seeds `ConsentEvidenceRow(source="synthetic_fixture",
actor="system")`; `world_model.py:392-407` emits `suggestions` as `EXPLICIT`, `confirmed=True`,
  `HIGH`. Fresh run: `explicit: 1, confirmed: 1` for a person who did nothing.
- Biography: `world_model.py:160-161` labels it `FIXTURE` (correct); `agent/planner.py:562-566`
  tells the outreach model it is "free text about this PERSON, written by a coordinator". The same
  string carries two provenances. Mr Ravi's is "has disclosed knee discomfort" (`fixtures.py:92`)
  — a health disclosure rendered as an identity fact with `MEDIUM` confidence on his own Privacy
  page and injected into the planner prompt.
- `world_model.py:132-133`: `"gentler activities" if value == "light" else "more active activities"`
  — a stated `intensity=either` (accepted by `STATED_VALUE_VOCABULARY`, `preferences.py:210`)
  renders as "Leans towards more active activities -- they told Care+ so." That is an
  inference presented as the person's statement. Same pattern for `social` in the web:
  `view-models.ts:1249-1250` always says "activities with other people" even for `solo`.

**Proposed design.** Read `ConsentEvidenceRow.source` and map `synthetic_fixture ⇒ FIXTURE`.
Change the planner brief to "profile note (synthetic fixture in this build)". Remove `EITHER`
values from `STATED_VALUE_VOCABULARY` (a preference for "either" is the absence of one). Fix the
two phrase tables to switch on the actual value. **Effort.** S. **Pin with:** world-model test
"a seeded consent is FIXTURE, not EXPLICIT"; "stating `either` is 422".

---

### F10 — Staleness is wall-clock (90 real days) while expiry is on the simulated calendar — **P2**

`world_model.py:50-53,326-330` compares `updated_at` (wall) to `_utcnow()`; `_preference_expired`
(`sql_repository.py:3732-3736`) uses `run.current_day`. In any demo nothing is ever stale; in
production the two clocks coincide. Decide one clock (the person's calendar) and derive stale from
`run.current_day - local_date(updated_at)` when the run is simulated. **Effort.** S.

---

### F11 — The fixture biography influences the outreach LLM ranking; learned preferences and goals do not — **P2**

`agent/tools.py:84-105` `ToolContext` carries `context_note` and nothing from
`activity_dimension_preferences` or `activity_goals`; the deterministic outreach ranker only sees
`social_shape_score` (`sql_repository.py:2392-2417`). So on the outreach side "Socially motivated;
responds well to group-based encouragement" (fixture) can steer the planner while a person's own
"avoid outdoor until Friday" cannot. Not a safety issue (policy is untouched) but an inversion of
the source hierarchy. **Design.** Pass the resolved preferences (F1) as structured, fenced data to
`ToolContext`; drop `context_note` from the prompt or label it synthetic. **Effort.** S.

---

### F12 — Docs disagree with code — **P2**

- `docs/architecture.md:63-70` says a reset "clears the person's dimension preferences -- learned
  and stated" and "the table carries no `run_id`". Code: `sql_repository.py:463-476` (no delete),
  `db_models.py:359-391`, ADR 0004, migration `c2725d7de5df`. Stale paragraph.
- `main.py:724-728` / `docs/api.md:216`: world-model content "never reach[es] a coordinator". With
  `auth_enabled=False` (every demo), `require_senior` returns a senior (`auth.py:246-252` pattern)
  and `overview-view.tsx:164` / `decision-simulator.tsx:459` render the **full envelope including
  `stated_text` and free-text category values** on the simulator/evaluator page
  (`personal-world-model.tsx:45-59`). True under auth, false in the demo the reviewers will see.
- `activity_search.py:95-98` comment says the learned "near" bucket "matches" `intent.py`'s 1 km;
  the learned bucket is 2 km (`preferences.py:102`).
- `your-preferences.tsx:41-46` says confirm converts the row; it adds one (F6).

---

## Explicit answers

**1. What does Care+ actually know about a person?** On a fresh persona: language, age, one
biography sentence (all fixture), a rolling median/MAD of daily steps and its anchored reference
(inferred from synthetic days), and a consent flag (seeded). After use: up to 6 axes × a handful of
categorical values with a signed scalar each; outreach mutes; up to 4 goal kinds; momentary answers
to one question; per-listing tap/went/enjoyed counts; a UTC reply hour. Nothing about home
location, mobility, companions, budget, transport, routine by hour or weekday, health (correctly),
or what the person actually _likes doing_.

**2. Trustworthy.** Standing `senior_statement` rows with `stated_text` (own words, verbatim);
outreach mutes; `plan_follow_through` "went"; goals (chosen, closed vocabulary); baseline
confirmation. Their _direction_ is trustworthy; their scalar (±1.0, `n` = times repeated) is not a
confidence.

**3. Guesses.** Every `decline_reason`/`inferred` row (one tap ⇒ 0.333); every distance/intensity
value derived from a bucket (F2, F3); SOCIAL from "the people" (F5); `MODERATE` fallback
(F3); the fixture biography (labelled, but still a guess dressed as a fact on the planner side);
`typical_response_hour`.

**4. Stale.** Anything `decline_reason`/`inferred` from an earlier run (correctly hidden by
run-scoping, still in the table); `_STALE_AFTER` never fires in a simulated run (F10); the
architecture doc paragraph (F12); baseline `reference_steps` when the person has moved on but never
confirmed.

**5. Can contradict.** Only same `(dimension, value)` opposite-sign pairs are detected
(`world_model.py:356-387`). Not detected: PREFER near _and_ PREFER far (both stated); AVOID
`Group class` while `meet_people` goal is active; a `less_travel` goal vs an inferred like of
`far`; a stated `intensity=light` vs a `too_tiring` on light; a proposed-memory `social` vs a stated
`solo`. And the system _creates_ a contradiction on every reversed stance (F6).

**6. Conflated.** sentiment/confidence/count in `strength` (F1); format/content in `category`
(F4); "this one was too far" with "I dislike near things" (F2); "this level tired me" with "avoid
this level" (F3); "that session's slot" with "that time of day" (F5); "said it again" with "new
evidence" (F1, `observations+1`); fixture consent with explicit consent (F9); wall-clock with the
person's calendar (F8, F10); `confirmed` with `source == senior_statement` (F7).

**7. Stored, used nowhere.** See F7 table: goals (for ranking), `describe_preference`,
`_NEAR_THRESHOLD_M`, the `PREFER_SOMETHING_ELSE` strength branch, `confirmed`, context-answer
values (for tomorrow), `preferred_language` (for search), `age`.

**8. Which facts materially change ranking (measured).** Under the empty intent (pairwise swaps of
406 possible): `decline INTENSITY=light` 143, `decline DISTANCE=near` 134, `stated PREFER
TIMING=morning` 128, `inferred CATEGORY=Group class` 111, `decline TIMING=afternoon` 106,
`decline ENVIRONMENT=outdoor` 98, `stated PREFER SOCIAL` 85, `stated AVOID Group class` 82. **Zero
effect:** `decline DISTANCE=far`, `stated AVOID far`, `stated PREFER near`, `inferred near`,
`intensity=either`, and **all three stated PREFERs together**. Under a concrete intent
(`near 1km + social`) everything shrinks (max 66 swaps) and no fact changes the top 3 except
timing/category/environment. Conclusion: the facts that move the order most are exactly the
mis-generalised ones; the facts that were meant to matter (distance) are masked by friction.

**9. Facts that would materially improve recommendation** (each grounded in an existing seam):
(a) a distance _ceiling_ in metres (F2) — replaces bucket + friction; (b) activity _kind_ (F4);
(c) a routine slot (weekday×hour) with ≥2 observations, seeded from the person's own "went" plans
(`plan_follow_through`) rather than declines; (d) companion/group need as a first-class stated
fact rather than a keyword in a note (F5, F12-memory); (e) `preferred_language` as a soft intent
default; (f) goals as stated-tier preferences (F7); (g) "what to bring / cost matters" — `price`
is on the candidate and nothing ever learns from it. (h) For outreach: the same resolved
preferences instead of the biography (F11).

**10. Facts that should NOT be collected.** Health or mobility conditions (Mr Ravi's "knee
discomfort" should not be in a fixture biography that reaches a prompt and a Privacy page); step
targets or any per-day goal number (`target_per_week` exists — keep it un-scored, as the docstring
says, or drop it); reply hour from wall clock (F8); home address/GPS (a _self-chosen_ comfortable
distance is enough, `DistanceBasis` already anticipates a future routing adapter); free-text notes
as preference sources beyond the one explicit "remember this?" (the `_ALONE_KEYWORDS` match is the
right restraint, not a pattern to grow); inferred SOCIAL from a decline (already refused —
keep it); anything inferred while consent is withdrawn (already gated — keep it).

---

## Proposed canonical world-model architecture

### Two layers, one table each

**`preference_observations` — append-only evidence.** One row per thing that happened. Never
updated, never deleted (forget = a `retraction` observation). Replaces in-place `strength` writes.

```python
class PreferenceObservation(BaseModel):
    observation_id: str
    person_id: str
    run_id: str | None                 # None only for standing statements (ADR 0004 rule kept)
    source_tier: SourceTier            # CURRENT_REQUEST | TEMPORARY_STATED | STATED | STATED_GOAL
                                       # | RATIFIED | DECLINE_REASON | ENJOYMENT | CONTEXT_ANSWER
    dimension: PreferenceDimension     # DISTANCE | INTENSITY | TIMING | SOCIAL | ENVIRONMENT | KIND | FORMAT
    sentiment: Literal["like", "avoid", "neutral", "retract"]
    value: str | None                  # nominal axes (SOCIAL/ENVIRONMENT/KIND/FORMAT)
    numeric_value: float | None        # ordinal axes (DISTANCE metres, INTENSITY level index)
    slot: tuple[int, int] | None       # TIMING (weekday, hour)
    candidate_id: str | None           # what grounded it
    evidence_id: str                   # the response/enjoyment/answer row
    stated_text: str | None
    observed_at: datetime              # wall clock, audit only
    observed_on_day: date              # the person's calendar — the clock everything reasons on
    expires_on_day: date | None
    supersedes: str | None             # observation_id this ratifies (F6)
```

**`ResolvedPreference` — derived, never stored** (computed in `preferences.resolve(observations,
today, run_id)`, pure, exactly as `world_model.build_world_model` is pure today). One per
`(dimension, value|axis)`.

```python
class ResolvedPreference(BaseModel):
    dimension: PreferenceDimension
    value: str | None                  # nominal
    ceiling: float | None              # DISTANCE max_m / INTENSITY max_level
    slots: list[tuple[int, int]]       # TIMING, only slots with >= 2 agreeing observations
    sentiment: Literal["like", "avoid"]
    winning_tier: SourceTier
    confidence: FactConfidence         # from tier + DISTINCT evidence, capped MEDIUM unless stated/ratified
    evidence_count: int                # distinct observations (same utterance repeated = 1)
    weight: float                      # [0,1]: tier base × confidence factor; what the ranker reads
    expires_on_day: date | None
    supporting: list[str]              # observation ids
    contradicted_by: list[str]         # observation ids at a *lower* tier that disagree (shown, not used)
    stated_text: str | None
```

### Source hierarchy (resolution order; higher wins the axis outright)

1. `CURRENT_REQUEST` — today's `ActivityIntent` (already the hard filter + 7.0 weight; keep it _out_
   of the preference factor to end the intent/preference double count — an axis the intent
   constrains contributes 0 preference score).
2. `TEMPORARY_STATED` — statement with `expires_on_day` ≥ today.
3. `STATED` / `STATED_GOAL` / `RATIFIED` — standing own words, goals, confirmed inferences.
4. `STRONG_LEARNED` — ≥ 3 distinct `DECLINE_REASON`/`ENJOYMENT` observations agreeing.
5. `WEAK_LEARNED` — 1–2 observations (shown as "just a hint", weight ≤ 0.35).
6. `DEFAULT` — friction (distance), nothing else.

A lower tier never averages into a higher one on the same axis (keep today's precedence rule,
generalised from "stated" to "any higher tier"). Across _different_ axes contributions **sum**
(normalised by axes checked), not average.

### Scope hierarchy

`current request` (this search) > `temporary explicit` (until day D, run-scoped) > `persistent
explicit` (person-scoped, survives reset) > `learned` (run-scoped) > `default`. This is exactly
ADR 0004's split, now made a first-class field (`source_tier` + `expires_on_day`) rather than
derived from `source`/`expires_at` in `_preference_inactive`.

### Dimension-value granularity

| Axis        | Today                          | Proposed                                                                 |
| ----------- | ------------------------------ | ------------------------------------------------------------------------ |
| DISTANCE    | `near`/`far` @ 2 km            | metres; resolved to a ceiling                                            |
| INTENSITY   | `light`/`moderate`/`either`    | ordinal index; resolved to a max level; `either` not storable            |
| TIMING      | 3 buckets                      | (weekday, hour) slots; ≥2 to resolve; optional stated bucket             |
| SOCIAL      | `social`/`solo`/`either`       | keep, drop `either`                                                      |
| ENVIRONMENT | `indoor`/`outdoor`/`sheltered` | keep; allow _learning_ it from `NOT_FOR_ME` sub-reason "weather/setting" |
| CATEGORY    | free catalogue text (format)   | split: `KIND` (controlled content vocabulary, F4) + `FORMAT`             |

### What a migration would need

1. Alembic revision: create `preference_observations`; **backfill** one observation per existing
   `activity_dimension_preferences` row (`observations` ⇒ one row with `evidence_count` hint, since
   the history is gone; label `source_tier` from `source`/`expires_at` per ADR 0004; map
   `near/far` to `numeric_value = None` + `value` kept, so old rows resolve as today until new
   evidence arrives). Do **not** drop the old table in the same revision (offline SQLite and the
   hand-applied Supabase mirror both need a two-step). Supabase mirror file with the same guards as
   `202609130012`. RLS deny policies for the new table (there is a test asserting every ORM table
   has one — it will fail until added).
2. `models.py`: add `PreferenceObservation`, `ResolvedPreference`, `SourceTier`, `KIND`; keep
   `DimensionPreference` as the wire shape of `ResolvedPreference` for one release (or version the
   route). Regenerate the TS client (`pnpm client:generate`), commit `openapi/silverloop.json`.
3. `preferences.py`: `apply_decline`/`apply_enjoyment` become observation constructors;
   `resolve()`; `dimension_score` reads `ResolvedPreference.weight`. The pure-function tests
   largely survive by replacing "strength" assertions with "weight/sentiment/evidence_count".
4. `activity_search.py`: preference factor = axis sum; drop the intent-constrained axes from it;
   friction becomes the default distance ceiling.
5. `world_model.py`: facts from `ResolvedPreference` + raw observations (so "3 hints, 1 statement"
   reads correctly); `contradicted_by` replaces `_mark_contradictions`.
6. Web: `your-preferences.tsx` reads `evidence_count`/`confidence` instead of `strength`
   thresholds (`view-models.ts:1141-1150`); "That's right" ⇒ `ratify`.
7. Evaluation: dataset traces re-folded; expect NDCG movement; new ablation `no_preference_sum`.
8. Scenario YAML: none touches this table; add one for "too_far at 1200 m".

---

## What NOT to build

- **Not** a stored/cached `PersonWorldModel` table — the read-model discipline is right; keep it pure.
- **Not** a numeric confidence on facts (`FactConfidence` categorical is right); the fix is to
  separate the _inputs_ to it, not to expose a probability.
- **Not** an LLM that infers preferences from notes or transcripts; the single keyword gate in
  `context_question.py:91` is the boundary, and the "propose, then ask" pattern is the right one to
  reuse for any new inference.
- **Not** cross-run comparison of learned beliefs (ADR 0004 accepted losing it; append-only
  observations give it back for free, but do not build a UI for it).
- **Not** home address / geolocation to compute distance — a self-chosen ceiling suffices.
- **Not** any health, mobility or "capability" fact (`FollowThrough.UNABLE` docstring already forbids it).
- **Not** a second Beta-Bernoulli over dimensions; the ordinal-ceiling + count model is simpler and
  explains itself in a sentence.
- **Not** more decline-reason chips than a person can read; one sub-question on `bad_timing` and
  `not_for_me` is the ceiling.
- **Not** a coordinator view of preference _content_ — the aggregate-only decision stands; fix the
  demo-mode leak (F12) rather than widen it.
