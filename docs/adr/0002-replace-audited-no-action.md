# ADR 0002: What replaces `audited_no_action`

Status: Accepted (2026-09-13), with one amendment. M8 unsupported restraint and M10
context-dependent restraint are the restraint measures that lead. M7 (which restates M1's
complement wherever nothing is suppressed) and M9 (a logging check by construction) stay in the
technical tables only, labelled as such, and are not quoted in any headline or story copy.

## Context

The evaluation harness (`apps/api/src/silverloop/evaluation/`) folds three policies --
`fixed_threshold`, `contextual_rule` and `silverloop` -- over identical, decision-independent
replayed scenarios and scores them against a `metrics.py::PolicyMetrics` (M1-M6 in the generated
report, `docs/evaluation/policy-comparison.{json,md}`, read by `apps/web/lib/policy-comparison.ts`
and rendered by `apps/web/components/evidence-view.tsx`).

`audited_no_action` (M4) was defined as: denominator = every `QUIET` decision (`NO_ACTION` or
`SUPPRESS`); numerator = those with a non-empty rationale and a non-empty `quality_evidence_id`.

Measured before this change, `silverloop` scored 24/24 (100%) on M4 in **every arm of both
scenario sets** (core capped, core uncapped, holdout capped, holdout uncapped, and every gate
ablation). That is not a finding, it is a tautology: `silverloop.policy.decide`
(`server/src/silverloop/policy.py`) attaches a rationale on every branch and
`quality_evidence_id` comes from `signal.quality.evidence_id`, which `analyse_signal` populates
unconditionally, independent of which policy is folded over the step or what that policy decided.
The predicate cannot fail for Care+ by construction. For the two baselines, the harness
itself inflates the "audited" count further by appending `BUDGET_WITHHELD_RATIONALE`
(`evaluation/fold.py`) whenever the harness's uniform contact cap converts a would-be contact into
`SUPPRESS` -- so a meaningful fraction of a baseline's M4 numerator is the harness's own logger,
not the baseline's judgement. Despite this, the web UI (`evidence-view.tsx`) rendered M4 under the
label **"Correct no-action"** (`UI_TERMS.correctNoAction`, `apps/web/lib/view-models.ts`) and used
it in the Mr Ravi persona story to claim "a correct no-action on {M4}" -- a correctness claim the
metric never supported. `docs/WAYFINDER.md` already flagged this as open work: "M4
`audited_no_action` rework (the tautology is documented in the audit; the fix changes committed
numbers and the web reader, next slice)."

The harness already has the ingredients to measure the real question -- was a `NO_ACTION`
correct? -- because `scenario_spec.GroundTruthState` (`stable`, `explained_dip`,
`emerging_decline`, `persistent_decline`, `unusable_data`, `no_consent`) is world state, assigned
independently of any policy's decision, and never derived from `expected_decisions` (the
anti-circularity guard in `scenario_spec.py` rejects a `labels:` entry that is a `Decision`
member). M1/M2/M3/M6 already score against it; M4 was the one metric in the file that did not.

## Options considered

