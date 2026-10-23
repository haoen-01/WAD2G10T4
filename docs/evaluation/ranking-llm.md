# Care+ recorded-LLM ranking arm (`llm_recorded`)

**NOT_A_MODEL: the recordings replayed here were produced by `silverloop.evaluation.ranking_llm.scripted_model`, a deterministic rule-based stand-in -- NOT by a language model. Rule A varies the categories of the first three options; rule B drops options from position 6 onward that repeat a category already offered, never going below 5. Nothing in this report is evidence about any model's quality, and no delta below should be quoted as one. What it IS evidence for: the planner loop, its allow-list guardrail, its narrowing bound and its five degradation modes run end to end offline over every benchmark case, and the metric family below can tell a reordering from the deterministic order instead of reporting structural zeros. Re-record against a provider (`synthesise.py --inner anthropic --model ...`) and every number here becomes a statement about that model, with no code change.**

**NOT_USER_TRUTH: every persona, listing and observation trace behind this arm is the same synthetic design artefact the deterministic ranking benchmark uses. No row here is, or is derived from, a real senior's data.**

Each case is one (persona, query template) pair from the ranking benchmark, replayed through the production `agent.planner.plan_activity_ranking` loop with `agent.recorded_client.RecordedClient` as the transport and the deterministic `full` arm's order as `fallback_order`. The displayed order is assembled exactly as `sql_repository.search_activities` assembles it: the planner's order, then any option it was shown and left out, then the tail it never saw -- narrowing demotes, it never deletes. Relevance grades, splits and the metric family are the deterministic benchmark's own, unchanged (`_case_metrics` is imported, not reimplemented), so the deltas are paired and comparable. A request with no recorded answer raises `RecordingMiss`, degrades to `fallback_error` and is counted as a miss -- it is never silently averaged in. `planner_agreement@3` is a redundancy measure, not a quality one: agreement says the planner added nothing, disagreement says nothing about which order was better. Every interval below is a PERSONA-CLUSTERED bootstrap and every delta is paired over the same cases, so `n_clusters` is printed beside `n` everywhere: `n` is how many numbers were averaged, `n_clusters` is how many independent things they came from. This arm used to resample cases i.i.d., which on a design where six cases share one persona's trace, preference store and grade table is roughly 2.2x too narrow, and it let small deltas read as excluding zero that the clustered test does not support. Which deltas clear zero is read from the tables below on each regeneration, never restated here: it moves with the deterministic order the stand-in is compared against, and an earlier version of this paragraph that named three of them went stale for exactly that reason.

Generator version: `1.0.0` · Seed: `20260913` · Dataset digest: `34adab71f123746c…` · Weights digest: `52cf7aada06a2033…` · Recording digest: `77ed0c40e2c658e2…`

Recording: 97 entries across `core.json`, `holdout.json` · model `synthetic-scripted-stand-in-v1` · synthetic.

### Core set (60 cases)

Recorded: 60/60 cases · recording misses: 0

| Metric | `llm_recorded` | delta vs deterministic `full` |
|---|---|---|
| NDCG@1 | 0.8500 [0.7071, 0.9714] (n=60, n_clusters=10) | identical on every case |
| HitRate@3 (rel=3) | 0.5667 [0.3333, 0.7833] (n=60, n_clusters=10) | +0.0167 [+0.0000, +0.0500] (n=60, n_clusters=10; **includes 0**) |
| slate_ndcg@3 | 0.8643 [0.7403, 0.9609] (n=60, n_clusters=10) | +0.0010 [-0.0067, +0.0096] (n=60, n_clusters=10; **includes 0**) |
| NDCG@3 | 0.7772 [0.6465, 0.8902] (n=60, n_clusters=10) | -0.0152 [-0.0316, +0.0005] (n=60, n_clusters=10; **includes 0**) |
| context_rule_conformance@3 | 0.9922 [0.9804, 1.0000] (n=60, n_clusters=10) | -0.0006 [-0.0117, +0.0099] (n=60, n_clusters=10; **includes 0**) |
| P@3 (taste match) | 0.3278 [0.1611, 0.5111] (n=60, n_clusters=10) | -0.0278 [-0.0611, +0.0000] (n=60, n_clusters=10; **includes 0**) |
| MRR | 0.5765 [0.3711, 0.7614] (n=60, n_clusters=10) | +0.0025 [+0.0000, +0.0071] (n=60, n_clusters=10; **includes 0**) |
| unknown_admitted@3 | 0.1500 [0.1333, 0.1667] (n=60, n_clusters=10) | +0.0222 [+0.0000, +0.0556] (n=60, n_clusters=10; **includes 0**) |
| category_entropy@3 | 1.5405 [1.4627, 1.5850] (n=60, n_clusters=10) | +0.1417 [+0.0528, +0.2612] (n=60, n_clusters=10; excludes 0) |

