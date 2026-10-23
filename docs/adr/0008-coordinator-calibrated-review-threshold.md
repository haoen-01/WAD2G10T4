# 0008 — A coordinator's false-alarm judgement may move, within bounds, when a human is asked

**Status:** accepted, implemented 2026-09-15 on `Jonathan-threshold` (all three stages)
**Supersedes:** the WAYFINDER F16 constraint "overrides … must never rewrite the safety policy".
**Related:** [0007](0007-stated-context-explanations.md) (the window-in-simulated-days rule and "a
decided day is never re-decided", both reused), `policy.py`, `review_threshold.py`,
`review_threshold_replay.py`, `docs/review-threshold-spec.md`, `suggestions.md` → Suggestion 6.

## Context

Every senior reaches a coordinator at the same point: at least 40% below their own baseline for at
least three low days. The baseline is already personal (median of their last 28 valid days) and only
the senior can move it. The point at which a human is asked is not personal. A senior whose activity
naturally swings keeps reaching a coordinator for nothing.

Coordinators already record that they disagreed and why (`HumanAction`, `OverrideReason`, added
2026-09-13). Nothing read those records, and F16 said nothing on the decision path ever may.

## Decision

### 1. Tune the review threshold, never the baseline

"False alarm" is a judgement about whether a case needed a human, not about what is normal for the
person. Moving the baseline would silently change nudges, programme suggestions, the senior's screen
and the evaluation's ground truth. So only two numbers move per senior: how far below baseline, and
for how many low days, before a human is asked.

**Rejected:** letting coordinator feedback adjust the baseline.

### 2. `policy.py` stays deterministic; the threshold is an input to it

`decide` gains `review_threshold` (default 40% / 3 days) and `shadow_review_since` (default `None`).
The review block becomes three rungs, in order: the personal threshold, the absolute floor (60% / 3
days, whatever the personal setting), and the shadow check. All sit after consent, data quality,
confidence and the small-baseline gate, so none can fire when consent is withdrawn or the data
cannot be read. Stated explanations (`< 3` days) and rain (`< 2`) cannot intercept any of them,
because every allowed threshold needs at least three days.

With the default threshold the floor and shadow rungs are unreachable, so every scenario and every
committed evaluation artifact is byte-identical.

### 3. The protections are code, and the agent cannot negotiate them

- Allowed range 30–55% and 3–5 days, with no mixed settings: below 40% only at 3 days. That keeps every
  setting comparable with the starting setting in both dimensions, so going back never asks later. One
  step (5 points or 1 day) per change.
- The absolute floor always asks a human.
- The shadow check recomputes, from stored history, the first day the starting threshold would have
  asked within the current episode. If the personal threshold has not asked three days later, the
  case opens and the senior goes back to the starting threshold. A loosened threshold can delay a
  review by at most three days and can never make a decline disappear.
- A loosened threshold expires after 60 days unless a coordinator re-confirms it.
- Going back to a stricter, previously approved value never waits for approval.
- Nothing loosens unless **both** the proposer named "too tight for this person" **and** the
  coordinator's structured reason was "not a concern for this person". Free-text notes never count.

### 4. Propose, check, approve; append-only

A calibrator (fixed rules in stage 1, an agent in stage 2) only proposes. A pure guardrail rejects
anything outside the rules; a named coordinator approves with a code-computed replay on screen.
Proposals and decisions are two append-only tables; the live threshold is a fold over decisions, read
fresh on every evaluation, the same shape as baseline confirmation. Changes take effect the next
simulated day (ADR 0007 §5: a decided day is never re-decided).

**Rejected:** a second approver. A coordinator may approve a loosening for their own caseload and is
accountable for it; the approval is recorded under their account with the replay they were shown.

### 5. The model call never holds a transaction

A false-alarm review commits first; the calibrator runs with no session open; a second transaction
re-checks that nothing changed and re-runs the guardrail before inserting the proposal, the same
split `advance()` uses.

### 6. The senior is told, not asked

When a loosening takes effect, or a threshold goes back, the senior's home screen shows fixed
wording for seven simulated days. It follows the senior screen's vocabulary rules and asks nothing.

### 7. The agent checks afterwards whether its change was right

After an approved loosening the calibrator keeps watching. A looser setting goes back without
approval, from the next simulated day, when a coordinator marks a case "this should have reached me
sooner", when a much deeper decline (at least 60% below baseline, or the absolute floor) opens a case
within 14 days of the change, or when the shadow check fires. A revert only ever moves to a setting
that asks sooner or the same; if none exists nothing changes and the skip is audited. The shadow check
wins over the other triggers and returns to the starting setting. Fourteen days after a loosening
takes effect Care+ records whether the change was confirmed or not.

Each revert of an agent or fixed-rule change gets one write-up of what the earlier suggestion did not
anticipate (from the agent, or a fixed template when the model is off or fails). It is coordinator
text, checked by the same wording and privacy rules, can never change a setting, and is read back,
fenced, by the agent's next run; a value reverted away from is never proposed again.

A "reached me sooner" mark with nothing loosened starts a one-step tightening proposal, which a
coordinator approves like any other change. No other path proposes asking sooner after a false alarm.

## Consequences

- F16's constraint is reversed for this one path. Overrides still never reach `learning.py` or the
  ranker; the ranking boundary is unchanged.
- `HumanAction`'s docstring, the `CaseReviewRow` comment and the review audit's `learning_boundary`
  text are reworded to say what now reads a review.
- The guardrail at the top of `suggestions.md` ("Cannot bypass or negotiate past safety thresholds")
  now reads: thresholds change only through coordinator approval within fixed bounds, never by the
  agent directly.
- Some real declines reach a human later, by up to three days. That is the trade, accepted for a
  proof of concept; the settings are not tuned with real care teams.
- A persistence run broken by more than two consecutive low-wear days can still be answered by the
  rain or stated-explanation gates on that day. These are existing gap semantics, unchanged here.
- "Missed escalation stays zero with loosened thresholds" is false by construction (a 40% / 4-day
  threshold delays by design). The honest, tested claim is: delay at most three days; the floor always
  fires; nothing loosens without agreement. The committed default-threshold evaluation is unchanged.

## Not done

- **No scenario YAML.** Scenario files cannot express a coordinator review, and adding any breaks the
  authored-label digest. The properties are proven in pytest.
- **Proof that the agent classifies real coordinators' false alarms correctly.** Needs a pilot.
- **Applying the migration to the live Supabase project.** The mirror SQL is written; a human applies it.
