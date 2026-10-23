# Verification strategy

## Gates

`pnpm verify` runs formatting, linting, TypeScript/Python checks, unit/API tests, Playwright
browser/API tests, YAML safety scenarios and production builds. GitHub Actions installs pinned
Chromium and runs the same categories on pushes and pull requests. Since PR #62 the CI `verify` job runs
`pnpm test` with `NX_PARALLEL=1`, one test target at a time, because running the API suite at the same
time as the browser suite starved the e2e dev server on a hosted runner. The job timeout is 30 minutes,
and Playwright results are uploaded when the job fails or is cancelled.

A separate `postgres-integration` CI job starts a disposable PostgreSQL 17 service and runs
`pnpm test:postgres`. Local execution requires `SILVERLOOP_POSTGRES_TEST_URL`; the database name must
contain `test`, which prevents the test from targeting the normal Supabase `postgres` database.

`apps/api/tests/test_query_counts.py` pins how many SQL statements each coordinator and person read
issues. Against the shared database each statement is a round trip to the pooler, so query count
drives latency. Every read must stay within its ceiling in `_CEILINGS`, measured on six people with 23
days of history, and must use one pooled connection. The counts also must not grow with the data. A
caseload-wide read (people, priorities, fleet metrics, queue) must issue as many queries for two people
as for six. A person read (case, metrics, state, world model and others) must issue as many for 7 days
of history as for 23. A new per-person or per-intervention query therefore fails a test. Raising a
ceiling needs review. The file also checks that `GET /v1/coordinator/metrics` equals the sum of each
rostered person's `GET /v1/metrics`, and that `GET /v1/coordinator/priorities?person_id=` returns that
person's row from the full board. Everything runs on in-memory SQLite, so the tests count round trips
but do not time them.

Engine and pool options for a server database (`_engine_options`) are covered in
`apps/api/tests/test_engine_options.py`. That test builds the engine without connecting to a
database.

## Three-policy evaluation harness

`pnpm evaluate` replays every scenario in `scenarios/` (and, separately, `scenarios/holdout/`)
exactly once and folds three policies over the identical, decision-independent environment stream: `fixed_threshold` and `contextual_rule`
(playbook §10 baselines, evaluated on a "blind" view that structurally denies them Care+'s
personal median/MAD baseline) and `silverloop` (the real, unmodified `policy.decide`, seeing the
real signal). It prints a Markdown comparison table to stdout and writes
[`docs/evaluation/policy-comparison.md`](evaluation/policy-comparison.md) and
`policy-comparison.json`, which are committed and staleness-checked by `pnpm evaluate:check`
(part of `pnpm verify` and CI), the same pattern `scripts/check-contract.sh` uses for the OpenAPI
contract. The harness imports no database module, opens no network connection and completes in
well under a second.

Ground truth for the comparison's metrics is an additive `labels:` list in each scenario YAML,
describing world state (`stable`, `explained_dip`, `emerging_decline`, `persistent_decline`,
`unusable_data`, `no_consent`) -- never a policy's own decision. Scoring `silverloop` against its
own `expected_decisions` would be circular; `expected_decisions` is used only by
`test_evaluation_parity.py`, which proves the harness reproduces Care+'s already-trusted
behaviour exactly, and never feeds the metrics themselves.

### Two label columns, and why one was not enough

The `labels:` entries are hand-authored, but a test used to assert that each one equalled a rule
built from `analytics.py` and `quality.py` -- the same `quality.safe_to_interpret`, the same
`sustained_low_days >= 3`, the same -20% boundary the ladder itself reads. Functionally that
pinned the entire label set, holdout included, to the production signal pipeline: the ground truth
was the feature restated, and `silverloop`'s `0/19` on M2 and M3 was a narrower claim than it
looked, because every `persistent_decline` step is by construction a step where the escalation
predicate already holds.

Each scenario now also carries an additive `world:` block (`evaluation/world.py`): one
`LatentState(true_activity_level, cause, days_low, observable)` per event, saying what the author
scripted the person's day to actually be. `simulation.replay` advances that world FIRST and
observes it second; `label_from_latent` (`evaluation/latent_labels.py`) labels from it alone, with
cut points -- above 0.80 of the person's own norm is not low, three consecutive low days is
persistent -- that are definitions of the fiction and are tuned to nothing. `fold_policy` never
reads `latent`; ground truth must not reach a policy, and that is pinned both by source inspection
and by replacing every latent with its opposite and asserting every decision is unchanged.

The report prints `label_feature_agreement`, the share of steps where the two accounts agree
(78/81 today). **It is a diagnostic with a target below 100%, not a score to maximise**: at 1.000
the second label source has collapsed onto the first and the tautology has been rebuilt with extra
steps. The three disagreeing steps are listed in the artifact rather than reconciled away, and the
old equality assertion is now a reported rate -- an honest disagreement between two independent
label sources must not be a CI failure. What has NOT changed: every authored label is
byte-identical, and a test hashes them to prove it.

The report measures unnecessary-contact (M1), missed-persistent-change (M2), missed-escalation
(M3) and unwarranted-share-of-contacts-made (M6) rates against ground truth, plus a
hard-policy-violation count (M5) that gates the CLI's exit code (non-zero) only when `silverloop`
itself has violations -- currently zero, in every arm of both scenario sets. Baseline violations
are reported, not gated: demonstrating that a naive threshold policy can act without consent, on
unsafe data or without explaining itself is the entire point of the comparison. See the "Not
measured, and why" section of the generated report for what this harness deliberately excludes
(device-failure discrimination, intervention-adaptation rate, latency, tool-failure recovery,
message wording) and why. The harness never calls the LLM planner, in any arm.

`audited_no_action` (M4) was renamed to **`no_action_logging_integrity`**
(`docs/adr/0002-replace-audited-no-action.md`). It checks that a quiet decision (`NO_ACTION` or
`SUPPRESS`) carries a rationale and a quality evidence id -- a property of the logging pipeline,
not of whether the silence was warranted. Care+'s own ladder writes both fields on every
branch, so it reads 100% for `silverloop` in every arm regardless of whether any individual
decision was correct; it is retained under its honest name as a logging smoke test, not deleted,
because it still catches a policy branch that silently forgot to explain itself. The ground-truth
replacements are:

