# Audit E -- Evaluation / data science

Worktree `/Users/ianpong/Projects/ismoggers-v2` @ `010aa96`. Read-only. All paths below are under
`apps/api/src/silverloop/` unless prefixed. Both evaluators were run into
`scratchpad/audits/E/{policy,ranking}/`; the outputs are byte-identical to the committed
`docs/evaluation/*.{md,json}`. Probe scripts: `scratchpad/audits/E/probe_ranking.py`,
`scratchpad/audits/E/probe_policy.py` (commands and outputs quoted inline).

Reading guide. The two harnesses are unusually honest about their own limits -- ADR 0002 and ADR
0003 already name M4/M7/M9 and `context_rule_conformance` as tautological or confounded. This audit
confirms those, then goes past them. The headline: **neither harness has a ground truth that is
independent of the production feature pipeline.** The policy comparison's labels are a pure
function of `analyse_signal`'s output (the very fields the ladder reads); the ranking benchmark's
labels import a production constant, pin their match semantics to the production matcher by test,
and for 4 of 14 personas the "brief the ranker never sees" is handed to the ranker verbatim through
the trace. The numbers are reproducible and the framing is careful, but "Care+ 0/19 missed
persistent change" and "NDCG@3 0.80 vs random 0.60" are mostly statements about construction, not
about judgement.

---

## Findings

### E1. Policy-comparison ground truth is computed from the production signal pipeline; the "persistence and escalation are independent" caveat is false -- P0 (correctness of the headline claim)

**Evidence.**

- The label rule, as executed: `apps/api/tests/test_evaluation.py:918-934`
  `_derive_ground_truth_label(step)` reads `step.signal.quality.safe_to_interpret` (quality.py),
  `step.signal.context.rainy`, `step.signal.reference_delta_percent` (analytics.py) and
  `step.signal.sustained_low_days` (analytics.py), with cut points `-20` and `3`.
  `test_documented_ground_truth_rule_reproduces_every_scenario_label` (:937-955) asserts every
  authored YAML label equals this function's output on both sets -- so the YAML labels are, by
  test, exactly this function.
- The ladder reads the same fields with the same cut points: `evaluation/ladder.py:49-57`
  (`ESCALATION_DAYS = 3`, `NUDGE_SEVERITY = 20`), `:114` (`safe_to_interpret`), `:162`
  (`sustained_low_days >= ESCALATION_DAYS`); proven identical to `policy.decide` by
  `test_full_ladder_is_identical_to_the_real_policy` (`test_evaluation.py:535-562`).
