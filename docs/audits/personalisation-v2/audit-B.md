# Audit B — Ranking / recommender pipeline

Worktree `/Users/ianpong/Projects/ismoggers-v2` @ `010aa96`. Read-only. Every command below was run
as `cd apps/api && uv run python <script>`; scripts and full outputs are beside this file:

- `b_trace.py` / `b_trace_output.txt` — Sheltered Morning Walk traced end to end (20 numbered sections; "§n" below refers to them).
- `b_intent_weight_inert.py` / `b_intent_weight_inert_output.txt` — is `RANKING_WEIGHTS["intent"]` load-bearing?
- `b_intent_diffpos.py` / `b_intent_diffpos_output.txt` — where exactly it changes an order; evaluation catalogue vocabulary.

Files audited: `apps/api/src/silverloop/activity_search.py`, `preferences.py`, `learning.py`,
`replanning.py`, `intent.py`, `sql_repository.py` (`search_activities` L3895-4155,
`_activity_engagement` L4158-4230, `_rank_intervention_candidates` L2365-2415,
`_finalize_intervention` L2478-2596, `SOCIAL_DIMENSION_RANKING_WEIGHT` L230-255),
`agent/planner.py` (L172-200, L328-540), `agent/tools.py` (L111-156, L431-461),
`agent/guardrails.py` L475-520, `evaluation/ranking/{ablations,runner,labels,dataset,_dimensions}.py`,
`docs/adr/0003`, `docs/adr/0005`, `docs/evaluation/ranking-evaluation.md`, `docs/architecture.md` L427-441.

---

## 0. The pipeline as it actually runs, and the formula written out

### 0.1 Search path (`sql_repository.search_activities`, L3895-4155)

```
catalogue rows (_activity_candidate_models, ordered by activity_id)
  -> intent  (parse_intent keyword | plan_intent LLM with keyword fallback | chips)
  -> filter_candidates(candidates, intent, today)         activity_search L290
       _RULES in order, first hit wins: too_far, wrong_day, wrong_time_window,
       wrong_environment, wrong_company, full, inaccessible          L277-287
  -> rank_candidates_with_breakdown(kept, intent, prefs, rain, engagement, today)   L879
       score_candidate per candidate (6 factors, ScoreBreakdown)     L698-768
       sort key (-tier, -total, distance|inf, title)                 L924
       _dedupe_series (provider,title) within top 3                  L792
       _diversify one swap into slot 3 within DIVERSITY_SCORE_MARGIN L837
  -> plan_activity_ranking (LLM; sees top MAX_ACTIVITY_OPTIONS_RETURNED=10; may reorder/narrow)
       validate_activity_order: subset of shown keys, no dup, non-empty   guardrails L475
       narrowed options appended as FilterOutcome(rule="planner_narrowed")  sql_repository L4041
  -> audit row: ranking breakdown (operator only), planner evidence, agreement flag
  -> ActivityQueryResponse(results = RankedActivity[candidate, rank, reasons<=3, selected_by])
```

### 0.2 The exact score (activity_search.py L578-768, preferences.py L459-523)

For a surviving candidate `c`, intent `I`, active preferences `P`, per-listing engagement `E`, simulated day `d`, forecast `r`:

```
constrained(I) = #{ I.max_distance_m != None, I.time_window != ANY, I.social != EITHER,
                    I.environment != EITHER, I.intensity != EITHER, I.language != None }      (L578-589)
matched(c,I)   = # of those axes where c's field is POPULATED and matches                      (L383-468)
intent_fit     = matched / constrained            (0.0 when constrained == 0)                 (L719)

preference_fit = Σ_{rows m in P matched by c} strength_m · w(source_m) / Σ w(source_m)       (L479-500)
                 where "matched" = _candidate_dimension_value(dim, c) == m.value (None never matches),
                 rows on a dimension that also has a senior_statement row are dropped first,
                 w = {senior_statement 1.0, decline_reason 0.55, inferred 0.3};  0.0 if none matched
                 strength for learned rows = ± n/(n+2)  (n = observations; PREFER_SOMETHING_ELSE/OKAY capped at 0.15·n/(n+2))

engagement     = clamp( 0.25·interested + 0.35·went + 0.40·enjoyed
                        − 0.50·max(0, not_for_me − [in_cooldown]) , −1, 1)                   (L615-644)
repetition     = −1.0 if last_not_for_me != None and d − last_not_for_me < 14 days else 0.0   (L647-656)
context        = if r and I.environment == EITHER:  +1.0 indoor|sheltered, −0.5 outdoor, 0 unknown
                 else 0.0                                                                     (L733-745)
friction       = 0 if distance None or ≤ 500 m; else −min(1, (distance − 500) / 4500)         (L596-603)

total = 7·intent_fit + 2·preference_fit + 1.5·engagement + 2·repetition + 1.5·context + 1·friction
tier  = intent_fit + repetition                                                               (L929-940)
order = sort by (−tier, −total, distance (∞ if unknown), title)                               (L924)
```

then series-dedupe → one diversity swap (`third.total − item.total ≤ 0.5`, category differs) → LLM
reorder/narrow of the first 10 → top-K.

### 0.3 Outreach path (`_rank_intervention_candidates`, L2365-2415)

```
score(k) = expected_value(k) + 0.0043 · social_shape_score(k.social_shape, P)
expected_value = α_e/(α_e+β_e) · α_x/(α_x+β_x)        (learning.py L151-160; prior 0.25)
order = sort by (−score, key)                          -> ranked[0] is the deterministic choice
SOCIAL_DIMENSION_RANKING_WEIGHT = MIN_SINGLE_OBSERVATION_DELTA / 4 = 0.017 / 4 = 0.0043   (§17)
```

### 0.4 Sheltered Morning Walk, actual breakdown (§1-§7, §12)

Catalogue: `activity-sheltered-walk-1` (Tue 08:00 SGT) and `-2` (Fri 08:00), 1200 m, category
`"Group class"`, sheltered, social, light, languages English/Malay, available.

Request `"a gentle walk near me tomorrow morning"` → `parse_intent`:
`on_date=2026-09-15, time_window=morning, max_distance_m=1000 (from "near"), intensity=light, unparsed_terms=['walk']`.

