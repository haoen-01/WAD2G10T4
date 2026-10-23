# ADR 0003: Relevance and context appropriateness are scored separately, but the ranker stays one order

Status: Accepted (2026-09-13). The rain nudge stays in the ranker on judgement, not on proof;
authoring independent per-listing weather facts to validate it is not planned for the proof of
concept.

## Context

The Wayfinder issue map carries "Decide how relevance and contextual appropriateness are scored
separately", prompted by an observation from the E1 ranking benchmark
(`apps/api/src/silverloop/evaluation/ranking/`): the context ablation (`factor:context`, called
`no_context` when this ADR was written) -- rerunning the full
benchmark with `rain_forecast` forced to `False` -- **improves** `NDCG@3` on the core split by
`+0.0381 [+0.0048, +0.0751]` and on the holdout split by `+0.1890 [+0.1061, +0.2847]` (both
95% CIs exclude zero; numbers from `python -m silverloop.evaluation.ranking` on this dataset,
reproduced below). Read naively, that says "remove the rain nudge and the ranker gets better,"
which would argue for cutting a deliberate, documented product feature (F35: "context on the
action side," `activity_search.py`'s `context` factor).

That reading is wrong, for a structural reason that does not need any new metric to see:
`labels.py` grades relevance from a `PersonaBrief` -- hard constraints, stated tastes, stated
avoids, decline cooldown -- that is never told the weather (see `dataset.py`'s module docstring on
information asymmetry, and `labels.py`'s own docstring). Rain never appears anywhere in a
persona's brief, so a benchmark scored purely against that brief cannot help but read
"indoor/sheltered over outdoor when it's raining" as noise: it moves candidates the label rule has
no opinion about, and by a real, sometimes large amount -- `+0.0381` on core, `+0.1890` on holdout,
not a slight effect -- rather than something the label rule can weigh against what it does reward.
Relevance ("does this suit what they asked and have liked before?") and context appropriateness
("is this a good idea right now, given today's conditions?") are different questions. A gardening
session can be an excellent answer to the first and a poor answer to the second when it is raining.
One benchmark, scored one way, cannot tell those two questions apart -- and had been quietly asking
only the first. **This is an explanation for the size of the effect, not a case that the size is
acceptable**: how much relevance a product should be willing to trade for contextual fit is a
product decision this ADR does not settle, and no per-case analysis here quantifies what a senior
actually loses when the order shifts. See "What would change our mind."

**Correction after lead review.** An earlier draft of this ADR also tried to use a new
`context_rule_conformance_at_3` metric (then named `context_ndcg_at_3`) as _evidence that keeping
the rain nudge is a good idea_, citing a large negative `no_context` delta on it. That argument was
circular and has been removed. The grading rule behind that metric
(`context_labels.grade_context_fit`) does not import `activity_search`, but it deliberately
restates the same rain/environment premise the ranker's own `context` factor encodes (rain +
environment left open + outdoors = worse; an explicit environment ask overrides the forecast).
Measuring the ranker against a rule built from its own premise and then citing agreement as
validation is close to tautological: of course removing the factor a conformance check was defined
from breaks conformance to that check. What that comparison actually shows is narrower and still
useful -- the `context` factor is wired and behaves the way it is declared to behave -- but it is
an **implementation-conformance check**, not independent evidence that the rain nudge itself is a
good idea. This is exactly the label/feature coupling the separate, explicitly out-of-scope ticket
"Make evaluation labels structurally independent of the features they test" exists to address, and
this track does not resolve it by accident via a differently-named metric.

## Options considered

**A. Do nothing; treat the `no_context` NDCG delta as a real regression and remove the rain
nudge from `rank_candidates_with_breakdown`.**
Evidence against: this is exactly the reasoning error described above -- reading a relevance
benchmark's silence on weather as a verdict on weather. It would delete a working, disclosed
product feature purely because a benchmark was never told about weather. Rejected.

**B. Add weather to the relevance labels (`labels.py`) so context and relevance collapse back
into one number.**
Out of scope on two counts: it is not this track's call to edit hand-authored relevance labels
(explicitly excluded by the frontier rules and belongs to the sibling ticket "Make evaluation
labels structurally independent of the features they test"), and it would re-couple two genuinely
different questions the ticket asks to separate. Rejected.

**C. Restructure the ranker into two stages: a relevance order, then a deterministic
context gate/adjustment applied after, with its own reason line -- i.e. move `context` out of
`RANKING_WEIGHTS`'s six blended factors into a distinct post-ranking pass.**
Considered seriously, because it is the more visible way to make "context is a different
question" structural rather than just documented. The current design already has several of the
properties a separate stage would add, independent of any benchmark number:

- `context` is already a **named, independently weighted factor** in `ScoreBreakdown`, never
  folded invisibly into a single number -- an evaluator or the planner tool payload can already
  read its contribution in isolation (`score_candidate`'s `factors` list).
- `context` is already **subordinate to intent**: `_tier()` sorts on `intent + repetition`
  only, so a rain nudge can only ever reorder _within_ a tier the stated request already
  defined, never override what was asked.
- `context` already produces its **own disclosed reason line** (`ReasonBasis.CONTEXT`,
  `_rain_reason`), shown to the senior distinctly from an intent/preference/history line.

What this track does **not** have is real evidence, from this benchmark, that a separate stage
would behave any differently from the current bounded-weight-within-a-tier design for a real
senior -- the conformance metric described above cannot supply that, precisely because it is
built from the same premise it would be checking. Given "restructure the ranker only if the
evidence supports it," and no valid evidence gathered here for or against restructuring, the
correct default is not to change a shipped, working architecture on the strength of a benchmark
artifact alone. Deferred, not rejected: see "What would change our mind" and "Follow-up."

**D. (Chosen) Keep the ranker's single combined order and its existing `context` factor
unchanged. Report a second, separate evaluation metric -- `context_rule_conformance_at_3` --
computed by a declared rule over the case's own context (today's forecast, what was asked,
whether a listing is under cover), alongside relevance NDCG, clearly documented as a conformance
check on the declared rule rather than independent validation of it.**
This is the smallest change that stops relevance and "does the context factor behave as declared"
from being collapsed into one number, without touching `policy.py`, `RANKING_WEIGHTS`, or any
hand-authored relevance label, and without overclaiming what the new metric can show.

## Evidence gathered

All numbers from `cd apps/api && uv run python -m silverloop.evaluation.ranking --out
../../docs/evaluation` on this dataset (seed `20260908`, dataset digest `be0cd61e368cbe1a…`).

The arm was called `no_context` when this ADR was written and is now `factor:context` (M23): it
zeroes the `context` factor's weighted contribution rather than passing `rain_forecast=False`, so
it no longer also removes the CONTEXT reason lines, and it re-runs the production post-scoring
passes. The point estimates are unchanged; the intervals are restated below in both forms, because
the per-case interval on this dataset is about 2.2x too narrow (M22 -- six cases share one
persona).

| Split   | Metric                          | `factor:context` delta vs `full`, per-case CI | ...persona-clustered CI    | What it actually shows                                                                                      |
| ------- | ------------------------------- | --------------------------------------------- | -------------------------- | ----------------------------------------------------------------------------------------------------------- |
| core    | `ndcg_at_3` (relevance)         | **+0.0381** [+0.0048, +0.0741]                | +0.0381 [-0.0140, +0.1109] | Real, but the honest interval **includes zero**: the core relevance cost of the rain nudge is not resolved. |
| holdout | `ndcg_at_3` (relevance)         | **+0.1890** [+0.0986, +0.2760]                | +0.1890 [+0.0388, +0.3392] | Real, larger on holdout, and excludes zero even clustered -- on 4 personas.                                 |
| core    | `context_rule_conformance_at_3` | **-0.4724** [-0.5627, -0.3810]                | -0.4724 [-0.6016, -0.3345] | Expected by construction: the conformance rule restates the factor's own premise. Not independent evidence. |
| holdout | `context_rule_conformance_at_3` | **-0.4107** [-0.5475, -0.2735]                | -0.4107 [-0.6427, -0.1927] | Same caveat.                                                                                                |

**What is real evidence here, and what is not.** The `ndcg_at_3` deltas are real: on this dataset,
the relevance benchmark genuinely scores higher without the rain nudge. The mechanism proposed
above -- `labels.grade_candidate` never reads weather, so it cannot reward or penalise a
weather-driven reorder except as noise around the intent/preference signal it does score -- is
plausible and consistent with the code, but has not been checked case by case here; no per-case
breakdown in this track confirms it is the whole story for every case behind these two numbers, and
`+0.0381`/`+0.1890` are real-sized effects, not something to wave away as noise. The
`context_rule_conformance_at_3` deltas are **not** independent evidence that the rain nudge is
good: they are the expected result of ablating the input a same-premise conformance rule was
written to check, and they would move in the same direction and by a similar magnitude for _any_
weather rule the ranker actually implemented, good or bad. Nothing gathered on this track measures
whether prioritising indoor/sheltered options when it rains is actually a better outcome for a
senior than not doing so, and nothing here settles how much relevance the product should be willing
to spend on contextual fit -- that trade-off is a product decision, not a benchmark result.

## Decision

1. **Evaluation separates the two judgements, honestly labelled.** A new module,
   `apps/api/src/silverloop/evaluation/ranking/context_labels.py`, declares
   `grade_context_fit(candidate, intent, *, rain_forecast) -> {0, 1, 2}` -- GOOD_FIT (no rain, or
   the person explicitly asked for an environment), UNKNOWN_FIT (rain, environment left open,
   listing doesn't say), POOR_FIT (rain, environment left open, listing is outdoors). It does not
   import or call `activity_search`, but its module docstring states plainly that it shares the
   ranker's `context` factor's premise by construction and is therefore a conformance check, not
   an independent judgement. `runner.py` grades every kept candidate on both `labels.
grade_candidate` (relevance, hand-authored, untouched) and `context_labels.grade_context_fit`
   (conformance, newly declared here), and reports `ndcg_at_3` and
   `context_rule_conformance_at_3` side by side -- never combined into one number -- in
   `docs/evaluation/ranking-evaluation.{json,md}`, with `report.py`'s `METHODOLOGY` stating the
   conformance caveat inline so a reader of the artifact alone cannot mistake one for validation
   of the other.
2. **The ranker keeps one combined order.** `activity_search.py` is unchanged: `context` remains
   one of the six named, bounded, weighted factors in `RANKING_WEIGHTS`, still subordinate to
   intent via `_tier()`, still disclosed via its own `ReasonBasis.CONTEXT` line. No restructuring
   into a separate post-relevance gate/stage is made on this track. This rests on the conceptual
   argument (relevance and context appropriateness are different questions, so a relevance
   benchmark's silence on weather is not a verdict on the rain nudge) and on there being no valid
   evidence, gathered here, that the current bounded-weight design is failing at the thing it
   targets -- not on the conformance metric, which cannot supply that evidence either way.
3. **The relevance benchmark's `no_context` result is documented as an artifact of label scope**,
   not as a regression and not as something the conformance metric resolves, in `report.py`'s
   `METHODOLOGY` string and in this ADR.

## What the blocked sibling ticket should now evaluate against

**Correction after architecture review.** An earlier draft of this section handed the blocked
ticket the existing `no_intent` ablation as "starting evidence." That ablation is confounded and
should not be used for this, and the review that caught it is recorded here rather than quietly
fixed away.

`no_intent` (`ablations.py`) substitutes an empty `ActivityIntent()` for the real intent. Reading
`activity_search.py` shows this changes three things at once, not one:

1. It zeroes the `intent` factor's weighted score term (`score_candidate`'s `intent_fit`), which
   is the thing the sibling ticket is actually about.
2. It also zeroes `intent_fit` identically for every candidate (since `_constrained_axes
(ActivityIntent()) == 0` makes `intent_fit` `0.0` regardless of which candidate is being
   scored), which erases intent's role in `_tier()`'s sort key -- so `no_intent` also disables the
   tier that makes a stated request dominant, not just the soft weighting within a tier.
3. It resets `intent.environment` to `EITHER`, which re-enables `score_candidate`'s rain nudge
   (`apply_rain_bias = rain_forecast and intent.environment == EITHER`) for any case whose real
   intent had asked for a specific environment -- entangling this ablation with the `context`
   factor this ADR is about.

This is not theoretical: on this dataset, `context_rule_conformance_at_3`'s delta under `no_intent`
is `+0.0039 [+0.0000, +0.0117]` on core -- a metric that has nothing to do with intent moves under
an "intent" ablation, because `grade_context_fit` also reads `intent.environment`, and `no_intent`
changed that too. `no_intent`'s `ndcg_at_3` delta (core `-0.0015 [-0.0229, +0.0191]`, holdout
`-0.0147 [-0.0473, +0.0096]`, both CIs crossing zero) is therefore a measurement of "empty intent
vs. real intent," not "intent's soft weighting vs. no soft weighting," and should not be cited as
evidence for that ticket.

**What that ticket actually needs**, specified rather than implemented as a decision here: an
ablation that zeroes only the `intent` factor's weighted CONTRIBUTION to `total`, while leaving
(a) the hard filter (`filter_candidates`, already applied before ranking and unaffected either
way), (b) the tier the candidate is sorted into (still computed from the real intent), and (c) the
environment-aware rain rule (still reading the real `intent.environment`) all intact.

This track added exactly that as a new arm, originally called `no_intent_soft`. **The number this
section first handed on was wrong, and the corrected one is very different.** Both the arm and the
number are restated here rather than quietly replaced, because the way the first one was wrong is
the point.

**What was published (superseded):**

| Split   | `no_intent_soft` `ndcg_at_3` delta vs `full`        |
| ------- | --------------------------------------------------- |
| core    | `+0.0120` [`-0.0050`, `+0.0292`] (CI crosses zero)  |
| holdout | `+0.0517` [`+0.0179`, `+0.0886`] (CI excludes zero) |

Two defects, both since fixed (opportunity-matrix row M23):

1. The arm ran with `diversity=False` but was compared to `full`, which runs the diversity swap.
   Its delta therefore **contained `no_diversity`'s own delta** -- `+0.0045` of the core `+0.0120`
   and `+0.0112` of the holdout `+0.0517`. Every diversity-off arm is now compared to
   `no_diversity`, never to `full`, and each arm's baseline is printed in its header.
2. It re-sorted the breakdowns by hand and never re-ran the production series dedupe afterwards,
   so the top three could contain two sessions of one programme that dedupe had already resolved.
   That alone moved `series_duplication_rate_at_3` by `+0.44`. The arm now hands its re-sorted list
   back to the public `activity_search.postprocess`, so both production passes run.

**The corrected arm is `factor:intent`**, and its delta is:

| Split   | `factor:intent` delta vs `full`, on every reported metric |
| ------- | --------------------------------------------------------- |
| core    | `+0.0000` on all of them -- not a single case moved       |
| holdout | `+0.0000` on all of them -- not a single case moved       |

This is not "the dataset does not exercise the factor": zeroing the `intent` contribution changed a
weighted total on 50 of 60 core cases and 20 of 24 holdout cases, and changed the ranked order on 9
and 4 of them respectively. It changed no metric because **the intent factor's weighted term is
very nearly redundant with the tier it feeds**. `_tier` sorts on `intent.value + repetition.value`
first, so candidates that could be reordered by removing the intent contribution are, with few
exceptions, already separated by the tier; the exceptions (`intent=1, repetition=-1` against
`intent=0, repetition=0`, which share tier 0) reorder below the top three. The artifact prints this
as "masked by the tier sort" rather than as a null.

That is a materially different input to the blocked intent-factor ticket than `+0.0517` was: on
this dataset the soft intent weight buys nothing that the tier does not already buy, and a ticket
proposing to change it should start from that rather than from a number that was mostly the
diversity swap and a skipped dedupe. It remains one data point, not an answer: the benchmark is
synthetic, 60 cases from 10 personas, and `factor:intent` should **not** be evaluated against
`context_rule_conformance_at_3` as validation either for or against itself -- that metric cannot
validate anything it was not built to check, the same lesson this ADR learned about its own
original argument.

## Consequences

- The `no_intent_soft` number this ADR handed to the blocked intent-factor ticket was corrected
  under M23 and is superseded: see the table above. The arm is now `factor:intent`, its delta is
  `+0.0000` on every metric on both splits, and the original `+0.0120` / `+0.0517` contained
  `no_diversity`'s delta and a skipped series dedupe.
- `docs/evaluation/ranking-evaluation.{json,md}` gain one new metric
  (`context_rule_conformance_at_3`) per split and per ablation arm, labelled in `report.py` as a
  conformance check rather than an independent judgement; every existing metric, weight, and
  hand-authored label is untouched. `ranking --check` passes against the regenerated artifact.
- No change to `policy.py`, `RANKING_WEIGHTS`, `models.py`, or any scenario file. No schema,
  consent, or safety-gate implication.
- A regression test
  (`test_removing_context_improves_relevance_ndcg_but_breaks_context_rule_conformance`) pins the
  paired numbers above, with its docstring stating explicitly that the conformance-side assertion
  is expected-by-construction, not validation, so a future reader of the test cannot re-acquire
  the reasoning error this ADR was corrected for.
- Slate diversity work (mentioned in the grilling brief as a future consumer) now has a documented
  answer to "diversity of what, optimised against what": diversity operates on the ranker's single
  combined order exactly as today (`_diversify`/`_dedupe_series`), and if it ever needs to reason
  about _why_ a candidate is where it is, `ScoreBreakdown.factors` already carries `context` as a
  distinct, named entry rather than a component hidden inside a scalar.
- A new ablation arm, `no_intent_soft` (`ablations.py`), is added and reported in
  `docs/evaluation/ranking-evaluation.{json,md}` alongside the existing (now re-explained)
  `no_intent` arm. Both are for the blocked sibling ticket's future use, not decided here; this
  track only corrects what `no_intent` measures and supplies the isolated alternative.
  **Renamed under M23**: the two arms are now `factor:intent` and `input:no_intent`, and the
  corrected `factor:intent` number is in the table above.

## Follow-up (not done on this track)

Real validation of the rain nudge -- as opposed to a conformance check on its own premise -- needs
a context-appropriateness judgement authored from a source **other than** the ranker's own rule.
Candidates, in rough order of effort:

- Per-listing weather-sensitivity or shelter-quality facts added to the frozen dataset,
  authored independently of `indoor_outdoor` and not derived from the rain rule the ranker
  applies (e.g. "this outdoor tai chi class runs under a covered pavilion" vs "this one does
  not," a distinction `IndoorOutdoor` cannot currently express).
- Human-authored per-case context-appropriateness labels, the same discipline `labels.py`
  already applies to relevance (a person, not a rule mirroring the code, decides whether each
  top-3 result was a good idea given the stated weather).
- Real usage signal (declined/attended rates on rainy vs. dry days) -- out of scope today: it
  would require a real, authorised data source, which this prototype does not have.
  This is a natural extension of the explicitly out-of-scope sibling ticket "Make evaluation labels
  structurally independent of the features they test," and is recorded here rather than started, so
  it is not lost between the two tickets.

## What would change our mind

- If a future dataset or real-usage signal showed the `context` factor materially _hurting_
  outcomes a senior cares about -- via one of the Follow-up sources above, not via
  `context_rule_conformance_at_3` -- that would revisit point 2.
- If the Follow-up work above ever shipped an independently-authored context-appropriateness
  judgement and it disagreed sharply with the ranker's own rule, that would be real evidence for
  restructuring, unlike the conformance metric this ADR currently reports.
- If the planner tool payload or a future slate-diversity feature needed to _act_ on "this
  candidate was down-weighted for context reasons" as a first-class, queryable fact rather than
  one line in `ScoreBreakdown.factors`, that would be a concrete, evidenced reason to promote
  `context` into Option C's separate stage.
- This ADR does not settle how much relevance a senior should lose for a contextually safer or
  more comfortable option -- that is a product call, not something `+0.0381`/`+0.1890` on this
  benchmark can make. A product owner deciding that trade-off explicitly (e.g. a maximum acceptable
  relevance cost, or a per-case review of what actually moved) would supersede this ADR's point 2.