The ticket proposed four ground-truth-based candidates. All four turned out to be answering
different questions, so the decision below implements all four rather than choosing one -- with
one exception (see "Decision" for why `emerging_decline` is excluded from the "requires
intervention" set).

1. **Correct restraint rate** -- correct `NO_ACTION` / opportunities where ground truth says
   outreach was unnecessary. Cheap: same denominator M1 already uses
   (`{stable, explained_dip}`), computed from `DecisionRecord`s the harness already produces.
2. **Unsupported restraint** -- `NO_ACTION` / situations labelled as requiring intervention.
   Cheap: same denominator M2/M3 already use (`persistent_decline`).
3. **Restraint explanation coverage** -- `NO_ACTION` with >=1 evidence-backed explanation / all
   `NO_ACTION`. This is the same predicate M4 already computes
   (`_has_evidence_backed_rationale`), just re-scoped to `NO_ACTION` only instead of `QUIET`
   (`NO_ACTION` + `SUPPRESS`). Its value is narrower than it looks -- it is still a logging check,
   not a correctness check -- but it is honest about what it is scoped to (reasoned silence, not
   a budget/consent block dressed up in `SUPPRESS`'s own bookkeeping rationale).
4. **Context-dependent restraint** (ablation) -- `NO_ACTION` that becomes outreach when
   explanatory context (rain) is removed. This is the one candidate that does not read the
   ground-truth label at all; it reads two already-computed ablation arms
   (`silverloop_all_gates` vs `silverloop_no_rain_context`, from `evaluation/ladder.py` /
   `protocol.py`, which the equivalence test in `test_evaluation.py` proves is a faithful
   transcription of `policy.py`). It answers a genuinely different question from 1-3: not "was
   the silence correct" but "how much of the silence depends on this one specific gate, as
   opposed to some other gate that would have kept it quiet anyway".

Evidence gathered by actually running the harness (`uv run python -m silverloop.evaluation
../../scenarios --out ../../docs/evaluation`, see "Decision" for the numbers): candidates 1-3 are
computable directly from `DecisionRecord`s already produced by every arm, at zero additional
replay cost. Candidate 4 requires cross-referencing two policy variants' records for the same
`(scenario, step)`, which the existing ablation arm already replays -- no new environment replay
needed, just a join keyed on `(scenario, step)` instead of the existing `zip(..., strict=True)`
(which assumes matching order/length; the join is used here for clarity, not because the ablation
arm's ordering was found to be unsafe).

**Rejected refinement**: scoring "requires intervention" as `{persistent_decline,
emerging_decline}` rather than `persistent_decline` alone. The labelling rule
(`evaluation/report.py::LABELLING_RULE`) assigns `emerging_decline` to a dip that has not yet
persisted three valid-wear low days -- precisely the window the rain-context and
severity/persistence gates are designed to wait out before acting. Counting `emerging_decline` as
"requires intervention" would score the ladder's own designed patience as a miss, and would also
break consistency with M2/M3's existing denominator. Kept as `persistent_decline` only, matching
M2/M3.

**What retiring M4 outright would have cost**: M4 does catch a real (if narrow) regression class
-- a future ladder branch that returns `NO_ACTION` with an empty rationale list, or a
`quality.evidence_id` that silently stops being populated. Deleting the field would lose that
smoke test with no compensating coverage (M9's `NO_ACTION`-only scope does not cover `SUPPRESS`,
which M4 still checks). Renaming and relabelling it honestly keeps the check without the
misleading "correctness" framing.

## Decision

1. **Rename, do not retire, M4.** `audited_no_action` -> `no_action_logging_integrity`
   (`PolicyMetrics` field, JSON key, Markdown column, and the `RESTRAINT_NOTE` printed directly
   above its table). Denominator and numerator are unchanged (`QUIET` decisions;
   evidence-backed-rationale predicate). It is now documented, everywhere it appears, as a
   logging-integrity check, not a correctness measure.

2. **Add M7 correct restraint.** Denominator: steps labelled `stable` or `explained_dip`
   (`NO_INTERVENTION_NEEDED`, same set M1 uses). Numerator: decision == `NO_ACTION` specifically.
   `SUPPRESS` does **not** count, even though it is quiet: a `SUPPRESS` here means consent or the
   contact budget blocked a contact the policy _wanted_ to make, which is not evidence of correct
   judgement. `COORDINATOR_REVIEW` and any `CONTACT` decision are excluded from the numerator by
   construction (neither is `NO_ACTION`).

   **Correction (post-review): M7 is an algebraic identity of M1, not independent evidence, on
   the arms this harness has actually run.** On the shared denominator, every step is exactly one
   of `ACTION` (M1's numerator), `NO_ACTION` (M7's numerator) or `SUPPRESS`, so
   `correct_restraint.rate == 1 - unnecessary_contact.rate - suppress_share`. M7 only adds
   information beyond M1 when `SUPPRESS` is non-zero on `stable`/`explained_dip` steps. On every
   arm and scenario set replayed so far, no policy `SUPPRESS`es on those steps, so
   `suppress_share == 0` and M7 is exactly `1 - M1` -- restating the same fact under a different
   name, not a second finding. The web headline (`evidence-view.tsx`) previously plotted both as
   if they were independent bars; see "Consequences" for the fix. M7 is still worth reporting
   (it reads naturally as "how often was quiet actually right", and it is the number the M10
   ablation and the persona narrative build on), but every place it is printed now states the
   identity beside it rather than implying a second, independent correctness result.

3. **Add M8 unsupported restraint.** Denominator: steps labelled `persistent_decline`
   (`INTERVENTION_NEEDED`, same set M2/M3 use). Numerator: decision == `NO_ACTION` specifically --
   the policy presented reasoned inaction on a step that needed help. `SUPPRESS` on one of these
   steps is already counted by M2 ("missed persistent change") and is excluded here on purpose: a
   budget/consent-withheld contact is a different failure mode from the policy concluding, in its
   own rationale, that nothing was wrong. `COORDINATOR_REVIEW` and any `CONTACT` decision score as
   correct and are excluded from the numerator. Reported beside M2 in the restraint table (they
   share a denominator) so a reader can see directly whether the two diverge; they do exactly
   when a policy `SUPPRESS`es on a `persistent_decline` step, since M2 counts that as missed and
   M8 does not -- on the headline (capped) arm both baselines diverge sharply (`fixed_threshold`
   M2 13/19 vs M8 1/19; `contextual_rule` M2 15/19 vs M8 6/19), because the harness's uniform
   contact cap converts many of their would-be contacts on those steps into `SUPPRESS`.

4. **Add M9 restraint explanation coverage.** Denominator: every `NO_ACTION` decision (`SUPPRESS`
   excluded -- its rationale explains a consent/budget block, not a judgement of restraint).
   Numerator: the same evidence-backed-rationale predicate M4 uses. A policy that never emits
   `NO_ACTION` reports `0/0` (n/a).

   **Correction (post-review): M9 is a second logging-integrity check, not a correctness measure,
   and its baseline variation is not a restraint-quality finding.** M9 uses the identical
   predicate M4 uses, merely re-scoped from `QUIET` to `NO_ACTION`. `silverloop.policy.decide`
   attaches a rationale on every `NO_ACTION` branch, so M9 is 100% for it by the same
   construction that makes M4 100% for it -- not because ground truth was consulted. The
   baselines' scores are not evidence of worse judgement either: `fixed_threshold_decide`'s
   `NO_ACTION` branch always returns an empty rationale list (`baselines.py`), so its M9 is
   mechanically 0%, and `contextual_rule_decide` mixes branches that do and do not attach prose.
   Kept, not retired: M9 still catches a narrower regression than M4 (a `NO_ACTION` branch
   specifically, as opposed to a `SUPPRESS` branch, that stops writing a rationale), and removing
   it would lose that without adding coverage elsewhere. But it belongs with M4 in the
   logging-integrity family, not beside M7/M8 as a correctness measure, and every place it is
   printed now says so.

5. **Add M10 context-dependent restraint**, ablation-only (not a `PolicyMetrics` field -- it
   compares two policy variants, not one policy against ground truth). Denominator: every step
   `silverloop_all_gates` (the ablation reference, proven decision-for-decision identical to
   `policy.decide`) decided `NO_ACTION`. Numerator: of those, how many become `ACTION`
   (`CONTACT` or `COORDINATOR_REVIEW`) once `silverloop_no_rain_context` alone is run instead.
   Reported per scenario set (core, holdout) beneath the existing gate-ablation table.

6. **Every rate uses the harness's existing `Rate.formatted()`** (`n/d (rate%)`, or `n/d (n/a)`
   when the denominator is 0) in both Markdown and JSON (`{numerator, denominator, rate}`) -- no
   new formatting convention, and no bare percentage is ever printed. Several of the numbers below
   have single-digit denominators (holdout `missed_persistent_change`/`unsupported_restraint` is
   `n=1`); they are reported as `1/1` or `0/1`, not "100%" or "0%" alone.

### Numbers actually run (`docs/evaluation/policy-comparison.json`, seed 2026, headline budget-matched arm)

Core set (59 steps). M7's core `silverloop` result below (**17/17, 100%**) inherits the same
honest caveat `LABELLING_CAVEAT` already states for M1: the `stable`/`emerging_decline` boundary
these steps sit on the safe side of is the same -20% figure `policy.py`'s own nudge rung uses, so
M1/M7 near that boundary are not fully independent of the thing being scored:

| Policy            | M4 (logging)    | M7 correct restraint | M2 missed persistent change | M8 unsupported restraint | M9 explanation coverage |
| ----------------- | --------------- | -------------------- | --------------------------- | ------------------------ | ----------------------- |
| `fixed_threshold` | 16/38 (42.11%)  | 12/17 (70.59%)       | 13/19 (68.42%)              | 1/19 (5.26%)             | 0/22 (0.00%)            |
| `contextual_rule` | 21/44 (47.73%)  | 12/17 (70.59%)       | 15/19 (78.95%)              | 6/19 (31.58%)            | 8/30 (26.67%)           |
| `silverloop`      | 24/24 (100.00%) | 17/17 (100.00%)      | 0/19 (0.00%)                | 0/19 (0.00%)             | 20/20 (100.00%)         |

Holdout set (22 steps):

| Policy            | M4 (logging)    | M7 correct restraint | M2 missed persistent change | M8 unsupported restraint | M9 explanation coverage |
| ----------------- | --------------- | -------------------- | --------------------------- | ------------------------ | ----------------------- |
| `fixed_threshold` | 6/14 (42.86%)   | 6/12 (50.00%)        | 1/1 (100.00%)               | 0/1 (0.00%)              | 0/8 (0.00%)             |
| `contextual_rule` | 5/15 (33.33%)   | 6/12 (50.00%)        | 1/1 (100.00%)               | 0/1 (0.00%)              | 1/9 (11.11%)            |
| `silverloop`      | 14/14 (100.00%) | 9/12 (75.00%)        | 0/1 (0.00%)                 | 0/1 (0.00%)              | 10/10 (100.00%)         |

Context-dependent restraint (M10, ablation, uncapped by construction):

| Scenario set | M10           |
| ------------ | ------------- |
| core         | 2/20 (10.00%) |
| holdout      | 1/10 (10.00%) |

**Corrected reading of these numbers.** M4 is 100.00% for `silverloop` on every row above, as
predicted -- it cannot fail by construction, and this repeats the same tautology finding rather
than adding new evidence. **M7 is not independent of M1 here**: `SUPPRESS` never appears on a
`stable`/`explained_dip` step for any of the three policies on either set (checked against the
ledger directly), so `correct_restraint.rate == 1 - unnecessary_contact.rate` exactly in every
cell -- holdout `silverloop` M7 `9/12 (75.00%)` is arithmetically `1 - 3/12`, where `3/12` is
`silverloop`'s holdout M1. The only substantive movement in that row is M1 itself (`silverloop`
goes from 0/17 unnecessary contact on core to 3/12 on holdout -- it is not perfectly
discriminating on unseen scenarios); M7 restates that shift with its sign flipped, not a second,
independently-measured fact. **M9 is not independent of M4 for the same reason**: it is M4's
evidence-backed-rationale predicate re-scoped to `NO_ACTION`, so `silverloop`'s 100.00% here is
exactly as construction-locked as its M4, and the baselines' numbers (0% for `fixed_threshold`,
part-way for `contextual_rule`) reflect which of their `NO_ACTION` branches attach prose
(`baselines.py`), not a restraint-quality difference between them.

