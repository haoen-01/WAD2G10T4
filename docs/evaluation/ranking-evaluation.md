# Care+ activity-ranking evaluation

**NOT_USER_TRUTH: every persona, listing and observation trace in this benchmark is a synthetic design artefact authored for this evaluation. No row here is, or is derived from, a real senior's data, preferences or history. Graded relevance is assigned by a documented rule applied to an authored persona BRIEF the ranker never sees (see `dataset.py`'s module docstring); it is a labelling convention, not a fact about anyone.**

Each of the 6 query templates is run against every persona in the split, producing one 'case'. The ranker sees only an OBSERVATION TRACE (declines with reasons, enjoyment reports, interest taps, occasional stated preferences) folded through the production `apply_decline`/`apply_enjoyment`/`ActivityEngagement`; graded relevance (0-3) is assigned from the persona's separate, richer BRIEF (hard constraints, stated tastes, stated avoids, decline history) that the ranker never receives. Two metrics that were true by construction are no longer reported here at all: `constraint_satisfaction@3` was `1.0 if top else 0.0` (because `filter_candidates` removes every hard-constraint violation before anything is graded or ranked) and `series_duplication_rate@3` was 0.0000 (because `_dedupe_series` always runs). Both are now unit tests on `activity_search` itself, where a regression would actually fail something. The headline family is `NDCG@1`, `HitRate@3 (rel=3)` and `slate_ndcg@3`, whose ideal is computed under the product's own one-per-category slate rule so a within-margin variety swap is not scored as a loss; graded `NDCG@3` is kept in the technical table. `P@3` and `MRR` count a grade-3 TASTE MATCH as relevant, not the neutral grade 2: 77.8% of the core kept pool grades >=2, so the old `P@3 (rel>=2)` measured pool composition. `context_rule_conformance@3` is a SEPARATE metric from `NDCG@3` (relevance), not a variant of it: relevance asks whether a listing suits what the persona asked for and has liked before, graded from a persona brief that is never told about the weather; `context_rule_conformance@3` asks whether the ranker's top-3 matches a declared rain/environment rule (`context_labels.py`). That rule intentionally restates the SAME premise `activity_search.py`'s own `context` factor encodes, so this metric is an implementation-conformance check -- it shows the factor is wired and behaves as declared -- NOT an independent judgement of whether that rule is a good idea, and its `no_context` delta must not be read as evidence for or against the rain nudge itself. See docs/adr/0003-relevance-vs-context-appropriateness.md.

Generator version: `1.0.0` · Seed: `20260908` · Dataset digest: `34adab71f123746c…` · Weights digest: `52cf7aada06a2033…` · Holdout digest: `30b55f64a79f6af4…` · holdout_frozen: `true`

Catalogue: 60 listings · 10 core / 4 holdout personas · 6 query templates.

Core and holdout are reported separately and never pooled: holdout personas were never consulted while any ranking factor, weight or this dataset's own design was built. `holdout_frozen` says whether those four persona briefs still hash to the digest they were frozen at (`dataset.HOLDOUT_FROZEN_DIGEST`); a change to them is not forbidden, it is visible, and a genuine change belongs in a new set rather than under these numbers.

## Headline: full ranker vs reference lines

### Core set (60 cases, 10 personas)

**Headline lift, paired and persona-clustered.** Both arms are measured on the same cases with the same grade table and the same kept pool, so the difference is paired; and six cases share one persona, so personas -- not cases -- are what is resampled. Comparing two marginal CIs instead is the wrong test.

| `full` minus | NDCG@3 delta |
|---|---|
| `random` | +0.1752 [+0.0914, +0.2552] (n=60, n_clusters=10; excludes 0) |
| `catalogue_order` | +0.1662 [+0.0388, +0.2930] (n=60, n_clusters=10; excludes 0) |
| `intent_filter_static` | +0.1599 [+0.0332, +0.2942] (n=60, n_clusters=10; excludes 0) |
| `oracle` | -0.2076 [-0.3323, -0.0966] (n=60, n_clusters=10; excludes 0) |

| Stratum | personas | `full` | `random` | lift |
|---|---|---|---|---|
| `stated` | `eval-mr-goh`, `eval-mr-yusof` | 0.9002 [0.8005, 1.0000] (n=12, n_clusters=2) | 0.6636 [0.6183, 0.7089] (n=12, n_clusters=2) | +0.2366 [+0.1821, +0.2911] (n=12, n_clusters=2; excludes 0) |
| `inferred_only` | `eval-mdm-tan`, `eval-mdm-lee`, `eval-mr-ong`, `eval-mdm-siti`, `eval-mr-koh`, `eval-mdm-fatimah`, `eval-mr-tan-wc`, `eval-mdm-nora` | 0.7655 [0.6180, 0.8927] (n=48, n_clusters=8) | 0.6056 [0.4656, 0.7491] (n=48, n_clusters=8) | +0.1599 [+0.0555, +0.2582] (n=48, n_clusters=8; excludes 0) |

**The number to quote is the `inferred_only` one: +0.1599 [+0.0555, +0.2582] (n=48, n_clusters=8; excludes 0).** A `stated` persona hands the ranker, verbatim, one of the exact `(dimension, value)` pairs the grader reads from her brief, so her cases measure "obey what the person just told you" rather than "infer taste from behaviour". Both are real product behaviour; only the second is what this benchmark claims to measure. `eval-mr-koh` states the same SOCIAL fact from the opposite pole (`solo` stated against a `social` hard avoid) and is counted as inferred-only here -- on the wider reading the stated stratum is one persona larger.

**Per persona.** A macro mean hides its own worst case; these are the cases.

| Persona | cases | stated? | full NDCG@3 | random NDCG@3 | lift |
|---|---|---|---|---|---|
| `eval-mdm-tan` | 6 | no | 0.3648 | 0.3843 | -0.0195 |
| `eval-mr-goh` | 6 | yes | 0.8005 | 0.6183 | +0.1822 |
| `eval-mdm-lee` | 6 | no | 1.0000 | 0.8317 | +0.1683 |
| `eval-mr-ong` | 6 | no | 0.7206 | 0.5049 | +0.2157 |
| `eval-mdm-siti` | 6 | no | 1.0000 | 0.9545 | +0.0455 |
| `eval-mr-koh` | 6 | no | 0.6594 | 0.3217 | +0.3377 |
| `eval-mdm-fatimah` | 6 | no | 0.9135 | 0.5600 | +0.3535 |
| `eval-mr-tan-wc` | 6 | no | 0.6171 | 0.6741 | -0.0570 |
| `eval-mdm-nora` | 6 | no | 0.8484 | 0.6137 | +0.2347 |
| `eval-mr-yusof` | 6 | yes | 1.0000 | 0.7089 | +0.2911 |

2 of 10 personas score BELOW a random shuffle here: `eval-mdm-tan`, `eval-mr-tan-wc`.

**Learning curve.** The same persona, catalogue, query and grade table at every point; the only thing that varies is how many observation-trace events the ranker has been given. `cold_start` is the day a person signs up -- no learned preference and no engagement history, so only `intent`, `context` and `friction` are doing anything.

| Arm | trace events | NDCG@1 | HitRate@3 | NDCG@3 | lift over random |
|---|---|---|---|---|---|
| `cold_start` | 0 | 0.6214 | 0.3667 | 0.6327 | +0.0155 [-0.0241, +0.0586] (n=60, n_clusters=10; **includes 0**) |
| `first_signal` | 1 | 0.8143 | 0.5500 | 0.7735 | +0.1563 [+0.0796, +0.2272] (n=60, n_clusters=10; excludes 0) |
| `trace_prefix:1` | 1 | 0.8143 | 0.5500 | 0.7735 | +0.1563 [+0.0796, +0.2272] (n=60, n_clusters=10; excludes 0) |
| `trace_prefix:3` | 3 | 0.8500 | 0.5500 | 0.7924 | +0.1752 [+0.0914, +0.2552] (n=60, n_clusters=10; excludes 0) |
| `trace_prefix:5` | 5 | 0.8500 | 0.5500 | 0.7924 | +0.1752 [+0.0914, +0.2552] (n=60, n_clusters=10; excludes 0) |
| `full` | all | 0.8500 | 0.5500 | 0.7924 | +0.1752 [+0.0914, +0.2552] (n=60, n_clusters=10; excludes 0) |

**`cases_to_beat_random`: 1.** That many observation-trace events are needed before the paired, persona-clustered CI over the random floor excludes zero.

The longest trace in this split is 3 event(s), so every prefix length above that is the full trace under another name and the curve is flat there by construction -- not evidence that more evidence would not help. `first_signal` and `trace_prefix:1` are the same manipulation under two names and must agree exactly.