- **M7 correct restraint** -- `NO_ACTION` / steps labelled `stable` or `explained_dip` (the same
  denominator M1 uses). `SUPPRESS` does not count in the numerator: it means consent or the
  contact budget blocked a wanted contact, not that the policy judged the situation correctly.
  **Identity, not independent evidence, when `SUPPRESS` is absent from that denominator**: every
  step there is `ACTION`, `NO_ACTION` or `SUPPRESS`, so `M7 = 1 - M1 - suppress_share`. On every
  arm this harness has replayed, no policy `SUPPRESS`es a `stable`/`explained_dip` step, so M7 is
  exactly `1 - M1` and restates M1's complement rather than measuring something new -- see
  `docs/adr/0002-replace-audited-no-action.md` for the numbers this was checked against.
- **M8 unsupported restraint** -- `NO_ACTION` / steps labelled `persistent_decline` (the same
  denominator M2/M3 use). This isolates the specific failure of presenting reasoned inaction on a
  step that needed help, distinct from a budget/consent-withheld `SUPPRESS` (already counted by
  M2) or a correct `COORDINATOR_REVIEW` escalation. M8 is the metric in this family that actually
  discriminates on this replay -- shown beside M2 in the report specifically so a reader can see
  the two diverge whenever a policy `SUPPRESS`es on a `persistent_decline` step.
- **M9 restraint explanation coverage** -- evidence-backed `NO_ACTION` / all `NO_ACTION` (SUPPRESS
  excluded, since its rationale explains a block, not a judgement of restraint). **A second
  logging-integrity check, not a correctness measure**: M9 is M4's predicate re-scoped to
  `NO_ACTION`, so Care+ reads 100% on it for the same construction reason M4 does, and the
  baselines' scores reflect which of their hardcoded `NO_ACTION` branches happen to include
  prose (`evaluation/baselines.py`), not a difference in restraint quality.
- **M10 context-dependent restraint** (ablation-only) -- of Care+'s `NO_ACTION` decisions
  (all gates on), how many become outreach once the rain-context gate alone is switched off
  (`silverloop_no_rain_context`). Unlike M7/M8 this does not read the ground-truth label; it
  reads two ablation arms already computed for the gate table.

Every rate is always printed as `n/d (rate) across S scenarios, P personas`, never a bare
percentage, so a small denominator (several personas and scenarios have single-digit
`persistent_decline` or holdout `NO_ACTION` counts) is visible rather than hidden behind a headline
number. The two coverage counts exist **instead of** a confidence interval, not as a step towards
one: the steps inside a scenario are serially dependent by construction (day 3 of a decline exists
only because days 1 and 2 did) and the scenarios are hand-written from five personas, so a
bootstrap over them would manufacture a sampling distribution this harness does not have.
`test_policy_comparison_carries_no_confidence_interval` walks the whole JSON artifact and fails if
any rate ever grows one.

### Burden, and the follow-through funnel

Three burden numbers sit beside the correctness table, because two policies can reach identical
M1/M2 and still cost the person and the coordinator very different amounts:
`contacts_per_person_week` (one replayed step is one simulated day, so the denominator is real),
`max_consecutive_contact_days` (longest unbroken run of contacted days inside one scenario, never
across a boundary), and `escalations_per_case` -- escalation decisions per escalation episode,
where an episode is a maximal run of escalations on consecutive days. The last one is above 1.0 for
`silverloop` and that is the point: `14_baseline_drift` is eighteen declining days, which is one
concern the product refreshes rather than duplicates, and the ladder still emits a
`coordinator_review` on each of them. No metric M1-M10 can see that.

The follow-through funnel (`evaluation/funnel.py`) runs over an optional authored `outcomes:`
block, one entry per event, saying what the person does IF contacted that day -- a counterfactual
fact about them, like the latent world, never a record of what a policy did.
`offered -> responded -> accepted -> followed -> attended -> enjoyed`, each stage `n/d` of the one
before. It exists because `accepted` means "show me more" and nothing else: without the funnel a
policy producing twenty taps and no attendance scored identically to one producing two
attendances. Two core scenarios author a block today, the denominators are small, and the report
says so rather than printing a confident rate over five offers.

### Budget-matched arms

The comparison used to be unfair in Care+'s favour and is no longer. `silverloop` caps itself
at two contacts a week; neither baseline caps itself at all. Comparing "Care+ makes 11
contacts, the baselines 19 and 15" therefore compared a budgeted policy against unbudgeted ones and
scored the difference as judgement -- and the metrics layer then counted `contact_cap_breach`
against `contextual_rule`, whose docstring says it deliberately has no cap. That is grading a
policy on an exam it was built to fail.

Every scenario set is now folded twice over the identical replayed environment:

- **`capped`** (headline) -- the harness itself applies the same weekly cap to every policy,
  converting a would-be contact into `suppress` once the budget is spent. `contact_cap_breach` is
  structurally zero for everyone here, so the remaining violations mean something. The budget is
  a _rolling_ week -- two contacts in any seven consecutive scenario days
  (`evaluation/fold.py::CONTACT_CAP_WINDOW_DAYS`), the same clock `sql_repository.py` keeps for
  Care+'s own cap. It used to be a cumulative count for the whole scenario, which was
  indistinguishable on scenarios shorter than a week and silently held the baselines to a
  stricter rule than Care+ over the 18-day `14_baseline_drift`: with a true weekly budget
  the baselines' core M2 (missed persistent change) improves from 17/19 to 13/19
  (`fixed_threshold`) and 15/19 (`contextual_rule`); Care+'s stays 0/19. The headline gap
  is smaller than the previous artifact showed, and truthful.
- **`uncapped`** -- each policy exactly as written, kept so the size of the budget effect is
  visible. Not the headline.

Budget-matching does not simply flatter the baselines. On the core set it improves their M1
(5/17 -> 2/17 for both) purely because the harness silenced them after two contacts in a week, and
in the same move makes their M2 **worse** (`fixed_threshold` 1/19 -> 13/19, `contextual_rule`
6/19 -> 15/19): an undiscriminating policy spends its weekly budget on quiet days and has nothing
left when a real decline arrives. `silverloop`'s two arms are identical (16 contacts, 0 withheld),
which `test_evaluation.py::test_harness_cap_is_a_no_op_for_silverloop` asserts rather than assumes.

