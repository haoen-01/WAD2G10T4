# Holdout scenarios

Five scenarios added **after** the decision ladder was frozen, to answer the fair objection that
the core 15 were written alongside the policy that passes them.

## Rules this set is held to

1. **No threshold in `policy.py`, `analytics.py` or `quality.py` was changed, tuned, or
   re-checked against these scenarios.** If SilverLoop scores worse here than on the core set,
   the artifact reports that; it is not a reason to move a threshold.
2. **Labels were assigned before the decisions were read**, from the replayed world state, using
   the single rule below — the same rule the core set follows.
3. **Never pooled with the core set.** `python -m silverloop.evaluation` loads this directory as a
   separate scenario set and reports it in its own tables. `discover_scenarios` globs
   non-recursively, so the core run is unaffected by this directory's existence.
4. `expected_decisions` / `expected_cases` record what the real pipeline does, and exist only for
   the parity gate. Metric computation never reads them — scoring SilverLoop against its own
   output would be circular.

## Labelling rule (world state, never a policy decision)

Applied in order:

| Condition (from the replayed environment)            | Label                |
| ---------------------------------------------------- | -------------------- |
| Consent inactive                                     | `no_consent`         |
| Wear-time below the 8h minimum                       | `unusable_data`      |
| A dip under an unrefuted rain explanation            | `explained_dip`      |
| Better than −20% against the person's **own** median | `stable`             |
| Worse, with fewer than 3 consecutive valid-wear lows | `emerging_decline`   |
| Worse, with 3 or more                                | `persistent_decline` |

Known caveat, stated in the artifact too: the −20% boundary is the same number SilverLoop's own
nudge rung uses, so labels near that boundary are not fully independent of the policy. Rain,
consent, wear-time, persistence and escalation are independent of it.

## Coverage

`mdm-siti`, `mr-ravi`, `mdm-lim` (×2), `mdm-devi`. `mr-tan` is **not** in the holdout set.

## The freeze, and what to do when this set has to change

`FROZEN_DIGEST` in this directory holds the sha256 of these five YAML files' bytes (the same
`_scenario_digest` the harness computes and prints as `Holdout digest`). Every run of
`python -m silverloop.evaluation` prints `holdout_frozen: true|false`, and
`apps/api/tests/test_holdout_freeze.py::test_holdout_digest_matches_frozen_file` fails when the
two disagree.

This does not forbid a change; it makes one **visible**. If a scenario here genuinely has to
change, the answer is a new directory (`scenarios/holdout-v2/`) with its own frozen digest and its
own published numbers — not an edit under the old ones.

One edit has been made since this set was created: commit `4d3ddbd` corrected `h01` step 4's label
from `emerging_decline` to `stable`, because the original had been authored from the rolling median
rather than the anchored one the rule above names. It moved the score **against** SilverLoop (M1
holdout went from 2/11 to 3/12). The freeze exists so that the next such edit is equally legible,
not because that one was hidden.

Holdout-specific numbers are **not** asserted in the unit suite: they live in
`docs/evaluation/policy-comparison.{json,md}`, which `--check` re-verifies byte-for-byte. A unit
test that pins a holdout number has to be edited whenever the production signal pipeline changes,
and an assertion that is edited whenever it fails is not evidence.

The digest was re-taken once on 2026-09-13, when the additive `world:` block (an authored latent
state beside each event; see `docs/evaluation/policy-comparison.md`) landed in these files. No
`labels:` entry or event changed -- `apps/api/tests/test_evaluation.py` pins the labels' own digest
separately -- so the published numbers are unchanged; only the file bytes are.