| Metric | full | random (20 draws) | catalogue-order | intent_filter+static | oracle |
|---|---|---|---|---|---|
| NDCG@1 (is the best thing first) | 0.8500 [0.7762, 0.9190] (n=60) | 0.5873 [0.5264, 0.6530] (n=60) | 0.5865 [0.4984, 0.6770] (n=60) | 0.5762 [0.4762, 0.6714] (n=60) | 1.0000 [1.0000, 1.0000] (n=60) |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | 0.5500 [0.4333, 0.6833] (n=60) | 0.3367 [0.2558, 0.4258] (n=60) | 0.2667 [0.1667, 0.3833] (n=60) | 0.2333 [0.1333, 0.3500] (n=60) | 0.7500 [0.6333, 0.8667] (n=60) |
| slate_ndcg@3 (ideal under the one-per-category rule) | 0.8633 [0.8009, 0.9204] (n=60) | 0.6784 [0.6270, 0.7318] (n=60) | 0.6755 [0.6091, 0.7433] (n=60) | 0.6737 [0.5909, 0.7517] (n=60) | 1.0000 [1.0000, 1.0000] (n=60) |
| NDCG@3 | 0.7924 [0.7315, 0.8549] (n=60) | 0.6172 [0.5592, 0.6792] (n=60) | 0.6263 [0.5484, 0.7030] (n=60) | 0.6325 [0.5470, 0.7173] (n=60) | 1.0000 [1.0000, 1.0000] (n=60) |
| P@3 (taste match) | 0.3556 [0.2611, 0.4611] (n=60) | 0.1708 [0.1164, 0.2325] (n=60) | 0.1667 [0.0944, 0.2556] (n=60) | 0.2056 [0.1111, 0.3111] (n=60) | 0.6222 [0.5222, 0.7333] (n=60) |
| MRR (rel=3) | 0.5741 [0.4531, 0.6970] (n=60) | 0.2964 [0.2352, 0.3667] (n=60) | 0.2570 [0.1702, 0.3587] (n=60) | 0.2903 [0.2029, 0.3895] (n=60) | 0.7500 [0.6333, 0.8667] (n=60) |

The same rows with the CI resampled over PERSONAS rather than cases. Six cases share one persona's trace, preference store and grade table, so the per-case interval above is roughly 2.2x too narrow; this is the honest width.

| Metric | full | random (20 draws) | catalogue-order | intent_filter+static | oracle |
|---|---|---|---|---|---|
| NDCG@1 (is the best thing first) | 0.8500 [0.6976, 0.9714] (n=60, n_clusters=10) | 0.5873 [0.4724, 0.7118] (n=60, n_clusters=10) | 0.5865 [0.4357, 0.7524] (n=60, n_clusters=10) | 0.5762 [0.4167, 0.7476] (n=60, n_clusters=10) | 1.0000 [1.0000, 1.0000] (n=60, n_clusters=10) |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | 0.5500 [0.3333, 0.7333] (n=60, n_clusters=10) | 0.3367 [0.2158, 0.4775] (n=60, n_clusters=10) | 0.2667 [0.0667, 0.5000] (n=60, n_clusters=10) | 0.2333 [0.0500, 0.4500] (n=60, n_clusters=10) | 0.7500 [0.5667, 0.8833] (n=60, n_clusters=10) |
| slate_ndcg@3 (ideal under the one-per-category rule) | 0.8633 [0.7393, 0.9577] (n=60, n_clusters=10) | 0.6784 [0.5853, 0.7705] (n=60, n_clusters=10) | 0.6755 [0.5508, 0.8048] (n=60, n_clusters=10) | 0.6737 [0.5347, 0.8190] (n=60, n_clusters=10) | 1.0000 [1.0000, 1.0000] (n=60, n_clusters=10) |
| NDCG@3 | 0.7924 [0.6677, 0.9034] (n=60, n_clusters=10) | 0.6172 [0.5119, 0.7297] (n=60, n_clusters=10) | 0.6263 [0.4879, 0.7738] (n=60, n_clusters=10) | 0.6325 [0.4842, 0.7919] (n=60, n_clusters=10) | 1.0000 [1.0000, 1.0000] (n=60, n_clusters=10) |
| P@3 (taste match) | 0.3556 [0.1889, 0.5333] (n=60, n_clusters=10) | 0.1708 [0.0861, 0.2761] (n=60, n_clusters=10) | 0.1667 [0.0389, 0.3278] (n=60, n_clusters=10) | 0.2056 [0.0444, 0.4056] (n=60, n_clusters=10) | 0.6222 [0.4611, 0.7389] (n=60, n_clusters=10) |
| MRR (rel=3) | 0.5741 [0.3753, 0.7531] (n=60, n_clusters=10) | 0.2964 [0.2002, 0.4069] (n=60, n_clusters=10) | 0.2570 [0.0996, 0.4353] (n=60, n_clusters=10) | 0.2903 [0.1469, 0.4636] (n=60, n_clusters=10) | 0.7500 [0.5667, 0.8833] (n=60, n_clusters=10) |

**Discriminable cases: 51/60.** A case counts here when its ordering can change the headline metric at all -- when the best and the worst ordering of its kept pool score differently, which on this dataset is exactly the cases whose kept candidates do not all carry the same grade. The rest score identically under every ordering and drag the headline toward the pool's own composition. This stratum used to be defined as "holds a grade-3 AND something graded <=1", a much narrower rule justified by the same sentence: on core that dropped 21 of the 51 cases whose ordering demonstrably matters, on holdout 14 of 24, and it took whole personas out of the headline with them. The same rows over the discriminable cases only, persona-clustered:

| Metric | full | random (20 draws) | catalogue-order | intent_filter+static | oracle |
|---|---|---|---|---|---|
| NDCG@1 (is the best thing first) | 0.8235 [0.6600, 0.9650] (n=51, n_clusters=10) | 0.5144 [0.4287, 0.6122] (n=51, n_clusters=10) | 0.5135 [0.3810, 0.6698] (n=51, n_clusters=10) | 0.5014 [0.3693, 0.6696] (n=51, n_clusters=10) | 1.0000 [1.0000, 1.0000] (n=51, n_clusters=10) |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | 0.6078 [0.3846, 0.8085] (n=51, n_clusters=10) | 0.3569 [0.2402, 0.4990] (n=51, n_clusters=10) | 0.2745 [0.0755, 0.5306] (n=51, n_clusters=10) | 0.2353 [0.0556, 0.4706] (n=51, n_clusters=10) | 0.8431 [0.6889, 0.9592] (n=51, n_clusters=10) |
| slate_ndcg@3 (ideal under the one-per-category rule) | 0.8392 [0.7038, 0.9512] (n=51, n_clusters=10) | 0.6216 [0.5441, 0.6972] (n=51, n_clusters=10) | 0.6182 [0.5030, 0.7429] (n=51, n_clusters=10) | 0.6161 [0.4867, 0.7610] (n=51, n_clusters=10) | 1.0000 [1.0000, 1.0000] (n=51, n_clusters=10) |
| NDCG@3 | 0.7558 [0.6312, 0.8820] (n=51, n_clusters=10) | 0.5497 [0.4700, 0.6421] (n=51, n_clusters=10) | 0.5603 [0.4382, 0.7010] (n=51, n_clusters=10) | 0.5677 [0.4345, 0.7246] (n=51, n_clusters=10) | 1.0000 [1.0000, 1.0000] (n=51, n_clusters=10) |
| P@3 (taste match) | 0.3791 [0.2244, 0.5625] (n=51, n_clusters=10) | 0.1618 [0.0898, 0.2551] (n=51, n_clusters=10) | 0.1569 [0.0272, 0.3268] (n=51, n_clusters=10) | 0.2026 [0.0321, 0.4286] (n=51, n_clusters=10) | 0.6928 [0.5667, 0.8027] (n=51, n_clusters=10) |
| MRR (rel=3) | 0.6362 [0.4298, 0.8214] (n=51, n_clusters=10) | 0.3095 [0.2227, 0.4130] (n=51, n_clusters=10) | 0.2632 [0.1094, 0.4586] (n=51, n_clusters=10) | 0.3023 [0.1563, 0.5040] (n=51, n_clusters=10) | 0.8431 [0.6889, 0.9592] (n=51, n_clusters=10) |

| `full` minus (discriminable only) | NDCG@3 delta |
|---|---|
| `random` | +0.2061 [+0.1064, +0.2910] (n=51, n_clusters=10; excludes 0) |
| `catalogue_order` | +0.1955 [+0.0399, +0.3332] (n=51, n_clusters=10; excludes 0) |
| `intent_filter_static` | +0.1881 [+0.0348, +0.3264] (n=51, n_clusters=10; excludes 0) |
| `oracle` | -0.2442 [-0.3688, -0.1180] (n=51, n_clusters=10; excludes 0) |