### Gate ablation

`evaluation/ladder.py` is a transcription of the deterministic ladder with one boolean per gate,
so each gate can be switched off in turn. `policy.py` is never edited, imported-and-mutated or
monkeypatched -- that is an invariant. `test_full_ladder_is_identical_to_the_real_policy` folds the
transcription and `policy.decide` over every replayed step of both sets at every reachable contact
count and asserts full `PolicyResult` equality, so a drift between the two fails the suite instead
of silently producing a wrong ablation.

On the core set only `rain_context` and `contact_cap` change any headline metric; `consent` changes
one decision without moving a metric, and `data_quality`, `confidence` and `severity_persistence`
change nothing at all. On the holdout set `severity_persistence` becomes load-bearing
(M1 3/12 -> 4/12), which is a large part of why the holdout exists.

A null ablation result is reported as **masking**, not as uselessness: every step that would have
exercised the gate is independently blocked by another one. The clearest instance is the consent
gate, and it is a genuine gap in the evidence rather than a win -- across both sets there is still
no step where the consent gate alone decides the outcome, because `04_consent_revoked` also has
zero wear-time (the data-quality gate covers it) and `holdout/h03` reaches the post-revocation step
with the contact budget already spent (the cap covers it).

### Holdout set

`scenarios/holdout/` holds five scenarios added after the ladder was frozen, loaded by
`run_evaluation` as a **separate** scenario set with its own digest and never pooled with the core 15. `discover_scenarios` globs non-recursively, so the core run is unaffected by the directory's
existence; `python -m silverloop.scenarios` does not reach them either, which is why
`test_scenarios.py::test_holdout_scenario` runs them through the real `SqlAlchemyRepository`.
`scenarios/holdout/README.md` records the labelling rule and the rules the set is held to.

The set is **frozen**: `scenarios/holdout/FROZEN_DIGEST` holds the sha256 of those five files'
bytes, every run prints `holdout_frozen: true|false`, and
`test_holdout_freeze.py::test_holdout_digest_matches_frozen_file` fails when the two disagree. A
change is not forbidden, it is visible, and the answer to a genuine one is `scenarios/holdout-v2/`
with its own digest rather than an edit under the published numbers. Holdout-specific numbers are
for that reason **not** asserted in the unit suite -- they live in the artifact, which `--check`
re-verifies byte-for-byte; a unit test pinning a holdout number has to be edited whenever the
production signal pipeline moves, and an assertion edited whenever it fails is not evidence. The
ranking benchmark's holdout is four persona briefs in code rather than a directory, so it carries
the same discipline through `dataset.HOLDOUT_FROZEN_DIGEST`.

The result is honest rather than flattering: **`silverloop` scores worse on holdout than on core**
(M1 0/17 core -> 3/12 holdout; M6 0/16 -> 2/6). Two of the three M1 misses come from
`h04_rain_never_clears`, where the rain never stops and Care+'s rain gate expires after one
day, so it suggests a programme on day 2 and escalates on day 3 of a continuously rain-explained
dip. That labelling is a contestable product judgement and is flagged as such in the scenario file
and the artifact; it was not adjusted once the result was known. The third is
`h01_sync_gap_then_decline` step 4, a nudge on a day the anchored delta puts at -19.6% -- four
tenths of a point on the `stable` side of the -20% line. It is also the one step where the
authored latent world disagrees with the label and says a real dip had begun (see
`label_feature_agreement` in the artifact), which is exactly the kind of borderline the second
label column exists to surface.

### Threshold sensitivity

`fixed_threshold` acts at `steps < 3000` and Mr Ravi's seeded baseline is ~2,400 steps a day, so
"both baselines contact him 5/5, Care+ 0/5" is arithmetic before it is evidence. The harness
therefore sweeps the threshold across 2000-5000 and reports the whole curve, per person. No cut
point is both quiet for Mr Ravi and sensitive to real declines: at 2000/2500 he is left alone but
**3/3 persistent declines are missed**; at 3000 he takes 5 unwarranted contacts; at 3500+ every
decline is caught but M1 reaches 7/11 and he still takes 5.
`test_no_universal_threshold_is_simultaneously_quiet_and_sensitive` asserts that shape, so if a
threshold ever satisfied both the test fails and the claim has to be withdrawn.

### Metamorphic properties

Property tests, not case tests, in `test_evaluation.py`:

- Renaming every persona and changing every `preferred_language` must leave every decision and
  every rationale in every arm unchanged.
- Adding rain to a **single-day** dip must move the decision strictly towards less intrusion.
- Adding rain to a dip that has **already persisted two valid-wear days** must not change the
  decision at all -- the rain gate is not a blanket excuse.
- Revoking consent must never produce a more intrusive decision, at any step of either set, at any
  contact count.

### F5: five personas, and the honest 29-vs-90-day gap

Scenarios 08-11 (`mr-ravi`, `mr-tan`, `mdm-devi`, `mdm-siti`) join the original seven, which stay
on `mdm-lim` alone, taking the harness from 13 decision steps and one persona to 28 steps and
five. Each new persona is chosen to make a metric that was previously dead come alive: `mr-ravi`'s
low-but-stable baseline (playbook: "defeat the universal threshold") makes M1 (unnecessary
contact) non-zero for `fixed_threshold`/`contextual_rule` while `silverloop` stays at zero;
`mr-tan`'s repeated mild dips (synthetic -- not a playbook persona) make `contact_cap_breach` fire
for both uncapped baseline policies while `silverloop` suppresses its own third contact;
`mdm-devi`'s gradual decline (synthetic -- not a playbook persona, standing in for playbook
required scenario #4) gives M2/M3 a second `persistent_decline` data point instead of n=1;
`mdm-siti`'s low tracker adherence exercises `unsafe_data_action` for `fixed_threshold` (which,
unlike `contextual_rule` and `silverloop`, has no data-quality gate at all). `mr-tan` and
`mdm-devi` are explicitly labelled `is_playbook_persona=False` in
`silverloop.fixtures.DEMO_PERSONAS` and in the generated report -- they are inventions to exercise
a metric, not research- or interview-derived personas.