**M8 is the metric in this family that actually discriminates**, and it diverges visibly from M2
on their shared denominator: `fixed_threshold` core M2 is `13/19 (68.42%)` but M8 is
`1/19 (5.26%)`; `contextual_rule` core M2 is `15/19 (78.95%)` but M8 is `6/19 (31.58%)`. The gap
is the harness's uniform contact cap converting most of those policies' would-be contacts on
`persistent_decline` steps into `SUPPRESS` (counted by M2, not M8) rather than a `NO_ACTION`
judgement call (counted by both). `silverloop` is 0/19 on both M2 and M8 on core and 0/1 on both
on holdout -- it never presents reasoned inaction on a step this replay's ground truth says
needed help, on either scenario set.

## Consequences

- `PolicyMetrics.audited_no_action` is renamed to `no_action_logging_integrity`; any code reading
  the old field name breaks (none exists outside this repo; the two similarly-named product tests
  `test_stale_programme_fixture_becomes_audited_no_action` and
  `test_when_every_candidate_is_suppressed_the_result_is_an_audited_no_action` in
  `server/tests/` test the _product's_ audit-trail invariant, not this metric, and are
  unaffected).
- `docs/evaluation/policy-comparison.{json,md}` schema version bumped 2 -> 3 (new/renamed keys);
  regenerated and committed by this change (`pnpm evaluate` / `uv run python -m
silverloop.evaluation ../../scenarios --out ../../docs/evaluation`).
- `apps/web/lib/policy-comparison-types.ts` / `policy-comparison.ts` gain `noActionLoggingIntegrity`,
  `correctRestraintRate`, `unsupportedRestraintRate`, `restraintExplanationCoverage`. The
  Technical-details table (`PolicyComparisonTable`, behind `<details>`) and the Mr Ravi story
  still read `correctRestraintRate` under the "Correct no-action" label -- both present M1 and M7
  together in one place, so the relationship between them is visible rather than hidden.

  **Correction (post-review): the page's headline visual summary (`HEADLINE_METRICS` /
  `PolicyBarGroup`, and the plain-English table directly beneath it in the same card) previously
  plotted `correctRestraintRate` (M7) as a THIRD bar next to `unnecessaryContact` (M1), which --
  given the M7/M1 identity above -- showed the same fact twice under two different names and two
  different colours. Both were changed to plot `unsupportedRestraintRate` (M8) instead: a
  different denominator from M1 (steps that DID need outreach, not steps that didn't), so it is
  not M1's complement, its sample size on the arm the headline reads from (core, uncapped: n=19)
  is large enough to report honestly, and -- unlike M10 -- it is defined for all three policies,
  so it fits the existing one-bar-per-policy layout without inventing a number for baselines that
  have no gate ablation. `UI_TERMS.unsupportedRestraint` ("Unsupported restraint") was added; the
  existing `correctNoAction` term is kept for the Technical-details table. No `e2e` test
  asserted on the removed "Correct no-action" headline text (checked directly).**

- `docs/testing.md` updated to describe M7-M10, to state plainly that M4 and M9 are both logging
  checks (not correctness measures), and to state the M7/M1 identity.
- No scenario YAML label was edited; every new metric is computed from labels that already exist.
- `pnpm --filter web typecheck` and `pnpm --filter web lint` pass with the renamed/added fields;
  `uv run pytest -q` (full suite) and `uv run ruff check .` / `ruff format --check .` pass;
  `python -m silverloop.evaluation ../../scenarios --out ../../docs/evaluation --check` (the
  `evaluate-check` Nx target) passes against the regenerated, committed artifacts.

## What would change our mind

- If a future scenario set makes M7/M8 converge to 100%/0% for `silverloop` the same way M4
  always did, that would mean the ground-truth labelling rule has become circular with the
  policy again (the same failure mode `LABELLING_CAVEAT` already flags for the -20% boundary
  shared between the `stable`/`emerging_decline` label cut and the nudge rung) and the labelling
  rule, not the metric, would need to change.
- **M7's value as a reported metric depends on a `SUPPRESS`-on-no-intervention-needed scenario
  existing.** Right now M7 is a pure identity of M1 (`correct_restraint == 1 - unnecessary_contact`
  on every arm this harness runs) because no policy ever `SUPPRESS`es a `stable`/`explained_dip`
  step. If a scenario is added where that happens -- e.g. a `stable` day with consent revoked, or
  one that lands after the contact budget is spent -- M7 would start to diverge from `1 - M1` and
  would then be carrying information M1 does not. Until such a scenario exists, M7 should continue
  to be printed with its identity stated alongside it (as this ADR and `RESTRAINT_NOTE` now do),
  never as a lone bar implying an independent result.
- **M9 is kept as a second logging-integrity check, paired with M4, not as a correctness metric.**
  If a full audit of every scenario ever shows M9 and "M4 restricted to `NO_ACTION` records" are
  always numerically identical (i.e. `SUPPRESS`'s bookkeeping rationale never actually changed
  what M4 would have shown on the `NO_ACTION` subset), that would mean M9 has never yet caught
  anything M4 alone would have missed, and retiring M9 in favour of that computation inline would
  be reasonable. Kept separate for now because M4's `QUIET` scope is a deliberate, documented
  choice (see `PolicyMetrics.no_action_logging_integrity` docstring) that a future change should
  not have to re-derive from first principles, and because M9's narrower scope is cheap to keep.
- If a scenario is added with revoked consent, good wear-time and an unspent contact budget (the
  gap `_gate_verdict_section` already names for the `consent` gate), M10 should be extended to a
  consent-context variant alongside the existing rain-context one.
