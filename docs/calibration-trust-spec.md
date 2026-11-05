# Calibration trust — implementation spec

Status: Accepted; partly removed (see below).
Builds on ADR 0008 and `docs/review-threshold-spec.md`; none of their guarantees change.

> Sections A and B have been removed from the API with the routes no screen used:
> `review_lessons.py`, the `lesson` on a review response,
> the review-setting receipt and context-gap tally, and `POST /v1/cases/{id}/review` itself. The
> `context_gap_category` column stays on `case_reviews` (no table or column was dropped). The
> evaluation seam (D, `authored_metric`) stays.

## Objective

A coordinator's action is not ground truth. Make visible and measurable what each review can teach
Care+, which judgements moved a review setting, and what calibration does to workload and missed
review-worthy cases when coordinators are imperfect.

## Scope

1. **What each review teaches** — a pure classification of every review, an optional context-gap
   category, a per-person context-gap tally, and a "What Care+ learned from this review" panel.
2. **Review-setting receipt** — which reviews counted toward the current proposal or setting, which were
   excluded and why, evidence count beside the existing bounds.
3. **Calibration evaluation** — authored synthetic sequences with a latent review-worthy label, three
   simulated coordinator profiles, three arms, a committed report with `--check`, a chart on `/evidence`.
4. **Reviewer-pattern metric** (cut first) — per simulated profile in the evaluation only.

## Out of scope

Any policy effect of context gaps; changes to `policy.decide`, `review_threshold.py`, the threshold agent's
prompts or tools, `triage.py`, the senior screen; a product-side per-staff metric; continuous
evidence-weighted thresholds; changes to existing authored labels, digests, holdout or evaluation reports.

## Architecture decisions

**A. Storage.** The lesson is a pure function of the stored review
(`status`, `human_action`, `override_reason`, `reached_too_late`, `reviewer == "system"`), computed on
read in a new pure module `silverloop/review_lessons.py`. Precedence:

1. `reached_too_late` → `counts_toward_review_setting` / `reached_too_late`
2. resolved + `OVERRIDE` + `not_a_concern` → `counts_toward_review_setting` / `not_a_concern`
3. `OVERRIDE` + `known_context` → `records_context_gap` / `known_context`
4. otherwise → `teaches_nothing` / one of `agreed`, `on_hold`, `data_doubt`, `recent_contact`,
   `other_reason`, `not_resolved`, `no_structured_choice`, `system_closure`

Only the category is new data: nullable `case_reviews.context_gap_category` (Alembic revision on
`485506d5a415`, SQLite append-only triggers restored on downgrade, Supabase mirror SQL written, not
applied). `policy`, `review_threshold` and `agent.*` must never import `review_lessons` (tested).

**B. Contract** (`models.py`, additive):

- Enums `ContextGapCategory` (`away`, `already_in_touch`, `resting_or_recovering`, `other_known`),
  `ReviewLessonKind`, `ReviewLessonReason`, `ReviewReceiptStatus` (`counted_toward_loosening`,
  `asked_sooner`, `excluded`), `ReviewReceiptExclusion` (`not_eligible_to_loosen`,
  `before_current_setting`, `outside_window`, `after_proposal`, `no_opening_day`).
- `ReviewLesson {review_id, kind, reason, context_gap_category?, summary}` — fixed template text, no
  note text, no activity figures.
- `ReviewReceiptEntry {review_id, case_id, opened_day?, recorded_at, lesson, status, exclusion?, cited,
led_to_proposal_id?, led_to_decision_id?}` — no reviewer, no note.
- `ReviewSettingReceipt {subject: open_proposal|live_setting|next_proposal, proposal_id?, as_of_day,
counted_from_day?, window_start_day, needed, counted, entries, rule}`.
- `ContextGapTally {total, by_category: [ContextGapCount{category?, count}], disclosure}`.
- `ReviewRequest.context_gap_category` (422 unless `OVERRIDE` + `known_context`);
  `ReviewAction.context_gap_category`; `CaseReviewResponse.lesson`;
  `ReviewThresholdState.receipt` and `.context_gaps`.