| Metric | value (per-case CI) | value (persona-clustered CI) |
|---|---|---|
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | 0.9928 [0.9817, 1.0000] (n=60) | 0.9928 [0.9829, 1.0000] (n=60, n_clusters=10) |
| unknown_admitted@3 | 0.1278 [0.0778, 0.1889] (n=60) | 0.1278 [0.1000, 0.1500] (n=60, n_clusters=10) |
| category_entropy@3 | 1.3988 [1.2973, 1.4877] (n=60) | 1.3988 [1.2376, 1.5294] (n=60, n_clusters=10) |
| personalisation_divergence (clustered by unordered persona PAIR) | -- | 0.4733 [0.4188, 0.5225] (n=150, n_clusters=43) |
| reasons_grounded_rate (pooled) | 1455/1455 (100.00%) | -- |
| reasons_grounded_rate (macro-averaged per case, bootstrap CI) | 1.0000 [1.0000, 1.0000] (n=60) | -- |
| catalogue filler reason lines (not counted above) | 1 | -- |

### Holdout set (24 cases, 4 personas)

**Headline lift, paired and persona-clustered.** Both arms are measured on the same cases with the same grade table and the same kept pool, so the difference is paired; and six cases share one persona, so personas -- not cases -- are what is resampled. Comparing two marginal CIs instead is the wrong test.

| `full` minus | NDCG@3 delta |
|---|---|
| `random` | +0.1348 [-0.0003, +0.2700] (n=24, n_clusters=4; **includes 0**) |
| `catalogue_order` | +0.1193 [-0.0369, +0.2755] (n=24, n_clusters=4; **includes 0**) |
| `intent_filter_static` | +0.0827 [-0.1306, +0.2959] (n=24, n_clusters=4; **includes 0**) |
| `oracle` | -0.2633 [-0.4110, -0.1157] (n=24, n_clusters=4; excludes 0) |

| Stratum | personas | `full` | `random` | lift |
|---|---|---|---|---|
| `stated` | `eval-mr-lim-kw` | 0.8797 [0.8797, 0.8797] (n=6, n_clusters=1) | 0.5494 [0.5494, 0.5494] (n=6, n_clusters=1) | +0.3303 [+0.3303, +0.3303] (n=6, n_clusters=1; excludes 0) |
| `inferred_only` | `eval-mdm-poh`, `eval-mdm-suriati`, `eval-mr-hassan` | 0.6890 [0.5549, 0.8889] (n=18, n_clusters=3) | 0.6193 [0.4135, 0.9232] (n=18, n_clusters=3) | +0.0697 [-0.0344, +0.2096] (n=18, n_clusters=3; **includes 0**) |

**The number to quote is the `inferred_only` one: +0.0697 [-0.0344, +0.2096] (n=18, n_clusters=3; **includes 0**).** A `stated` persona hands the ranker, verbatim, one of the exact `(dimension, value)` pairs the grader reads from her brief, so her cases measure "obey what the person just told you" rather than "infer taste from behaviour". Both are real product behaviour; only the second is what this benchmark claims to measure. `eval-mr-koh` states the same SOCIAL fact from the opposite pole (`solo` stated against a `social` hard avoid) and is counted as inferred-only here -- on the wider reading the stated stratum is one persona larger.

**Per persona.** A macro mean hides its own worst case; these are the cases.

| Persona | cases | stated? | full NDCG@3 | random NDCG@3 | lift |
|---|---|---|---|---|---|
| `eval-mdm-poh` | 6 | no | 0.5549 | 0.5211 | +0.0338 |
| `eval-mr-lim-kw` | 6 | yes | 0.8797 | 0.5494 | +0.3303 |
| `eval-mdm-suriati` | 6 | no | 0.8889 | 0.9232 | -0.0343 |
| `eval-mr-hassan` | 6 | no | 0.6231 | 0.4135 | +0.2096 |

1 of 4 personas score BELOW a random shuffle here: `eval-mdm-suriati`.

**Learning curve.** The same persona, catalogue, query and grade table at every point; the only thing that varies is how many observation-trace events the ranker has been given. `cold_start` is the day a person signs up -- no learned preference and no engagement history, so only `intent`, `context` and `friction` are doing anything.

| Arm | trace events | NDCG@1 | HitRate@3 | NDCG@3 | lift over random |
|---|---|---|---|---|---|
| `cold_start` | 0 | 0.6032 | 0.1667 | 0.6067 | +0.0049 [-0.0142, +0.0227] (n=24, n_clusters=4; **includes 0**) |
| `first_signal` | 1 | 0.7341 | 0.4167 | 0.6993 | +0.0975 [+0.0061, +0.1888] (n=24, n_clusters=4; excludes 0) |
| `trace_prefix:1` | 1 | 0.7341 | 0.4167 | 0.6993 | +0.0975 [+0.0061, +0.1888] (n=24, n_clusters=4; excludes 0) |
| `trace_prefix:3` | 3 | 0.7302 | 0.4167 | 0.7367 | +0.1348 [-0.0003, +0.2700] (n=24, n_clusters=4; **includes 0**) |
| `trace_prefix:5` | 5 | 0.7302 | 0.4167 | 0.7367 | +0.1348 [-0.0003, +0.2700] (n=24, n_clusters=4; **includes 0**) |
| `full` | all | 0.7302 | 0.4167 | 0.7367 | +0.1348 [-0.0003, +0.2700] (n=24, n_clusters=4; **includes 0**) |

**`cases_to_beat_random`: 1.** That many observation-trace events are needed before the paired, persona-clustered CI over the random floor excludes zero.

The longest trace in this split is 2 event(s), so every prefix length above that is the full trace under another name and the curve is flat there by construction -- not evidence that more evidence would not help. `first_signal` and `trace_prefix:1` are the same manipulation under two names and must agree exactly.

| Metric | full | random (20 draws) | catalogue-order | intent_filter+static | oracle |
|---|---|---|---|---|---|
| NDCG@1 (is the best thing first) | 0.7302 [0.5992, 0.8571] (n=24) | 0.5766 [0.4889, 0.6715] (n=24) | 0.5794 [0.4563, 0.7024] (n=24) | 0.5476 [0.4325, 0.6706] (n=24) | 1.0000 [1.0000, 1.0000] (n=24) |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | 0.4167 [0.2083, 0.6250] (n=24) | 0.2104 [0.1292, 0.2938] (n=24) | 0.0833 [0.0000, 0.2083] (n=24) | 0.2500 [0.0833, 0.4167] (n=24) | 0.6250 [0.4167, 0.8333] (n=24) |
| slate_ndcg@3 (ideal under the one-per-category rule) | 0.8224 [0.7354, 0.9003] (n=24) | 0.6919 [0.6209, 0.7620] (n=24) | 0.6988 [0.6038, 0.7934] (n=24) | 0.7440 [0.6264, 0.8554] (n=24) | 1.0000 [1.0000, 1.0000] (n=24) |
| NDCG@3 | 0.7367 [0.6417, 0.8327] (n=24) | 0.6018 [0.5131, 0.6954] (n=24) | 0.6174 [0.5073, 0.7345] (n=24) | 0.6540 [0.5385, 0.7605] (n=24) | 1.0000 [1.0000, 1.0000] (n=24) |
| P@3 (taste match) | 0.2222 [0.1111, 0.3472] (n=24) | 0.0757 [0.0451, 0.1097] (n=24) | 0.0417 [0.0000, 0.1111] (n=24) | 0.1667 [0.0556, 0.2778] (n=24) | 0.5278 [0.3333, 0.7083] (n=24) |
| MRR (rel=3) | 0.3706 [0.1998, 0.5545] (n=24) | 0.1918 [0.1245, 0.2583] (n=24) | 0.0765 [0.0345, 0.1319] (n=24) | 0.1948 [0.1028, 0.3014] (n=24) | 0.6250 [0.4167, 0.8333] (n=24) |

The same rows with the CI resampled over PERSONAS rather than cases. Six cases share one persona's trace, preference store and grade table, so the per-case interval above is roughly 2.2x too narrow; this is the honest width.

| Metric | full | random (20 draws) | catalogue-order | intent_filter+static | oracle |
|---|---|---|---|---|---|
| NDCG@1 (is the best thing first) | 0.7302 [0.5635, 0.8968] (n=24, n_clusters=4) | 0.5766 [0.4259, 0.8039] (n=24, n_clusters=4) | 0.5794 [0.3968, 0.8571] (n=24, n_clusters=4) | 0.5476 [0.3690, 0.8532] (n=24, n_clusters=4) | 1.0000 [1.0000, 1.0000] (n=24, n_clusters=4) |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | 0.4167 [0.0000, 0.8333] (n=24, n_clusters=4) | 0.2104 [0.0708, 0.2833] (n=24, n_clusters=4) | 0.0833 [0.0000, 0.2500] (n=24, n_clusters=4) | 0.2500 [0.0417, 0.5417] (n=24, n_clusters=4) | 0.6250 [0.2083, 0.9167] (n=24, n_clusters=4) |
| slate_ndcg@3 (ideal under the one-per-category rule) | 0.8224 [0.7123, 0.9326] (n=24, n_clusters=4) | 0.6919 [0.5626, 0.8515] (n=24, n_clusters=4) | 0.6988 [0.5128, 0.8963] (n=24, n_clusters=4) | 0.7440 [0.5308, 0.9419] (n=24, n_clusters=4) | 1.0000 [1.0000, 1.0000] (n=24, n_clusters=4) |
| NDCG@3 | 0.7367 [0.5890, 0.8843] (n=24, n_clusters=4) | 0.6018 [0.4475, 0.8227] (n=24, n_clusters=4) | 0.6174 [0.4223, 0.8664] (n=24, n_clusters=4) | 0.6540 [0.4461, 0.8878] (n=24, n_clusters=4) | 1.0000 [1.0000, 1.0000] (n=24, n_clusters=4) |
| P@3 (taste match) | 0.2222 [0.0000, 0.4444] (n=24, n_clusters=4) | 0.0757 [0.0257, 0.1042] (n=24, n_clusters=4) | 0.0417 [0.0000, 0.1250] (n=24, n_clusters=4) | 0.1667 [0.0278, 0.3611] (n=24, n_clusters=4) | 0.5278 [0.1806, 0.7222] (n=24, n_clusters=4) |
| MRR (rel=3) | 0.3706 [0.0329, 0.7083] (n=24, n_clusters=4) | 0.1918 [0.0614, 0.2782] (n=24, n_clusters=4) | 0.0765 [0.0150, 0.1672] (n=24, n_clusters=4) | 0.1948 [0.0625, 0.3198] (n=24, n_clusters=4) | 0.6250 [0.2083, 0.9167] (n=24, n_clusters=4) |