`mdm-lim`'s generated fixture is byte-identical to before F5 (pinned by hash in
`apps/api/tests/test_personas.py::test_mdm_lim_history_is_byte_identical_to_pre_f5`) and keeps her
28-day history + 1 current-day fixture. The playbook's definition of done asks for 60-90 days of
history for every persona; the four new personas get 90, but `mdm-lim` was deliberately left at 29. Regenerating her history to reach 90 days would shift every scenario's `expected_decisions`,
the e2e assertions and the committed evaluation artifact that are pinned to her existing fixture,
which is a materially riskier change than F5's actual goal (widening the evaluation sample). This
gap is accepted, not hidden: `mdm-lim` alone remains short of the 60-90-day target.

## Ranking evaluation

`pnpm evaluate` also runs `python -m silverloop.evaluation.ranking`, a second, independent
benchmark of `silverloop.activity_search` -- the user-initiated search/rank/diversify pipeline,
which the three-policy harness above never exercises (that harness scores the proactive-outreach
ladder only). It lives in `apps/api/src/silverloop/evaluation/ranking/`, imports no database
module, no FastAPI app and no LLM client (asserted the same way `test_evaluation.py`'s own
boundary test is), and completes in about two seconds. `pnpm evaluate:check` (part of `pnpm
verify` and CI) fails if [`docs/evaluation/ranking-evaluation.md`](evaluation/ranking-evaluation.md)
and `ranking-evaluation.json` are stale.

**What it measures.** A frozen, synthetic catalogue of 60 listings and 14 personas (10 core / 4
holdout, `evaluation/ranking/dataset.py`) run through 6 query templates -- an unconstrained ask, a
day/time/environment/intensity-constrained one, a social-plus-distance one, a language-constrained
one, a tight-distance one and an evening-solo one. Each (persona, template) pair is one "case", so
the core set is 60 cases from 10 personas and the holdout 24 from 4.

The headline family is `NDCG@1` (is the best thing first), `HitRate@3 (rel=3)` (is a taste match
anywhere in the slate) and `slate_ndcg@3`, whose ideal is computed under the product's own
one-per-category rule so a within-margin variety swap is not scored as a loss; graded `NDCG@3`,
`P@3 (taste match)`, `MRR (rel=3)`, `context_rule_conformance@3`, `unknown_admitted@3`,
`category_entropy@3`, `personalisation_divergence` and `reasons_grounded_rate` sit in the technical
table beneath it. `P@k`/`MRR` count a grade-3 taste match as relevant, not the neutral grade 2:
77.8% of the core kept pool grades >=2, so the old `P@3 (rel>=2)` was measuring pool composition.
Two former rows are gone, because neither could fail -- `constraint_satisfaction@3` was
`1.0 if top else 0.0` and `series_duplication_rate@3` was 0.0000 on every arm because
`_dedupe_series` always runs. Both are now unit tests on `activity_search` itself
(`test_every_hard_constraint_violation_is_removed_before_ranking_ever_sees_it`,
`test_the_top_three_never_repeat_a_series_however_many_sessions_are_offered`).

**Every interval is reported twice.** Six cases share one persona's trace, preference store and
grade table, so bootstrapping cases i.i.d. claims six times the evidence the benchmark has; the
per-case CI on core NDCG@3 is 0.13 wide where the persona-clustered one is 0.28. Both are printed,
with `n` and `n_clusters` in every header, and every arm comparison is a **paired, clustered**
delta rather than two marginal CIs eyeballed side by side. Four reference lines sit beside the
headline: seeded random (20 draws), catalogue order, `intent_filter+static` (the same filtered pool
sorted by distance then title -- what a rule-based catalogue app would do) and an oracle sort. The
artifact also prints a per-persona table (the macro mean hides the worst persona, and the table
names every persona that ranks below a random shuffle), a stated / inferred-only stratification with the
inferred-only number headlined, `discriminable_cases` (a case can only tell a good ranking from a
bad one if its ordering can change the headline metric at all -- best ordering scores differently
from worst, which on this dataset is exactly "not every kept candidate carries the same grade":
51/60 core, 24/24 holdout) and a learning curve from `cold_start` through `trace_prefix:k` with
`cases_to_beat_random`.

**Twenty-three arms** (`full` plus twenty-two ablations, pinned by `test_the_arm_count_matches_the_number_documented_in_testing_md`), of two kinds, each compared to its own declared baseline. A `factor:<name>`
arm zeroes exactly one `ScoreFactor`'s weighted contribution, leaves every factor VALUE -- and so
the hard filter, the tier and the rain rule -- as production computed it, re-sorts and re-runs the
production post-scoring passes through `activity_search.postprocess`; its delta is that factor's
weight alone. An `input:*` arm changes one argument instead, which is honest but rarely touches
exactly one factor, so each declares the factors it moves (`input:no_engagement` also zeroes
`repetition`; `input:no_intent` also re-enables the rain nudge). `no_preference_dim:<D>` drops one
learned dimension, the only way to separate an axis the ranker reads more than once. `cold_start`,
`first_signal` and `trace_prefix:k` truncate the observation trace. An arm that runs with the
diversity swap off is compared to `no_diversity`, never to `full`. A delta of exactly zero prints
as one of three findings -- not exercised, masked by the tier sort, or masked by this metric --
with the case counts behind each, so a masked ablation is never misread as a tested-and-clean one.

**Metamorphic properties.** `apps/api/tests/test_ranking_metamorphic.py` states twelve relations
between two runs over the same 60 cases -- invariance under input permutation, provider/title
renames, location names, a +7-day shift of the whole world and the person's own name and language;
direction under a stated avoid, distance, a "not for me", rain and a fuller intent match. Two fail
today and are marked `xfail(strict=True)` against the opportunity-matrix row that will fix them, so
the suite documents the flaw rather than hiding it.

