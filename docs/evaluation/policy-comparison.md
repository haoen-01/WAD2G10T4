# Care+ policy comparison

**Seeded software-policy simulation; not clinical validation.**

This run replays 15 core scenario(s) (59 decision steps, 5 persona(s)) and 5 holdout scenario(s) through three policies folded over an identical, decision-independent environment stream. Core and holdout are reported separately and are never pooled. Rates are always printed as `n/d (rate)`; a bare percentage over a small sample would be dishonest.

Harness version: `2.0.0` · Seed: `2026` · Core digest: `9d3307a75f165dbc…` · Holdout digest: `f26ce915d34dd5df…`

The harness never calls the LLM planner; every number here is reproducible from the frozen seed alone.

The headline table is **budget-matched**: the harness applies the identical weekly contact cap to every policy, converting a would-be contact into `suppress` once the budget is spent. Without this, the comparison rewarded Care+ for having a cap rather than for choosing better, and it counted `contact_cap_breach` against `contextual_rule`, which has no cap by construction -- an exam it was built to fail. The uncapped arm is kept below so the size of the budget effect stays visible, but it is not the headline and `contact_cap_breach` there describes behaviour rather than scoring judgement.

**Every rate carries its own coverage, and none carries a confidence interval.** A rate is printed as `0/19 (0.00%) across 3 scenarios, 2 personas`: the counts are the distinct scenarios and people the denominator was drawn from. They are there instead of a bootstrap interval, not as a step towards one. The steps inside a scenario are serially dependent by construction -- day 3 of a decline exists only because days 1 and 2 did -- and the scenarios themselves are hand-written from a handful of personas, so resampling them would manufacture a sampling distribution that the design of this harness does not have. The two counts answer the question a CI would only appear to answer: how much independent evidence sits behind the number. Where a rate reads `n/1 scenario`, it is one scripted week's opinion and must be read as one.

## Ground truth

Ground-truth labels are world state, assigned from the replayed environment by a single rule applied identically to core and holdout: consent inactive -> `no_consent`; wear-time below the 8h minimum -> `unusable_data`; a dip under an unrefuted rain explanation -> `explained_dip`; otherwise, against the person's own ANCHORED median -- what was typical for them when observation began, not the rolling window -- better than -20% -> `stable`, worse with fewer than three consecutive valid-wear low days -> `emerging_decline`, three or more -> `persistent_decline`.

Why the labels anchor. The rule originally read "against the person's own median", meaning the rolling one. That inherits the exact defect the baseline clamp exists to fix: a person whose activity falls and stays down drags their rolling median down with them, so by roughly day 17 of a sustained 56% decline the rule would label them `stable` and score any outreach as unnecessary contact. The ground truth would have marked the fix as a regression. Anchoring the label to what was typical when observation began is a no-op for every short scenario -- where the two medians agree -- and is the only reading under which a long decline can be labelled honestly at all.

Honest caveat: the rule above shares **three predicates**, not one threshold, with the ladder it is used to score.

| Label predicate | Ladder predicate reading the same value | Independent? |
|---|---|---|
| `unusable_data` = `not signal.quality.safe_to_interpret` | `ladder.py` data-quality gate, the identical expression | **No** |
| `persistent_decline` = `sustained_low_days >= 3` | the escalation gate's `sustained_low_days >= ESCALATION_DAYS` (= 3) | **No** |
| the -20% boundary between `stable` and `emerging_decline` | the nudge rung's own severity threshold | **No** |
| `explained_dip` = rainy and at or past the -20% boundary | the rain gate, which also requires `sustained_low_days < 2` and so expires after one day | Yes |
| `no_consent` = consent inactive | the consent gate | Yes, but it is a fact about permission, not a judgement either side could get wrong |

An earlier version of this paragraph claimed the opposite -- that "everything either side of the boundary (rain, consent, wear-time, persistence, escalation) is independent". Wear-time and persistence are not, and the consequence is concrete: every `persistent_decline` step is by construction a step where the escalation predicate already holds, so M2 and M3 can only be non-zero through a consent, quality or contact-cap interception. Care+'s `0/19` on both is therefore a narrower claim than it looks. The `world:` latent labels below are the second, genuinely separate account of the same days that this table is the argument for.

### Latent world labels (M24)

**Two label columns, and the number that says whether the second one is real.** `label_authored` is the hand-written `labels:` entry, unchanged. `label_latent` is `label_from_latent` applied to the scenario's additive `world:` block -- the author's statement of what the person's day actually was (how much of their own norm they really did, what drove it, how long it had run, whether the device saw it), written without reference to any generated number. The latent's cut points -- above 0.80 of the person's norm is not low; three consecutive low days is persistent -- are definitions of the fictional world and are tuned to nothing.

`label_feature_agreement` is the share of steps where `label_latent` matches the signal-derived rule. **A value of 1.000 would mean the second label source has collapsed back onto the first and the harness is a tautology again, with extra steps.** It must be read as a diagnostic with a target below 100%, never as a score to maximise: the two accounts are supposed to part company where measurement and truth part company, and every step at which they do is listed below rather than reconciled away.

What the latent does NOT yet do: it does not generate the observed numbers. The event table in `simulation.py` is still what the wearable reports, unchanged to the byte, and the latent is advanced beside it rather than through it (`simulation.replay` moves the world first, then observes it, and `_observe` carries a seeded noise channel that is off for every committed artifact). So the two accounts are consistent by authoring, not by construction -- which is exactly why the agreement rate has to be printed instead of assumed.

`label_feature_agreement`: **78/81 (96.30%) across 20 scenarios, 5 personas**

`label_authored` vs the signal-derived rule: 81/81 (100.00%) across 20 scenarios, 5 personas. This used to be asserted equal by `test_documented_ground_truth_rule_reproduces_every_scenario_label`, which is what pinned every hand-written label to `analytics.py` and `quality.py` for good. The test now reports this rate and lists any disagreement instead of failing on it.

Every replayed scenario carries an authored `world:` block.

The 3 step(s) where the authored world and the signal-derived rule disagree -- listed, not reconciled:

| Step | Event | `label_authored` | signal rule | `label_latent` |
|---|---|---|---|---|
| `core/09_contact_cap_pressure` step 3 | `activity_declines` | `emerging_decline` | `emerging_decline` | `persistent_decline` |
| `core/10_gradual_decline` step 3 | `activity_declines` | `emerging_decline` | `emerging_decline` | `persistent_decline` |
| `holdout/h01_sync_gap_then_decline` step 4 | `activity_declines` | `stable` | `stable` | `emerging_decline` |

## Core set