| Arm metric | value |
|---|---|
| planner_agreement@3 (agent-mode runs) | 0.9333 [0.8778, 0.9778] (n=60, n_clusters=10) |
| narrowing_rate (agent-mode runs) | 0.2110 [0.1942, 0.2269] (n=60, n_clusters=10) |
| max_promotion_observed | 3 place(s) |
| guardrail_rejection_rate | 0/60 (0.00%) (rejected proposals / proposals) |
| fallback_rate[`agent`] | 60/60 (100.00%) |

`agent` is listed among the modes and is not a fallback: every run has exactly one mode and the modes sum to the case count, so no fallback rate can be quoted without its denominator.

| Cost (SYNTHETIC -- see NOT_A_MODEL) | value |
|---|---|
| latency p50 | 925 ms |
| latency p95 | 1604 ms |
| tokens per run (mean) | 3364.9 |
| tokens per run (p95) | 3512 |

Cost figures are reported, never asserted: no test gates on them.

| Guardrail rule | rejections |
|---|---|
| (none bound on this split) | 0 |

### Holdout set (24 cases)

Recorded: 24/24 cases · recording misses: 0

| Metric | `llm_recorded` | delta vs deterministic `full` |
|---|---|---|
| NDCG@1 | 0.7302 [0.5635, 0.8968] (n=24, n_clusters=4) | identical on every case |
| HitRate@3 (rel=3) | 0.4167 [0.0000, 0.8333] (n=24, n_clusters=4) | identical on every case |
| slate_ndcg@3 | 0.8199 [0.6942, 0.9456] (n=24, n_clusters=4) | -0.0026 [-0.0272, +0.0196] (n=24, n_clusters=4; **includes 0**) |
| NDCG@3 | 0.7078 [0.5582, 0.8574] (n=24, n_clusters=4) | -0.0289 [-0.0708, +0.0130] (n=24, n_clusters=4; **includes 0**) |
| context_rule_conformance@3 | 1.0000 [1.0000, 1.0000] (n=24, n_clusters=4) | +0.0180 [+0.0000, +0.0540] (n=24, n_clusters=4; **includes 0**) |
| P@3 (taste match) | 0.1528 [0.0000, 0.3056] (n=24, n_clusters=4) | -0.0694 [-0.1389, +0.0000] (n=24, n_clusters=4; **includes 0**) |
| MRR | 0.3713 [0.0344, 0.7083] (n=24, n_clusters=4) | +0.0007 [+0.0000, +0.0022] (n=24, n_clusters=4; **includes 0**) |
| unknown_admitted@3 | 0.1389 [0.0833, 0.1667] (n=24, n_clusters=4) | +0.0139 [-0.0417, +0.0833] (n=24, n_clusters=4; **includes 0**) |
| category_entropy@3 | 1.3905 [1.2516, 1.5294] (n=24, n_clusters=4) | +0.3197 [+0.1111, +0.5074] (n=24, n_clusters=4; excludes 0) |

| Arm metric | value |
|---|---|
| planner_agreement@3 (agent-mode runs) | 0.8611 [0.7778, 0.9444] (n=24, n_clusters=4) |
| narrowing_rate (agent-mode runs) | 0.2191 [0.2039, 0.2343] (n=24, n_clusters=4) |
| max_promotion_observed | 3 place(s) |
| guardrail_rejection_rate | 0/24 (0.00%) (rejected proposals / proposals) |
| fallback_rate[`agent`] | 24/24 (100.00%) |

`agent` is listed among the modes and is not a fallback: every run has exactly one mode and the modes sum to the case count, so no fallback rate can be quoted without its denominator.

| Cost (SYNTHETIC -- see NOT_A_MODEL) | value |
|---|---|
| latency p50 | 1064 ms |
| latency p95 | 1699 ms |
| tokens per run (mean) | 3367.4 |
| tokens per run (p95) | 3523 |

Cost figures are reported, never asserted: no test gates on them.

| Guardrail rule | rejections |
|---|---|
| (none bound on this split) | 0 |