**Information asymmetry, not circularity.** Grading a ranker against the same signal it was built
from would be worthless. Each persona is authored as a `PersonaBrief` -- hard constraints, stated
tastes, stated avoids, a mobility radius -- that the ranker never sees; graded relevance (0-3) is
read lexicographically from the brief alone (see `dataset.py`'s and `labels.py`'s module
docstrings for the exact rule, including the one place the specification's wording had to be
resolved rather than merely followed). The ranker instead receives an OBSERVATION TRACE -- declines
with reasons, enjoyment reports, interest taps, occasional stated preferences -- folded through the
real, unmodified `preferences.apply_decline`/`apply_enjoyment` into `ActivityPreferences` and a
per-listing `ActivityEngagement` map (`traces.py`). The trace is a genuinely imperfect proxy for
the brief (a decline reason maps to exactly one `PreferenceDimension`, so a taste the trace never
reasons about is never learned), which is what stops this benchmark from grading the ranker against
its own inputs. Hard constraints never reach the grader at all: `filter_candidates` removes every violation before
anything is graded or ranked, which is why the artifact no longer carries a
`constraint_satisfaction@3` row and `activity_search`'s own unit tests carry the property instead.

The asymmetry is not perfect, and the artifact says where. Three of the fourteen personas hand the
grader's own `(dimension, value)` pair straight back to the ranker as a stated preference, which
measures "obey what the person just told you" rather than "infer taste from behaviour"; those
cases are reported as their own stratum, and the number to quote is the inferred-only one.

**What this benchmark can claim, and what it cannot.** Every persona, listing and trace is a
labelled synthetic design artefact (`NOT_USER_TRUTH` in the artifact); none of it is, or is derived
from, a real senior's preferences or history. A high score here is evidence the ranker orders a
small, hand-authored catalogue sensibly under an information-asymmetric grading rule; it is not
evidence about real-world engagement, real catalogue diversity, or the felt quality of a
recommendation. `dataset.py`'s DISTANCE/TIMING bucket boundaries and the reasons-grounded
verifier's small "does the candidate actually satisfy this axis" checks are deliberately
independent re-implementations of logic that is private inside `preferences.py`/`activity_search.py`
(documented in `_dimensions.py`/`_grounding.py`); a future change to either module's private
bucketing could silently drift from this benchmark's own copy without either side raising an error,
which is an accepted, stated seam rather than a hidden risk.

## The recorded-LLM arm (`llm_recorded`)

Until this arm existed, **no agent behaviour in this repository was measured at all.** CI runs
with `LLM_ENABLED=false`, so every planner counter on `/v1/metrics` was structurally zero, and
both evaluation harnesses state in their own module docstrings that they never call the planner.
"The agent earns its place" had no number behind it, in either direction.

`python -m silverloop.evaluation.ranking_llm --out docs/evaluation` closes that. It replays the
production `agent.planner.plan_activity_ranking` loop -- the same prompt, tool surface, guardrail,
iteration cap and five-way degradation -- over all 84 ranking-benchmark cases, with
`agent.recorded_client.RecordedClient` as the transport instead of a provider. Nothing is
monkeypatched; the only thing that changes is where the response comes from. It writes
[`docs/evaluation/ranking-llm.md`](evaluation/ranking-llm.md) and `ranking-llm.json` and never
touches `ranking-evaluation.{json,md}`, which the deterministic benchmark owns.

**The recordings are synthetic, and that is stated everywhere.** They were produced by
`evaluation/ranking_llm/scripted_model.py`, a deterministic rule-based stand-in -- rule A varies
the categories of the first three options, rule B drops tail options repeating a category already
offered, never below five -- and **not by a language model**. Latency and token counts in the
fixtures are derived from the request hash and are not measurements. Every recording file carries
`"synthetic": true` and a `NOT A MODEL` banner; the artifact repeats it above every table; a test
asserts both. So:

- **What this arm is evidence for.** The loop, its allow-list guardrail, its narrowing bound and
  each of its degradation paths run end to end offline over every benchmark case; the metric
  family can distinguish a reordering from the deterministic order (planner agreement, narrowing
  rate and the largest promotion observed are printed in `docs/evaluation/ranking-llm.md`, with
  persona-clustered intervals) rather than reporting structural zeros; a stale
  or missing recording is reported, loudly, as `not recorded`.
- **What it is not evidence for.** Anything about a model's quality. The NDCG delta in that
  artifact is the stand-in's rule, not a model's judgement, and no test gates on it. Re-record
  against a provider (`python -m silverloop.evaluation.ranking_llm.synthesise --inner anthropic
--model <id>`, one human-run command, the only moment in this pipeline with a network
  connection) and every number becomes a statement about that model with no code change.

**Keying, and why a stale recording fails loudly.** A recorded response is keyed by
`sha256` of the canonical JSON of `{model, system, tools, messages}` -- the four fields that
determine what was asked. Edit a prompt, a tool schema or the deterministic order and the lookup
misses: `RecordingMiss` is raised inside `messages.create`, the loop degrades through the path it
already had, and the run is recorded as `fallback_error` with the reason `RecordingMiss`. The arm
counts those misses and the artifact prints them, so a recording that no longer matches its prompt
can never quietly replay as though it did. `max_tokens`, `tool_choice`, thinking and effort are
deliberately outside the key: they shape how an answer is produced, not which answer a recording
stands for.