**Discriminable cases: 24/24.** A case counts here when its ordering can change the headline metric at all -- when the best and the worst ordering of its kept pool score differently, which on this dataset is exactly the cases whose kept candidates do not all carry the same grade. The rest score identically under every ordering and drag the headline toward the pool's own composition. This stratum used to be defined as "holds a grade-3 AND something graded <=1", a much narrower rule justified by the same sentence: on core that dropped 21 of the 51 cases whose ordering demonstrably matters, on holdout 14 of 24, and it took whole personas out of the headline with them. The same rows over the discriminable cases only, persona-clustered:

**Every case in this split is discriminable, so this stratum is the split and the table below restates the persona-clustered one above.** Any difference between the two numbers would be a bug, not a finding.

| Metric | full | random (20 draws) | catalogue-order | intent_filter+static | oracle |
|---|---|---|---|---|---|
| NDCG@1 (is the best thing first) | 0.7302 [0.5635, 0.8968] (n=24, n_clusters=4) | 0.5766 [0.4259, 0.8039] (n=24, n_clusters=4) | 0.5794 [0.3968, 0.8571] (n=24, n_clusters=4) | 0.5476 [0.3690, 0.8532] (n=24, n_clusters=4) | 1.0000 [1.0000, 1.0000] (n=24, n_clusters=4) |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | 0.4167 [0.0000, 0.8333] (n=24, n_clusters=4) | 0.2104 [0.0708, 0.2833] (n=24, n_clusters=4) | 0.0833 [0.0000, 0.2500] (n=24, n_clusters=4) | 0.2500 [0.0417, 0.5417] (n=24, n_clusters=4) | 0.6250 [0.2083, 0.9167] (n=24, n_clusters=4) |
| slate_ndcg@3 (ideal under the one-per-category rule) | 0.8224 [0.7123, 0.9326] (n=24, n_clusters=4) | 0.6919 [0.5626, 0.8515] (n=24, n_clusters=4) | 0.6988 [0.5128, 0.8963] (n=24, n_clusters=4) | 0.7440 [0.5308, 0.9419] (n=24, n_clusters=4) | 1.0000 [1.0000, 1.0000] (n=24, n_clusters=4) |
| NDCG@3 | 0.7367 [0.5890, 0.8843] (n=24, n_clusters=4) | 0.6018 [0.4475, 0.8227] (n=24, n_clusters=4) | 0.6174 [0.4223, 0.8664] (n=24, n_clusters=4) | 0.6540 [0.4461, 0.8878] (n=24, n_clusters=4) | 1.0000 [1.0000, 1.0000] (n=24, n_clusters=4) |
| P@3 (taste match) | 0.2222 [0.0000, 0.4444] (n=24, n_clusters=4) | 0.0757 [0.0257, 0.1042] (n=24, n_clusters=4) | 0.0417 [0.0000, 0.1250] (n=24, n_clusters=4) | 0.1667 [0.0278, 0.3611] (n=24, n_clusters=4) | 0.5278 [0.1806, 0.7222] (n=24, n_clusters=4) |
| MRR (rel=3) | 0.3706 [0.0329, 0.7083] (n=24, n_clusters=4) | 0.1918 [0.0614, 0.2782] (n=24, n_clusters=4) | 0.0765 [0.0150, 0.1672] (n=24, n_clusters=4) | 0.1948 [0.0625, 0.3198] (n=24, n_clusters=4) | 0.6250 [0.2083, 0.9167] (n=24, n_clusters=4) |

| `full` minus (discriminable only) | NDCG@3 delta |
|---|---|
| `random` | +0.1348 [-0.0003, +0.2700] (n=24, n_clusters=4; **includes 0**) |
| `catalogue_order` | +0.1193 [-0.0369, +0.2755] (n=24, n_clusters=4; **includes 0**) |
| `intent_filter_static` | +0.0827 [-0.1306, +0.2959] (n=24, n_clusters=4; **includes 0**) |
| `oracle` | -0.2633 [-0.4110, -0.1157] (n=24, n_clusters=4; excludes 0) |

| Metric | value (per-case CI) | value (persona-clustered CI) |
|---|---|---|
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | 0.9820 [0.9558, 1.0000] (n=24) | 0.9820 [0.9460, 1.0000] (n=24, n_clusters=4) |
| unknown_admitted@3 | 0.1250 [0.0417, 0.2222] (n=24) | 0.1250 [0.0833, 0.1667] (n=24, n_clusters=4) |
| category_entropy@3 | 1.0708 [0.8344, 1.2967] (n=24) | 1.0708 [0.7684, 1.4461] (n=24, n_clusters=4) |
| personalisation_divergence (clustered by unordered persona PAIR) | -- | 0.5238 [0.4333, 0.6061] (n=21, n_clusters=6) |
| reasons_grounded_rate (pooled) | 595/595 (100.00%) | -- |
| reasons_grounded_rate (macro-averaged per case, bootstrap CI) | 1.0000 [1.0000, 1.0000] (n=24) | -- |
| catalogue filler reason lines (not counted above) | 1 | -- |

## Ablations: which factor is load-bearing on this dataset?

Two kinds of arm, and the difference matters. A **factor arm** (`factor:<name>`) zeroes exactly one `ScoreFactor`'s weighted CONTRIBUTION to `total`, leaves every factor VALUE -- and therefore the hard filter, the tier and the environment-aware rain rule -- exactly as production computed it, re-sorts on the adjusted totals and re-runs the production post-scoring passes (`activity_search.postprocess`). Its delta is attributable to that factor's weight alone. An **input arm** (`input:*`) changes one argument instead; that is closer to "what if we never had this data", but an input rarely touches exactly one factor, so each one prints the list of factors it can move. A `no_preference_dim:<D>` arm drops one learned dimension, which is the only way to separate an axis the ranker reads more than once. Every arm is compared to its OWN baseline, printed in its header: an arm that runs with the diversity swap off is compared to `no_diversity`, never to `full`, because a comparison to `full` folds the swap's own delta into the factor's.

### Ablations -- Core set (paired delta vs each arm's own baseline; 60 cases from 10 personas)

**`factor:intent`** -- measured against `full`; touches `intent`.

Zeroes only the `intent` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | masked by this metric: the order changed on 30/60 case(s) without moving this number | masked by this metric: the order changed on 30/60 case(s) without moving this number |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 30/60 case(s) without moving this number | masked by this metric: the order changed on 30/60 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0004 [-0.0013, +0.0000] | -0.0004 [-0.0013, +0.0000] |
| NDCG@3 | +0.0028 [-0.0007, +0.0081] | +0.0028 [-0.0007, +0.0076] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0039 [+0.0000, +0.0117] | +0.0039 [+0.0000, +0.0117] |
| P@3 (taste match) | +0.0056 [+0.0000, +0.0167] | +0.0056 [+0.0000, +0.0167] |
| MRR (rel=3) | +0.0022 [-0.0005, +0.0063] | +0.0022 [+0.0000, +0.0051] |
| unknown_admitted@3 | +0.0667 [+0.0333, +0.1056] | +0.0667 [+0.0444, +0.0889] |
| category_entropy@3 | -0.0042 [-0.0459, +0.0333] | -0.0042 [-0.0459, +0.0333] |

**`factor:preference`** -- measured against `full`; touches `preference`.

