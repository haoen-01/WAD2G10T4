# Holdout scenarios

Five scenarios added **after** the decision ladder was frozen, to answer the fair objection that
the core 15 were written alongside the policy that passes them.

## Rules this set is held to

1. **No threshold in `policy.py`, `analytics.py` or `quality.py` was changed, tuned, or
   re-checked against these scenarios.** If a holdout scenario fails, that is reported; it is not
   a reason to move a threshold.
2. **Kept apart from the core set.** `server/tests/test_scenarios.py` runs these through the real
   `SqlAlchemyRepository` exactly like the core files, but as their own test cases, and checks
   that the core glob (non-recursive) never picks this directory up.
3. `expected_decisions` / `expected_cases` record what the real pipeline does on each day.

## Labels (world state, never a policy decision)

Each step also carries a `labels:` entry, assigned before the decisions were read, from the
replayed world state, applied in order:

| Condition (from the replayed environment)            | Label                |
| ---------------------------------------------------- | -------------------- |
| Consent inactive                                     | `no_consent`         |
| Wear-time below the 8h minimum                       | `unusable_data`      |
| A dip under an unrefuted rain explanation            | `explained_dip`      |
| Better than −20% against the person's **own** median | `stable`             |
| Worse, with fewer than 3 consecutive valid-wear lows | `emerging_decline`   |
| Worse, with 3 or more                                | `persistent_decline` |

The −20% boundary is the same number the policy's nudge rung uses, so labels near that boundary
are not fully independent of the policy. Rain, consent, wear-time, persistence and escalation are.

## Coverage

`mdm-siti`, `mr-ravi`, `mdm-lim` (×2), `mdm-devi`. `mr-tan` is **not** in the holdout set.

## Changing this set

If a scenario here genuinely has to change, add a new directory (`scenarios/holdout-v2/`) rather
than editing these, so the change is visible.