- No new routes. Audit records `context_gap_category_present: bool`, never the value.

**C. Receipt** is derived in `_threshold_state` from existing review, proposal and decision rows via
`review_lessons.build_receipt`. Subject: open proposal (as of `proposed_on_day`) → else the proposal behind
the live approval → else `next_proposal` as of today ("N of 2 needed"). Only a looser proposal made by
the agent or the fixed rule can be the open or live subject; an asking-sooner proposal or a coordinator's
manual set is skipped, because no review counted toward it. `counted_from` is
`resolve_live_threshold(facts, as_of).effective_from_day`; window is 30 days. `_threshold_episode_context`
is not refactored; an equivalence test pins the receipt's counted set to what the calibrator counts.
Agent proposals show the fixed counting rule plus what the agent cited.

**D. Calibration evaluation** drives the real repository on in-memory SQLite (pattern of
`evaluation/ranking_llm/threshold_sequence.py`).

- Seam: `SqlAlchemyRepository(..., authored_metric: Callable[[str, date], DailyMetric | None] | None = None)`;
  in `advance()` it replaces the event's metric when it returns one (not for `consent_revoked`). Not on the
  Protocol, not over HTTP.
- Package `silverloop/evaluation/calibration/` (`sequences.py`, `profiles.py`, `runner.py`, `metrics.py`,
  `report.py`, `__main__.py`); `evaluation/__init__` does not import it; repository imports are lazy.
- Sequences authored in Python (never under `scenarios/`), with `CALIBRATION_SEQUENCES_DIGEST` pinned.
- Profiles: `accurate`, `dismissive` (always not a concern), `over_cautious` (always agree + reached too
  late). Deterministic.
- Arms: `starting_setting` (never approves), `fixed_rule` (LLM off, approves), `agent`
  (`ScriptedThresholdModel`, approves, no network).
- Metrics: workload, review-worthy retained/missed, max delay vs starting arm, threshold movement,
  put-backs by trigger, floor/shadow cases, calibration skips; reviewer pattern per profile.
- Output `docs/evaluation/review-calibration.{json,md}`: simulated days and counts only, no ids or times.
  Nx `evaluate-calibration[-check]`, chained into root `evaluate` / `evaluate:check`.
- Web: `lib/review-calibration{,-types}.ts` reads the JSON server-side (null-safe);
  `components/review-calibration-card.tsx` (inline SVG workload-vs-misses chart, synthetic disclosure),
  mounted from `app/(platform)/evidence/page.tsx`.

**E. Reviewer pattern** lives only in the evaluation, per simulated profile. No product route.

## Build tracks and file ownership

| Track                | Area     | Files                                                                                                                                                                                                  |
| -------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A1 contract (first)  | backend  | `models.py`, `db_models.py`, migration, mirror SQL, `sql_repository.py` seam, `openapi/`, `client/src/api-client`                                                                                      |
| A2 lessons + receipt | backend  | `review_lessons.py`, `sql_repository.py`, `repository.py`, `main.py`, API tests                                                                                                                        |
| B evaluation         | backend  | `evaluation/calibration/*`, root `package.json`, `docs/evaluation/review-calibration.*`, `test_calibration_evaluation.py`                                                                              |
| C Care Team          | frontend | `view-models.ts`, `review-card.tsx`, `care-team-view.tsx`, `review-threshold-card.tsx` (mount), new `review-lesson-panel.tsx`, `review-setting-receipt.tsx`, `context-gap-tally.tsx`, e2e on `mdm-lim` |
| D evaluator          | frontend | `lib/review-calibration*.ts`, `review-calibration-card.tsx`, `evidence/page.tsx`                                                                                                                       |

## Risks to guard

- Threshold agent prompts and `scripted.json` must not change (no category or lesson in tool payloads).
- `known_context` still produces its `no_change` proposal; the panel says the setting did not change.
- `reached_too_late` wins over `known_context` (pinned test).
- Lesson and receipt text passes `coordinator_text_violations`; nothing new on `/senior` or `/screen-preview`.
- Weekly cap uses the wall clock: author sequences so it never binds; assert zero cap skips.
- UI copy separates `already_in_touch` ("In touch through another service or family") from
  `recent_contact`; the form clears the category when the reason changes.