- The caveat text claims only the -20% boundary is shared: `evaluation/report.py:71-77`
  ("Everything either side of the boundary (rain, consent, wear-time, persistence, escalation) is
  independent"). Same text in `scenarios/holdout/README.md:33-35` and
  `docs/evaluation/policy-comparison.md:19`. **Docs disagree with code**: `persistent_decline`
  is `sustained_low_days >= 3` (test_evaluation.py:932-934) and the escalation rung is
  `sustained_low_days >= ESCALATION_DAYS(3)` (ladder.py:162); `unusable_data` is
  `not safe_to_interpret` (test_evaluation.py:926) and the data-quality gate is
  `not signal.quality.safe_to_interpret` (ladder.py:114). These are the same production numbers,
  not merely the same threshold value.
- Consequence, measured (`probe_policy.py`, section A):
  ```
  core: decisions on persistent_decline={'coordinator_review': 19}; min severity=-56.1; all sustained>=3: True
  core: persistent_decline steps with severity between 20 and 40 (escalation impossible by policy rule): 0/19
  holdout: decisions on persistent_decline={'coordinator_review': 1}; min severity=-48.0
  ```
  Every `persistent_decline` step is, by the label rule, a step where the ladder's own
  escalation predicate holds (>=3 sustained days) and, by the fixture (`evaluation/simulation.py:113-123`,
  `steps = max(2100, 3400 - previous_low_days * 450)` against a ~5,000-step mdm-lim baseline),
  severity is always >= 40. So M2 = 0/19 and M3 = 0/19 for `silverloop` are reachable only
  through consent/quality/cap interception, which the fixtures never trigger on those steps.
  The one place `silverloop` does score imperfectly (holdout M1 3/12) is exactly where the label
  rule and the ladder disagree on a _design_ question (`explained_dip` ignores persistence,
  the rain gate expires after 2 days; probe section B lists `h01` step 4, `h04` steps 2-3).

**Root cause.** "World state" was operationalised as "the production `SignalSummary`", so the
label is a re-statement of the ladder's inputs at the ladder's own cut points. There is no hidden
truth anywhere in the policy harness: `EnvironmentStep` (simulation.py:51-93) carries the same
`signal` the policy sees, and nothing else.

**Severity.** P0 for how the artifact is _read_ (the evidence page and ADR 0002 quote M2/M3/M8
as discriminating), not for product safety.

**Substrate.** `simulation._advance_metric` already synthesises the world per event; `EnvironmentStep`
has `__slots__` room for a hidden-state field; `GroundTruthState` is a StrEnum; the executable
rule in `test_evaluation.py` can be lifted into `evaluation/labels.py`.

**Proposed design -- hidden latent state, labels from the latent, never from the signal.**

- `evaluation/world.py`: `@dataclass(frozen=True) class LatentState: true_activity_level: float
(fraction of personal norm, e.g. 0.45); cause: Literal["none","weather","illness_like","device","holiday","routine_change"]; explained_by_context: bool; days_low: int`.
  `_advance_metric` becomes `_advance(event, history, current, latent) -> (metric, context, consent, latent)`:
  each event mutates the latent first, then _observes_ it into a `DailyMetric` through a noise
  model (`observed_steps = norm * true_level * lognormal(0, sigma)` seeded per scenario; wear
  hours drawn from the persona's adherence). Rain events set `cause="weather"` and only lower
  `true_activity_level` for the days rain lasts.
- `evaluation/labels.py::label_from_latent(latent, consent) -> GroundTruthState`: `no_consent`
  if consent inactive; `explained_dip` if `cause=="weather" and explained_by_context`;
  `persistent_decline` if `true_activity_level <= 0.8 and days_low >= 3` -- here "3" is the
  _authored_ definition of persistence in the latent, tuned to nothing; `unusable_data` is
  authored per event (`low_wear`), not read from `quality.py`.
- Add `EnvironmentStep.latent` and keep `signal` for the policy; `fold_policy` never sees `latent`.
- Report gains "label/feature agreement" as a _diagnostic_: `share of steps where
label_from_latent == _derive_from_signal`. When it is 100% the harness is back to tautology and
  says so.
- Keep the anchored-median rationale (report.py:60-70) as a property of the latent
  (`true_activity_level` is relative to the persona's authored norm, so it cannot drift).

**Files.** `evaluation/simulation.py`, new `evaluation/world.py`, new `evaluation/labels.py`,
`evaluation/scenario_spec.py` (labels become optional overrides, derived by default),
`evaluation/report.py` (replace `LABELLING_CAVEAT`), `scenarios/*.yaml` (labels regenerated),
`docs/evaluation/policy-comparison.*`, `docs/testing.md:26-30`, `scenarios/holdout/README.md`.

**Effort.** M.

**Test to pin.** `test_labels_are_not_a_function_of_signal_summary`: construct two steps with
identical `SignalSummary` but different latents (e.g. `cause="weather"` vs `cause="none"` with the
same observed steps) and assert the labels differ; and the converse, identical latent with two
noisy observations, same label. Plus `test_label_feature_agreement_is_reported_not_assumed`.

---

### E2. Ranking benchmark: the information asymmetry does not hold for 4/14 personas, and label match semantics are pinned to the production matcher -- P0 (validity of "independent ground truth")

**Evidence.**

- Claim: `ranking/dataset.py:8-21`, `ranking/labels.py:1-4`, `ranking/report.py:31-37`
  ("an authored persona BRIEF the ranker never sees"), `docs/testing.md:222-236`.
- Trace path: `ranking/traces.py:52-71` turns every `StatedPreferenceEvent` into a
  `DimensionPreference(source="senior_statement", strength=+-1.0, confirmed=True)`, which
  `preferences._weighted_dimension_score` (preferences.py:485-496) treats as the _whole_
  contribution on that dimension. Personas whose brief facts are also in their trace, verbatim:
  ```
  eval-mr-goh     taste:social=social   <- senior_statement social +1.0   (dataset.py:1112,1116-1118)
  eval-mr-koh     hard:social=social    <- senior_statement solo  +1.0    (dataset.py:1177,1179-1181)
  eval-mr-yusof   taste:social=solo     <- senior_statement solo  +1.0    (dataset.py:1234,1238)
  eval-mr-lim-kw  hard:category=Karaoke <- senior_statement Karaoke -1.0  (dataset.py:1270,1272-1274)
  ```
  (`probe_ranking.py` section A). For these cases the grade-3/grade-0 rule _is_ the ranker's
  strongest input. `eval-mr-yusof` scores NDCG@3 = 1.000 (section D).
- Match semantics: `ranking/_dimensions.py:35-66` mirrors `preferences._candidate_dimension_value`,
  and `test_evaluation_helpers_agree_with_the_production_helpers_they_duplicate`
  (`tests/test_ranking_evaluation.py:575-598`) **asserts** the label-side matcher equals the
  production matcher for every candidate and dimension. The label's notion of "this listing is
  a Gardening / near / morning / social thing" is therefore, by test, the ranker's notion.
  The docstring calls this "an accepted, documented seam" (`_dimensions.py:18-23`) -- but the
  test makes it the opposite of a seam: drift is _forbidden_, so the label can never disagree
  with the feature about what a listing is.
- `ranking/labels.py:24` `from silverloop.activity_search import DECLINE_COOLDOWN_DAYS` and
  `:43-46, :62-63`: the grade-0 cooldown route is the ranker's own `repetition` rule
  (`activity_search.py:143, :606-615`) restated with the same constant. `report.py:63-69` even
  hashes `DECLINE_COOLDOWN_DAYS` into `weights_digest` -- correctly flagging that a label input is
  a ranker parameter.

**Root cause.** "Hidden truth" was implemented as a _separate list on the same object_
(`PersonaBrief`, dataset.py:1060-1078) with a convention about who reads which list. The
convention is not enforced for `StatedPreferenceEvent`, and the label vocabulary is the
`PreferenceDimension` enum itself, so a label can only ever say things the ranker can already
represent.

**Severity.** P0 for the claim; the benchmark is still a useful _regression_ harness.

**Substrate.** `PersonaBrief`, `grade_candidate`, `dataset_digest`, the existing test that pins
`_dimensions` to production (invert its purpose: it becomes a _leakage detector_).

**Proposed design -- two independent truth sources.**

1. **Per-listing declared facts** (`ranking/listing_facts.py`): `@dataclass(frozen=True) class
ListingFacts: activity_id: str; activity_kind: str  # free text authored from the listing's
description, e.g. "gentle standing movement", NOT `category`; effort: Literal["seated","standing","walking","vigorous"]; covered: bool | None  # is there a roof (authored from venue, independent of indoor_outdoor); group_size: Literal["1","2-5","6+"] | None; chatter: Literal["quiet","some","lively"] | None; needs_booking: bool`.
   Authored in a separate file, by hand, never derived from `ActivityCandidate` fields, digest-
   tracked separately (`facts_digest`). A test asserts `listing_facts.py` imports nothing from
   `activity_search`/`preferences`/`models` beyond `str` ids.
2. **Persona brief re-expressed in that vocabulary**: `PersonaBrief.wants: tuple[Want, ...]` where
   `Want = (field: str, value: str, polarity: Literal["like","avoid","hard_avoid"])` over
   `ListingFacts` fields only (e.g. `("effort","walking","like")`, `("chatter","lively","hard_avoid")`).
   `grade_candidate(persona, facts[activity_id], engagement, today)` reads only `ListingFacts`
   and the engagement _fact_ (`last_not_for_me`), with the cooldown length authored in the brief
   (`persona.wont_retry_days`), not imported from the ranker.
3. **Leakage guard**: `test_brief_facts_do_not_appear_in_trace_as_statements`: for each persona,
   assert no `StatedPreferenceEvent` names a `(dimension, value)` that maps, through
   `_candidate_dimension_value`, to the same set of listings as any `Want` (or, simpler: forbid
   `StatedPreferenceEvent` entirely in `CORE_PERSONAS`/`HOLDOUT_PERSONAS` and move "stated"
   personas into a separate `STATED_SPLIT`, reported on its own, where the ranker legitimately
   sees the statement).
4. Invert `test_evaluation_helpers_agree_...` into `test_label_vocabulary_is_disjoint_from_ranker_vocabulary`:
   assert the set of `ListingFacts` field names is disjoint from `PreferenceDimension` values and
   that `ranking/labels.py` has no import from `activity_search` or `preferences`.

**Files.** `ranking/dataset.py`, new `ranking/listing_facts.py`, `ranking/labels.py`,
`ranking/report.py` (add `facts_digest`), `tests/test_ranking_evaluation.py`, `docs/testing.md`,
`docs/adr/0003` (its follow-up section names exactly this).

**Effort.** M (authoring 60 listing-fact rows and 14 briefs is the bulk).

**Test to pin.** The two above, plus `test_grade_depends_on_listing_facts_not_candidate_fields`:
mutate an `ActivityCandidate.category`/`indoor_outdoor` and assert the grade is unchanged;
mutate the corresponding `ListingFacts` row and assert it changes.

---

### E3. Bootstrap CIs use the wrong independence unit; effective n is 10 (core) / 4 (holdout), not 60 / 24 -- P1

**Evidence.**

- `ranking/runner.py:374-377`: cases = `personas x QUERY_TEMPLATES`; `:419-422` bootstraps over
  the per-case list (`metrics.py:92-117` resamples `values` i.i.d.). Six cases per persona share
  one trace, one preference store, one grade table; templates differ only in the intent.
- Recomputed with a persona-cluster bootstrap (`probe_ranking.py` section D):
  ```
  core   per-case (n=60): 0.7990 [0.7315,0.8602] width 0.129 | persona-cluster (n=10): [0.6385,0.9269] width 0.288
  holdout per-case (n=24): 0.7262 [0.6406,0.8129] width 0.172 | persona-cluster (n=4):  [0.5664,0.8860] width 0.320
  per-persona NDCG@3 (core): mdm-tan 0.254, mr-koh 0.592, mr-tan-wc 0.617 ... mdm-lee 1.0, mr-yusof 1.0
  ```
  The reported CI is ~2.2x too narrow on core and the random floor (0.6019 [0.5443, 0.6592])
  is _inside_ the cluster CI's lower half. "Full beats random" (`test_random_floor_is_strictly_below_full_on_ndcg_at_3`,
  test_ranking_evaluation.py:238-244) compares means; with 10 clusters it is not a significant
  difference on this evidence.
- `personalisation_divergence` bootstraps 156 _pairs_ drawn from 10 personas (`runner.py:299-336`,
  `:445-446`; artifact `n=156`). Pairs sharing a persona are dependent; the CI `[0.33, 0.46]` is
  not interpretable.
- Ablation `paired_delta` (metrics.py:136-146) pairs by case -- right idea, same clustering problem.
- Policy comparison: no CI at all (`metrics.Rate` is n/d only), which is honest, but the 59 core
  steps come from 15 scenarios of which **11 are mdm-lim** with one shared fixture history
  (`probe_policy.py` section C), and steps within a scenario are serially dependent. `docs/testing.md:78`
  mentions single-digit denominators but not this.

**Root cause.** The bootstrap was written for "one number per replayed case"; persona was not
modelled as the sampling unit.

**Severity.** P1: every CI in `ranking-evaluation.md` overstates precision.

**Substrate.** `bootstrap_stat` / `paired_delta` signatures; `CaseResult.persona.person_id`.

**Proposed design.** `metrics.cluster_bootstrap_stat(values: Sequence[float], clusters:
Sequence[Hashable], *, seed, resamples=2000) -> Stat` (resample clusters with replacement,
concatenate their values, take the mean; report `n_clusters` alongside `n`). Same for
`cluster_paired_delta`. Report both per-case and per-persona CIs side by side, with the
persona count in the header; drop `personalisation_divergence`'s CI or cluster it by the
_unordered persona pair_. For the policy comparison, add a `Rate.by_scenario` breakdown and a
"scenarios contributing to the numerator" count next to every `n/d` (e.g. "0/19 across 3
scenarios, 2 personas") -- a count, no CI.

**Files.** `ranking/metrics.py`, `ranking/runner.py`, `ranking/report.py`,
`evaluation/metrics.py` (`Rate` gains `clusters: int`), `evaluation/report.py`.

**Effort.** S.

**Test to pin.** `test_cluster_bootstrap_is_wider_than_case_bootstrap_when_clusters_disagree`
(synthetic: 2 clusters with means 0.2/0.9, 6 values each). `test_ci_headers_state_cluster_count`.

---

### E4. Holdout sets were re-checked, re-labelled and pinned after "freezing" -- P1

**Evidence.**

- Rule: `scenarios/holdout/README.md:8-12` ("No threshold ... was changed, tuned, or re-checked
  against these scenarios"; "Labels were assigned before the decisions were read").
- Git (topological order): holdout created `44f2197 2026-09-06 00:38:43`; `f85c6b4 2026-09-06 01:26:06
refine outreach learning policy` (policy.py) 48 minutes later; `9d90a7e 2026-09-09 added senior
confirmed baseline references` (analytics.py); `5938030 2026-09-12` edits `holdout/h05` (adds
  `expected_outcomes`); `4d3ddbd 2026-09-12` changes `h01` step-4 label `emerging_decline -> stable`
  (h01 file comment lines 5-10 say so).
- `test_evaluation.py:874-912` `test_consent_gate_is_evidenced_on_holdout_and_still_masked_on_core`:
  its docstring records that an analytics change (F21/F22) altered `sustained_low_days` on the
  holdout set and the assertion was _inverted_ to match. The holdout's ablation result is now a
  pinned regression expectation: any future analytics change will be checked against holdout by CI.
- Ranking: `HOLDOUT_PERSONAS` and `RANKING_WEIGHTS` were both introduced in the same 2026-09-12
  window (`4d3ddbd`, `e989d4a`); the claim "never consulted while any ranking factor, weight or
  this dataset's own design was built" (`ranking/report.py:242-243`) has no independent evidence
  either way. Structural problem: holdout shares the catalogue and all six templates with core
  (`runner.py:374-377`); only the persona varies, and one of four holdout personas
  (`eval-mdm-suriati`, dataset.py:1285-1294) has a taste that can never fire (`'Choir'` vs
  catalogue `'Community Choir'`, probe section B), so 6/24 holdout cases carry zero taste signal
  by design. (The persona note says this is deliberate; it still means the holdout is 3
  informative personas.)
- Doc/code mismatches on the same page: `docs/testing.md:137` "core 13" (there are 15,
  `policy-comparison.md:5`); `docs/testing.md:143` "M1 0/11 core -> 2/11 holdout; M6 0/11 -> 1/6"
  (artifact: 0/17 -> 3/12; 0/16 -> 2/6, `policy-comparison.md:30-32,79-82`); `docs/testing.md:214-218`
  "Seven arms" (there are 8, `ranking/ablations.py:41-50`).

**Root cause.** "Holdout" is a directory, not a process: nothing prevents labels/expected values
being edited, and tests were written that assert holdout-specific numbers.

**Severity.** P1.

**Substrate.** `_scenario_digest` (runner.py:127-132) already hashes holdout bytes;
`holdout_digest` is printed in the artifact.

**Proposed design.**

- `scenarios/holdout/FROZEN_DIGEST` committed once; `run_evaluation` prints
  `holdout_frozen: true/false` by comparing; a change requires a new directory
  `scenarios/holdout-v2/` and a dated README entry. Never edit `holdout/*.yaml` again.
- Move holdout-specific assertions out of `test_evaluation.py` into a `--check`-style artifact
  comparison only (the artifact already pins them); tests should assert _properties_
  ("no ablation increases violations on any set"), not holdout numbers.
- Ranking: add `HOLDOUT_TEMPLATES` (2-3 intents never used on core, e.g. "afternoon, sheltered,
  any company", "Mandarin + near") and evaluate holdout personas on holdout templates; report
  core-persona x holdout-template as a third cell so template generalisation is separable from
  persona generalisation.
- Fix the three doc mismatches.

**Files.** `evaluation/runner.py`, `scenarios/holdout/README.md`, `tests/test_evaluation.py`,
`ranking/dataset.py`, `ranking/runner.py`, `docs/testing.md`.

**Effort.** S (freeze + docs) / M (holdout templates).

**Test to pin.** `test_holdout_digest_matches_frozen_file`.

---

### E5. Ablation confounds beyond `no_intent`: `no_engagement` also removes `repetition` and history explanations; `no_intent_soft` is measured against the wrong baseline -- P1

**Evidence.**

- `ranking/ablations.py:200-203` `no_engagement` passes `engagement={}`. In production
  `_repetition(engagement=None, today)` returns `0.0` (`activity_search.py:647-649`), and
  `_history_reason(None)` returns `None` (`:662-667`). Measured (`probe_ranking.py` section E):
  ```
  core:    no_engagement: candidates whose REPETITION factor also changed=17; lost a HISTORY reason line=33
  holdout: no_engagement: ... REPETITION changed=8; HISTORY lines lost=20
  ```
  So `no_engagement` = engagement + repetition + explanation ablated together; its NDCG delta
  (core -0.0279 [-0.0514, -0.0089]) is not attributable to the engagement factor.
  `test_each_ablation_changes_exactly_one_keyword_argument` (test_ranking_evaluation.py:262-320)
  passes because it counts _keyword arguments_, not factors.
- `no_intent_soft` (`ablations.py:172-189`) passes `diversity=False`; the report compares it to
  `full` (`runner.py:436-443`). Its delta therefore contains `no_diversity`'s delta:
  core `+0.0120` includes `+0.0045`; holdout `+0.0517` includes `+0.0112` (section E). ADR 0003
  hands the holdout number to the blocked intent ticket (`docs/adr/0003:190-198`) without this
  correction.
- `no_repetition` prints "does not exercise" on NDCG (artifact) although 17 core / 8 holdout kept
  candidates are inside a cooldown (section E). It is _masked_: with `last_not_for_me=None` the
  same decline moves to the durable `not_for_me` count (`activity_search.py:629-633`,
  `-0.5 x 1.5`), and the label already grades those candidates 0 via the same cooldown
  (E2). The report's wording ("does not exercise the factor") is misleading here -- the factor is
  exercised and neutralised by another factor.
- `no_preferences` does **not** remove engagement (checked: `ablations.py:190-199` keeps
  `engagement=engagement`). It does remove PREFERENCE reason lines; harmless for NDCG.
- `no_context` does **not** change filtering (`filter_candidates` never reads rain,
  `activity_search.py:280-316`). Confirmed clean apart from the E7 tautology.

**Root cause.** Ablations are done by input substitution where the input feeds more than one
factor; the structural test checks argument identity rather than `ScoreBreakdown` factor identity.

**Severity.** P1.

**Substrate.** `ScoreBreakdown.factors` (models.py:811-830); `_with_intent_contribution_zeroed`
(ablations.py:67-78) is already the right shape.

**Proposed design.** Replace input-substitution arms with **contribution-zeroing arms** for every
factor: `zero_factor(ranked_with_diversity_off, name)` = `_with_intent_contribution_zeroed`
generalised (`factor.name == name -> contribution 0`, recompute `total`, re-sort by the same key,
re-run `_dedupe_series` and `_diversify` -- expose both as public `activity_search.postprocess(ranked,
diversity: bool)` so the harness does not re-implement them). Keep `no_intent` and `no_engagement`
as "input arms" but label them `input:no_intent` / `input:no_engagement` with the list of factors
they touch. Compare every `diversity=False` arm against `no_diversity`, never against `full`.
Strengthen the structural test: for each arm, assert exactly one `ScoreFactor.name` has changed
`contribution` across all candidates (`test_each_factor_arm_changes_exactly_one_factor_contribution`).
Print "masked by <factor>" instead of "does not exercise" when the ablated factor's _value_ differs
on some candidate but the order does not change.

**Files.** `ranking/ablations.py`, `activity_search.py` (public `postprocess`), `ranking/runner.py`,
`ranking/report.py`, `tests/test_ranking_evaluation.py`, `docs/adr/0003` (correct the
`no_intent_soft` number's baseline).

**Effort.** M.

**Test to pin.** The factor-contribution structural test above; and
`test_soft_arms_are_reported_against_no_diversity`.

---

### E6. Tautological or saturated metrics in the ranking artifact (beyond `context_rule_conformance`) -- P1

**Evidence.**

- `constraint_satisfaction_at_3`: literally `1.0 if top else 0.0` (`runner.py:193`). Not computed
  from anything. Docs say "by construction" (report.py:45-49) -- fine, but it occupies a headline
  row and a per-ablation row ("does not exercise") in every table.
- `reasons_grounded_rate` = 1443/1443 and 525/525. `_reason_grounded` (`runner.py:253-277`):
  `CONTEXT -> case.template.rain_forecast`, and every template has `rain_forecast=True`
  (dataset.py:1365-1385). 433 core / 175 holdout CONTEXT lines are "grounded" without checking
  that the candidate is under cover (section E). `PREFERENCE -> dimension_score != 0` is true
  whenever _any_ dimension matches, not the one the line cites. `VARIETY` reads the flag the
  ranker set. `HISTORY` re-implements `_history_reason` exactly. The metric cannot fail for the
  production ranker; `test_reasons_grounded_rate_is_high_on_the_real_run` (> 0.9) pins a
  tautology.
- `series_duplication_rate_at_3` = 0.0000 by construction: `_dedupe_series` always runs
  (`activity_search.py:928`). The only arm where it moves (`no_intent_soft` +0.44) is the arm
  whose docstring says the number is an artefact (`ablations.py:95-102`).
- `unknown_admitted_at_3` = 0 on full; moves only under `no_intent`, where it is a side effect of
  the confound (unknown-distance candidates sort last on `_UNKNOWN_DISTANCE_SORT`).
- `P@3 (rel>=2)` treats grade-2 _neutral_ as relevant (`metrics.py:17`). Pool composition:
  core kept grades `{0:157, 1:248, 2:982, 3:435}` -> 77.8% of the pool is >=2, and random P@3 is
  0.788 (section C). P@3 measures pool composition, not ranking.
- `NDCG@3` ceiling is trivially reachable in 4 core cases whose whole pool is grade 2 (any order
  scores 1.0) and 9/60 core, 9/24 holdout cases have **no** grade-3 candidate at all (section C),
  so a third of holdout cases cannot distinguish a good ranker from a bad one at the top.
- `category_entropy_at_3` is reported without a target; it moves with `no_diversity` by
  construction (`_diversify` is defined as a category swap, `activity_search.py:837-879`).

**Root cause.** Metrics were chosen to enumerate ranker properties rather than to be falsifiable
against an independent truth; several re-derive the property from the same code path.

**Severity.** P1 (report hygiene; they crowd out the two metrics that do carry information).

**Substrate.** `_case_metrics`, `_METRIC_LABELS`.

**Proposed design.**

- Drop `constraint_satisfaction_at_3` and `series_duplication_rate_at_3` from the artifact; turn
  both into unit tests on `activity_search` (`test_top3_never_repeats_a_series`,
  `test_filter_precedes_rank`).
- Replace `reasons_grounded_rate` with `explanation_faithfulness`: for each shown reason line,
  check the _specific_ claim against `ListingFacts` (E2): a CONTEXT line requires
  `facts.covered is True`; a PREFERENCE line citing dimension D requires the persona `Want` on D;
  an INTENT line citing axis A requires the candidate to satisfy A (this part `_grounding.py`
  already does). Report `faithful / shown` per basis, and `claims_unverifiable` (lines citing a
  fact the listing does not carry) separately.
- Change `RELEVANT_THRESHOLD` to 3 for P@k/MRR and rename to `P@3 (taste match)`; keep NDCG graded.
- Report `discriminable_cases` per split (cases with >=1 grade-3 and >=1 grade<=1 in the pool)
  and compute headline NDCG over those only, with the count printed.

**Files.** `ranking/runner.py`, `ranking/metrics.py`, `ranking/report.py`, `tests/test_activity_search.py`,
`tests/test_ranking_evaluation.py`.

**Effort.** S.

**Test to pin.** `test_explanation_faithfulness_can_fail`: hand a candidate with `covered=False`
a CONTEXT line and assert the metric counts it unfaithful.

---

### E7. `context_rule_conformance@3` is the ranker's rule restated, and `no_context`'s NDCG "win" is partly the label's silence on weather -- P2 (confirmed, already documented; refinement)

**Evidence.** `ranking/context_labels.py:66-72` vs `activity_search.py:735-748`: identical premise
(rain and `environment == EITHER` -> outdoor worse, unknown neutral, explicit ask overrides).
`test_removing_context_improves_relevance_ndcg_but_breaks_context_rule_conformance`
(test_ranking_evaluation.py:207-224) pins `ci_high < 0`, i.e. pins the tautology as a regression
test. ADR 0003 states all of this correctly. What it does not state: every template runs with
rain (dataset.py:1365-1385), so the artifact never shows the ranker on a dry day, and the
`no_context` NDCG delta is _also_ the only measurement of "how much relevance the rain nudge
costs" -- which ADR 0003 (:31-34) says is a product decision nobody has quantified per case.

**Proposed design.** With `ListingFacts.covered` (E2) authored independently of
`indoor_outdoor`, define `context_fit_at_3 = mean(top3: covered is True or facts.effort == "seated")`
under rain, and `relevance_cost_of_context = NDCG@3(full) - NDCG@3(no_context)` reported per case
with the list of cases where the top-1 changed. Add dry-day twins of every template
(`rain_forecast=False`) so `no_context` is a no-op there and the metric's masked/unmasked split is
visible. Retire `context_rule_conformance@3` once `context_fit_at_3` exists; until then keep the
label as is.

**Files.** `ranking/context_labels.py`, `ranking/dataset.py`, `ranking/runner.py`. **Effort.** S
after E2. **Test.** `test_context_fit_disagrees_with_indoor_outdoor_for_a_covered_outdoor_listing`.

---

### E8. NDCG@3 with an oracle of three same-category taste matches structurally penalises the product's diversity rule -- P2

**Evidence.** 9/14 personas' only grade-3 route is a CATEGORY taste (dataset.py:1092,1145,1175,
1192,1207,1219,1253,1268,1302); each category has 5 listings, so the ideal top-3 is three sessions
of one kind. `_diversify` swaps a different-category candidate into slot 3 when the top three
share a category (`activity_search.py:850-878`). Measured: every variety-promoted case lowers
NDCG@3 vs `no_diversity` (core 2/2, holdout 2/3, section E); `no_diversity` shows as a
"win" (+0.0045, +0.0112) in the artifact. The benchmark's optimum is the product's anti-pattern.
Also, the product shows `SHOWN_LIMIT = 10` (runner.py:62) but every ranking metric is @3.

**Proposed design.** Report a metric family, not one number: `NDCG@1` (is the best thing first),
`HitRate@3(rel=3)` (is _a_ taste match in the slate), `MRR(rel=3)`, `P@3(rel=3)`, and a slate
metric `slate_ndcg@3` where the ideal is computed under the same one-per-category constraint the
product imposes (ideal = best-per-category order). Report `@10` for the shown list as
`HitRate@10` only. Put `NDCG@1` and `HitRate@3` in the headline; keep graded NDCG@3 in the
technical table.

**Files.** `ranking/metrics.py` (`hit_rate_at_k`, `slate_ndcg_at_k(relevances, categories, k)`),
`ranking/runner.py`, `ranking/report.py`. **Effort.** S. **Test.**
`test_slate_ndcg_does_not_penalise_a_category_swap_within_margin`.

---

### E9. Floors are computed fairly, with two caveats -- P3

**Evidence.** Random (`runner.py:215-230`) shuffles `case.kept` (post-filter), seeded per case,
20 draws averaged then bootstrapped across cases -- fair, though the CI is of the 20-draw mean
(within-case variance is averaged out, so the random CI is narrower than one random ordering
would be). Catalogue order (`:233-240`) is `_ROWS` order, whose first row per category is
consistently the near, available, English, morning session -- a mildly favourable "default", so
the 0.611 floor is an honest _strong_ baseline, not a weak one. Neither floor runs
`_dedupe_series`/`_diversify`, which only disadvantages the floors on series-duplication (not
reported for them). Oracle (`:243-250`) is correct. Verdict: fair; add a third floor,
`intent_filter+static` (filter, then sort by distance then title with no learned/context
factors), which is the honest "what a rule-based catalogue app would do" arm and is missing.

---

### E10. The LLM re-ranker is never evaluated, offline or otherwise -- P1

**Evidence.** Ablation arms (`ranking/ablations.py:41-50`) are all deterministic. The bounded
re-rank loop is `agent/planner.py:330-380` (`rank_activities(context, *, settings, fallback_order,
client_factory=...)`) returning `ActivityPlanRun{mode, selected_order, iterations, guardrail_rejections,
fallback_reason, usage}`. Live ops counters exist (`models.py` `OperationalMetrics.planner_runs`,
`planner_agreed_with_ranker`, `planner_fallback_modes`, `planner_guardrail_rejections`) but only for
the _outreach_ planner in a running system. `test_agent_planner.py:84-86` already has a
`FakeClient(responses=[...])` scripted-response shape; the import-boundary test
(`test_ranking_evaluation.py:45-64`) forbids `silverloop.agent` in the ranking package, so this
arm cannot live inside `evaluation/ranking/` as written.

**What would be needed offline.**

- `evaluation/ranking/llm_arm.py` (a _sibling_ package allowed to import `agent`), with a
  `RecordedRankerClient` that replays JSON fixtures keyed by `sha256(case_id + prompt_digest)`;
  fixtures recorded once with `LLM_ENABLED=true` via `client_factory`, committed under
  `apps/api/tests/fixtures/llm_rerank/`, and a `--record` flag that refuses to run in CI.
- Arm `llm_rerank` uses `fallback_order = full arm order` and `context.options = kept`; metrics
  identical to E8; plus agent metrics: `planner_agreement@3` (Jaccard of top-3 vs deterministic),
  `fallback_rate` by `mode`, `guardrail_rejection_rate = rejections / proposals`,
  `narrowing_rate = 1 - len(selected)/len(options)`, and `latency_ms` from the recording (reported,
  not asserted).
- Determinism: the arm is skipped with an explicit "not recorded" row when fixtures are absent,
  never a silent 0.

**Files.** new `evaluation/ranking_llm/`, `agent/planner.py` (no change; `client_factory` is
already injectable), `tests/test_ranking_llm_arm.py`, `docs/testing.md`. **Effort.** M.
**Test.** `test_llm_arm_never_reorders_outside_allow_list` (already true via guardrails; pin on
the recorded fixture) and `test_llm_arm_reports_not_recorded_when_fixtures_missing`.

---

### E11. External validity: the benchmark catalogue's `category` is activity content; the product fixture's `category` is format -- P2

**Evidence.** Benchmark categories: "Tai Chi", "Gardening", "Karaoke", ... (dataset.py:129-969).
Production fixture categories (`fixtures.py`, `adapters/*`): `"Group class"` x8, `"Social group"`
x3, `"Self-guided"` x2, `"Drop-in, self-guided"` x1. `PreferenceDimension.CATEGORY` learns from
`candidate.category` (`preferences.py:193-198, 241-242`). The lead's known flaw ("category is
format, a walk decline penalises tai chi") is therefore _invisible_ to this benchmark: with
content-categories, `no_preferences` costs -0.117 NDCG and CATEGORY looks like the most valuable
learned dimension; in the product catalogue the same learner would generalise a "not for me" on
one group class to every group class. The benchmark cannot detect the flaw the product has.

**Proposed design.** Author the `ListingFacts.activity_kind` (E2) _and_ set half the benchmark
listings' `category` to format strings mirroring the product's taxonomy; add persona traces whose
decline is on one format-category listing and whose brief `Want` is about `activity_kind`; the
expected result (a regression this benchmark should _show_) is a grade-1/0 collision on unrelated
listings. Report `category_overreach_rate = share of top-3 candidates demoted by a CATEGORY
preference whose `activity_kind` differs from the declined listing's`.

**Files.** `ranking/dataset.py`, `ranking/listing_facts.py`. **Effort.** S. **Test.**
`test_format_category_decline_does_not_demote_a_different_activity_kind` (expected to fail today
-- that is the point; mark `xfail(strict=True)` with the lead's ticket).

---

### E12. No learning, burden, follow-through, world-model or agent metrics exist in either artifact -- P2 (design requested)

**Evidence.** `NOT_MEASURED` (`evaluation/report.py:79`; artifact "Not measured, and why") lists
intervention-adaptation, latency, tool-failure recovery, message quality. `docs/testing.md:333-336`:
follow-through is not represented in the harness. The ranking benchmark folds `apply_decline`/
`apply_enjoyment` once (traces.py:37-75) but never asks whether a decline moved the _right_
listing in the _right direction_. The accepted-outreach cooldown is dead in the harness by design
(`ladder.py:24-37`; `policy.py:17` `ACCEPTED_OUTREACH_COOLDOWN_DAYS = 3`). `WorldModelQuality`
(models.py:1333-1346) counts exist only on the live `/world-model` endpoint. Below are concrete
designs, each naming the substrate it builds on.

**12a. Learning metrics** (`evaluation/ranking/learning_probes.py`, pure functions over
`preferences.apply_decline`/`apply_enjoyment`/`dimension_score` and `activity_search.rank_candidates_with_breakdown`):

- `decline_direction_correct`: for each `(persona, listing, DeclineReason)` in an authored probe
  table, rank before and after `apply_decline`; assert the declined listing's rank does not
  improve and record `moved_listings = {id: delta_rank}`. Metric: `share of moved listings whose
ListingFacts share the declined attribute` (should be high) and `collateral = share whose
facts do not` (the lead's "walk decline penalises tai chi"). Denominator: moved listings.
- `distance_monotonicity`: probe with `TOO_FAR` on a listing at d0; after learning, the
  `preference` factor value as a function of candidate distance must be non-increasing in
  `distance_m` (today it is a step at 2,000 m, `preferences.py:102,131-134`, so a 1.2 km decline
  learns "dislikes near" -- the lead's flaw). Metric: count of adjacent-distance inversions over
  a sorted synthetic ladder of 10 distances; target 0.
- `intensity_direction`: `TOO_TIRING` on MODERATE must not raise LIGHT's score below its pre-decline
  value; report the signed delta.
- `three_matches_beat_one`: a candidate matching 3 stated tastes must score `preference` >= one
  matching 1 (today `_weighted_dimension_score` averages, preferences.py:485-500; expected fail).
- `statement_outranks_inference`: after `apply_decline` x5 on dimension D then a
  `senior_statement` the other way, the statement must dominate (`_SOURCE_WEIGHT`, precedence
  rule) -- pin the invariant "current explicit intent outranks historical inference".
- Outreach learner (`learning.PreferenceLearner`): `directional_update`: for each
  `(outcome, follow_through, enjoyment)` combination, `expected_value` after must be >= before
  iff the combination is in an authored "positive" set; table of 3 x 4 x 3 = 36 cells, report
  the number of cells that disagree with the authored sign.
  Pins the lead's "environment/intensity can't be learned as likes": `LIKED_ASPECT_DIMENSIONS`
  (preferences.py:326-331) has no ENVIRONMENT/INTENSITY key; the probe table will show 0 movement
  and the report should say "unlearnable dimension", not "no effect".
- **Information contribution per dimension**: for each `PreferenceDimension`, an arm
  `no_preference_dim:<D>` that drops only that dimension's rows from `ActivityPreferences`;
  report paired NDCG@1/HitRate@3 delta per dimension (clustered by persona). Builds on E5's
  factor-zeroing helper.

**12b. Burden / anti-nagging metrics** (policy harness, `evaluation/metrics.py`):

- `contacts_per_person_week` (already derivable: `contact_volume` / person-weeks; add the
  denominator), `max_consecutive_contact_days`, `contacts_after_accept_within_3d` (needs the
  fold to model an accept: add an authored `accepts_on_step:` list to scenarios so
  `days_since_last_accepted` is populated and the dead gate becomes exercisable),
  `escalations_per_case` (case churn -- scenario 14 already documents the duplicate-case defect),
  `questions_asked` and `questions_answered_that_changed_a_decision` (drive
  `context_question.question_for(state, asked_recently=)` inside the replay and re-run the
  ladder with `memory_from_answer` applied; a question is "decision-changing" if any later
  `Decision` differs). Denominators: person-days for rates; print `n/d`.

**12c. Follow-through funnel** (new `evaluation/funnel.py` over `OperationalMetrics`-shaped
counts; offline via an authored `outcomes:` block per scenario, mirroring the existing optional
`expected_outcomes:`):
`offered -> responded(accepted/declined/deferred/no_response) -> followed(completed/partial/not_this_time/unable)
-> enjoyed(enjoyed/okay/not_for_me)`. Report each stage as `n/d` of the previous stage, per
candidate key and pooled, and `silence_rate = no_response / offered`. The `FollowThrough` and
`Enjoyment` enums (models.py:92-105, 954) and `learning._FOLLOW_THROUGH_WEIGHTS` are the substrate;
`sql_repository.record_follow_through` (:3258) / `record_enjoyment` (:4677) are the live writers.

**12d. World-model metrics** (offline, from a replayed run's `PersonWorldModel`, models.py:1349):
counts `explicit / inferred / confirmed / temporary(expires_at set) / stale / expired_excluded /
contradicted (len(contradicts)>0)` are already in `WorldModelQuality`. Missing and needed:
`corrected` (a fact whose `value` changed under the same `key` after a `senior_statement`) and
`rejected` (a `senior_statement` that reversed an inferred fact -- `PreferenceStance` flips,
sql_repository `_confirm_dimension_preference`). Add `avg_evidence_count` (sum
`PersonFact.evidence_count` / facts) and the three-way split the lead asked for:
`facts_consulted` (dimensions read by `dimension_score` for the case), `facts_that_changed_top_k`
(per-fact leave-one-out on the ranked list, top-3 set difference non-empty),
`facts_explanation_only` (fact appears in a shown reason but its removal does not change top-3).
Leave-one-out is cheap: one `rank_candidates_with_breakdown` call per fact per case.

**12e. Agent metrics** -- see E10; offline via recorded fixtures.

**Effort.** 12a S-M, 12b M (scenario schema grows), 12c M, 12d S (leave-one-out only), 12e M.

**Tests to pin.** One property test per probe, all `xfail(strict=True)` where the lead's known
flaws predict failure today (distance step, intensity, averaged matches), so the benchmark
_documents_ the flaws instead of hiding them.

---

### E13. Metamorphic tests exist for the policy ladder but not for the ranker -- P2

**Evidence.** `test_evaluation.py:728-822` has four metamorphic properties (display name/language
invariance; rain moves strictly less intrusive; rain does not excuse persistence; revoking consent
never increases intrusion). `grep -rn metamorphic apps/api/tests` finds none for `activity_search`.

**Proposed design** (`tests/test_ranking_metamorphic.py`, over `CATALOGUE` and `CORE_PERSONAS`):

- Invariance: permute `candidates` input order; rename `provider`/`title` consistently (keeping
  series keys); change `location.name`; shift every `start_at` by +7 days together with
  `FROZEN_TODAY`; change `display_name`/`preferred_language` when no language constraint. Assert
  identical `activity_id` order.
- Direction: adding a `senior_statement` AVOID on a candidate's category never raises that
  candidate; increasing `distance_m` of one candidate never raises it; a `not_for_me` today
  never raises it; adding rain never raises an OUTDOOR candidate when `environment == EITHER`
  and never changes anything when environment is explicit; a fuller intent match never ranks
  below a lesser one (the `_tier` invariant) regardless of preferences.
- Each property runs across all 60 core cases; failures list the case.

**Effort.** S. These also serve as the "irrelevant attribute changes don't change ranking" tests
the lead asked for.

---

## Denominator and small-n honesty (cross-cutting)

- Policy comparison: every rate is `n/d` (metrics.py:120-133); good. Missing: the number of
  distinct scenarios/personas behind each numerator (E3). Holdout `M2/M3/M8` are `n=1`; the
  Mr Tan/Mdm Devi/Mdm Siti per-persona tables are 3-5 steps each and print `0/0 (n/a)` correctly.
- Ranking: `Stat.n` is cases, never personas (E3). `reasons_grounded_rate` pooled `1443/1443` is
  an honest denominator on a tautological numerator (E6).
- The sweep (`evaluation/sweep.py`) is uncapped and per-person -- the best-designed table in
  either artifact; keep it.

## Confirmations of the lead's known flaws that this audit's evidence supports

- Distance categorical near/far at 2,000 m: `preferences.py:102,131-134`; the benchmark's
  `_dimensions.py:32,46` copies it, so the benchmark _cannot_ observe the "1.2 km learns dislikes
  near" defect (its own persona `eval-mdm-siti` declines `aqua-2` at 3,900 m, which is "far",
  and states taste "near": the flaw is dodged by authoring).
- Preference matches averaged: `preferences.py:485-500`.
- Environment/intensity unlearnable as likes: `LIKED_ASPECT_DIMENSIONS` (preferences.py:326-331).
- Category = format in production: E11.
- Double counting of distance: intent (`_intent_reasons` distance line, activity_search.py:393-406),
  preference (DISTANCE dimension), friction (`_friction`, :596-603) -- three factors read
  `distance_m`; the benchmark's `no_preferences`/`no_intent_soft` arms cannot separate them; E12a's
  per-dimension arm plus a `no_friction` factor-zeroing arm (E5) would.

---

## What NOT to build

1. **Do not add weather to the relevance labels** (ADR 0003 option B) -- it re-couples the two
   questions; E7's `ListingFacts.covered` is the independent route.
2. **Do not implement the "labels structurally independent" ticket by renaming metrics** or by
   another same-premise conformance rule -- E2's listing-facts vocabulary is the only design here
   that actually removes the coupling; anything short of a second vocabulary is the ADR 0003
   mistake again.
3. **Do not add CIs to the policy comparison.** With 5 persona fixtures and 15 serially dependent
   scenarios, a bootstrap would be theatre; counts of contributing scenarios/personas (E3) are the
   honest addition.
4. **Do not tune `RANKING_WEIGHTS` against this benchmark** in its current form -- E2/E6 mean it
   rewards CATEGORY tastes and same-category slates; a weight sweep now would optimise against a
   label that is the feature.
5. **Do not build a live-LLM evaluation arm.** Recorded fixtures only (E10); a non-deterministic
   number in a `--check`ed artifact breaks the determinism discipline both harnesses rely on.
6. **Do not "fix" the holdout numbers** (h04's rain-never-clears labels, h01's step 4). They are
   the only places the label rule and the ladder disagree; that disagreement is the finding.
   Freeze the directory (E4) instead.
7. **Do not delete M4/M7/M9 or `context_rule_conformance`** -- they are already labelled as
   logging/conformance checks; deleting loses cheap regression coverage. Move them below the
   fold and out of the headline JSON keys the web reader plots.
8. **Do not extend the harness to model consent design** (parked for the PoC). The consent
   _gate_ is correctly reported as masked (`policy-comparison.md:200-208`); that is enough.
9. **Do not add `DEVICE_TASK` to `Decision`** for the harness's sake (`NOT_MEASURED` item 1) --
   contract change for an evaluation convenience.
