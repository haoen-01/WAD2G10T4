# 0009 — What a review teaches is derived, and context gaps change nothing

**Status:** accepted, implemented 2026-09-16 on `feat/calibration-trust`
**Supersedes:** nothing. **Related:** [0008](0008-coordinator-calibrated-review-threshold.md) (the
review setting this explains; none of its guarantees change), `review_lessons.py`,
`docs/calibration-trust-spec.md`, `CONTEXT.md`.

## Context

ADR 0008 lets a coordinator's "not a concern for this person" judgement move a senior's review
setting. A coordinator's action is not ground truth, and the product did not show which reviews moved
a setting, which taught nothing, or what a known-context override meant. Only the choices below are
hard to reverse; the rest is in the spec.

## Decision

### 1. A review lesson is computed on read, from the stored review

`review_lessons.classify_review` is a pure function of `status`, `human_action`, `override_reason`,
`reached_too_late` and whether the reviewer is `system`. Nothing about the lesson is stored, so
changing its wording or grouping later needs no migration or backfill. The only new stored fact is
the one a coordinator states and nothing else can recover: the nullable column
`case_reviews.context_gap_category` (Alembic `7c3e9a1f4b28`), not backfilled because no past reviewer
was asked.

**Rejected:** a stored lesson row, which would freeze today's classification into append-only
evidence.

### 2. Context gaps have no policy effect

A context-gap category is tallied per person for the care team and read by no decision, proposal or
review setting. `policy.py`, `review_threshold.py` and `agent/` must never import `review_lessons`;
an import-boundary test (`test_review_lessons_contract.py`) enforces it. The category is also kept
out of the threshold agent's tool payloads.

**Rejected:** letting known context suppress or delay review. It would let an unverified category
silence a real decline.

### 3. The audit records only that a category was given

The `case_reviewed` audit event carries `context_gap_category_present: bool`, never the value, the same
redaction the review note already has (`note_present`). The value lives on the review row and in the
case's action history.

### 4. "Reached too late" wins over known context

Precedence is: system closure (never a human judgement), then `reached_too_late`, then a resolved
`not_a_concern`, then `known_context`, then teaches nothing. A case marked as reaching the coordinator
too late counts toward asking sooner even when it was also overridden for known context, so the signal
that makes Care+ safer is never hidden by a context-gap label. Pinned by test.

### 5. The reviewer-pattern metric lives only in the evaluation

Override rates and put-back shares are reported per simulated coordinator profile in
`docs/evaluation/review-calibration.*`. There is no product route or screen for a per-staff metric.

**Rejected:** a per-coordinator metric on Care Team. It would turn a calibration aid into staff
monitoring, and there is no real reviewer data to justify it.

## Consequences

- A category can only be sent with `human_action=override` and `override_reason=known_context`;
  anything else is a 422.
- Lessons, the review-setting receipt and context-gap tallies are run-scoped, so a demo reset clears
  them, as it clears threshold history.
- The receipt mirrors the calibrator's counting rather than sharing code with it; an equivalence test
  pins the two together.
- The Supabase mirror for the new column is written and must be applied by hand.

## Not done

- Using context gaps to change anything Care+ decides.
- Any evidence that real coordinators' judgements match the simulated profiles.