- Runtime budget for the evaluation ~90s; drop to two sequences before weakening containment checks.
- Resets clear gap tallies and receipts (run-scoped), as with threshold history.

## Acceptance criteria

1. Every human review returns a `lesson` matching `classify_review` across the full input grid; system
   closures are `teaches_nothing/system_closure`.
2. `context_gap_category` accepted only with `OVERRIDE` + `known_context` (else 422); stored, returned in
   action history, absent from audit (presence flag only).
3. `ReviewThresholdState.context_gaps` tallies per category for the active run; categories change no
   decision, proposal or threshold row (test + import-boundary test).
4. After submit, Care Team shows "What Care+ learned from this review": kind, reason, category, and the
   proposal or decision it led to.
5. The review-setting card shows the receipt (counted, asked sooner, excluded with reasons, evidence count)
   beside bounds; counted set equals the calibrator's (equivalence test).
6. Alembic upgrade/downgrade on SQLite and PostgreSQL keeps `case_reviews` append-only; mirror and revision
   pins updated.
7. `pnpm evaluate:check` passes; existing evaluation reports and scenario digests byte-identical;
   `review-calibration.*` regenerates identically.
8. The report covers three arms × three profiles; pytest pins that the dismissive profile is contained:
   missed ≤ starting arm, max delay ≤ 3 days, every ≥60%/3-day episode opens a case.
9. `/evidence` renders the workload-vs-misses chart from the committed JSON, labelled synthetic simulated
   profiles, null-safe.
10. All of the above offline (SQLite, fixtures, LLM off); `pnpm verify` green.

## Validation

`pnpm format:check`, `client:check`, `lint`, `typecheck`, API pytest, web unit tests, e2e on 3100/8100,
`evaluate:check`, `test:scenarios`, `build`; PostgreSQL-gated suites against a local test cluster.
Reviews: code review, design review (Care Team, `/evidence`), architecture check, acceptance check.

## As built

Delivered together with the UX redesign. Deviations from the text above:

- **Precedence.** `classify_review` checks `reviewer == "system"` first, before `reached_too_late`, so a
  malformed system row can never read as a coordinator judgement.
- **`build_receipt` signature.** Keyword-only `reviews`, `proposals`, `facts`, `decisions`, `today`, over
  plain dataclasses (`ReceiptReview`, `ReceiptProposal`, `ReceiptDecision`) and `ThresholdDecisionFact`s
  rather than rows. For a proposal subject only decisions recorded before the proposal are folded. Two
  equivalence tests in `test_review_setting_receipt.py` pin the counted set to the calibrator's.
- **Added from the UX audit.** `ReviewCase.since_last_review`, a server-produced delta from the pure
  `case_delta.py` (nothing new stored; `None` once resolved), and classified error bodies for stored demo
  state that predates the contract (`stored_state.py`, `error_responses.py`).
- **Placement.** Care Team became a grouped roster, so the lesson panel and context-gap tally sit on the
  case page (`/care-team/cases/[caseId]`) and the receipt and tally on the person's review-timing page
  (`/care-team/review-timing/[personId]`). The calibration card is inside the Policy Evaluation tab's
  "Review-setting calibration" section (`/evaluation#calibration`).
- **Agent arm.** The scripted stand-in proposes after a single "not a concern" review, where the fixed
  rule waits for two, so the agent arm loosens earlier and more often. It is a stand-in, not a model.
- **Containment margin.** The dismissive profile's worst delay is 3 days in both loosening arms: exactly
  the shadow-check grace, with no slack. Containment holds in every cell.
- **Weekly cap headroom.** At most 4 proposals in any run (agent arm, dismissive, `slow_slide`) against a
  cap of 5; zero cap skips is asserted, but the margin is one proposal.
- **Not yet done.** The Supabase mirror `202609160020_review_context_gap.sql` is not applied; the live
  threshold-agent recording is still open.