Zeroes only the `preference` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0381 [-0.0762, -0.0095] | -0.0381 [-0.0762, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 36/60 case(s) without moving this number | masked by this metric: the order changed on 36/60 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0433 [-0.0733, -0.0196] | -0.0433 [-0.0951, -0.0060] |
| NDCG@3 | -0.0499 [-0.0783, -0.0271] | -0.0499 [-0.0995, -0.0162] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0033 [+0.0000, +0.0099] | +0.0033 [+0.0000, +0.0099] |
| P@3 (taste match) | -0.0722 [-0.1222, -0.0333] | -0.0722 [-0.1556, -0.0167] |
| MRR (rel=3) | -0.0435 [-0.0874, -0.0112] | -0.0435 [-0.0907, -0.0028] |
| unknown_admitted@3 | +0.0278 [+0.0056, +0.0500] | +0.0278 [+0.0056, +0.0500] |
| category_entropy@3 | +0.1306 [+0.0667, +0.2071] | +0.1306 [+0.0444, +0.2363] |

**`factor:engagement`** -- measured against `full`; touches `engagement`.

Zeroes only the `engagement` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0476 [-0.0857, -0.0095] | -0.0476 [-0.1143, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | -0.0333 [-0.0833, +0.0000] | -0.0333 [-0.1000, +0.0000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0208 [-0.0417, -0.0032] | -0.0208 [-0.0528, +0.0000] |
| NDCG@3 | -0.0195 [-0.0346, -0.0067] | -0.0195 [-0.0436, +0.0000] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | masked by this metric: the order changed on 23/60 case(s) without moving this number | masked by this metric: the order changed on 23/60 case(s) without moving this number |
| P@3 (taste match) | -0.0222 [-0.0444, -0.0056] | -0.0222 [-0.0556, +0.0000] |
| MRR (rel=3) | -0.0548 [-0.1032, -0.0119] | -0.0548 [-0.1304, +0.0000] |
| unknown_admitted@3 | masked by this metric: the order changed on 23/60 case(s) without moving this number | masked by this metric: the order changed on 23/60 case(s) without moving this number |
| category_entropy@3 | +0.0084 [-0.0444, +0.0654] | +0.0084 [-0.0667, +0.0918] |

**`factor:repetition`** -- measured against `full`; touches `repetition`.

Zeroes only the `repetition` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed |
| slate_ndcg@3 (ideal under the one-per-category rule) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed |
| NDCG@3 | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed |
| P@3 (taste match) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed |
| MRR (rel=3) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed |
| unknown_admitted@3 | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed |
| category_entropy@3 | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 18/60 case(s) and the ranked order never changed |

**`factor:context`** -- measured against `full`; touches `context`.

Zeroes only the `context` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | +0.0476 [+0.0048, +0.1000] | +0.0476 [+0.0000, +0.1429] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | +0.0500 [+0.0000, +0.1167] | +0.0500 [+0.0000, +0.1500] |
| slate_ndcg@3 (ideal under the one-per-category rule) | +0.0538 [+0.0177, +0.0991] | +0.0538 [+0.0000, +0.1406] |
| NDCG@3 | +0.0541 [+0.0240, +0.0887] | +0.0541 [+0.0056, +0.1260] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | -0.4563 [-0.5536, -0.3540] | -0.4563 [-0.6017, -0.2924] |
| P@3 (taste match) | +0.0500 [+0.0167, +0.0833] | +0.0500 [+0.0111, +0.0944] |
| MRR (rel=3) | +0.0437 [-0.0032, +0.1059] | +0.0437 [-0.0143, +0.1455] |
| unknown_admitted@3 | -0.0333 [-0.0611, -0.0111] | -0.0333 [-0.0500, -0.0167] |
| category_entropy@3 | -0.0486 [-0.1348, +0.0222] | -0.0486 [-0.1904, +0.0556] |

**`factor:friction`** -- measured against `full`; touches `friction`.

Zeroes only the `friction` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0238 [-0.0619, +0.0000] | -0.0238 [-0.0571, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | +0.0000 [-0.0500, +0.0500] | +0.0000 [-0.0500, +0.0500] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0092 [-0.0333, +0.0073] | -0.0092 [-0.0308, +0.0064] |
| NDCG@3 | -0.0088 [-0.0327, +0.0073] | -0.0088 [-0.0310, +0.0064] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | masked by this metric: the order changed on 40/60 case(s) without moving this number | masked by this metric: the order changed on 40/60 case(s) without moving this number |
| P@3 (taste match) | +0.0000 [-0.0167, +0.0167] | +0.0000 [-0.0167, +0.0167] |
| MRR (rel=3) | -0.0266 [-0.0668, +0.0012] | -0.0266 [-0.0640, +0.0000] |
| unknown_admitted@3 | -0.1167 [-0.1722, -0.0667] | -0.1167 [-0.1444, -0.0889] |
| category_entropy@3 | -0.0778 [-0.1333, -0.0333] | -0.0778 [-0.1444, -0.0222] |

**`input:no_intent`** -- measured against `full`; touches `intent`, `context`.

Substitutes an empty `ActivityIntent()`. CONFOUNDED, and kept only as the honest "what if nothing was asked for" arm: it also resets `environment` to EITHER, which switches `score_candidate`'s rain nudge back on for any case whose real intent asked for a specific environment, and it flattens every candidate's `intent` factor value to 0, which removes intent from the tier as well. Read `factor:intent` for the intent weight's own effect.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0119 [-0.0714, +0.0452] | -0.0119 [-0.0667, +0.0452] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | +0.0167 [-0.0333, +0.0833] | +0.0167 [-0.0333, +0.0667] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0004 [-0.0308, +0.0285] | -0.0004 [-0.0314, +0.0285] |
| NDCG@3 | -0.0026 [-0.0334, +0.0259] | -0.0026 [-0.0309, +0.0221] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0013 [-0.0144, +0.0163] | +0.0013 [-0.0144, +0.0150] |
| P@3 (taste match) | +0.0000 [-0.0278, +0.0222] | +0.0000 [-0.0222, +0.0222] |
| MRR (rel=3) | -0.0132 [-0.0644, +0.0320] | -0.0132 [-0.0555, +0.0331] |
| unknown_admitted@3 | +0.0056 [-0.0778, +0.0778] | +0.0056 [-0.0222, +0.0389] |
| category_entropy@3 | -0.0264 [-0.0973, +0.0444] | -0.0264 [-0.0751, +0.0249] |

**`input:no_engagement`** -- measured against `full`; touches `engagement`, `repetition`.

Passes `engagement={}`. CONFOUNDED: the same map carries `last_not_for_me`, so this also zeroes the `repetition` factor and removes every HISTORY reason line. Read `factor:engagement` and `factor:repetition` for the two weights separately.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0643 [-0.1167, -0.0190] | -0.0643 [-0.1310, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | -0.0333 [-0.0833, +0.0000] | -0.0333 [-0.1000, +0.0000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0310 [-0.0568, -0.0088] | -0.0310 [-0.0678, +0.0000] |
| NDCG@3 | -0.0298 [-0.0510, -0.0108] | -0.0298 [-0.0669, +0.0000] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | masked by this metric: the order changed on 34/60 case(s) without moving this number | masked by this metric: the order changed on 34/60 case(s) without moving this number |
| P@3 (taste match) | -0.0222 [-0.0444, -0.0056] | -0.0222 [-0.0556, +0.0000] |
| MRR (rel=3) | -0.0548 [-0.1032, -0.0119] | -0.0548 [-0.1304, +0.0000] |
| unknown_admitted@3 | masked by this metric: the order changed on 34/60 case(s) without moving this number | masked by this metric: the order changed on 34/60 case(s) without moving this number |
| category_entropy@3 | +0.0084 [-0.0444, +0.0654] | +0.0084 [-0.0667, +0.0918] |

**`input:no_preferences`** -- measured against `full`; touches `preference`.

Passes an empty `ActivityPreferences`: nothing learned from the observation trace reaches the ranker at all. The "what did the learning buy" arm, at the input rather than the weight.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.1048 [-0.1619, -0.0571] | -0.1048 [-0.2095, -0.0190] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | -0.0500 [-0.1167, +0.0000] | -0.0500 [-0.1167, +0.0000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0826 [-0.1242, -0.0465] | -0.0826 [-0.1539, -0.0237] |
| NDCG@3 | -0.0862 [-0.1258, -0.0525] | -0.0862 [-0.1570, -0.0316] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0033 [+0.0000, +0.0099] | +0.0033 [+0.0000, +0.0099] |
| P@3 (taste match) | -0.1111 [-0.1722, -0.0556] | -0.1111 [-0.2167, -0.0333] |
| MRR (rel=3) | -0.1144 [-0.1817, -0.0587] | -0.1144 [-0.2301, -0.0195] |
| unknown_admitted@3 | +0.0278 [+0.0056, +0.0500] | +0.0278 [+0.0056, +0.0500] |
| category_entropy@3 | +0.1306 [+0.0667, +0.2071] | +0.1306 [+0.0444, +0.2363] |

**`no_preference_dim:distance`** -- measured against `full`; touches `preference`.

Drops every learned `distance` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_preference_dim:intensity`** -- measured against `full`; touches `preference`.

Drops every learned `intensity` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | masked by this metric: the order changed on 4/60 case(s) without moving this number | masked by this metric: the order changed on 4/60 case(s) without moving this number |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 4/60 case(s) without moving this number | masked by this metric: the order changed on 4/60 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0036 [-0.0084, +0.0000] | -0.0036 [-0.0109, +0.0000] |
| NDCG@3 | -0.0026 [-0.0059, +0.0000] | -0.0026 [-0.0077, +0.0000] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | masked by this metric: the order changed on 4/60 case(s) without moving this number | masked by this metric: the order changed on 4/60 case(s) without moving this number |
| P@3 (taste match) | masked by this metric: the order changed on 4/60 case(s) without moving this number | masked by this metric: the order changed on 4/60 case(s) without moving this number |
| MRR (rel=3) | -0.0010 [-0.0021, -0.0000] | -0.0010 [-0.0029, +0.0000] |
| unknown_admitted@3 | masked by this metric: the order changed on 4/60 case(s) without moving this number | masked by this metric: the order changed on 4/60 case(s) without moving this number |
| category_entropy@3 | masked by this metric: the order changed on 4/60 case(s) without moving this number | masked by this metric: the order changed on 4/60 case(s) without moving this number |

**`no_preference_dim:timing`** -- measured against `full`; touches `preference`.

Drops every learned `timing` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0381 [-0.0762, -0.0095] | -0.0381 [-0.1143, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 4/60 case(s) without moving this number | masked by this metric: the order changed on 4/60 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0201 [-0.0425, -0.0045] | -0.0201 [-0.0603, +0.0000] |
| NDCG@3 | -0.0201 [-0.0425, -0.0045] | -0.0201 [-0.0603, +0.0000] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | masked by this metric: the order changed on 4/60 case(s) without moving this number | masked by this metric: the order changed on 4/60 case(s) without moving this number |
| P@3 (taste match) | -0.0278 [-0.0611, -0.0056] | -0.0278 [-0.0833, +0.0000] |
| MRR (rel=3) | -0.0333 [-0.0667, -0.0083] | -0.0333 [-0.1000, +0.0000] |
| unknown_admitted@3 | masked by this metric: the order changed on 4/60 case(s) without moving this number | masked by this metric: the order changed on 4/60 case(s) without moving this number |
| category_entropy@3 | +0.0111 [+0.0000, +0.0333] | +0.0111 [+0.0000, +0.0333] |

**`no_preference_dim:social`** -- measured against `full`; touches `preference`.

Drops every learned `social` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0476 [-0.0952, -0.0095] | -0.0476 [-0.1238, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | -0.0500 [-0.1167, +0.0000] | -0.0500 [-0.1167, +0.0000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0487 [-0.0870, -0.0176] | -0.0487 [-0.1183, +0.0000] |
| NDCG@3 | -0.0442 [-0.0815, -0.0145] | -0.0442 [-0.1094, +0.0000] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | -0.0033 [-0.0099, +0.0000] | -0.0033 [-0.0099, +0.0000] |
| P@3 (taste match) | -0.0556 [-0.1167, -0.0111] | -0.0556 [-0.1611, +0.0111] |
| MRR (rel=3) | -0.0625 [-0.1236, -0.0139] | -0.0625 [-0.1625, +0.0000] |
| unknown_admitted@3 | +0.0111 [+0.0000, +0.0278] | +0.0111 [+0.0000, +0.0278] |
| category_entropy@3 | -0.0333 [-0.0778, +0.0000] | -0.0333 [-0.1000, +0.0000] |

**`no_preference_dim:environment`** -- measured against `full`; touches `preference`.

Drops every learned `environment` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_preference_dim:category`** -- measured against `full`; touches `preference`.

Drops every learned `category` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_preference_dim:activity_type`** -- measured against `full`; touches `preference`.

Drops every learned `activity_type` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0190 [-0.0476, +0.0000] | -0.0190 [-0.0571, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 20/60 case(s) without moving this number | masked by this metric: the order changed on 20/60 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0047 [-0.0118, +0.0000] | -0.0047 [-0.0142, +0.0000] |
| NDCG@3 | -0.0144 [-0.0256, -0.0051] | -0.0144 [-0.0261, -0.0043] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0033 [+0.0000, +0.0099] | +0.0033 [+0.0000, +0.0099] |
| P@3 (taste match) | -0.0222 [-0.0444, -0.0056] | -0.0222 [-0.0500, +0.0000] |
| MRR (rel=3) | -0.0176 [-0.0426, +0.0000] | -0.0176 [-0.0529, +0.0000] |
| unknown_admitted@3 | +0.0167 [+0.0000, +0.0389] | +0.0167 [+0.0000, +0.0389] |
| category_entropy@3 | +0.1195 [+0.0556, +0.1931] | +0.1195 [+0.0306, +0.2279] |

**`cold_start`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

Day zero for a new person: no observation trace at all, so no learned preference and no engagement history. What the deterministic factors (`intent`, `context`, `friction`) achieve on their own, before the learner has anything to work with.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.2286 [-0.3143, -0.1476] | -0.2286 [-0.3452, -0.1143] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | -0.1833 [-0.2833, -0.0833] | -0.1833 [-0.3000, -0.0667] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.1715 [-0.2359, -0.1106] | -0.1715 [-0.2677, -0.0854] |
| NDCG@3 | -0.1597 [-0.2101, -0.1116] | -0.1597 [-0.2375, -0.0849] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0033 [+0.0000, +0.0099] | +0.0033 [+0.0000, +0.0099] |
| P@3 (taste match) | -0.1722 [-0.2444, -0.1111] | -0.1722 [-0.2722, -0.0833] |
| MRR (rel=3) | -0.2440 [-0.3345, -0.1575] | -0.2440 [-0.3871, -0.1153] |
| unknown_admitted@3 | +0.0389 [+0.0167, +0.0667] | +0.0389 [+0.0167, +0.0667] |
| category_entropy@3 | +0.1639 [+0.0778, +0.2627] | +0.1639 [+0.0444, +0.3168] |

**`first_signal`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

The first trace event only -- one decline, one enjoyment report or one stated preference. The same manipulation as `trace_prefix:1`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0357 [-0.0810, +0.0000] | -0.0357 [-0.0881, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 33/60 case(s) without moving this number | masked by this metric: the order changed on 33/60 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0186 [-0.0377, -0.0044] | -0.0186 [-0.0427, +0.0000] |
| NDCG@3 | -0.0189 [-0.0382, -0.0048] | -0.0189 [-0.0419, +0.0000] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0033 [+0.0000, +0.0099] | +0.0033 [+0.0000, +0.0099] |
| P@3 (taste match) | -0.0056 [-0.0167, +0.0000] | -0.0056 [-0.0167, +0.0000] |
| MRR (rel=3) | -0.0176 [-0.0427, -0.0006] | -0.0176 [-0.0510, +0.0000] |
| unknown_admitted@3 | masked by this metric: the order changed on 33/60 case(s) without moving this number | masked by this metric: the order changed on 33/60 case(s) without moving this number |
| category_entropy@3 | +0.0111 [+0.0000, +0.0333] | +0.0111 [+0.0000, +0.0333] |

**`trace_prefix:1`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

The first 1 trace event(s). Read the series as a learning curve: how much evidence does the learner need before it helps?

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0357 [-0.0810, +0.0000] | -0.0357 [-0.0881, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 33/60 case(s) without moving this number | masked by this metric: the order changed on 33/60 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0186 [-0.0377, -0.0044] | -0.0186 [-0.0427, +0.0000] |
| NDCG@3 | -0.0189 [-0.0382, -0.0048] | -0.0189 [-0.0419, +0.0000] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0033 [+0.0000, +0.0099] | +0.0033 [+0.0000, +0.0099] |
| P@3 (taste match) | -0.0056 [-0.0167, +0.0000] | -0.0056 [-0.0167, +0.0000] |
| MRR (rel=3) | -0.0176 [-0.0427, -0.0006] | -0.0176 [-0.0510, +0.0000] |
| unknown_admitted@3 | masked by this metric: the order changed on 33/60 case(s) without moving this number | masked by this metric: the order changed on 33/60 case(s) without moving this number |
| category_entropy@3 | +0.0111 [+0.0000, +0.0333] | +0.0111 [+0.0000, +0.0333] |

**`trace_prefix:3`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

The first 3 trace event(s). Read the series as a learning curve: how much evidence does the learner need before it helps?

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`trace_prefix:5`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

The first 5 trace event(s). Read the series as a learning curve: how much evidence does the learner need before it helps?

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_diversity`** -- measured against `full`; touches no scoring factor.

The production pipeline with only the diversity swap switched off; the tier sort and the series dedupe still run, so the delta is the swap alone. This arm is also the BASELINE every other diversity-off arm is measured against.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

### Ablations -- Holdout set (paired delta vs each arm's own baseline; 24 cases from 4 personas)

**`factor:intent`** -- measured against `full`; touches `intent`.

Zeroes only the `intent` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0357 [-0.1071, +0.0000] | -0.0357 [-0.1071, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 12/24 case(s) without moving this number | masked by this metric: the order changed on 12/24 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0179 [-0.0538, +0.0000] | -0.0179 [-0.0538, +0.0000] |
| NDCG@3 | -0.0146 [-0.0437, +0.0000] | -0.0146 [-0.0437, +0.0000] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0098 [+0.0000, +0.0293] | +0.0098 [+0.0000, +0.0293] |
| P@3 (taste match) | -0.0139 [-0.0417, +0.0000] | -0.0139 [-0.0417, +0.0000] |
| MRR (rel=3) | -0.0215 [-0.0637, +0.0000] | -0.0215 [-0.0625, +0.0000] |
| unknown_admitted@3 | +0.0417 [+0.0000, +0.1111] | +0.0417 [+0.0000, +0.0833] |
| category_entropy@3 | +0.0383 [+0.0000, +0.1148] | +0.0383 [+0.0000, +0.1148] |

**`factor:preference`** -- measured against `full`; touches `preference`.

Zeroes only the `preference` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.1190 [-0.2381, -0.0278] | -0.1190 [-0.2500, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | -0.0833 [-0.2083, +0.0000] | -0.0833 [-0.2500, +0.0000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.1028 [-0.1710, -0.0396] | -0.1028 [-0.1811, -0.0244] |
| NDCG@3 | -0.1188 [-0.1706, -0.0682] | -0.1188 [-0.1681, -0.0488] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0180 [+0.0000, +0.0442] | +0.0180 [+0.0000, +0.0540] |
| P@3 (taste match) | -0.1111 [-0.1806, -0.0556] | -0.1111 [-0.2222, +0.0000] |
| MRR (rel=3) | -0.0687 [-0.1385, -0.0146] | -0.0687 [-0.1768, -0.0069] |
| unknown_admitted@3 | +0.0278 [+0.0000, +0.0694] | +0.0278 [+0.0000, +0.0556] |
| category_entropy@3 | +0.3753 [+0.1876, +0.5666] | +0.3753 [+0.1389, +0.5765] |

**`factor:engagement`** -- measured against `full`; touches `engagement`.

Zeroes only the `engagement` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0675 [-0.1667, +0.0357] | -0.0675 [-0.2857, +0.0833] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 16/24 case(s) without moving this number | masked by this metric: the order changed on 16/24 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0037 [-0.0327, +0.0281] | -0.0037 [-0.0300, +0.0281] |
| NDCG@3 | -0.0155 [-0.0452, +0.0197] | -0.0155 [-0.0552, +0.0256] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0098 [+0.0000, +0.0293] | +0.0098 [+0.0000, +0.0293] |
| P@3 (taste match) | -0.0139 [-0.0417, +0.0000] | -0.0139 [-0.0417, +0.0000] |
| MRR (rel=3) | -0.0847 [-0.1489, -0.0217] | -0.0847 [-0.2500, +0.0000] |
| unknown_admitted@3 | masked by this metric: the order changed on 16/24 case(s) without moving this number | masked by this metric: the order changed on 16/24 case(s) without moving this number |
| category_entropy@3 | +0.1808 [+0.0556, +0.3339] | +0.1808 [+0.0000, +0.4277] |

**`factor:repetition`** -- measured against `full`; touches `repetition`.

Zeroes only the `repetition` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed |
| slate_ndcg@3 (ideal under the one-per-category rule) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed |
| NDCG@3 | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed |
| P@3 (taste match) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed |
| MRR (rel=3) | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed |
| unknown_admitted@3 | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed |
| category_entropy@3 | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed | masked by the tier sort (`intent` + `repetition`): the arm moved a weighted contribution on 8/24 case(s) and the ranked order never changed |

**`factor:context`** -- measured against `full`; touches `context`.

Zeroes only the `context` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | +0.1667 [+0.0476, +0.2976] | +0.1667 [+0.0000, +0.3333] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | +0.2083 [+0.0417, +0.3750] | +0.2083 [+0.0000, +0.6250] |
| slate_ndcg@3 (ideal under the one-per-category rule) | +0.0981 [+0.0410, +0.1614] | +0.0981 [+0.0164, +0.2247] |
| NDCG@3 | +0.0945 [+0.0315, +0.1682] | +0.0945 [-0.0059, +0.2510] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | -0.3450 [-0.5085, -0.1898] | -0.3450 [-0.6293, -0.0607] |
| P@3 (taste match) | +0.1111 [+0.0139, +0.2222] | +0.1111 [-0.0417, +0.3750] |
| MRR (rel=3) | +0.2058 [+0.0712, +0.3573] | +0.2058 [+0.0000, +0.4924] |
| unknown_admitted@3 | -0.0139 [-0.0417, +0.0000] | -0.0139 [-0.0417, +0.0000] |
| category_entropy@3 | -0.1111 [-0.2987, +0.0765] | -0.1111 [-0.3333, +0.0556] |

**`factor:friction`** -- measured against `full`; touches `friction`.

Zeroes only the `friction` factor's weighted contribution to `total`, leaving every factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then re-runs the production post-scoring passes.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | +0.0714 [+0.0000, +0.1786] | +0.0714 [+0.0000, +0.2143] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 19/24 case(s) without moving this number | masked by this metric: the order changed on 19/24 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | +0.0160 [-0.0158, +0.0509] | +0.0160 [+0.0000, +0.0321] |
| NDCG@3 | +0.0124 [-0.0148, +0.0391] | +0.0124 [+0.0034, +0.0213] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | masked by this metric: the order changed on 19/24 case(s) without moving this number | masked by this metric: the order changed on 19/24 case(s) without moving this number |
| P@3 (taste match) | masked by this metric: the order changed on 19/24 case(s) without moving this number | masked by this metric: the order changed on 19/24 case(s) without moving this number |
| MRR (rel=3) | +0.0424 [+0.0000, +0.1049] | +0.0424 [+0.0000, +0.1250] |
| unknown_admitted@3 | -0.1111 [-0.2083, -0.0278] | -0.1111 [-0.1528, -0.0694] |
| category_entropy@3 | -0.0278 [-0.1389, +0.0556] | -0.0278 [-0.1111, +0.0556] |

**`input:no_intent`** -- measured against `full`; touches `intent`, `context`.

Substitutes an empty `ActivityIntent()`. CONFOUNDED, and kept only as the honest "what if nothing was asked for" arm: it also resets `environment` to EITHER, which switches `score_candidate`'s rain nudge back on for any case whose real intent asked for a specific environment, and it flattens every candidate's `intent` factor value to 0, which removes intent from the tier as well. Read `factor:intent` for the intent weight's own effect.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0357 [-0.1429, +0.0556] | -0.0357 [-0.1905, +0.0833] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 16/24 case(s) without moving this number | masked by this metric: the order changed on 16/24 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0262 [-0.0832, +0.0227] | -0.0262 [-0.1125, +0.0340] |
| NDCG@3 | -0.0211 [-0.0765, +0.0260] | -0.0211 [-0.1007, +0.0340] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0098 [+0.0000, +0.0293] | +0.0098 [+0.0000, +0.0293] |
| P@3 (taste match) | -0.0139 [-0.0417, +0.0000] | -0.0139 [-0.0417, +0.0000] |
| MRR (rel=3) | -0.0215 [-0.0637, +0.0000] | -0.0215 [-0.0625, +0.0000] |
| unknown_admitted@3 | -0.0417 [-0.1667, +0.0694] | -0.0417 [-0.0833, +0.0000] |
| category_entropy@3 | +0.0383 [-0.0833, +0.1772] | +0.0383 [-0.0556, +0.1111] |

**`input:no_engagement`** -- measured against `full`; touches `engagement`, `repetition`.

Passes `engagement={}`. CONFOUNDED: the same map carries `last_not_for_me`, so this also zeroes the `repetition` factor and removes every HISTORY reason line. Read `factor:engagement` and `factor:repetition` for the two weights separately.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.0675 [-0.1667, +0.0357] | -0.0675 [-0.2857, +0.0833] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | masked by this metric: the order changed on 19/24 case(s) without moving this number | masked by this metric: the order changed on 19/24 case(s) without moving this number |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0037 [-0.0327, +0.0281] | -0.0037 [-0.0300, +0.0281] |
| NDCG@3 | -0.0155 [-0.0452, +0.0197] | -0.0155 [-0.0552, +0.0256] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0098 [+0.0000, +0.0293] | +0.0098 [+0.0000, +0.0293] |
| P@3 (taste match) | -0.0139 [-0.0417, +0.0000] | -0.0139 [-0.0417, +0.0000] |
| MRR (rel=3) | -0.0847 [-0.1489, -0.0217] | -0.0847 [-0.2500, +0.0000] |
| unknown_admitted@3 | masked by this metric: the order changed on 19/24 case(s) without moving this number | masked by this metric: the order changed on 19/24 case(s) without moving this number |
| category_entropy@3 | +0.1808 [+0.0556, +0.3339] | +0.1808 [+0.0000, +0.4277] |

**`input:no_preferences`** -- measured against `full`; touches `preference`.

Passes an empty `ActivityPreferences`: nothing learned from the observation trace reaches the ranker at all. The "what did the learning buy" arm, at the input rather than the weight.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.1190 [-0.2381, -0.0278] | -0.1190 [-0.2500, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | -0.0833 [-0.2083, +0.0000] | -0.0833 [-0.2500, +0.0000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.1129 [-0.1782, -0.0526] | -0.1129 [-0.1811, -0.0447] |
| NDCG@3 | -0.1258 [-0.1750, -0.0773] | -0.1258 [-0.1681, -0.0699] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0180 [+0.0000, +0.0442] | +0.0180 [+0.0000, +0.0540] |
| P@3 (taste match) | -0.1111 [-0.1806, -0.0556] | -0.1111 [-0.2222, +0.0000] |
| MRR (rel=3) | -0.0687 [-0.1385, -0.0146] | -0.0687 [-0.1768, -0.0069] |
| unknown_admitted@3 | +0.0278 [+0.0000, +0.0694] | +0.0278 [+0.0000, +0.0556] |
| category_entropy@3 | +0.3753 [+0.1876, +0.5666] | +0.3753 [+0.1389, +0.5765] |

**`no_preference_dim:distance`** -- measured against `full`; touches `preference`.

Drops every learned `distance` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_preference_dim:intensity`** -- measured against `full`; touches `preference`.

Drops every learned `intensity` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | +0.0952 [+0.0238, +0.1905] | +0.0952 [+0.0000, +0.2857] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | +0.1667 [+0.0417, +0.3333] | +0.1667 [+0.0000, +0.5000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | +0.0481 [+0.0120, +0.0962] | +0.0481 [+0.0000, +0.1443] |
| NDCG@3 | +0.0335 [+0.0084, +0.0670] | +0.0335 [+0.0000, +0.1006] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | -0.0782 [-0.1564, -0.0196] | -0.0782 [-0.2346, +0.0000] |
| P@3 (taste match) | +0.0556 [+0.0139, +0.1111] | +0.0556 [+0.0000, +0.1667] |
| MRR (rel=3) | +0.1586 [+0.0397, +0.3125] | +0.1586 [+0.0000, +0.4757] |
| unknown_admitted@3 | -0.0139 [-0.0417, +0.0000] | -0.0139 [-0.0417, +0.0000] |
| category_entropy@3 | masked by this metric: the order changed on 5/24 case(s) without moving this number | masked by this metric: the order changed on 5/24 case(s) without moving this number |

**`no_preference_dim:timing`** -- measured against `full`; touches `preference`.

Drops every learned `timing` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_preference_dim:social`** -- measured against `full`; touches `preference`.

Drops every learned `social` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_preference_dim:environment`** -- measured against `full`; touches `preference`.

Drops every learned `environment` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_preference_dim:category`** -- measured against `full`; touches `preference`.

Drops every learned `category` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_preference_dim:activity_type`** -- measured against `full`; touches `preference`.

Drops every learned `activity_type` row from `ActivityPreferences`. The only way to separate axes the ranker reads more than once -- `distance_m` is scored by `intent`, by the DISTANCE preference and by `friction`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.1190 [-0.2381, -0.0278] | -0.1190 [-0.2500, +0.0000] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | -0.0833 [-0.2083, +0.0000] | -0.0833 [-0.2500, +0.0000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0927 [-0.1614, -0.0303] | -0.0927 [-0.1811, -0.0021] |
| NDCG@3 | -0.1117 [-0.1657, -0.0595] | -0.1117 [-0.1681, -0.0276] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0180 [+0.0000, +0.0442] | +0.0180 [+0.0000, +0.0540] |
| P@3 (taste match) | -0.1111 [-0.1806, -0.0556] | -0.1111 [-0.2222, +0.0000] |
| MRR (rel=3) | -0.0645 [-0.1359, -0.0069] | -0.0645 [-0.1726, +0.0000] |
| unknown_admitted@3 | +0.0278 [+0.0000, +0.0694] | +0.0278 [+0.0000, +0.0556] |
| category_entropy@3 | +0.3753 [+0.1876, +0.5666] | +0.3753 [+0.1389, +0.5765] |

**`cold_start`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

Day zero for a new person: no observation trace at all, so no learned preference and no engagement history. What the deterministic factors (`intent`, `context`, `friction`) achieve on their own, before the learner has anything to work with.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | -0.1270 [-0.2500, +0.0040] | -0.1270 [-0.3571, +0.0556] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | -0.2500 [-0.4167, -0.0833] | -0.2500 [-0.5000, +0.0000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.1346 [-0.2080, -0.0588] | -0.1346 [-0.2514, -0.0175] |
| NDCG@3 | -0.1300 [-0.2042, -0.0569] | -0.1300 [-0.2608, -0.0055] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | +0.0180 [+0.0000, +0.0442] | +0.0180 [+0.0000, +0.0540] |
| P@3 (taste match) | -0.1667 [-0.2639, -0.0833] | -0.1667 [-0.3333, +0.0000] |
| MRR (rel=3) | -0.2458 [-0.3862, -0.1082] | -0.2458 [-0.5546, -0.0103] |
| unknown_admitted@3 | +0.0417 [+0.0000, +0.0833] | +0.0417 [+0.0000, +0.0833] |
| category_entropy@3 | +0.4864 [+0.2432, +0.7332] | +0.4864 [+0.1494, +0.7332] |

**`first_signal`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

The first trace event only -- one decline, one enjoyment report or one stated preference. The same manipulation as `trace_prefix:1`.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | +0.0040 [-0.1429, +0.1548] | +0.0040 [-0.3294, +0.2857] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | +0.0000 [-0.2083, +0.2083] | +0.0000 [-0.5000, +0.5000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0148 [-0.0962, +0.0682] | -0.0148 [-0.2115, +0.1443] |
| NDCG@3 | -0.0374 [-0.1190, +0.0427] | -0.0374 [-0.2354, +0.1006] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | -0.0782 [-0.1564, -0.0196] | -0.0782 [-0.2346, +0.0000] |
| P@3 (taste match) | -0.0556 [-0.1667, +0.0556] | -0.0556 [-0.3333, +0.1667] |
| MRR (rel=3) | -0.0246 [-0.2456, +0.2017] | -0.0246 [-0.5494, +0.4757] |
| unknown_admitted@3 | +0.0139 [-0.0278, +0.0556] | +0.0139 [-0.0417, +0.0833] |
| category_entropy@3 | +0.1667 [+0.0556, +0.2778] | +0.1667 [+0.0000, +0.4167] |

**`trace_prefix:1`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

The first 1 trace event(s). Read the series as a learning curve: how much evidence does the learner need before it helps?

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | +0.0040 [-0.1429, +0.1548] | +0.0040 [-0.3294, +0.2857] |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | +0.0000 [-0.2083, +0.2083] | +0.0000 [-0.5000, +0.5000] |
| slate_ndcg@3 (ideal under the one-per-category rule) | -0.0148 [-0.0962, +0.0682] | -0.0148 [-0.2115, +0.1443] |
| NDCG@3 | -0.0374 [-0.1190, +0.0427] | -0.0374 [-0.2354, +0.1006] |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | -0.0782 [-0.1564, -0.0196] | -0.0782 [-0.2346, +0.0000] |
| P@3 (taste match) | -0.0556 [-0.1667, +0.0556] | -0.0556 [-0.3333, +0.1667] |
| MRR (rel=3) | -0.0246 [-0.2456, +0.2017] | -0.0246 [-0.5494, +0.4757] |
| unknown_admitted@3 | +0.0139 [-0.0278, +0.0556] | +0.0139 [-0.0417, +0.0833] |
| category_entropy@3 | +0.1667 [+0.0556, +0.2778] | +0.1667 [+0.0000, +0.4167] |

**`trace_prefix:3`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

The first 3 trace event(s). Read the series as a learning curve: how much evidence does the learner need before it helps?

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`trace_prefix:5`** -- measured against `full`; touches `preference`, `engagement`, `repetition`.

The first 5 trace event(s). Read the series as a learning curve: how much evidence does the learner need before it helps?

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

**`no_diversity`** -- measured against `full`; touches no scoring factor.

The production pipeline with only the diversity swap switched off; the tier sort and the series dedupe still run, so the delta is the swap alone. This arm is also the BASELINE every other diversity-off arm is measured against.

| Metric | delta (per-case CI) | delta (persona-clustered CI) |
|---|---|---|
| NDCG@1 (is the best thing first) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| HitRate@3 (rel=3; is a taste match anywhere in the slate) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| slate_ndcg@3 (ideal under the one-per-category rule) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| NDCG@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| context_rule_conformance@3 (synthetic; conformance to a declared rule that restates the ranker's own premise -- NOT independent validation, see METHODOLOGY) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| P@3 (taste match) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| MRR (rel=3) | this dataset does not exercise the factor | this dataset does not exercise the factor |
| unknown_admitted@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |
| category_entropy@3 | this dataset does not exercise the factor | this dataset does not exercise the factor |