**Record mode is never reachable from a test.** `RecordedClient(mode="record")` refuses to
construct when `CI`, `GITHUB_ACTIONS`, `CONTINUOUS_INTEGRATION` or `BUILDKITE` is set, and no test
imports `synthesise.py`. Fixtures live under `apps/api/tests/recordings/` and are reviewed in the
diff like any other test data. Regenerating them is three commands, and `synthesise.py` prints the
last two: `python -m silverloop.evaluation.ranking_llm.synthesise`, then
`pnpm exec prettier --write apps/api/tests/recordings` (the writer indents every array, prettier
keeps short ones inline, and `pnpm format:check` enforces prettier's answer), then
`python -m silverloop.evaluation.ranking_llm --out ../../docs/evaluation`.

**Configuration.** `LLM_PROVIDER=recorded` plus `LLM_RECORDING_PATH=<file or directory>`.
`runtime.validate_runtime` permits `LLM_ENABLED=true` with this provider under the `offline`
profile -- it is the one exception, and not a loophole, because the recorded client reads a file
and makes no network call. It still refuses a real provider offline, still enforces the iteration
ceiling, and now requires the recording path up front rather than letting an unset one surface as
a silent `fallback_disabled` mid-run.

**Tests.** `tests/test_recorded_client.py` (keying, replay determinism, miss -> `fallback_error`/
`RecordingMiss`, record-mode refusal, the client-factory branch, the runtime rules, the intent
replay, the guardrail rule table, the cost counters) and `tests/test_ranking_llm_arm.py` (the arm
runs the real loop over every case, reports `not recorded` when fixtures are absent, mirrors the
repository's displayed order, and keeps its artifact deterministic and free of absolute paths).

## The response clock

An offer nobody answers is closed as `no_response` two simulated days after it was made (see
`docs/api.md`, "Silence resolves itself"). `apps/api/tests/test_response_clock.py` pins it at the
contract: open inside the window with `awaiting_reply_until` stated; closed once the window
passes; a recorded answer never overwritten; withdrawn offers never counted as silence; a replayed
`event_id` never resolving twice; the audit event by `system` naming `resolved_by`; the candidate
posterior moving by exactly one `no_response` weight and only once; three silences never muting a
candidate the way three declines do; a late reply told the offer closed rather than "already
recorded"; the two metrics counters; the trace's response stage naming the date. The same file
asserts the contact cap counts the person's simulated week (nine days of advances in one second
release the budget) and still binds inside it.

Scenario YAML can now assert outcomes as well as decisions: an optional `expected_outcomes:` list,
one entry per intervention created (oldest first, `null` for one still open), checked by
`scenarios.py` after the decisions. `05_sustained_decline.yaml` asserts `[no_response, null]`, and
`15_contact_cap_counts_simulated_days.yaml` -- two contacts, six recovery days, then a mild dip
that is permitted a nudge rather than `suppress`ed -- asserts `[no_response, no_response, null]`.
The evaluation harness reads neither key.

## The follow-through loop

Outreach used to end at the sentence. A person tapped "Yes, tell me more", was shown nothing more,
and the tap was recorded as a success. The tests added with the follow-through loop cover the three
beats that were missing and, more importantly, the integrity claim underneath them.

**`test_learning_weights.py` — acceptance is not success.** `PreferenceLearner` used to count
outcomes, so an `accepted` was one success exactly like a `coordinator_resolved`. It is now
weighted, and the tests assert the _relationships_ rather than the constants, so a retune of
`_OUTCOME_WEIGHTS` has to preserve the product claim or fail:

- A bare tap moves the posterior at least twice less than a reported completion, and no run of taps
  ever overtakes a single completion.
- `deferred` moves nothing in either direction, and sits strictly above silence, which sits strictly
  above a refusal.
- A follow-through **supersedes** the acceptance weight rather than stacking on it — one
  intervention contributes at most one unit of evidence, asserted against both the superseded value
  and the stacked value a naive `+=` would produce.
- The differentiating property, asserted directly: a candidate everybody taps and nobody does ranks
  **below** one that is offered a third as often and actually carried out. The same test asserts the
  counterfactual — ranking on acceptance alone inverts the order — so the property cannot pass for
  the wrong reason.
- An **exhaustiveness guard** over both weight tables. `record` returns silently for an outcome it
  has no weight for, which is the right runtime behaviour and exactly the wrong failure mode to
  leave unguarded: a new `OutcomeKind` or `FollowThrough` member would otherwise ship, raise
  nothing, log nothing, and simply stop being learned from.

**`test_follow_up.py` — descriptive, never causal.** `observe_effect` reads days a person lived for
a hundred reasons and puts them next to a text message, so most of these tests are about what it
must refuse to say. It reports itself unavailable below two valid-wear days after the outreach;
`returned_toward_usual` requires **both** a rise and a landing near the anchored reference, so
500 → 900 steps against a 4,000-step reference is "a little higher" and never "back to usual";
low-wear days are excluded from both windows, and the outreach day itself belongs to neither. A
parametrised test walks every reachable path — no history, nothing before, nothing after, too few
after, all low wear, a rise, a fall, no change — and asserts the caveat is present on all of them.
There is no code path that produces a number without the sentence saying a single record cannot
show cause.

**`test_outreach_content.py` — the button leads somewhere.** Both movement candidates return real
steps; an unknown `candidate_key` returns kind `none` and invents nothing; a `programme:` key with
no programme attached does not fabricate a venue. The fixed content is also asserted against the
senior shell's own vocabulary guard (`stable|watch|review|\d+%`) and against prescriptive counts and
durations, so a violation fails in a unit test rather than in a browser two layers away.

**`test_follow_through_api.py` / `test_follow_through_ownership.py`.** `deferred` is accepted and
audited while coordinator-only outcomes are still refused; follow-through is 422 before acceptance,
422 after any non-acceptance, and 422 on a repeat; the follow-up route is always 200 with "too early
to say" as a normal answer. Three declines suppress a candidate deterministically, and — the edge
case that decides whether suppression is a feature or an outage — when **every** candidate for a
decision is muted the result is an audited `NO_ACTION` with a reason naming the person's own choice,
never a crash and never a silent skip. Suppression is asserted to narrow the permitted set without
ever raising a decision rung. The ownership file mirrors `test_intervention_outcome_ownership.py`
across all five new routes: out of scope is 404 rather than 403 so none of them is an existence
oracle, the refusal leaves the victim's interventions, audit trail and preference scores untouched,
and only the senior may write a candidate preference — a coordinator attempting to mute a suggestion
on someone else's behalf gets 403.

**Browser.** `apps/e2e/tests/loop.spec.ts` drives the real Vue app against the real API (SQLite,
fixtures, sign-in off). The follow-through screens tested by the former browser specs are not part
of the current web app; the API behaviour above is still covered by the API tests.

### What this does **not** change: the evaluation harness

`scenarios/*.yaml` still express **decisions only**. Follow-through is not represented in the
evaluation harness at all: no scenario carries an outcome, an acceptance or a follow-through, the
three policies are folded over a decision-independent environment stream, and the `labels:` ground
truth describes world state rather than anything a person replied. Nothing above feeds M1-M6, the
gate ablation, the threshold sweep or the metamorphic properties, and the causal comparison between
outreach and no outreach is unaffected — it remains a cross-policy comparison over many replayed
people, which is precisely why `FollowUpObservation.caveat` says the single-person view is not that
comparison. If follow-through is ever added to the harness it needs its own ground-truth labelling
scheme; reusing `expected_decisions` for it would be circular in the same way scoring `silverloop`
against its own decisions would be.

## Search-path goldens

`apps/api/tests/test_search_ranking_golden.py` pins what `POST /v1/activities/search` actually
records, end to end, in two committed files under `apps/api/tests/golden/`:

- **`search_detail_ranking.jsonl`** — the stored audit event's `detail.ranking` rows (and result
  order) for 145 searches across the five personas and a fixed set of request texts. The evaluation
  artifacts cover only the pure ranker over the harness's own inputs; this file also covers the
  repository's read phase (engagement counting, series roll-up, rain, preferences), so a change
  anywhere on the search path shows up here.