The 15 scenarios Care+'s thresholds were developed against. Treat these as in-sample.

### Budget-matched (headline) -- uniform weekly cap of 2

| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | M3 missed escalation | M4 no-action logging integrity | M6 unwarranted share of contacts made | M5 violations (steps) |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 59 | 2/17 (11.76%) across 8 scenarios, 3 personas | 13/19 (68.42%) across 4 scenarios, 2 personas | 19/19 (100.00%) across 4 scenarios, 2 personas | 16/38 (42.11%) across 13 scenarios, 5 personas | 2/21 (9.52%) across 10 scenarios, 5 personas | 30 (21 step(s)) |
| `contextual_rule` | 59 | 2/17 (11.76%) across 8 scenarios, 3 personas | 15/19 (78.95%) across 4 scenarios, 2 personas | 19/19 (100.00%) across 4 scenarios, 2 personas | 21/44 (47.73%) across 15 scenarios, 5 personas | 2/15 (13.33%) across 7 scenarios, 4 personas | 15 (15 step(s)) |
| `silverloop` | 59 | 0/17 (0.00%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 24/24 (100.00%) across 12 scenarios, 5 personas | 0/16 (0.00%) across 9 scenarios, 3 personas | 0 (0 step(s)) |

**Methodology.** M4 (`no_action_logging_integrity`, formerly `audited_no_action`) and M9 (`restraint_explanation_coverage`) check that a decision carries a rationale and a quality evidence id -- a property of the logging pipeline, not of whether the silence was correct. M9 is the identical predicate as M4, just scoped to `NO_ACTION` alone instead of every `QUIET` decision. Care+'s own ladder populates both fields on every branch, so **M4 and M9 both read 100% for it in every arm by construction**, regardless of whether any individual decision was right -- they are logging smoke tests, not correctness scores, and are retained under that honest label rather than deleted. The baselines' M9 (0% for `fixed_threshold`, part-way for `contextual_rule`) is not a restraint-quality finding either: it reflects which of their hardcoded `NO_ACTION` branches happen to include prose in `baselines.py`, not how sound their silence was.

**M7 correct restraint** and **M8 unsupported restraint** are the ground-truth-scored metrics in this family: M7 is `NO_ACTION` / steps where the label says outreach was unnecessary (`stable`/`explained_dip`, M1's denominator); M8 is `NO_ACTION` / steps where the label says outreach was required (`persistent_decline`, M2's denominator -- shown beside M8 below so a reader can see directly whether they diverge; they do exactly when `SUPPRESS` appears on a `persistent_decline` step, since M2 counts `SUPPRESS` as missed and M8 does not). `SUPPRESS` never counts toward M7 or M8's numerators -- it means consent or the contact budget blocked a contact the policy wanted to make, which is a different failure mode from the policy concluding, in its own rationale, that nothing was wrong -- and `COORDINATOR_REVIEW` / any `CONTACT` decision is excluded from both by definition (neither is `NO_ACTION`).

**M7 is an identity of M1 whenever `SUPPRESS` is absent.** On M1's own denominator, every step is exactly `ACTION` (M1's numerator), `NO_ACTION` (M7's numerator) or `SUPPRESS`, so `M7 = 1 - M1 - suppress_share`. M7 only carries information beyond M1 when `SUPPRESS` is non-zero on `stable`/`explained_dip` steps; on every arm and scenario set this harness has replayed, no policy `SUPPRESS`es on those steps, so M7 restates M1's complement rather than measuring something new -- see `docs/adr/0002-replace-audited-no-action.md` for the numbers this was checked against.

| Policy | M8 unsupported restraint | M2 missed persistent change | M7 correct restraint (restates M1) | M9 explanation coverage (logging check) |
|---|---|---|---|---|
| `fixed_threshold` | 1/19 (5.26%) across 4 scenarios, 2 personas | 13/19 (68.42%) across 4 scenarios, 2 personas | 12/17 (70.59%) across 8 scenarios, 3 personas | 0/22 (0.00%) across 11 scenarios, 3 personas |
| `contextual_rule` | 6/19 (31.58%) across 4 scenarios, 2 personas | 15/19 (78.95%) across 4 scenarios, 2 personas | 12/17 (70.59%) across 8 scenarios, 3 personas | 8/30 (26.67%) across 12 scenarios, 3 personas |
| `silverloop` | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 17/17 (100.00%) across 8 scenarios, 3 personas | 20/20 (100.00%) across 9 scenarios, 3 personas |

| Policy | Contacts made | Budget withheld by harness | Escalations | Can it escalate at all? |
|---|---|---|---|---|
| `fixed_threshold` | 21 | 16 | 0 | **no -- never emits `coordinator_review`, so M3 is structural, not a judgement error** |
| `contextual_rule` | 15 | 13 | 0 | **no -- never emits `coordinator_review`, so M3 is structural, not a judgement error** |
| `silverloop` | 16 | 0 | 19 | yes |

### Uncapped (each policy exactly as written)

`silverloop` caps itself, so its uncapped numbers are its own doing; neither baseline caps itself at all. That asymmetry is the reason the arm above exists.

| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | M3 missed escalation | M4 no-action logging integrity | M6 unwarranted share of contacts made | M5 violations (steps) |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 59 | 5/17 (29.41%) across 8 scenarios, 3 personas | 1/19 (5.26%) across 4 scenarios, 2 personas | 19/19 (100.00%) across 4 scenarios, 2 personas | 0/22 (0.00%) across 11 scenarios, 3 personas | 5/37 (13.51%) across 10 scenarios, 5 personas | 66 (37 step(s)) |
| `contextual_rule` | 59 | 5/17 (29.41%) across 8 scenarios, 3 personas | 6/19 (31.58%) across 4 scenarios, 2 personas | 19/19 (100.00%) across 4 scenarios, 2 personas | 8/31 (25.81%) across 13 scenarios, 3 personas | 5/28 (17.86%) across 7 scenarios, 4 personas | 43 (28 step(s)) |
| `silverloop` | 59 | 0/17 (0.00%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 24/24 (100.00%) across 12 scenarios, 5 personas | 0/16 (0.00%) across 9 scenarios, 3 personas | 0 (0 step(s)) |

### Budget effect (uncapped -> capped)

Read the direction of travel carefully. A baseline's M1 improves under the cap because the harness silenced it after two contacts, not because it judged better -- and the same cap makes its M2 (missed persistent change) worse, because an undiscriminating policy spends its whole budget on quiet days and has nothing left when a real decline arrives. That trade is the actual finding; the M1 improvement on its own is an artefact of the budget.

| Policy | Contacts uncapped | Contacts capped | Delta | M6 unwarranted share uncapped | M6 capped |
|---|---|---|---|---|---|
| `fixed_threshold` | 37 | 21 | -16 | 5/37 (13.51%) across 10 scenarios, 5 personas | 2/21 (9.52%) across 10 scenarios, 5 personas |
| `contextual_rule` | 28 | 15 | -13 | 5/28 (17.86%) across 7 scenarios, 4 personas | 2/15 (13.33%) across 7 scenarios, 4 personas |
| `silverloop` | 16 | 16 | +0 | 0/16 (0.00%) across 9 scenarios, 3 personas | 0/16 (0.00%) across 9 scenarios, 3 personas |

## Holdout set

5 scenarios added after the policy was frozen. No threshold in `policy.py`, `analytics.py` or `quality.py` was changed, tuned or re-checked against them; the labels were assigned by the rule above from the replayed world state, before the decisions were looked at. Personas covered: `mdm-siti`, `mr-ravi`, `mdm-lim`, `mdm-devi`.

### Budget-matched (headline) -- uniform weekly cap of 2

| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | M3 missed escalation | M4 no-action logging integrity | M6 unwarranted share of contacts made | M5 violations (steps) |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 22 | 3/12 (25.00%) across 4 scenarios, 4 personas | 1/1 (100.00%) across 1 scenario, 1 persona | 1/1 (100.00%) across 1 scenario, 1 persona | 6/14 (42.86%) across 5 scenarios, 4 personas | 3/8 (37.50%) across 4 scenarios, 4 personas | 13 (8 step(s)) |
| `contextual_rule` | 22 | 4/12 (33.33%) across 4 scenarios, 4 personas | 1/1 (100.00%) across 1 scenario, 1 persona | 1/1 (100.00%) across 1 scenario, 1 persona | 5/15 (33.33%) across 5 scenarios, 4 personas | 4/7 (57.14%) across 4 scenarios, 4 personas | 7 (7 step(s)) |
| `silverloop` | 22 | 3/12 (25.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 14/14 (100.00%) across 5 scenarios, 4 personas | 2/6 (33.33%) across 4 scenarios, 3 personas | 0 (0 step(s)) |

**Methodology.** M4 (`no_action_logging_integrity`, formerly `audited_no_action`) and M9 (`restraint_explanation_coverage`) check that a decision carries a rationale and a quality evidence id -- a property of the logging pipeline, not of whether the silence was correct. M9 is the identical predicate as M4, just scoped to `NO_ACTION` alone instead of every `QUIET` decision. Care+'s own ladder populates both fields on every branch, so **M4 and M9 both read 100% for it in every arm by construction**, regardless of whether any individual decision was right -- they are logging smoke tests, not correctness scores, and are retained under that honest label rather than deleted. The baselines' M9 (0% for `fixed_threshold`, part-way for `contextual_rule`) is not a restraint-quality finding either: it reflects which of their hardcoded `NO_ACTION` branches happen to include prose in `baselines.py`, not how sound their silence was.

**M7 correct restraint** and **M8 unsupported restraint** are the ground-truth-scored metrics in this family: M7 is `NO_ACTION` / steps where the label says outreach was unnecessary (`stable`/`explained_dip`, M1's denominator); M8 is `NO_ACTION` / steps where the label says outreach was required (`persistent_decline`, M2's denominator -- shown beside M8 below so a reader can see directly whether they diverge; they do exactly when `SUPPRESS` appears on a `persistent_decline` step, since M2 counts `SUPPRESS` as missed and M8 does not). `SUPPRESS` never counts toward M7 or M8's numerators -- it means consent or the contact budget blocked a contact the policy wanted to make, which is a different failure mode from the policy concluding, in its own rationale, that nothing was wrong -- and `COORDINATOR_REVIEW` / any `CONTACT` decision is excluded from both by definition (neither is `NO_ACTION`).

**M7 is an identity of M1 whenever `SUPPRESS` is absent.** On M1's own denominator, every step is exactly `ACTION` (M1's numerator), `NO_ACTION` (M7's numerator) or `SUPPRESS`, so `M7 = 1 - M1 - suppress_share`. M7 only carries information beyond M1 when `SUPPRESS` is non-zero on `stable`/`explained_dip` steps; on every arm and scenario set this harness has replayed, no policy `SUPPRESS`es on those steps, so M7 restates M1's complement rather than measuring something new -- see `docs/adr/0002-replace-audited-no-action.md` for the numbers this was checked against.

| Policy | M8 unsupported restraint | M2 missed persistent change | M7 correct restraint (restates M1) | M9 explanation coverage (logging check) |
|---|---|---|---|---|
| `fixed_threshold` | 0/1 (0.00%) across 1 scenario, 1 persona | 1/1 (100.00%) across 1 scenario, 1 persona | 6/12 (50.00%) across 4 scenarios, 4 personas | 0/8 (0.00%) across 4 scenarios, 3 personas |
| `contextual_rule` | 0/1 (0.00%) across 1 scenario, 1 persona | 1/1 (100.00%) across 1 scenario, 1 persona | 6/12 (50.00%) across 4 scenarios, 4 personas | 1/9 (11.11%) across 5 scenarios, 4 personas |
| `silverloop` | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 9/12 (75.00%) across 4 scenarios, 4 personas | 10/10 (100.00%) across 4 scenarios, 4 personas |

| Policy | Contacts made | Budget withheld by harness | Escalations | Can it escalate at all? |
|---|---|---|---|---|
| `fixed_threshold` | 8 | 6 | 0 | **no -- never emits `coordinator_review`, so M3 is structural, not a judgement error** |
| `contextual_rule` | 7 | 4 | 0 | **no -- never emits `coordinator_review`, so M3 is structural, not a judgement error** |
| `silverloop` | 6 | 0 | 2 | yes |

### Uncapped (each policy exactly as written)

`silverloop` caps itself, so its uncapped numbers are its own doing; neither baseline caps itself at all. That asymmetry is the reason the arm above exists.

| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | M3 missed escalation | M4 no-action logging integrity | M6 unwarranted share of contacts made | M5 violations (steps) |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 22 | 6/12 (50.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 1/1 (100.00%) across 1 scenario, 1 persona | 0/8 (0.00%) across 4 scenarios, 3 personas | 6/14 (42.86%) across 4 scenarios, 4 personas | 26 (14 step(s)) |
| `contextual_rule` | 22 | 6/12 (50.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 1/1 (100.00%) across 1 scenario, 1 persona | 1/11 (9.09%) across 5 scenarios, 4 personas | 6/11 (54.55%) across 4 scenarios, 4 personas | 15 (11 step(s)) |
| `silverloop` | 22 | 3/12 (25.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 14/14 (100.00%) across 5 scenarios, 4 personas | 2/6 (33.33%) across 4 scenarios, 3 personas | 0 (0 step(s)) |

### Budget effect (uncapped -> capped)

Read the direction of travel carefully. A baseline's M1 improves under the cap because the harness silenced it after two contacts, not because it judged better -- and the same cap makes its M2 (missed persistent change) worse, because an undiscriminating policy spends its whole budget on quiet days and has nothing left when a real decline arrives. That trade is the actual finding; the M1 improvement on its own is an artefact of the budget.

| Policy | Contacts uncapped | Contacts capped | Delta | M6 unwarranted share uncapped | M6 capped |
|---|---|---|---|---|---|
| `fixed_threshold` | 14 | 8 | -6 | 6/14 (42.86%) across 4 scenarios, 4 personas | 3/8 (37.50%) across 4 scenarios, 4 personas |
| `contextual_rule` | 11 | 7 | -4 | 6/11 (54.55%) across 4 scenarios, 4 personas | 4/7 (57.14%) across 4 scenarios, 4 personas |
| `silverloop` | 6 | 6 | +0 | 2/6 (33.33%) across 4 scenarios, 3 personas | 2/6 (33.33%) across 4 scenarios, 3 personas |

### Core vs holdout, budget-matched

| Policy | M1 core | M1 holdout | M6 core | M6 holdout | M7 core | M7 holdout | M8 core | M8 holdout |
|---|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 2/17 (11.76%) across 8 scenarios, 3 personas | 3/12 (25.00%) across 4 scenarios, 4 personas | 2/21 (9.52%) across 10 scenarios, 5 personas | 3/8 (37.50%) across 4 scenarios, 4 personas | 12/17 (70.59%) across 8 scenarios, 3 personas | 6/12 (50.00%) across 4 scenarios, 4 personas | 1/19 (5.26%) across 4 scenarios, 2 personas | 0/1 (0.00%) across 1 scenario, 1 persona |
| `contextual_rule` | 2/17 (11.76%) across 8 scenarios, 3 personas | 4/12 (33.33%) across 4 scenarios, 4 personas | 2/15 (13.33%) across 7 scenarios, 4 personas | 4/7 (57.14%) across 4 scenarios, 4 personas | 12/17 (70.59%) across 8 scenarios, 3 personas | 6/12 (50.00%) across 4 scenarios, 4 personas | 6/19 (31.58%) across 4 scenarios, 2 personas | 0/1 (0.00%) across 1 scenario, 1 persona |
| `silverloop` | 0/17 (0.00%) across 8 scenarios, 3 personas | 3/12 (25.00%) across 4 scenarios, 4 personas | 0/16 (0.00%) across 9 scenarios, 3 personas | 2/6 (33.33%) across 4 scenarios, 3 personas | 17/17 (100.00%) across 8 scenarios, 3 personas | 9/12 (75.00%) across 4 scenarios, 4 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/1 (0.00%) across 1 scenario, 1 persona |

## Ablation: which of Care+'s own gates is load-bearing?

### Gate ablation -- core set

Each row switches off exactly one gate of a transcription of the ladder that lives inside the evaluation package (`evaluation/ladder.py`); `policy.py` is never edited or patched. The reference row is that transcription with every gate ON, and the test suite asserts it is decision-for-decision identical to `silverloop.policy.decide`, so any delta below is attributable to the disabled gate. Ablations run harness-uncapped, otherwise switching off the contact-cap gate would be invisible.

| Disabled gate | Steps decided differently | M1 unnecessary contact | M2 missed persistent change | M8 unsupported restraint | M4 no-action logging integrity | M6 unwarranted share | Contacts | Escalations | M5 violations | Load-bearing here? |
|---|---|---|---|---|---|---|---|---|---|---|
| _(reference: all gates on)_ | -- | 0/17 (0.00%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 24/24 (100.00%) across 12 scenarios, 5 personas | 0/16 (0.00%) across 9 scenarios, 3 personas | 16 | 19 | 0 | -- |
| `consent` | 1 | 0/17 (0.00%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 24/24 (100.00%) across 12 scenarios, 5 personas | 0/16 (0.00%) across 9 scenarios, 3 personas | 16 | 19 | 0 | yes |
| `data_quality` | 0 | 0/17 (0.00%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 24/24 (100.00%) across 12 scenarios, 5 personas | 0/16 (0.00%) across 9 scenarios, 3 personas | 16 | 19 | 0 | **no -- removing it changes nothing on this set** |
| `confidence` | 0 | 0/17 (0.00%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 24/24 (100.00%) across 12 scenarios, 5 personas | 0/16 (0.00%) across 9 scenarios, 3 personas | 16 | 19 | 0 | **no -- removing it changes nothing on this set** |
| `rain_context` | 2 | 2/17 (11.76%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 22/22 (100.00%) across 10 scenarios, 5 personas | 2/18 (11.11%) across 10 scenarios, 3 personas | 18 | 19 | 0 | yes |
| `severity_persistence` | 0 | 0/17 (0.00%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 24/24 (100.00%) across 12 scenarios, 5 personas | 0/16 (0.00%) across 9 scenarios, 3 personas | 16 | 19 | 0 | **no -- removing it changes nothing on this set** |
| `interpretable_scale` | 0 | 0/17 (0.00%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 24/24 (100.00%) across 12 scenarios, 5 personas | 0/16 (0.00%) across 9 scenarios, 3 personas | 16 | 19 | 0 | **no -- removing it changes nothing on this set** |
| `contact_cap` | 3 | 0/17 (0.00%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 21/21 (100.00%) across 10 scenarios, 3 personas | 0/19 (0.00%) across 9 scenarios, 3 personas | 19 | 19 | 3 | yes |

Gate meanings:

- `consent` -- Inactive consent blocks every outreach decision (SUPPRESS).
- `data_quality` -- Wear-time below the 8h minimum yields an audited NO_ACTION.
- `confidence` -- Baseline/wear coverage below 0.45 confidence yields NO_ACTION.
- `rain_context` -- Rain suppresses a dip that has not yet persisted two valid-wear days.
- `severity_persistence` -- A dip must be at least 20% below the personal median before any contact is permitted (ablation: any dip below the median becomes contact-eligible).
- `interpretable_scale` -- A baseline too small for a percentage to mean anything yields NO_ACTION.
- `contact_cap` -- At most two contacts per rolling week; the third is SUPPRESSed.

### Context-dependent restraint -- core set

M10 context-dependent restraint. Denominator: every step Care+ (all gates on) decided `NO_ACTION`. Numerator: of those, how many become a `CONTACT` or `COORDINATOR_REVIEW` decision once the rain-context gate alone is switched off (`silverloop_no_rain_context`, the same ablation arm as the table above). This is the one restraint metric that does not read the scenario's ground-truth label: it asks how much of Care+'s silence is actually load-bearing on the rain explanation specifically, as opposed to some other gate (confidence, persistence, the interpretable-scale floor) that would have kept it quiet regardless. A low rate here does not mean the rain gate is useless -- it means most of the reference's `NO_ACTION`s on this set have another sufficient reason to stay quiet, which the ablation table's `steps changed` / `outreach unblocked` split above already shows directly.

M10: 2/20 (10.00%) across 9 scenarios, 3 personas

### Gate ablation -- holdout set

Each row switches off exactly one gate of a transcription of the ladder that lives inside the evaluation package (`evaluation/ladder.py`); `policy.py` is never edited or patched. The reference row is that transcription with every gate ON, and the test suite asserts it is decision-for-decision identical to `silverloop.policy.decide`, so any delta below is attributable to the disabled gate. Ablations run harness-uncapped, otherwise switching off the contact-cap gate would be invisible.

| Disabled gate | Steps decided differently | M1 unnecessary contact | M2 missed persistent change | M8 unsupported restraint | M4 no-action logging integrity | M6 unwarranted share | Contacts | Escalations | M5 violations | Load-bearing here? |
|---|---|---|---|---|---|---|---|---|---|---|
| _(reference: all gates on)_ | -- | 3/12 (25.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 14/14 (100.00%) across 5 scenarios, 4 personas | 2/6 (33.33%) across 4 scenarios, 3 personas | 6 | 2 | 0 | -- |
| `consent` | 2 | 3/12 (25.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 13/13 (100.00%) across 5 scenarios, 4 personas | 2/6 (33.33%) across 4 scenarios, 3 personas | 6 | 3 | 1 | yes |
| `data_quality` | 0 | 3/12 (25.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 14/14 (100.00%) across 5 scenarios, 4 personas | 2/6 (33.33%) across 4 scenarios, 3 personas | 6 | 2 | 0 | **no -- removing it changes nothing on this set** |
| `confidence` | 0 | 3/12 (25.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 14/14 (100.00%) across 5 scenarios, 4 personas | 2/6 (33.33%) across 4 scenarios, 3 personas | 6 | 2 | 0 | **no -- removing it changes nothing on this set** |
| `rain_context` | 1 | 4/12 (33.33%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 13/13 (100.00%) across 4 scenarios, 4 personas | 3/7 (42.86%) across 4 scenarios, 3 personas | 7 | 2 | 0 | yes |
| `severity_persistence` | 3 | 4/12 (33.33%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 13/13 (100.00%) across 5 scenarios, 4 personas | 3/7 (42.86%) across 4 scenarios, 3 personas | 7 | 2 | 0 | yes |
| `interpretable_scale` | 0 | 3/12 (25.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 14/14 (100.00%) across 5 scenarios, 4 personas | 2/6 (33.33%) across 4 scenarios, 3 personas | 6 | 2 | 0 | **no -- removing it changes nothing on this set** |
| `contact_cap` | 2 | 3/12 (25.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 12/12 (100.00%) across 5 scenarios, 4 personas | 2/8 (25.00%) across 4 scenarios, 3 personas | 8 | 2 | 2 | yes |

Gate meanings:

- `consent` -- Inactive consent blocks every outreach decision (SUPPRESS).
- `data_quality` -- Wear-time below the 8h minimum yields an audited NO_ACTION.
- `confidence` -- Baseline/wear coverage below 0.45 confidence yields NO_ACTION.
- `rain_context` -- Rain suppresses a dip that has not yet persisted two valid-wear days.
- `severity_persistence` -- A dip must be at least 20% below the personal median before any contact is permitted (ablation: any dip below the median becomes contact-eligible).
- `interpretable_scale` -- A baseline too small for a percentage to mean anything yields NO_ACTION.
- `contact_cap` -- At most two contacts per rolling week; the third is SUPPRESSed.

### Context-dependent restraint -- holdout set

M10 context-dependent restraint. Denominator: every step Care+ (all gates on) decided `NO_ACTION`. Numerator: of those, how many become a `CONTACT` or `COORDINATOR_REVIEW` decision once the rain-context gate alone is switched off (`silverloop_no_rain_context`, the same ablation arm as the table above). This is the one restraint metric that does not read the scenario's ground-truth label: it asks how much of Care+'s silence is actually load-bearing on the rain explanation specifically, as opposed to some other gate (confidence, persistence, the interpretable-scale floor) that would have kept it quiet regardless. A low rate here does not mean the rain gate is useless -- it means most of the reference's `NO_ACTION`s on this set have another sufficient reason to stay quiet, which the ablation table's `steps changed` / `outreach unblocked` split above already shows directly.

M10: 1/10 (10.00%) across 4 scenarios, 4 personas

### Verdict per gate

`steps changed` counts replayed steps this ablation decided differently from the all-gates-on reference. `outreach unblocked` counts how many MORE contacts or escalations it produced. The two differ, and the difference matters: a gate that only changes which quiet decision is recorded has not been shown to prevent anything.

| Gate | steps changed (core) | steps changed (holdout) | outreach unblocked (core) | outreach unblocked (holdout) | Verdict |
|---|---|---|---|---|---|
| `consent` | 1 | 2 | 0 | 1 | prevents outreach on holdout only |
| `data_quality` | 0 | 0 | 0 | 0 | **no measurable effect on any scenario in either set** |
| `confidence` | 0 | 0 | 0 | 0 | **no measurable effect on any scenario in either set** |
| `rain_context` | 2 | 1 | 2 | 1 | prevents outreach on both sets |
| `severity_persistence` | 0 | 3 | 0 | 1 | prevents outreach on holdout only |
| `interpretable_scale` | 0 | 0 | 0 | 0 | **no measurable effect on any scenario in either set** |
| `contact_cap` | 3 | 2 | 3 | 2 | prevents outreach on both sets |

Neither result means a gate is useless, and neither is a licence to delete a safety gate. Both mean the gate is **masked** on this evidence base: some other gate independently blocks every step that would have exercised it. Gates in that position here: `data_quality`, `confidence`, `interpretable_scale`.

## Threshold sensitivity

### Universal-threshold sensitivity -- core set

`fixed_threshold` acts when `steps < 3000`, and Mr Ravi's seeded baseline is ~2,400 steps a day, so he fails that line by construction. Reporting only that would beg the question, so the threshold is swept instead. If any single cut point left Mr Ravi alone AND still caught a real decline, the "personal baseline beats a universal threshold" claim would be false; the per-person columns are where to check. Uncapped on purpose -- a budget would truncate over-contacting at low thresholds and hide it.

| Threshold (steps) | Contacts | M1 unnecessary contact | M2 missed persistent change | contacts: `mdm-devi` | contacts: `mdm-lim` | contacts: `mdm-siti` | contacts: `mr-ravi` | contacts: `mr-tan` |
|---|---|---|---|---|---|---|---|---|
| 2000 | 4 | 0/17 (0.00%) across 8 scenarios, 3 personas | 19/19 (100.00%) across 4 scenarios, 2 personas | 0 (0 unwarranted) | 2 (0 unwarranted) | 2 (0 unwarranted) | 0 (0 unwarranted) | 0 (0 unwarranted) |
| 2500 | 4 | 0/17 (0.00%) across 8 scenarios, 3 personas | 19/19 (100.00%) across 4 scenarios, 2 personas | 0 (0 unwarranted) | 2 (0 unwarranted) | 2 (0 unwarranted) | 0 (0 unwarranted) | 0 (0 unwarranted) |
| 3000 | 37 | 5/17 (29.41%) across 8 scenarios, 3 personas | 1/19 (5.26%) across 4 scenarios, 2 personas | 3 (0 unwarranted) | 24 (0 unwarranted) | 2 (0 unwarranted) | 5 (5 unwarranted) | 3 (0 unwarranted) |
| 3500 | 48 | 7/17 (41.18%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 4 (0 unwarranted) | 34 (2 unwarranted) | 2 (0 unwarranted) | 5 (5 unwarranted) | 3 (0 unwarranted) |
| 4000 | 48 | 7/17 (41.18%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 4 (0 unwarranted) | 34 (2 unwarranted) | 2 (0 unwarranted) | 5 (5 unwarranted) | 3 (0 unwarranted) |
| 4500 | 49 | 7/17 (41.18%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 4 (0 unwarranted) | 35 (2 unwarranted) | 2 (0 unwarranted) | 5 (5 unwarranted) | 3 (0 unwarranted) |
| 5000 | 49 | 7/17 (41.18%) across 8 scenarios, 3 personas | 0/19 (0.00%) across 4 scenarios, 2 personas | 4 (0 unwarranted) | 35 (2 unwarranted) | 2 (0 unwarranted) | 5 (5 unwarranted) | 3 (0 unwarranted) |

### Universal-threshold sensitivity -- holdout set

`fixed_threshold` acts when `steps < 3000`, and Mr Ravi's seeded baseline is ~2,400 steps a day, so he fails that line by construction. Reporting only that would beg the question, so the threshold is swept instead. If any single cut point left Mr Ravi alone AND still caught a real decline, the "personal baseline beats a universal threshold" claim would be false; the per-person columns are where to check. Uncapped on purpose -- a budget would truncate over-contacting at low thresholds and hide it.

| Threshold (steps) | Contacts | M1 unnecessary contact | M2 missed persistent change | contacts: `mdm-devi` | contacts: `mdm-lim` | contacts: `mdm-siti` | contacts: `mr-ravi` |
|---|---|---|---|---|---|---|---|
| 2000 | 2 | 0/12 (0.00%) across 4 scenarios, 4 personas | 1/1 (100.00%) across 1 scenario, 1 persona | 0 (0 unwarranted) | 1 (0 unwarranted) | 1 (0 unwarranted) | 0 (0 unwarranted) |
| 2500 | 2 | 0/12 (0.00%) across 4 scenarios, 4 personas | 1/1 (100.00%) across 1 scenario, 1 persona | 0 (0 unwarranted) | 1 (0 unwarranted) | 1 (0 unwarranted) | 0 (0 unwarranted) |
| 3000 | 14 | 6/12 (50.00%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 4 (0 unwarranted) | 3 (0 unwarranted) | 4 (3 unwarranted) | 3 (3 unwarranted) |
| 3500 | 20 | 10/12 (83.33%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 5 (0 unwarranted) | 7 (3 unwarranted) | 4 (3 unwarranted) | 4 (4 unwarranted) |
| 4000 | 20 | 10/12 (83.33%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 5 (0 unwarranted) | 7 (3 unwarranted) | 4 (3 unwarranted) | 4 (4 unwarranted) |
| 4500 | 20 | 10/12 (83.33%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 5 (0 unwarranted) | 7 (3 unwarranted) | 4 (3 unwarranted) | 4 (4 unwarranted) |
| 5000 | 20 | 10/12 (83.33%) across 4 scenarios, 4 personas | 0/1 (0.00%) across 1 scenario, 1 persona | 5 (0 unwarranted) | 7 (3 unwarranted) | 4 (3 unwarranted) | 4 (4 unwarranted) |

## Per-persona comparison (core set, uncapped arm)

Same metrics as above, scored separately for each seeded persona -- the population-wide table can hide a discriminator that only shows up for one person's own baseline (see `mr-ravi`, playbook demo purpose: defeat a universal step threshold). Read this table next to the threshold sweep, not on its own.

### Mdm Lim (`mdm-lim`, playbook persona)

Playbook primary persona. 29-day fixture (28 history + 1 current), unchanged since before F5 -- see the F5 compatibility note in docs/testing.md.

| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | M3 missed escalation | M4 no-action logging integrity | M6 unwarranted share of contacts made | M5 violations (steps) |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 44 | 0/11 (0.00%) across 6 scenarios, 1 persona | 1/18 (5.56%) across 3 scenarios, 1 persona | 18/18 (100.00%) across 3 scenarios, 1 persona | 0/20 (0.00%) across 9 scenarios, 1 persona | 0/24 (0.00%) across 6 scenarios, 1 persona | 44 (24 step(s)) |
| `contextual_rule` | 44 | 0/11 (0.00%) across 6 scenarios, 1 persona | 6/18 (33.33%) across 3 scenarios, 1 persona | 18/18 (100.00%) across 3 scenarios, 1 persona | 6/27 (22.22%) across 11 scenarios, 1 persona | 0/17 (0.00%) across 4 scenarios, 1 persona | 27 (17 step(s)) |
| `silverloop` | 44 | 0/11 (0.00%) across 6 scenarios, 1 persona | 0/18 (0.00%) across 3 scenarios, 1 persona | 0/18 (0.00%) across 3 scenarios, 1 persona | 14/14 (100.00%) across 8 scenarios, 1 persona | 0/12 (0.00%) across 7 scenarios, 1 persona | 0 (0 step(s)) |

### Mr Ravi (`mr-ravi`, playbook persona)

Playbook primary persona: low but stable baseline, knee discomfort disclosed. Demo purpose: defeat a universal fixed step threshold (playbook §2).

| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | M3 missed escalation | M4 no-action logging integrity | M6 unwarranted share of contacts made | M5 violations (steps) |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 5 | 5/5 (100.00%) across 1 scenario, 1 persona | 0/0 (n/a) | 0/0 (n/a) | 0/0 (n/a) | 5/5 (100.00%) across 1 scenario, 1 persona | 8 (5 step(s)) |
| `contextual_rule` | 5 | 5/5 (100.00%) across 1 scenario, 1 persona | 0/0 (n/a) | 0/0 (n/a) | 0/0 (n/a) | 5/5 (100.00%) across 1 scenario, 1 persona | 8 (5 step(s)) |
| `silverloop` | 5 | 0/5 (0.00%) across 1 scenario, 1 persona | 0/0 (n/a) | 0/0 (n/a) | 5/5 (100.00%) across 1 scenario, 1 persona | 0/0 (n/a) | 0 (0 step(s)) |

### Mr Tan (`mr-tan`, SYNTHETIC, not playbook)

SYNTHETIC -- not in the product playbook; no research or interview basis. Invented to demonstrate the weekly contact-fatigue cap: repeated mild dips draw repeated contact from an uncapped baseline policy, which Care+ suppresses.

| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | M3 missed escalation | M4 no-action logging integrity | M6 unwarranted share of contacts made | M5 violations (steps) |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 3 | 0/0 (n/a) | 0/0 (n/a) | 0/0 (n/a) | 0/0 (n/a) | 0/3 (0.00%) across 1 scenario, 1 persona | 4 (3 step(s)) |
| `contextual_rule` | 3 | 0/0 (n/a) | 0/0 (n/a) | 0/0 (n/a) | 0/0 (n/a) | 0/3 (0.00%) across 1 scenario, 1 persona | 4 (3 step(s)) |
| `silverloop` | 3 | 0/0 (n/a) | 0/0 (n/a) | 0/0 (n/a) | 1/1 (100.00%) across 1 scenario, 1 persona | 0/2 (0.00%) across 1 scenario, 1 persona | 0 (0 step(s)) |

### Mdm Devi (`mdm-devi`, SYNTHETIC, not playbook)

SYNTHETIC -- not in the product playbook; no research or interview basis. Invented to give the evaluation harness a second, independent persistent-decline case (playbook required scenario #4: gradual multi-week decline) so M2/M3 are not measured on a single data point.

| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | M3 missed escalation | M4 no-action logging integrity | M6 unwarranted share of contacts made | M5 violations (steps) |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 4 | 0/0 (n/a) | 0/1 (0.00%) across 1 scenario, 1 persona | 1/1 (100.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 0/3 (0.00%) across 1 scenario, 1 persona | 4 (3 step(s)) |
| `contextual_rule` | 4 | 0/0 (n/a) | 0/1 (0.00%) across 1 scenario, 1 persona | 1/1 (100.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 0/3 (0.00%) across 1 scenario, 1 persona | 4 (3 step(s)) |
| `silverloop` | 4 | 0/0 (n/a) | 0/1 (0.00%) across 1 scenario, 1 persona | 0/1 (0.00%) across 1 scenario, 1 persona | 1/1 (100.00%) across 1 scenario, 1 persona | 0/2 (0.00%) across 1 scenario, 1 persona | 0 (0 step(s)) |

### Mdm Siti (`mdm-siti`, playbook persona)

Playbook primary persona: irregular sync, limited smartphone use. Demo purpose: data-quality discrimination -- low tracker adherence must yield audited NO_ACTION, never an inference from missing data.

| Policy | Sample size | M1 unnecessary contact | M2 missed persistent change | M3 missed escalation | M4 no-action logging integrity | M6 unwarranted share of contacts made | M5 violations (steps) |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 3 | 0/1 (0.00%) across 1 scenario, 1 persona | 0/0 (n/a) | 0/0 (n/a) | 0/1 (0.00%) across 1 scenario, 1 persona | 0/2 (0.00%) across 1 scenario, 1 persona | 6 (2 step(s)) |
| `contextual_rule` | 3 | 0/1 (0.00%) across 1 scenario, 1 persona | 0/0 (n/a) | 0/0 (n/a) | 2/3 (66.67%) across 1 scenario, 1 persona | 0/0 (n/a) | 0 (0 step(s)) |
| `silverloop` | 3 | 0/1 (0.00%) across 1 scenario, 1 persona | 0/0 (n/a) | 0/0 (n/a) | 3/3 (100.00%) across 1 scenario, 1 persona | 0/0 (n/a) | 0 (0 step(s)) |

## Hard violations by type (M5 breakdown)

Budget-matched arm first. `contact_cap_breach` is structurally zero there for every policy, because the harness enforces the budget -- which is exactly why the uncapped column beside it must not be read as a judgement score.

| Policy | Arm | unconsented_outreach | unsafe_data_action | low_confidence_action | unexplained_action | contact_cap_breach | forbidden_action |
|---|---|---|---|---|---|---|---|
| `fixed_threshold` | capped | 1 | 4 | 4 | 21 | 0 | 0 |
| `contextual_rule` | capped | 0 | 0 | 0 | 15 | 0 | 0 |
| `silverloop` | capped | 0 | 0 | 0 | 0 | 0 | 0 |
| `fixed_threshold` | uncapped | 1 | 4 | 4 | 37 | 20 | 0 |
| `contextual_rule` | uncapped | 0 | 0 | 0 | 28 | 15 | 0 |
| `silverloop` | uncapped | 0 | 0 | 0 | 0 | 0 | 0 |

## Burden

### Burden -- core set, budget-matched

**What the policy cost, as opposed to whether it was right.** Two policies can reach identical M1 and M2 and still differ in whether their contacts arrived on four consecutive mornings or spread across a month, and in whether one coordinator concern cost one escalation or sixteen. `contact_volume` alone is blind to both, so each burden number carries its denominator.

- `contacts_per_person_week` -- contacts over the person-weeks actually replayed. One replayed step is one of the person's simulated days, so a 9-event scenario is 9 person-days.
- `max_consecutive_contact_days` -- the longest unbroken run of contacted days inside a single scenario, with the scenario named. Runs never cross a scenario boundary: two scenarios are two different weeks of two possibly different people.
- `escalations_per_case` -- escalation DECISIONS per escalation EPISODE, an episode being a maximal run of escalations on consecutive simulated days. This is the harness's stand-in for the product's rule that a case is refreshed rather than duplicated; anything above 1.0 is the coordinator-side cost of re-raising a concern already raised.

| Policy | Contacts per person-week | Longest run of contacted days | Escalations per case |
|---|---|---|---|
| `fixed_threshold` | 21 contacts / 8.43 person-weeks (2.49 per person-week) | 2 (`14_baseline_drift`) | 0/0 (no escalation episode) |
| `contextual_rule` | 15 contacts / 8.43 person-weeks (1.78 per person-week) | 2 (`14_baseline_drift`) | 0/0 (no escalation episode) |
| `silverloop` | 16 contacts / 8.43 person-weeks (1.90 per person-week) | 2 (`15_contact_cap_counts_simulated_days`) | 19/4 (4.75 per case) across 4 scenarios, 2 personas |

### Burden -- holdout set, budget-matched

**What the policy cost, as opposed to whether it was right.** Two policies can reach identical M1 and M2 and still differ in whether their contacts arrived on four consecutive mornings or spread across a month, and in whether one coordinator concern cost one escalation or sixteen. `contact_volume` alone is blind to both, so each burden number carries its denominator.

- `contacts_per_person_week` -- contacts over the person-weeks actually replayed. One replayed step is one of the person's simulated days, so a 9-event scenario is 9 person-days.
- `max_consecutive_contact_days` -- the longest unbroken run of contacted days inside a single scenario, with the scenario named. Runs never cross a scenario boundary: two scenarios are two different weeks of two possibly different people.
- `escalations_per_case` -- escalation DECISIONS per escalation EPISODE, an episode being a maximal run of escalations on consecutive simulated days. This is the harness's stand-in for the product's rule that a case is refreshed rather than duplicated; anything above 1.0 is the coordinator-side cost of re-raising a concern already raised.

| Policy | Contacts per person-week | Longest run of contacted days | Escalations per case |
|---|---|---|---|
| `fixed_threshold` | 8 contacts / 3.14 person-weeks (2.55 per person-week) | 2 (`h03_consent_revoked_mid_decline`) | 0/0 (no escalation episode) |
| `contextual_rule` | 7 contacts / 3.14 person-weeks (2.23 per person-week) | 2 (`h02_low_baseline_under_rain`) | 0/0 (no escalation episode) |
| `silverloop` | 6 contacts / 3.14 person-weeks (1.91 per person-week) | 2 (`h03_consent_revoked_mid_decline`) | 2/2 (1.00 per case) across 2 scenarios, 2 personas |

## Follow-through

**`accepted` means "show me more" and nothing else.** The product records that distinction everywhere; the policy harness was not measuring it at all, so a policy producing twenty taps and no attendance scored identically to one producing two attendances. Each stage is `n/d` of the stage BEFORE it, never a share of the top.

The `outcomes:` block is authored per scenario, one optional entry per event, and says what the person does IF contacted on that day -- a counterfactual fact about them, in the same spirit as `world:`, not a record of what any policy did. That is what keeps this from scoring Care+ against its own output. A step nobody contacted never enters the denominator, so a quieter policy offers less and is measured on less; a contact made on a day with no authored outcome is counted separately as an unauthored offer, because an unauthored day is missing data and treating it as silence would invent a refusal.

### Follow-through funnel -- core set, budget-matched

2 of 15 scenario(s) in this set author an `outcomes:` block: `05_sustained_decline`, `15_contact_cap_counts_simulated_days`. **These denominators are small on purpose and must be read as such** -- the funnel is a working measurement over a handful of authored days, not yet a finding about how people respond to outreach.

| Policy | Offered (unauthored) | Coverage | Responded | Accepted | Silence | Followed up | Attended | Enjoyed |
|---|---|---|---|---|---|---|---|---|
| `fixed_threshold` | 3 (18) | 2 scenario(s), 1 persona(s) | 2/3 (66.67%) | 1/3 (33.33%) | 1/3 (33.33%) | 1/1 (100.00%) | 0/1 (0.00%) | 0/0 (n/a) |
| `contextual_rule` | 3 (12) | 2 scenario(s), 1 persona(s) | 2/3 (66.67%) | 1/3 (33.33%) | 1/3 (33.33%) | 1/1 (100.00%) | 0/1 (0.00%) | 0/0 (n/a) |
| `silverloop` | 5 (11) | 2 scenario(s), 1 persona(s) | 2/5 (40.00%) | 2/5 (40.00%) | 3/5 (60.00%) | 2/2 (100.00%) | 1/2 (50.00%) | 1/1 (100.00%) |

### Follow-through funnel -- holdout set, budget-matched

No scenario in this set authors an `outcomes:` block, so every stage below would read `0/0`. The funnel is defined and executable (`evaluation/funnel.py`); it has no data here, and that is reported rather than filled in.

## Context (core set)

| Policy | Arm | Contact volume | Human review count | no_action | gentle_nudge | programme_suggestion | coordinator_review | suppress |
|---|---|---|---|---|---|---|---|---|
| `fixed_threshold` | capped | 21 | 0 | 22 | 21 | 0 | 0 | 16 |
| `contextual_rule` | capped | 15 | 0 | 30 | 7 | 8 | 0 | 14 |
| `silverloop` | capped | 16 | 19 | 20 | 11 | 5 | 19 | 4 |
| `fixed_threshold` | uncapped | 37 | 0 | 22 | 37 | 0 | 0 | 0 |
| `contextual_rule` | uncapped | 28 | 0 | 30 | 7 | 21 | 0 | 1 |
| `silverloop` | uncapped | 16 | 19 | 20 | 11 | 5 | 19 | 4 |

## Soft counters (reported, not gated)

| Policy | consent_not_recorded (core, budget-matched) |
|---|---|
| `fixed_threshold` | 1 |
| `contextual_rule` | 0 |
| `silverloop` | 0 |

## Not measured, and why

- **Device-failure discrimination**: There is no `DEVICE_TASK` member in `Decision`; adding one would change the OpenAPI contract, which is out of scope for this harness.
- **Intervention-adaptation rate**: Requires `learning.py` and recorded outcomes inside the replay loop, which this harness does not run.
- **Event-to-decision latency**: A wall-clock measurement; introducing it would break the harness's determinism.
- **Tool-failure recovery**: Requires the agent/tool-calling layer, which sits outside the deterministic policy boundary this harness evaluates.
- **Message wording quality**: The harness never calls the LLM planner. The comparison is about the policy ladder, so the planner is excluded to keep every number reproducible from a frozen seed.