**Hard filter removes Sheltered Morning Walk** (`too_far`: "1.2 km away; you asked for 1 km or
less") together with 15/29 listings; 11 more go on `wrong_day`, 1 on `wrong_time_window`; the two
survivors are _Community Gardening_ and _Chair Mobility & Balance_ — the person asked for a walk
and gets neither walk in the catalogue (§3). Scored directly (§6, cold start, no rain):

```
intent      +0.667 ×7.0 = +4.667  Matched 2 of the 3 thing(s) asked for.   (distance 1200>1000 not matched)
preference  +0.000 ×2.0 = +0.000  Nothing learned applies to this listing.
engagement  +0.000 ×1.5 = +0.000
repetition  +0.000 ×2.0 = +0.000
context     +0.000 ×1.5 = +0.000
friction    −0.156 ×1.0 = −0.156  1.2 km away.
TOTAL +4.511   tier +0.667   reasons: ["Runs in the morning, as you asked.", "Gentle, as you asked."]
```

Dimension extraction (§4): distance→`"near"` (1200 < 2000), intensity→`"light"`, timing→`"morning"`,
social→`"social"`, environment→`"sheltered"`, category→`"Group class"`.

---

## 1. Findings

Severity key: P0 correctness/safety · P1 high-value · P2 enhancement · P3 research.

### F1 (P0) "Too tiring" on a LIGHT listing teaches _avoid light_ — the gentler options are demoted

**Evidence.** §5/§8: `apply_decline([], TOO_TIRING, SMW)` → `('intensity','light',-0.333)`. Under that
row a LIGHT candidate scores `preference −0.333, total −0.822`; a MODERATE one `0.000 / −0.156`.
A person who found the slow walk tiring is now shown the brisk walk first. `preferences.py`
L183-186: `_declined_value(INTENSITY)` records `candidate.intensity.value`; unlabelled → `"moderate"`
(a guess recorded as a fact, §8 "'too tiring' on an UNLABELLED candidate teaches ('intensity','moderate')").
**Root cause.** Ordinal axis (light < moderate) modelled as nominal equality. "Too tiring" is a
_directional_ statement ("less than this"), stored as "not this bucket".
**Existing substrate.** `DimensionPreference` rows, `_candidate_dimension_value`, `ActivityIntensity` (2 levels).
**Proposed design.** Represent directional dimensions as a signed threshold, not a bucket:
`DimensionPreference(dimension=INTENSITY, value="<=light", ...)` is ugly; better a typed feature
layer (see §2) where `intensity` is an ordinal `0/1` (unknown = None) and TOO_TIRING writes
`IntensityCeiling(level_of_declined_candidate)`; scoring is monotonic: candidates at or below the
ceiling get 0 penalty, above get −strength. On an unlabelled candidate write nothing.
**Files.** `preferences.py` (`_declined_value`, `_candidate_dimension_value`, `STATED_VALUE_VOCABULARY`),
`activity_search._preference_reason`, `models.PreferenceDimension` docs, Supabase mirror unchanged
(value stays a string) — or a new `direction` column if a typed encoding is preferred.
**Effort.** S–M. **Pin.** `test_too_tiring_on_a_light_listing_never_demotes_lighter_options` and
`test_too_tiring_on_an_unlabelled_listing_records_nothing`. Breaks `test_too_tiring_moves_intensity_and_too_far_does_not` (asserts value == "light").

### F2 (P0) "Too far" at 1.2 km teaches _avoid near_; three distance thresholds disagree

**Evidence.** §5/§7: TOO_FAR on SMW (1200 m) → `('distance','near',-0.333)`; a 300 m candidate is
then demoted `−0.666` (total 6.334 vs 7.0) while a 3000 m candidate is untouched (`preference 0.000`).
Thresholds: `intent._NEARBY_DEFAULT_M = 1000` (hard filter), `preferences._FAR_DISTANCE_M = 2000`
(bucket), `activity_search._NEAR_FRICTION_M/_FAR_FRICTION_M = 500/5000` (friction),
`activity_search._NEAR_THRESHOLD_M = 1000` — **defined at L98 with a comment claiming it matches the
learned "near" boundary, and never used** (`grep` → only its definition). Unknown distance + TOO_FAR
writes `"far"` (L180) — a guess.
**Root cause.** Continuous quantity bucketed into two nominal values with a boundary unrelated to
the boundary the intent parser and friction use; a directional decline stored as bucket identity.
**Proposed design.** `DistanceTolerance` learned as a soft ceiling in metres from the person's own
declines/enjoyments: TOO_FAR at _d_ lowers `tolerance_m` toward _d_ (e.g. EMA / quantile); "liked the
location" at _d_ raises it. Score with one monotonic travel utility
`u(d) = −clip((d − tolerance_m)/scale, 0, 1)` and delete `friction`, the near/far bucket and the
filter's 1000 m default (see F6). One threshold, owned by one function.
**Files.** `preferences.py`, `activity_search.py` (`_friction`, `_preference_reason` DISTANCE), `intent.py`,
`evaluation/ranking/_dimensions.py` (mirrors 2000), `labels.py` personas using `("distance","near")`.
**Effort.** M. **Pin.** `test_too_far_at_1200m_never_demotes_a_300m_listing`;
`test_travel_utility_is_monotonic_in_distance`. Breaks `test_too_far_creates_a_distance_preference_never_offered_before`,
`test_dimension_score_skips_an_unknown_distance_rather_than_guessing` (partly), `test_liked_the_location_uses_the_candidates_own_distance_bucket`,
`test_evaluation_helpers_agree_with_the_production_helpers_they_duplicate` (FAR_DISTANCE_M == 2000), `_distance_constrained` template.

### F3 (P0) UNKNOWN on a constrained axis is scored as a MISMATCH and costs a whole tier

**Evidence.** §11: intent `language=Malay, time_window=morning`. SMW (lists Malay) → `intent_fit 1.0,
tier 1.0, total +6.844`; the same listing with `language_tags=[]` survives the filter (correct,
L270-274) but scores `intent_fit 0.5, tier 0.5, total +3.344`. `_intent_reasons` (L393-468) only
counts populated matches; `_constrained_axes` counts every asked axis, so absence lands in the
denominator as a miss. Because `_tier = intent + repetition` is the primary sort key, no learned
like, history or context can ever lift the unlisted-language candidate back above a listed one.
Across the 84 evaluation cases the survivors carry 98 distance-UNKNOWN, 56 social-UNKNOWN,
28 language-UNKNOWN, 28 env-UNKNOWN, 28 intensity-UNKNOWN instances (`b_intent_weight_inert_output.txt`).
The benchmark's `unknown_admitted@3` metric then _rewards_ this demotion — a label that restates the feature.
**Root cause.** Three-valued match (MATCH / MISMATCH / UNKNOWN) collapsed to boolean in the
numerator only. Violates the brief's invariant "UNKNOWN never silently becomes FALSE".
**Proposed design.** Feature extraction returns `Tri = MATCH | MISMATCH | UNKNOWN` per axis;
request-fit averages over `MATCH+MISMATCH` axes only (UNKNOWN excluded from the denominator), and
UNKNOWN is surfaced as a _disclosure_ ("Language not listed") — never a score. Drop the tier (see F5).
**Files.** `activity_search.py` (`_intent_reasons`, `_constrained_axes`, `score_candidate`), `runner.py` `unknown_admitted_at_3` semantics.
**Effort.** S. **Pin.** `test_an_unlisted_field_never_lowers_the_request_fit`.
Breaks `test_intent_fit_counts_every_matched_axis_not_only_the_three_lines_the_card_shows` only if it relies on unknowns (check), and `unknown_admitted@3 == 0.0` artifact values.

### F4 (P0) The diversity swap compares totals, not tiers — a weaker request match can be promoted into slot 3

**Evidence.** §14: request `morning + light`; three LIGHT "Group class" listings (tier 1.0, total 7.0)
and one MODERATE "Social group" listing (tier **0.5**, total 7.0 because stated category like +2.0 and
engagement +1.5 exactly offset the intent deficit 3.5). `_diversify` L860 checks
`third_total − item.total > DIVERSITY_SCORE_MARGIN` only → the intensity-mismatching candidate takes
slot 3, `variety_promoted=True`. `no_diversity` order is `[G1, G2, G3, G9]`.
This contradicts the module's own contract (L106-111 "nothing learned or inferred can override a
stated request"), `docs/architecture.md` L428-432, and the tier docstring L929-937.
**Root cause.** Two ordering semantics (lexicographic tier-first vs scalar margin) mixed; the swap
was written against the scalar. Also the margin comment "roughly an extra 2 km" is 0.444, not 0.5 (L145-149 vs L136-137; minor).
**Proposed design.** Diversity operates on a single utility with no tier (F5), _or_ the swap must
require `tier(item) == tier(third)`. Prefer the former: `diversify(top_k, λ)` as greedy MMR over a
content-category feature with a hard cap of one promotion, keeping the margin.
**Files.** `activity_search._diversify`. **Effort.** S. **Pin.** `test_diversity_never_promotes_a_lower_tier_candidate`
(build exactly §14). Nothing existing breaks.

### F5 (P1) The intent soft factor (weight 7) is inert for the top-K; ADR 0003's `no_intent_soft` arm is itself confounded

**Evidence.** After `filter_candidates`, every survivor either MATCHES or is UNKNOWN on distance,
time, social, environment and language (those five are `_RULES`); only **intensity** is in
`_INTENT_AXES` (L578-585) but not in `_RULES` (L277-287), so it is the only axis where a survivor
can genuinely mismatch. Within a tier every candidate has the same `intent_fit`, so `7·intent_fit`
is a constant offset. Experiment: set `RANKING_WEIGHTS["intent"] = 0` (scratch monkeypatch) and
re-rank all 84 evaluation cases — 13 orders change, **first difference at positions 20–50, never
in the top 3**, and always the same shape: a tier-0 item with `(intent 1.0, repetition −1.0)`
against a tier-0 item with `(0.0, 0.0)` (`b_intent_diffpos_output.txt`). In the product the model
sees only the first 10.
ADR 0003 hands the blocked ticket `no_intent_soft` NDCG deltas (+0.012 core / +0.052 holdout). That
arm (`ablations.py` L81-128) re-sorts _after_ production series dedupe on the un-adjusted totals and
does not re-run dedupe (its own docstring: `series_duplication_rate@3 +0.444`). Re-admitting
same-programme sessions that were graded relevant is what moves NDCG, not the intent term —
`no_diversity` (which keeps dedupe) moves NDCG only +0.0045/+0.011. So the number handed over is not evidence about the soft term either way.
**Root cause.** Redundancy between hard filter, soft score and tier; the soft score's only real
content (intensity mismatch, UNKNOWN penalty) is hidden inside a factor labelled "what the person asked for".
**Proposed design.** Delete `intent` from the weighted sum and delete `_tier`. Keep a small
`request_fit` for _soft-only_ asks (today: intensity; tomorrow: "walk" as a content term, see F6)
with UNKNOWN excluded (F3). Document that hard asks are honoured by the filter and are not re-scored.
**Files.** `activity_search.py`, `ablations.py` (`no_intent`, `no_intent_soft` become meaningless), `report.py` weights digest, `docs/adr/0003` handoff section.
**Effort.** S–M. **Pin.** `test_request_fit_only_scores_soft_axes`; evaluation check that top-3 is
unchanged vs today on the 84 cases (regression). Breaks `test_every_factor_is_bounded_and_named`
(factor names), `test_a_stated_request_outranks_every_learned_preference_combined` (asserts the
weight inequality), `test_a_fuller_match_is_never_overtaken_by_learned_preference_context_and_history`
(depends on tier but is satisfiable by filtering), `test_a_recent_not_for_me_can_still_pull_a_full_match_down_a_tier`,
`test_no_intent_soft_zeros_only_the_intent_contribution_and_keeps_the_real_tier`, `test_no_intent_soft_ablation_is_reported_in_the_artifact`,
`test_the_search_audit_records_the_breakdown_for_evaluators` (factor set), `test_weights_digest_is_stable`/`test_committed_artifact_is_not_stale` (artifact regen).

### F6 (P1) A vague phrase becomes a hard constraint: "near me" = 1000 m cut-off, and "walk" is unparsed

**Evidence.** §2-§3: `"a gentle walk near me tomorrow morning"` → `max_distance_m=1000`; SMW at 1200 m
and 15/29 listings are removed as `too_far`; `unparsed_terms=['walk']`; the two survivors are gardening
and chair mobility. `intent.py` L64-75 (`_NEARBY` → `_NEARBY_DEFAULT_M`), L232-290 (no content
vocabulary). The LLM intent planner fills the same `ActivityIntent`, which has no field for activity content.
**Root cause.** Soft language ("near", "close by") and explicit numbers ("within 800 m") both land in
the one hard field `max_distance_m`; the contract has no soft-distance or content slot.
**Proposed design.** `ActivityIntent.max_distance_m` stays hard **only** when the person gave a
number; a nearby phrase sets `distance_soft: bool` (or `preferred_distance_m`) that feeds the
travel utility (F2) and never the filter. Add `content_terms: list[str]` (parsed by a small
vocabulary: walk, tai chi, garden, sing, craft…) matched against a per-listing `content_tags`
(fixtures) as a _soft_ request-fit feature and a reason line. `unparsed_terms` keeps its job for what is still unknown.
**Files.** `models.ActivityIntent` (+ `pnpm client:generate`), `intent.py`, `agent/intent_planner.py` prompt/schema, `fixtures.py` (`content_tags`), `activity_search.py`.
**Effort.** M. **Pin.** `test_near_me_never_hard_filters_a_1200m_listing`, `test_walk_is_a_soft_content_match`.
Breaks `test_not_wanting_to_walk_too_far_yields_a_distance_limit`, `test_too_far_is_removed_with_a_named_rule` (if built on the phrase), `_meet_people_nearby` template.

### F7 (P1) Preference utility averages over matched dimensions only: 3 likes == 1 like; like + dislike == "nothing learned"

**Evidence.** §9: one inferred like (+0.333) → `dimension_score 0.333`; three matched likes on
category, timing and social → **0.333**; a +0.333 like and a −0.333 dislike → `0.0` and the
breakdown note reads "Nothing learned applies to this listing." (L727-731 keys the note on `== 0.0`).
Cross-dimension mixing: inferred +0.6 CATEGORY like vs decline −0.333 DISTANCE dislike → −0.004
because source weights (0.3 vs 0.55) are applied _across_ dimensions (`_weighted_dimension_score` L479-500).
**Root cause.** Wrong denominator (matched rows) and source weighting used as a cross-axis mixer.
**Proposed design.** `preference_utility(c, P) = Σ_dims s_d · m_d / Σ_dims |s_d|` where `s_d` is the
signed strength on dimension `d` (statement supersedes, else decline over inferred _within_ `d`),
`m_d ∈ {+1 match, −1 mismatch on a closed vocabulary, 0 unknown}`. Denominator = **active
preference dimensions the candidate can be judged on**, so 3/3 matches beats 1/3, and a
contradiction is reported as such (`note="1 like confirmed, 1 dislike contradicted"`).
Report `coverage = judged_dims / active_dims` on the breakdown.
**Files.** `preferences._weighted_dimension_score`, `dimension_score`, `social_shape_score` (keep single-axis path), `activity_search.score_candidate` note.
**Effort.** S. **Pin.** `test_three_confirmed_likes_outscore_one`, `test_a_like_and_a_dislike_are_reported_not_cancelled`.
Breaks `test_without_a_statement_inferred_rows_still_average_by_source_tier` (asserts −0.5<score<0 on one dim — may still hold), `test_social_shape_score_matches_dimension_score_on_the_same_evidence`.

### F8 (P1) CATEGORY is format in production ("Group class" = 17/29 listings) but content in the benchmark

**Evidence.** §1: fixture categories `{Group class 17, Social group 7, Self-guided 4, Drop-in 1}`.
§18: "liked the activity" on SMW → `('category','Group class',+0.333)` which now boosts 17 listings
including Tai Chi, Warm Water Exercise, Brisk Walk Group. NOT_FOR_ME on a walk demotes all of them.
The evaluation catalogue (`b_intent_diffpos_output.txt`) uses content categories — Tai Chi, Gardening,
Karaoke, Board Games… (12 × 5) — and the largest ablation effect (`no_preferences` NDCG −0.117 core / −0.096 holdout)
is driven by category tastes the production catalogue cannot express. `_diversify` diversifies on the same field (§12 both survivors are "Group class").
**Root cause.** One free-text field carrying two meanings; no content ontology on `ActivityCandidate`.
**Proposed design.** Add `content_tags: list[str]` (walking, tai_chi, gardening, singing, craft, games, water…) and
`format: Literal[class, social_group, self_guided, drop_in]` to the candidate (fixture-authored,
"not listed" when absent). CATEGORY preference learns on `content_tags` (multi-label: a decline
writes a small negative on each tag; enjoyment a positive); diversity uses `content_tags`;
format becomes its own optional soft axis. Re-author the benchmark catalogue on the same schema so the ablation measures production.
**Files.** `models.ActivityCandidate` (+ migration + Supabase mirror + client regen), `fixtures.py`, `preferences.py`, `activity_search._diversify`, `evaluation/ranking/dataset.py`.
**Effort.** M–L. **Pin.** `test_disliking_a_walk_never_demotes_tai_chi`. Breaks `test_not_for_me_uses_the_candidates_own_category`, `test_category_preference_grounds_a_reason_when_it_matches`, dataset digest.

### F9 (P1) Three environment ontologies: filter/intent, preference, and rain disagree about "sheltered"

**Evidence.** §10: intent `INDOOR` keeps sheltered SMW (`_ENVIRONMENT_COMPATIBLE` L78-82) and
awards it an intent reason; a stated `prefer indoor` gives sheltered SMW `dimension_score 0.0`
(exact string compare, `preferences._environment_value` L148-166); rain treats sheltered as
indoor (+1.0, L737) although the fixture's own copy says "runs in light rain" (fixtures L456).
**Root cause.** Environment is ordinal-ish (indoor ⊂ covered ⊃ sheltered; outdoor) but modelled as nominal in one place and as a compatibility set in another.
**Proposed design.** One `environment_compatibility(ask, listing) -> Tri` used by filter, preference and context, with `covered = indoor|sheltered`. Preference vocabulary gains `"covered"`.
**Files.** `preferences.py`, `activity_search.py`, `evaluation/ranking/_grounding.py`. **Effort.** S. **Pin.** `test_a_learned_indoor_like_counts_a_sheltered_listing`. Breaks `test_environment_preference_matches_indoor_outdoor_never_category` only if its fixture uses sheltered.

### F10 (P1) Double counting: distance ×4, environment ×4, time ×3

**Evidence.** §19: "near me" ask + stated like `near` on SMW: intent +4.667 (partial), preference +2.0,
friction −0.156, plus the filter already decided it — and two card lines say the same thing
("within the 1 km you asked for" is not shown only because 1200>1000; "Close to home — you've preferred that before" is).
Environment: `_wrong_environment` (filter) + `_intent_reasons` + ENVIRONMENT preference + `context`.
Time: `_wrong_time_window` + intent + TIMING preference.
**Root cause.** Each factor re-derives a feature instead of consuming a shared feature vector.
**Proposed design.** Feature extraction once (§2.3); each signal owns one feature: travel utility owns
distance; request-fit owns _soft_ asks; preference utility owns learned tastes on axes the person did
_not_ constrain today (an axis constrained today is not re-scored from history — the ask is the
person's current word and already honoured); context owns weather×cover.
**Files.** `activity_search.py`. **Effort.** S once F5/F7 land. **Pin.** `test_a_constrained_axis_is_not_rescored_from_history`.

### F11 (P1) Scale: the rain nudge outweighs ten "too far" declines; every benchmark case is a rainy day

**Evidence.** §13: preference contribution after n TOO_FAR declines = −0.666 (1), −1.0 (2), −1.2 (3),
−1.666 (10); rain indoor +1.5, outdoor −0.75 (spread 2.25); friction ≥ −1.0. `dataset.py` L1364-1372:
all six `QueryTemplate`s pass `rain_forecast=True`, so `full` never scores a dry day; `no_context`
+0.038 core / +0.189 holdout NDCG (ADR 0003) is the only evidence, and ADR 0003 explicitly declines to weigh it.
Weights 7/2/1.5/2/1.5/1 have no tuning record; `weights_digest` pins them into the artifact.
**Root cause.** Hand-set weights on incommensurable scales; asymmetric rain values (+1/−0.5) not grounded.
**Proposed design.** Context as a bounded _multiplicative_ suitability `s ∈ [0.5, 1]` on outdoor-in-rain
only (no bonus for indoor — being under cover is not a merit on its own), disclosed as now. Vary
`rain_forecast` across templates (half dry) so the benchmark measures the dry case too. Fit remaining
additive weights by a small pairwise-preference sweep on the frozen dataset (evaluation/sweep.py exists for policy; add a ranking variant) and record it in an ADR.
**Files.** `activity_search.py`, `dataset.py`, `report.py`. **Effort.** M. **Pin.** `test_rain_never_lifts_an_indoor_listing_above_a_better_fit_on_a_dry_day`; artifact regen.
Breaks `test_rain_forecast_ranks_indoor_and_sheltered_above_outdoor_when_environment_is_open` (semantics kept, magnitudes change), `test_removing_context_improves_relevance_ndcg_but_breaks_context_rule_conformance` (pinned numbers).

### F12 (P1) Engagement and the cooldown are keyed per _session_ — a "not for me" on Tuesday's walk promotes Friday's

**Evidence.** §15: engagement `{activity-sheltered-walk-1: not_for_me=1, last=today}` →
`-walk-2` ranks #1 (tier 0, repetition 0) and `-walk-1` #2 (tier −1). `fixtures.py` L880-889 mints one
`activity_id` per session; `_activity_engagement` L4158 keys on `activity_id`; `_dedupe_series` keys on
(provider, title) but engagement does not. The per-key Beta learner for outreach has the same shape (`programme:<id>`).
**Root cause.** Item memorisation at the wrong granularity; no `series_id`.
**Proposed design.** Add `series_key` (already computed by `_series_key`) to `ActivityEngagement`
aggregation: responses roll up to the series with a per-session override; cooldown applies to the
series. Longer term, learn on attributes (F8) so an "enjoyed" on one session lifts all listings sharing tags.
**Files.** `sql_repository._activity_engagement`, `activity_search.rank_candidates_with_breakdown` (lookup by series then id), `traces.build_engagement`.
**Effort.** S. **Pin.** `test_a_not_for_me_on_one_session_holds_back_the_whole_programme`. Breaks `test_a_declined_listing_is_held_back_on_the_next_search` only in its assertion detail; `test_the_top_three_are_never_three_sessions_of_one_programme` unaffected.

### F13 (P1) Engagement arithmetic ignores recency and counts duplicate taps

**Evidence.** §15: `not_for_me=1` then `interested=1` (cooldown popped by the newer tap, L4180-4185)
→ `engagement −0.25`: the most recent word loses. Four "interested" taps → `+1.0`
(`test_interested_twice_is_one_plan_and_two_responses` pins that duplicates are stored and counted).
`enjoyed=1, not_for_me=3` → `engagement −1.0` while the card still says "You enjoyed this one before" (`_history_reason` L659-676 ignores negatives).
**Root cause.** Bag-of-counts with hand weights; reasons computed from a different rule than the score.
**Proposed design.** `item_affinity = latest_signal_weight · recency(Δdays) + small decayed history`
with one response per (listing, day) de-duplicated; reason line chosen from the _same_ state
("You said you were interested on Tuesday"). Keep `repetition` as the only hard-ish demotion, series-scoped (F12).
**Files.** `activity_search._engagement/_history_reason`, `sql_repository._activity_engagement`. **Effort.** S. **Pin.** `test_the_most_recent_response_wins`, `test_repeated_taps_do_not_compound`.
Breaks `test_the_persons_own_responses_move_the_engagement_factor_and_ground_a_history_line`, `test_one_decline_is_charged_once_while_the_cooldown_runs` (numbers).

### F14 (P2) Time is three nominal buckets: "bad timing" at 08:00 avoids 11:30; 16:59 ≠ 17:00

**Evidence.** `b_intent_weight_inert_output.txt` last line: BAD_TIMING on 08:00 SGT →
`('timing','morning',−0.333)`; an 11:30 SGT listing scores −0.333. `_time_window_for_hour` L153-163 and
`preferences._timing_bucket` L137-145 duplicated (also `replanning.py` L67-77 and `_grounding.py`).
**Proposed design.** Keep buckets for _asks_ (people say "morning"); learn timing as an hour-of-day
kernel (`avoid_hour=8, width=2h`) so 11:30 is barely affected. **Effort.** S. **Pin.** `test_bad_timing_at_8_barely_touches_1130`. Breaks `test_bad_timing_moves_timing_using_the_candidates_own_slot`, `test_liked_the_timing_uses_the_candidates_own_slot`.

### F15 (P2) Outreach cold start is alphabetical; the social nudge is a 0.004 tie-breaker; no attribute generalisation

**Evidence.** §17: all three gentle-nudge keys start at 0.25; sort key `(−score, key)` → `chair_mobility`
first by string order; stated PREFER social lifts `companion_walk` to 0.2543. ADR 0005 status line
accepts "the weaker social tie-break (exact ties only)". `_preference_learners` keys on `candidate_key`
only (L2065-2069); a programme accepted last month teaches nothing about a new programme with the same tags.
**Proposed design.** Prior from attribute affinity (same feature layer as search: social shape,
intensity, content tags) blended with the per-key posterior by evidence count
(`w = n/(n+k)`); explicit cold-start policy (rotate/least-recently-offered) instead of key order.
**Files.** `sql_repository._rank_intervention_candidates`, `learning.py`. **Effort.** M. **Pin.** `test_cold_start_outreach_is_not_alphabetical`. Breaks `test_social_nudge_cannot_override_a_single_real_acceptance` only if the bound changes (keep the bound).

### F16 (P2) The LLM rerank is bounded in _set_ but not in _displacement_, and is blind to the evidence it is reordering

**Evidence.** `tools._activity_options_payload` L431-446 sends category, distance, environment,
intensity, time window, deterministic rank and the ≤3 card reasons — no preference rows, no
engagement, no breakdown; `SYSTEM_PROMPT_ACTIVITY` L172-200 tells it to rank "only on how well an
option matches the stated request and the reasons already shown". `validate_activity_order` L475-520
checks subset/dup/non-empty only: rank 10 → rank 1 is approved. It may also _narrow_ (hide permitted
options; audited as `planner_narrowed`, L4041). A `VARIETY` reason attached at slot 3 travels with a
card the model moves to slot 1. `snapshot_stale` discards the reorder correctly.
**Proposed design.** Pass the compact breakdown and the person's active preferences (already
non-sensitive summaries) so the model adds information rather than undoing it; bound displacement
(`|new_rank − deterministic_rank| ≤ 2`) in the guardrail; recompute variety/series flags after reorder; keep narrowing but require a per-item reason string.
**Files.** `agent/tools.py`, `agent/guardrails.py`, `agent/planner.py`, `sql_repository.search_activities`. **Effort.** S–M. **Pin.** `test_guardrail_rejects_a_displacement_beyond_the_bound`. Breaks `test_guardrail_accepts_a_reordered_subset` (if it reverses a long list).

### F17 (P2) Replanning's "similar option" is similar in day/time/company/pace, not in what it is

**Evidence.** `replanning._intent_like` L80-114 builds the intent from `indoor_outdoor`, time window,
`social_shape`, `intensity`; category/content is not carried, and `rank_candidates` then orders by
the same distance-first fallback. A full tai chi class can be replaced by a crafts session at the same hour.
**Proposed design.** When `content_tags` exist (F8), seed the request-fit with the original's tags. **Effort.** S. **Pin.** `test_a_full_tai_chi_is_replaced_by_something_like_tai_chi_when_available`.

### F18 (P2) Cold start with an empty ask is nearest-first, full stop; `nothing_matched` is one wrong phrase away

**Evidence.** §20: with `ActivityIntent()` every total equals `friction` (`True` for all 29). §3: a
"near me" phrase leaves 2 survivors; a 900 m radius would leave none. **Proposed design.** Cold-start
prior = attribute affinity from the persona's confirmed facts (world model) + soon-first + content
diversity; when the hard filter leaves < 3, relax the softest ask and say so (already an honest
`nothing_matched`, but an offer of the nearest relaxation is better). **Effort.** M. **Pin.** `test_cold_start_top_three_are_not_three_nearest_classes`.

### F19 (P3) Unmotivated constants and no decay

`n/(n+2)` strength (L82), 0.55/0.3 source weights (L96-100), 0.15 caps, 14-day cooldown (L143), 0.15
`describe_preference` threshold (L558-563), 500/5000 m friction, 0.5 margin, 0.25/0.35/0.4/0.5
engagement weights. Learned rows never decay (only statements can be time-boxed). Nothing here is a
bug; it is a tuning surface with no evaluation attached. Pin whatever the sweep in F11 chooses.

### F20 (P3) Doc/code disagreements

| Claim                                                                                                            | Where                                                                    | Code                                                                                 |
| ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| "`_NEAR_THRESHOLD_M` … a learned DISTANCE preference of 'near' means the same physical distance the parser uses" | `activity_search.py` L95-98                                              | constant unused; learned bucket boundary is 2000 m (`preferences.py` L102, L131-134) |
| "no combination of learned preference, history, weather and distance can lift a weaker match past a fuller one"  | `activity_search.py` L106-111, L929-937; `docs/architecture.md` L428-432 | `_diversify` L855-875 can (F4)                                                       |
| `no_intent_soft` "isolates the intent factor's weighted score term"                                              | `docs/adr/0003` handoff; `ablations.py` L81-103                          | re-sort undoes series dedupe; the NDCG delta is a dedupe effect (F5)                 |
| "Half a friction unit — roughly an extra 2 km"                                                                   | `activity_search.py` L145-149                                            | 2 km = 0.444 friction (minor)                                                        |
| ranking-evaluation.md: "graded relevance … stated tastes" on CATEGORY                                            | `docs/evaluation/ranking-evaluation.md`                                  | benchmark categories are content; production categories are format (F8)              |

---

## 2. Proposed replacement pipeline — one responsibility per signal

Keep the shape the invariants require (pure module, filter before any model, breakdown audit-only,
reasons grounded). Replace the six-factor sum + tier with the following stages. Types are sketched in
Python; all live in `activity_search.py`/`preferences.py` unless noted.

### 2.1 Retrieval

Unchanged (`_activity_candidate_models`); add `series_key` and `content_tags` to `ActivityCandidate` (F8/F12).

### 2.2 Hard eligibility (`eligibility.py` or keep in `activity_search`)

```python
class EligibilityRule(Protocol):  # (candidate, request, today) -> str | None
_HARD_RULES = (too_far_explicit, wrong_day, wrong_time_window, wrong_environment, wrong_company, full, inaccessible)
```

Same seven rules; **`too_far` fires only when the person gave a number** (`request.max_distance_m` and `request.distance_is_explicit`). UNKNOWN never fires (as today).

### 2.3 Feature extraction — one place, tri-valued

```python
class Tri(Enum): MATCH, MISMATCH, UNKNOWN
@dataclass(frozen=True)
class Features:
    distance_m: int | None
    hour_local: float | None
    environment: Literal["indoor","sheltered","outdoor"] | None
    intensity: int | None          # 0 light, 1 moderate
    social: Literal["social","solo"] | None
    content_tags: frozenset[str]
    format: str | None
    languages: frozenset[str]
    series_key: tuple[str, str]
def extract(candidate) -> Features
def compare(feature_value, ask_or_pref_value) -> Tri   # None -> UNKNOWN, never MISMATCH
```

`preferences._candidate_dimension_value`, `_grounding.py`, `_dimensions.py`, `replanning._time_window_for_hour` all collapse into this one module (evaluation may import it — it is no longer private).

### 2.4 Request fit (soft asks only)

```python
def request_fit(f: Features, req: Request) -> Signal   # Signal(value in [0,1] | None, note, reasons)
```

Scores only axes that are _not_ hard-filtered: intensity, content terms, soft distance phrase. Averages over judged axes; UNKNOWN excluded; `None` when nothing soft was asked. No tier.

### 2.5 Preference utility with coverage

```python
def preference_utility(f: Features, prefs: ActivePreferences, req: Request) -> Signal
    # per active dimension d NOT constrained by req today: s_d ∈ [-1,1] (statement supersedes; else decline > inferred within d)
    # m_d = +1 MATCH, -1 MISMATCH (closed vocab only), 0 UNKNOWN
    # value = Σ s_d·m_d / Σ |s_d| ; coverage = judged/active ; note lists confirmed & contradicted
```

Directional axes (distance tolerance, intensity ceiling, hour kernel) are stored as typed rows (`value` string keeps the DB schema: `"<=light"`, `"tolerance_m=1400"`, `"hour=8±2"`) and scored monotonically (F1/F2/F14).

### 2.6 Item affinity (this listing / this series)

```python
def item_affinity(series_history: SeriesEngagement, today) -> Signal   # latest-response-wins, recency-decayed, deduped taps
def repetition_hold(series_history, today) -> bool                      # 14-day hold after "not for me", series-scoped; ended by a newer "interested"
```

Hold is applied as a _post-sort demotion to the tail_ (not a −2.0 term), which is what the docstring already describes.

### 2.7 Context suitability

```python
def context_suitability(f: Features, ctx: Context, req: Request) -> float  # multiplier in [0.5, 1.0]; 1.0 unless rain ∧ outdoor ∧ env not asked
```

Disclosed on the breakdown; a `CONTEXT` reason only when it changed the order.

### 2.8 Friction — monotonic travel utility

```python
def travel_utility(distance_m: int | None, tolerance_m: float) -> float  # 0 at/below tolerance, -1 at tolerance+scale; None -> 0, sorts last
```

`tolerance_m` = learned distance tolerance (F2) falling back to the persona/default 1500 m; the only place distance is scored.

### 2.9 Combination

```
utility = context_suitability · ( w_r·request_fit + w_p·preference_utility·coverage_boost + w_a·item_affinity + w_t·travel_utility )
```

with weights fitted by the sweep (F11) and pinned; `ScoreBreakdown.factors` renamed to
`request_fit, preference, affinity, travel, context` plus `hold: bool`, `coverage: float`.

### 2.10 Bounded LLM rerank

As today plus: breakdown + active preferences in the payload; displacement bound ±2 in `validate_activity_order`; flags recomputed after reorder.

### 2.11 Top-K diversification

Greedy MMR on `content_tags` (Jaccard) with λ≈0.8 over the first K=5, series dedupe first; at most one promotion beyond the margin; `variety_promoted` unchanged in meaning.

### 2.12 Explanations

`reasons` derived from the _same_ `Signal.reasons` that produced non-zero contributions (request → affinity → context → variety → preference), still ≤3, still never negative, and an UNKNOWN disclosure line ("Language not listed") allowed as a fourth, `CATALOGUE`-basis line.

---

## 3. Evaluation plan for the redesign

1. **Fix the benchmark before the ranker.** Re-author `dataset.py`'s catalogue on the production
   schema (format + content tags), vary `rain_forecast` (3 dry / 3 wet templates), add a
   `near_phrase` template (soft distance) and a `walk` content template, add personas with directional
   declines (TOO_TIRING on light; TOO_FAR at 1.2 km; BAD_TIMING at 08:00 with 11:30 listings). Make
   labels independent of features: graders read the persona brief's _content tastes_ and a stated
   distance tolerance, never `_dimensions.py`.
2. **Metrics.** Keep NDCG@3/P@3/MRR on the relevance grade; replace `unknown_admitted@3` with
   `unknown_disclosed@3` (an UNKNOWN in the top-3 must carry a disclosure line, and must not be
   demoted relative to a MATCH on other grounds); keep `series_duplication@3`, change
   `category_entropy@3` to `content_entropy@3`; add `directional_consistency` (after TOO_TIRING on
   level _L_, no candidate with level < _L_ loses rank) and `preference_coverage_monotonic` (adding a
   confirmed like never lowers a matching candidate). Report `context_rule_conformance@3` only as the conformance check ADR 0003 already labels it.
3. **Ablations that isolate one thing.** `no_request_fit`, `no_preference`, `no_affinity`,
   `no_travel`, `no_context`, `no_diversity` — each by one keyword, re-running dedupe/diversity every
   time (retire `no_intent`/`no_intent_soft`).
4. **Regression gate.** The 84 existing cases' top-3 under the new pipeline vs today's `full`
   artifact: report the paired NDCG delta and _list every case whose top-3 changed_ with both breakdowns, for review before merge.
5. **Weight fit.** Small grid/pairwise sweep on the core split only; holdout untouched; record the chosen weights and their CI in an ADR; `weights_digest` regenerates.
6. **Product checks (API tests).** The five worked scenarios above (§7 near demotion, §8 light demotion, §11 unknown language, §14 tier promotion, §15 series cooldown) become `test_activity_search.py` cases with the expected _direction_, not the number.

---

## 4. Tests that pin current behaviour and would break

`apps/api/tests/test_activity_search.py`: `test_every_factor_is_bounded_and_named` (factor names/order),
`test_a_stated_request_outranks_every_learned_preference_combined` (weight inequality), `test_a_fuller_match_is_never_overtaken_by_learned_preference_context_and_history`,
`test_a_recent_not_for_me_can_still_pull_a_full_match_down_a_tier`, `test_friction_grows_with_distance_and_costs_nothing_when_unknown` (factor index 5),
`test_the_persons_own_responses_move_the_engagement_factor_and_ground_a_history_line`, `test_one_decline_is_charged_once_while_the_cooldown_runs`,
`test_a_recent_not_for_me_holds_a_listing_back_for_the_cooldown_and_then_releases_it`, `test_diversity_*` (three), `test_rain_*` (four), `test_a_learned_dislike_now_demotes_what_it_applies_to`,
`test_intent_fit_counts_every_matched_axis_not_only_the_three_lines_the_card_shows`, `test_more_intent_matches_rank_higher`, `test_preference_dimension_grounds_a_reason_when_it_matches_a_populated_field`.
`test_preferences.py`: `test_too_far_creates_a_distance_preference_never_offered_before`, `test_too_tiring_moves_intensity_and_too_far_does_not`, `test_bad_timing_moves_timing_using_the_candidates_own_slot`,
`test_not_for_me_uses_the_candidates_own_category`, `test_liked_the_location_uses_the_candidates_own_distance_bucket`, `test_liked_the_timing_uses_the_candidates_own_slot`,
`test_without_a_statement_inferred_rows_still_average_by_source_tier`, `test_dimension_score_skips_an_unknown_distance_rather_than_guessing`, `test_social_shape_score_matches_dimension_score_on_the_same_evidence`, `test_describe_preference_*`.
`test_intent.py`: `test_not_wanting_to_walk_too_far_yields_a_distance_limit`, `test_within_800m_and_2km_both_parse` (keep), `test_understood_words_never_appear_in_unparsed_terms`.
`test_activity_responses.py`: `test_too_far_from_a_search_card_teaches_the_distance_dimension`, `test_a_second_too_far_strengthens_rather_than_duplicates`, `test_the_search_audit_records_the_breakdown_for_evaluators` (factor set),
`test_a_declined_listing_is_held_back_on_the_next_search`, `test_interested_twice_is_one_plan_and_two_responses`, `test_an_interested_after_a_not_for_me_ends_the_cooldown`, `test_cooldown_constant_is_the_one_the_ranker_uses`, `test_a_stated_value_must_belong_to_its_dimension` (vocabulary).
`test_ranking_evaluation.py`: `test_weights_digest_is_stable`, `test_committed_artifact_is_not_stale`, `test_dataset_digest_is_stable`, `test_labels_never_reference_ranking_weights_keys`,
`test_each_ablation_changes_exactly_one_keyword_argument`, `test_no_intent_*` (three), `test_removing_context_improves_relevance_ndcg_but_breaks_context_rule_conformance` (pinned deltas), `test_evaluation_helpers_agree_with_the_production_helpers_they_duplicate` (2000 m, buckets),
`test_constraint_satisfaction_is_one_by_construction`, `test_random_floor_is_strictly_below_full_on_ndcg_at_3`.
`test_replanning.py`: `test_a_full_listing_with_a_real_alternative_offers_it`, `test_a_recently_declined_listing_is_not_offered_as_the_replacement`.
`test_activity_planner.py`: `test_guardrail_accepts_a_reordered_subset`, `test_a_model_that_echoes_the_deterministic_order_reproduces_it_exactly`.
`test_agent_integration.py`: `test_social_nudge_cannot_override_a_single_real_acceptance` (keep passing).
Contract: `ScoreBreakdown`/`ScoreFactor` are in `models.py` → `pnpm client:generate` and `client:check`.
E2E (`apps/e2e/tests/product-loop.spec.ts`) pins the decline-reason UI and the `/senior/activities` route, not scores or reason text; `apps/web/components/senior/activity-card.tsx` renders `reason.text` only.

---

## 5. What NOT to build

- A separate "context stage" (ADR 0003 option C) — the problem is magnitude and asymmetry, not stage placement; a bounded multiplier inside one utility is enough.
- More `RANKING_WEIGHTS` entries or a heavier weighted sum before the feature layer exists; every new factor today would re-derive distance/environment/time a fifth time.
- A learned-to-rank model or embeddings for a 29-listing fixture catalogue; the failure modes are representational (nominal vs ordinal, wrong keys, wrong denominators), not capacity.
- Consent-model work (parked); the consent _gate_ is not bypassable through ranking — only ADR 0001's already-documented "engagement counts even while withdrawn" reading exists, and it is a design decision, not a bypass.
- Rewriting the LLM reranker as the primary ranker, or letting it see health signals; keep it bounded and optional.
- Hand-tuning the current 7/2/1.5/2/1.5/1 weights against the existing benchmark: five of the six templates cannot see the differences that matter (format categories, always-rain, no soft distance).
- A per-listing "shelter quality" fact solely to validate the rain nudge (ADR 0003 follow-up) before the environment ontology is unified (F9).