- **`search_scenarios_golden.jsonl`** — paths the first file cannot reach: a variety swap on the
  search path, a went-and-enjoyed plan report, same-day repeat taps, an "interested" on a sibling
  session after a decline, and a search whose bounded planner (a scripted transport, never the
  network) is rejected once, then narrows and reorders.

**When to regenerate.** Only for a deliberate change to ranking or to what the audit records — never
to make a failing test pass. A golden failure on a change that was not meant to move rankings is the
test doing its job.

**How.** From `apps/api`:
`SILVERLOOP_REGENERATE_SEARCH_GOLDEN=1 uv run pytest tests/test_search_ranking_golden.py`, then run
it again without the variable to confirm it passes. When the same change also moves the evaluation
reports or the recorded-LLM fixtures, regenerate in this order: `evaluation.ranking` into
`docs/evaluation`, the `ranking_llm` recordings (`synthesise`, then prettier), the `ranking_llm`
report, and the goldens last — then `pnpm evaluate:check` and the scenarios, which should not move.

**Review the diff before accepting it**, grouped by the cause you expect: every changed row should
be explainable by the change, and a row nothing explains is a regression. Record the reviewed
summary in the test module's docstring. History: both files were captured before the
ranker-inspector refactor (commit `0fdc84f`) and proved it behaviour-identical; they were
regenerated on 2026-09-15 for the recorded-discrepancy fixes — every row gained `tier`,
`matched_axes` and `coverage` (D2); 90 of 145 cases swap sessions within a programme because equal
scores now break soonest first, and none reorders programmes (D18); preference and engagement values
moved where an unclarified "not for me" is held back and activity types resolve per value (D7, D17);
reason lines follow positive contributions (D12, D15); the scripted planner case labels its unseen
tail `ranker` (D3). They were regenerated again on 2026-09-15 (round 2), when the capture gained
`more_reasons` beside the visible `reasons`. Round 2 was reviewed field by field: the item-1
checkpoint (card reasons moved to `more_reasons` before any wording change) left both golden files
byte-identical, so no visible line moved; the regeneration itself changed only reason text — the
catalogue filler line became the bare catalogue label (item 8f), stated, goal and learned lines were
reworded by source and every "--" dash became a comma phrase (item 3) — and added the `more_reasons`
capture (62 lines across both files). No order, score, tier, filter or count changed. The same round
left `docs/evaluation/ranking-evaluation.*` and the intent recordings byte-identical, and the
`ranking_llm` metrics unchanged (only the synthetic stand-in's latency, token figures and recording
digest moved, because reason text is part of each recorded request).

## Review-threshold calibrator

The committed evaluation is unchanged: no scenario YAML was added, the authored-label digest and the
holdout are untouched, and `policy.decide` with the default setting is byte-identical
(`test_full_ladder_is_identical_to_the_real_policy` now also folds all 14 allowed settings with and
without a shadow date). The properties are proven in pytest instead:

- `test_review_threshold.py` — every guardrail rule pinned pass and fail, the live-setting fold,
  expiry, reconfirm, the fixed-rule proposer, notice wording against the senior vocabulary.
- `test_review_threshold_properties.py` — the floor always asks; no setting delays a review past the
  starting setting's first day plus three; random approval stacks never make a revert or expiry ask later.
- `test_review_threshold_api.py`, `test_review_threshold_checking.py` — approval flow, cooldown, cap,
  manual set, reverts, expiry, far-more-severe, checking-period close, write-ups, reads write nothing,
  run-row lock ordering.
- `test_threshold_planner.py` — the agent on fake transports: revision, cap, every fallback, note
  injection never loosens, fencing, no ids or wall-clock times in prompts, byte-identical prompts for
  identical flows, no senior statements in any tool payload.
- `test_review_threshold_recording.py` — the synthetic `tests/recordings/review_threshold/scripted.json`
  replays through the guided sequence with `transport == "recorded"`.
- `test_review_threshold_postgres.py` (gated on `SILVERLOOP_POSTGRES_TEST_URL`) — concurrent reviews,
  approvals, consent changes and advances on a loosened setting deadlock-free.
- The e2e database resets only Mdm Lim, so the Mdm Wong guided sequence is pinned in
  `test_review_threshold_demo.py`.

## Calibration trust and the UX redesign

`pnpm evaluate:check` now also runs `evaluate-calibration-check`
(`python -m silverloop.evaluation.calibration --out ../../docs/evaluation --check`). It fails if
`docs/evaluation/review-calibration.{json,md}` would change. The other evaluation reports and the
scenario digests are unchanged. Regenerate with `pnpm evaluate`.

API tests:

- `test_review_lessons_contract.py`: `classify_review` over the full input grid, reached-too-late over
  known context, the context-gap tally, and the import boundary (`policy.py`, `review_threshold.py` and
  `agent/` never import `review_lessons`).
- `test_review_context_gap_contract.py`: the 422 rule, storage, presence-only audit, the tally and
  receipt on the threshold state, and the `authored_metric` seam.
- `test_review_context_gap_migration.py`: Alembic `7c3e9a1f4b28` up and down, keeping `case_reviews`
  append-only.
- `test_review_setting_receipt.py`: receipt subjects, exclusions and what each review led to. Two
  equivalence tests pin the counted set to what the calibrator counts.
- `test_calibration_evaluation.py`: pinned sequences digest, determinism, no network in the agent arm,
  lazy imports, no ids or wall-clock times, committed artifacts current, dismissive-profile containment,
  zero weekly-cap skips, and floor and shadow check exercised.
- `test_case_delta.py`, `test_case_since_last_review_api.py`: the since-last-review anchor, the items,
  that nothing the senior said and no note appears, `None` once resolved, and the routes whose schemas
  can carry it.
- `test_stored_state_compat.py`: a legacy snapshot without `decided_by_gate` still serves history,
  returns a classified `stored_state_incompatible` on replay and `latest`, and recovers on reset. It
  also checks that server validation errors are `internal_error` 500s while request validation stays a 422.

The browser suite is one spec, `apps/e2e/tests/loop.spec.ts` (five tests, Mdm Lim only): the home
page reports the backend connected; a simulated decline (played straight through the API — there is
no Simulator screen) reaches the senior, who replies; a persistent decline creates a review case,
not a suggestion, checked via the API response alone; withdrawing consent on the senior screen shows
on the home overview and can be undone; an unknown address shows the not-found page.

Web unit tests (`node:test` over `apps/web/src/lib/*.test.ts`) cover the pure logic: `labels` (badge
wording), `daily-tasks`, `api-errors`, `format-date`, `current-user` and `route-guard`.

## What the tests establish

- Personal median/MAD baseline calculations behave deterministically.
- Missing wear-time and rain reduce confidence or prevent premature action.
- Revoked consent always blocks outreach.
- The intervention ladder reaches human review only after sustained decline.
- Contact caps do not suppress a genuine no-action/recovery decision, but do block excess messages.
- The FastAPI contract creates review evidence and returns the coordinator queue.
- Client event IDs are idempotent across process restarts and cannot be reused for another event.
- Every `POST /v1/simulation/advance` response carries the full ten-stage decision trace
  (`follow_through` sits at order 8, between recording the outcome and learning from it); there is
  no Simulator screen to view it in any more, so this is asserted against the API response directly.
- Stale programme fixtures produce an audited `NO_ACTION`, not an outdated suggestion.
- A decision with every candidate muted also produces an audited `NO_ACTION`, with a reason naming
  the person's own choice.
- Duplicate outcomes are rejected without applying preference learning twice, and a follow-through
  is recorded once per intervention or not at all.
- Acceptance moves the preference posterior far less than a reported completion, and a candidate
  with high acceptance and low follow-through ranks below one with the reverse.
- Every `OutcomeKind` and `FollowThrough` member has a learning weight, so a new member cannot
  silently stop being learned from.
- Every follow-up observation carries its non-causal caveat, including the unavailable ones.
- "Yes, tell me more" leads to fixed, reviewed content on the senior surface, and that content
  carries no coordinator vocabulary or raw figures.
- No senior can read or write another person's follow-through, outreach detail, follow-up,
  preferences or day disputes, and only the senior may mute their own suggestions.
- A real Chromium session connects a simulated decline (played through the API, not a Simulator
  screen) to the senior's reply, and a persistent decline reaching `coordinator_review` is checked
  against the API response alone -- there is no Care Team screen in the current web app to review it
  from. A senior can withdraw and restore consent, from the browser.
- The Vue app typechecks (`vue-tsc`, with unused imports as errors) and builds for production
  (`vite build`).
- PostgreSQL applies the Alembic head, preserves idempotent state across repository restarts,
  enforces consent withdrawal and rejects mutation of append-only decision evidence.
- The intent factor is scored from every matched axis, never from the three-line card; a fuller
  match is never overtaken by learned preference, weather, history and distance combined; only
  the person's own recent "not for me" can pull a matching listing down; the top three are never
  three sessions of one programme; every positive contribution is a reason on the card face or in
  `more_reasons` (shown when the card is opened, counted as `reasons_suppressed`), and a final
  entry never has more than three face lines; one decline is charged once while its cooldown runs.
- A stated preference supersedes inferred rows on its dimension rather than averaging with them;
  an enjoyment report supersedes attendance in the outreach learner; a coordinator closing a case
  moves nothing; three `bad_day` declines never mute a candidate.
- While consent is withdrawn a search is answered and a tap recorded, but nothing is inferred;
  what the person states is still honoured.
- The quiet-day question is reachable for every persona (the fixture biography never silences
  it), and its answer is a fact about one day in the world model.
- Every new route 404s for another person's plan, preference or world model; the preference
  `value` path segment, `language`, `raw_text` and `rank_shown` are bounded at the contract; a
  client cannot spoof `parsed_by`; a racing double tap is a 409; the follow-through audit records
  `note_present`, never the note; the request log carries the route template, never the path.
- The intent planner reaches the model with only `LLM_ENABLED=true` set; the planner's
  allow-list is exactly the shown set; person text and catalogue titles reach a prompt fenced and
  labelled as data, and a poisoned title, a "SYSTEM:" directive or a forged closing fence cannot
  add, drop or reorder outside the allow-list.
- Every ORM table has a deny policy in a Supabase mirror file, and the newest mirror advances
  `alembic_version` to the repository head.
- The documented ground-truth rule reproduces every scenario label, core and holdout. Making it
  executable found one holdout label (`h01_sync_gap_then_decline` step 4) authored from the
  rolling delta instead of the anchored one; it was corrected to `stable` on 2026-09-12 and the
  holdout row of the policy comparison moved accordingly (Care+'s one nudge there now
  counts as an unnecessary contact). No policy threshold changed.
- The API behind the senior surface (search, "I'm interested", "Not for me" and the preferences it
  teaches) is covered by the API tests; the current web app does not have those screens.

## What the tests do not establish

- Clinical validity, fall detection accuracy or improved health outcomes.
- Healthy 365 API access or government endorsement.
- Real AAC programme availability.
- Fairness across demographic groups from synthetic data.
- Production security, durability or emergency response suitability.
- That outreach causes activity to change. `FollowUpObservation` describes what one person's days
  did around one suggestion and says so on every result; it is not evidence of effect, and the
  tests assert the caveat rather than any causal claim.
- That the follow-through weights are correctly calibrated. The tests fix the _ordering_ the
  product depends on — a completion outranks a tap, a deferral moves nothing — not the numbers,
  which are a design choice made without outcome data and would need a field pilot to justify.
- That people report follow-through honestly, or at all. Every follow-through in the suite is
  synthetic and submitted by the test; nothing here establishes a real reporting rate, and
  `None` is deliberately indistinguishable between "not asked" and "chose not to say".
- That candidate suppression matches what a person actually wants. Three declines is a chosen
  threshold, not a measured one.

Those claims require authorised data, ethics/privacy review, field pilots and outcome evaluation.

Human-only checks are kept separately in [`manual-ui-checklist.md`](manual-ui-checklist.md).
