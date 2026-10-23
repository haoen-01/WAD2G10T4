# Review-threshold calibrator — implementation spec

Status: accepted for build, 2026-09-15. Map: [Wayfinder: the review-threshold calibrator, built in three stages](https://github.com/peachoolongtee/ismoggers/issues/42).

Sources: `suggestions.md` → "# Suggestion 6" (the feature, its settings and its eight decisions) and
`docs/handover-review-threshold.md` (investigation; removed 2026-10-18, in git history). This spec is the architect review of
2026-09-15 against branch `Jonathan-threshold` (Jonathan + `origin/main`), with the lead's amendments
marked **[lead]**. Line numbers are from that date; search by name.

Reconciled 2026-09-15 with PR #50 (care-priority board, `main` @ 1d2b4fb), merged into the build branch
before tracks C and D start. See "Reconciliation with care priorities (PR #50)" and §13.

## Objective

Let a coordinator's structured false-alarm judgement tune, per senior and within fixed bounds, the
point at which Care+ asks a human (the review threshold), never the baseline. The agent
proposes, code bounds it, a coordinator decides, and the agent checks afterwards whether it was right.

## Scope

All three stages of Suggestion 6 on the real code paths, one commit per stage on `Jonathan-threshold`:

1. **Fixed-rule calibrator** with every protection (range, floor, shadow check, expiry, immediate
   revert), storage, approval flow, review-form reasons, senior notice (plus a read-only Demo Tools
   senior-screen preview, §13), fixed-rule proposer, sixth
   persona, per-person demo reset, guided scenario, Care Team screens.
2. **Threshold agent**: read-only tools, four-way cause classification, guardrail, fallback.
3. **Checking afterwards**: far-more-severe revert, checking-period close, write-ups fed back,
   tightening rounds, replay recording, ADR and docs.

## Out of scope

- Any change to `analytics.py` (the baseline) or to nudges, programme suggestions, consent, data
  quality, the contact cap and the outreach planner.
- New scenario YAML, authored-label or holdout changes (`AUTHORED_LABEL_DIGEST` and
  `docs/evaluation/*` stay byte-identical).
- Applying the migration to the live Supabase project (the mirror SQL is written; a human applies it).
- A PR to `main`; a real-care-team pilot; a live recording made by an agent (the user records
  `live_demo.json`).
- Showing a non-default persona on `/senior` with auth off. `/senior` stays pinned to `DEMO_PERSON_ID`;
  any persona's senior home is previewed read-only at Demo Tools `/screen-preview` (§13).
- Changes to `triage.py` windows, ordering, watch thresholds, `CarePriorityRow` or `CareContext` (one
  wording change excepted; see the PR #50 reconciliation).

## Architecture decisions

### Modules

- `silverloop/review_threshold.py` — pure; imports only stdlib and `silverloop.models`. Constants,
  `ReviewThreshold`, live-threshold resolution, structural guardrail, fixed-rule proposer,
  `is_false_alarm`, senior notice wording.
- `silverloop/review_threshold_replay.py` — imports `analytics`, `policy`, `review_threshold`; never
  the DB. Per-day signal series, shadow check, replay, variability summary.
- `silverloop/agent/threshold_guardrails.py` — structural verdict + coordinator-facing wording check.
- `silverloop/agent/threshold_tools.py`, `silverloop/agent/threshold_planner.py` — stage 2.
- `silverloop.evaluation` must still never import `silverloop.agent` or `silverloop.config`.

### 1. Threshold type, policy, attention band, ladder mirror, floor position

```python
@dataclass(frozen=True)
class ReviewThreshold:
    severity_pct: int      # 30..55, multiples of 5
    persistence_days: int  # 3..5
    def fires(self, severity: float, sustained_low_days: int) -> bool:
        return sustained_low_days >= self.persistence_days and severity >= self.severity_pct
    def looser_than(self, other) -> bool   # looser in either dimension
    def stricter_than(self, other) -> bool
DEFAULT_REVIEW_THRESHOLD = ReviewThreshold(40, 3)
ABSOLUTE_REVIEW_FLOOR = ReviewThreshold(60, 3)
MIN_SEVERITY_PCT, MAX_SEVERITY_PCT, SEVERITY_STEP_PCT = 30, 55, 5
MIN_PERSISTENCE_DAYS, MAX_PERSISTENCE_DAYS, PERSISTENCE_STEP_DAYS = 3, 5, 1
SHADOW_GRACE_DAYS = 3; SHADOW_SCAN_DAYS = 28; CHECKING_PERIOD_DAYS = 14
LOOSENED_EXPIRY_DAYS = 60; COOLDOWN_DAYS = 7; WEEKLY_PROPOSAL_CAP = 5
PROPOSALS_PER_ROUND = 3; FIXED_RULE_FALSE_ALARMS = 2; FIXED_RULE_WINDOW_DAYS = 30
FAR_MORE_SEVERE_PCT = ABSOLUTE_REVIEW_FLOOR.severity_pct   # 60
SENIOR_NOTICE_DAYS = 7; REPLAY_WINDOW_DAYS = 56
ALLOWED_THRESHOLDS: tuple[ReviewThreshold, ...]  # the 14 allowed settings (no mixed values; see Stage 1 review amendments)
```

`policy.decide` gains keyword parameters with defaults
`review_threshold: ReviewThreshold = DEFAULT_REVIEW_THRESHOLD, shadow_review_since: date | None = None`.
The review block (`policy.py` 156–167) becomes three rungs, in order, after the small-baseline gate
and before the programme rung:

1. **Personal threshold** — `review_threshold.fires(...)` → `COORDINATOR_REVIEW`, priority 80,
   `decided_by=SEVERITY_PERSISTENCE`. Rationale:
   `f"Activity is more than {t.severity_pct}% below the personal baseline."`,
   `f"The decline has persisted for at least {WORDS[t.persistence_days]} valid-wear days."`,
   `"A human must review before any higher-touch outreach."` with `WORDS={3:"three",4:"four",5:"five"}`.
   Byte-identical to today with the default.
2. **Floor** — `ABSOLUTE_REVIEW_FLOOR.fires(...)` → `COORDINATOR_REVIEW`, 80,
   `decided_by=PolicyGate.REVIEW_FLOOR`. Rationale:
   `"Activity is at least 60% below the personal baseline for at least three valid-wear days."`,
   `"This is Care+'s absolute review floor; it applies whatever this person's review setting is."`,
   `"A human must review before any higher-touch outreach."`
3. **Shadow** — `shadow_review_since is not None` → `COORDINATOR_REVIEW`, 80,
   `decided_by=PolicyGate.SHADOW_CHECK`. Rationale:
   `f"Care+'s starting review setting would have asked for a human on {since.isoformat()}."`,
   `"This person's own review setting has not asked within the 3-day grace period, so a human is asked now."`,
   `"A human must review before any higher-touch outreach."`

Why: under the default, rungs 2–3 are unreachable (floor ⊂ default), so every scenario and committed
artifact stays byte-identical. Consent, quality and confidence precede them, so the floor never fires
with consent withdrawn or failed data. Small-baseline precedes them as today. Stated explanations
(`< 3` days) and rain (`< 2`) can never intercept a ≥3-day rung, and `MIN_PERSISTENCE_DAYS == 3 >=
EXPLANATION_MAX_SUSTAINED_DAYS`. The contact cap stays below every review rung.

**Attention band** (`sql_repository.py` ~1488): replace `severity >= 40 and sustained >= 3` with
`live.fires(severity, sustained) or ABSOLUTE_REVIEW_FLOOR.fires(severity, sustained)`, keeping the
`or policy.decision == COORDINATOR_REVIEW` disjunct (covers the shadow rung).

**`evaluation/ladder.py`**: same two keyword parameters, templated rationale, floor and shadow rungs
unconditionally after the scale gate. **No** new `LadderConfig` fields (they would add ablation rows).
Import the two constants from `review_threshold`. Update the "what is mirrored" docstring.

**Tests**: extend `test_full_ladder_is_identical_to_the_real_policy` with an inner loop over
`ALLOWED_THRESHOLDS × shadow_review_since ∈ {None, step.metric.day}` (existing `contacts` loop stays).
`test_context_explanation.py`: assert `MIN_PERSISTENCE_DAYS >= EXPLANATION_MAX_SUSTAINED_DAYS` and
`ABSOLUTE_REVIEW_FLOOR.persistence_days >= EXPLANATION_MAX_SUSTAINED_DAYS`.

### 2. Shadow check (stateless; reads never write)

```python
@dataclass(frozen=True)
class DaySignal: day: date; signal: SignalSummary
def day_signals(metrics, contexts, *, person_id, last_n, confirmed_reference_on, conflict_on) -> list[DaySignal]
def review_fires(signal, threshold) -> bool   # decide(signal, consent_active=True, interventions_last_7_days=0, review_threshold=threshold).decision is COORDINATOR_REVIEW
def shadow_review_since(days: Sequence[DaySignal], *, threshold_on: Callable[[date], ReviewThreshold]) -> date | None
```

`day_signals` recomputes each day exactly as `_evaluate` does (`analyse_signal` over prior rows with
that row's `context_json`, the confirmed reference as of that day, `_self_reported_conflict` that day).

`shadow_review_since` returns F for today D only when all hold:

1. `threshold_on(D).looser_than(DEFAULT)`.
2. D is inside an unfinished episode: the days after the most recent day with
   `safe_to_interpret and sustained_low_days == 0` (the recovery-close predicate), scanning back ≤28
   days; low-wear days do not end an episode; if D itself is such a day → `None`.
3. F = first day in the episode where `review_fires(signal, DEFAULT)`.
4. `D - F >= SHADOW_GRACE_DAYS`.
5. No day d in `[F, D)` had `review_fires(signal_d, threshold_on(d))` (the floor counts, being inside `decide`).

In `_evaluate`, after `_confirmed_reference`: `live = resolve_live_threshold(facts, current.day)`; only
if `live.threshold.looser_than(DEFAULT)` build the ≤28-day series and compute `since`; pass both to `decide`.

**Revert write**: only in `advance()`'s write phase, via
`_apply_review_threshold_daily_checks(session, run, state, review_case_row, now)` after `_create_case`.
If `state.decided_by_gate is PolicyGate.SHADOW_CHECK`: insert `review_threshold_decisions`
`kind="reverted", revert_trigger="shadow_check"`, restored = DEFAULT (stack cleared),
`ends_approval_id` = live approval, `decided_by="system"`, `trigger_case_id`, `decided_on_day=D`,
`effective_from_day=D+1`; audit `review_threshold_reverted` (ids only); ids in `decision_recorded` detail.

**Idempotency**: per-day advance is single-winner; unique `ends_approval_id`; because the revert is
effective next day, re-reading day D still yields the same state (ADR 0007 §5: a decided day is never re-decided).

### 3. Storage, live resolution, migration, mirror

Every change row has `effective_from_day = decided_on_day + 1`, except `expired` rows, whose
`effective_from_day` is the day stateless expiry already applied.

**`review_threshold_proposals`** (append-only), one row per calibrator output:
`proposal_id` String(64) PK · `run_id` FK scenario_runs idx · `person_id` FK people idx ·
`output_kind` String(20) `proposal|no_change|write_up` · `proposer` String(20)
`agent|fixed_rule|coordinator|starting_setting` · `round_id` String(64)? · `round_index` Integer? ·
`previous_severity_pct` Integer · `previous_persistence_days` Integer · `proposed_severity_pct` Integer? ·
`proposed_persistence_days` Integer? · `cause` String(40)? · `reasoning` Text · `cited_evidence_ids` JSON
(resolved real ids) · `trigger_case_id` String(64)? FK review_cases · `trigger_review_ids` JSON ·
`reported_by` String(120)? (reviewing coordinator's `sub`) · `coordinator_reason` String(40)? ·
`write_up_for_decision_id` String(64)? UNIQUE, no FK · `agent_run_json` JSON? · `proposed_on_day` Date ·
`proposed_at` timestamptz. Indexes `ix_review_threshold_proposals_run_day (run_id, proposed_on_day)`,
`ix_review_threshold_proposals_reporter_at (reported_by, proposed_at)`.

**`review_threshold_decisions`** (append-only):
`decision_id` PK · `run_id` FK idx · `person_id` FK idx · `kind` String(30)
`approved|rejected|reverted|expired|reconfirmed|check_confirmed|check_unresolved` · `proposal_id` FK? UNIQUE ·
`ends_approval_id` self-FK? UNIQUE · `affects_decision_id` self-FK? · `revert_trigger` String(30)?
`shadow_check|reached_too_late|far_more_severe` · `previous_severity_pct` · `previous_persistence_days` ·
`severity_pct`? · `persistence_days`? · `decided_by` String(120) · `rejection_reason` String(40)? ·
`note` Text? · `cause_confirmed` Boolean? · `replay_json` JSON? (required by code for `approved`) ·
`trigger_case_id` FK? · `trigger_review_id` FK case_reviews? · `decided_on_day` Date ·
`effective_from_day` Date · `decided_at` timestamptz. Index
`ix_review_threshold_decisions_run_effective (run_id, effective_from_day)`.

**`case_reviews`**: add `reached_too_late` Boolean NULL.

**Live resolution** — pure fold `resolve_live_threshold(facts: Sequence[ThresholdDecisionFact], day) ->
LiveReviewThreshold(threshold, source, approval_id, loosened, effective_from_day, expires_on_day)`, read
fresh on every `_evaluate`. Stack over rows with `effective_from_day <= day` ordered by
(`effective_from_day`, `decided_at`, `decision_id`): `approved` pushes (loosened = looser than its
previous in either dimension); `reconfirmed` resets the top approval's 60-day clock; `reverted` pops (a
`shadow_check` revert clears the stack); `expired` pops; then while top is loosened and
`day >= expires_on_day`, pop (stateless expiry; the daily check writes the `expired` row that day for
audit and notice); `rejected`/`check_*` change nothing; empty → DEFAULT.

**Migration** `apps/api/alembic/versions/<rev>_add_review_threshold_calibration.py`,
`down_revision="d8b1e4f70c2a"`: both tables; SQLite `_reject_update`/`_reject_delete` triggers and
PostgreSQL `_append_only` triggers (copy `c2f4a8d1e6b7`); batch add `case_reviews.reached_too_late` as
`e3b7d5c18a42` does; downgrade drops the column and restores the `case_reviews` SQLite triggers.

**Mirror** `infra/supabase/migrations/202609150019_review_threshold_calibration.sql`: idempotent tables
and indexes; `alter table public.case_reviews add column if not exists reached_too_late boolean`;
guarded append-only triggers and RLS/revoke/deny-policy blocks for both tables; `update
public.alembic_version set version_num='<rev>' where version_num='d8b1e4f70c2a'`. Add both tables to
`infra/supabase/rls_posture_apply.sql`.

**Tests that move**: `test_persistence.py:229` 28 → 30 (with names); `test_api.py:59` and
`test_postgres_integration.py:613` pin the new revision; new `test_review_threshold_migration.py`.

### 4. False-alarm review → proposal, model call outside the transaction

`is_false_alarm(status, human_action, override_reason)`: `status == RESOLVED and human_action ==
OVERRIDE and override_reason in {NOT_A_CONCERN, KNOWN_CONTEXT, DATA_DOUBT}`. `RECENT_CONTACT`, `OTHER`,
acknowledgements and system closures are not false alarms. The false-alarm day is the case's `opened_day`.

New `OverrideReason.NOT_A_CONCERN = "not_a_concern"`; `ReviewRequest.reached_too_late: bool = False`
(validator rejects it with `override_reason=NOT_A_CONCERN`).

`review_case(..., reached_too_late=False)` becomes three-phase like `advance()`:

1. **Transaction A** (existing): write the review (with `reached_too_late`) and audit; if
   `reached_too_late` and live is loosened, write `reverted/reached_too_late` in the same transaction;
   decide the follow-up without writing: `calibrate` (false alarm, no open proposal, cap not reached,
   consent on), `tighten` (reached too late with nothing loosened; stage 3), `write_up` (revert of an
   agent/fixed-rule approval; stage 3), or none. Cap reached or proposal open → audit
   `review_threshold_calibration_skipped` with a reason code. Commit.
2. **Read session**: `_threshold_episode_context(session, run, case_id, review_id)`; snapshot
   `(latest_proposal_id, latest_decision_id, consent_active, current_day)`; close.
3. **No session**: stage 1 fixed-rule proposer; stage 2 `_plan_threshold_safely(context)` with fixed-rule fallback.
4. **Transaction B**: re-fetch run, re-check snapshot (changed → audit
   `review_threshold_calibration_discarded`, ids and mode only); re-run `validate_threshold_output` on
   fresh facts; insert proposal; audit `review_threshold_proposed`.

The same split serves the reject route (retry up to 3 per round) and stage-3 write-ups.
`CaseReviewResponse` is unchanged; the UI re-fetches threshold state.

### 5. Threshold agent (stage 2)

```python
ThresholdPlannerMode = Literal["agent","fallback_disabled","fallback_error","fallback_exhausted","fallback_no_proposal"]
class ThresholdPlanRun(BaseModel):  # copy of ActivityPlanRun
    evidence_id; agent_version; task: Literal["calibrate","write_up"]; mode; model; provider
    transport: ActivityPlannerTransport | None; started_at; latency_ms; iterations; max_iterations
    tool_calls: list[AgentToolCall]; guardrail_rejections: list[str]
    proposal: ThresholdAgentProposal | None; fallback_reason; usage: AgentUsage
    def as_evidence(self) -> dict[str, Any]
def plan_threshold_calibration(context, *, settings, fallback: ThresholdAgentProposal, client_factory=None) -> ThresholdPlanRun
def write_up_reversal(context, *, settings, fallback_text: str, client_factory=None) -> ThresholdPlanRun
```

Reuse `PlannerState`, `_tool_use_blocks`, `log_provider_failure`, `planner_transport`; call
`silverloop.agent.planner._build_client` via module attribute (keeps monkeypatching). Constants in
`agent/constants.py`: `THRESHOLD_AGENT_VERSION="silverloop-threshold-calibrator-v1"`,
`MAX_EPISODE_DAYS_RETURNED=21`, `MAX_REVIEWS_RETURNED=10`, `MAX_THRESHOLD_HISTORY_RETURNED=10`. Cap =
`settings.llm_max_iterations` bounded by 8.

**Read-only tools** (`threshold_tools.py`, `ThresholdEpisodeContext` with pre-serialised payloads + alias
map): `get_episode_activity`, `get_context_evidence` (stated-explanation notes fenced),
`get_review_history` (coordinator notes **fenced**), `get_threshold_history` (rejection notes and past
write-ups **fenced**), `get_normal_variability` (code-computed `variability_summary`: median, MAD/median,
share of valid days >40/45/50/55/60% below, counts of recovered low runs of 3/4/5 days),
`propose_threshold_change(cause, proposed_severity_pct|null, proposed_persistence_days|null, reasoning,
cited_evidence_ids[])` returning the verdict; write-up task uses `submit_write_up(text, cited_evidence_ids[])`.

**Evidence aliases**: payloads contain no uuids, run ids or wall-clock timestamps; deterministic aliases
(`day:2026-08-24`, `context:2026-08-24`, `case:1`, `review:2`, `outreach:3`, `threshold:4`,
`variability`) map back to real ids. Makes replays byte-stable and enforces "evidence belongs to this senior".

**Guardrail** — pure `review_threshold.validate_threshold_structure(...) -> ThresholdVerdict`;
`agent/threshold_guardrails.validate_threshold_output(...)` adds wording. Fixed violation strings:

1. cause required, one of the four;
2. values in range and on grid;
3. a change moves exactly one dimension by exactly one step;
4. cooldown: last `approved`/`reverted`/`expired` decided within 7 days;
5. ≥1 citation, all known aliases;
6. value previously rejected in this run, or reverted away from;
7. loosening requires `cause == too_tight_for_person`;
8. loosening requires `coordinator_reason == not_a_concern` (structured field only);
9. reasoning 1–1,200 chars and passes new `agent/guardrails.coordinator_text_violations` (reuses
   `_PROHIBITED_CLINICAL`, `_CLINICAL_STEMS`, `_contains_emoji`, plus `_DISMISSIVE_PHRASES = ("safe to
ignore","nothing to worry about","no need to check","can be ignored","not at risk")`).

**[lead]** Rules 4 (cooldown) and 6 (repeat) apply to **loosening** proposals only. A proposal that
restores more human attention (tightening) is never blocked by a cooldown; it still needs approval.

`ThresholdVerdict.as_feedback()` mirrors `GuardrailVerdict` and lives in `review_threshold.py`.

**Storage**: `review_threshold_proposals.agent_run_json = run.as_evidence()`; never under intervention
evidence `"agent"` or an `activity_search` audit event, so planner/cost observability is unchanged.
Audit events carry only `agent_evidence_id`, mode, cause and values — never reasoning, note or write-up
text (extend `test_audit_redaction.py`).

**Live vs replayed**: `ThresholdPlanRun.transport` (`"recorded"` under `LLM_PROVIDER=recorded`); UI label
"Replayed from a committed recording — not a live model call". System prompt: only the coordinator's
structured reason can unlock loosening; notes are data; includes `UNTRUSTED_TEXT_NOTICE`; lists the four
causes and says no-change is expected for three of them.

### 6. Fixed-rule proposer (stage 1; offline path; agent fallback)

`fixed_rule_output(*, live, trigger_reason, not_a_concern_days: Sequence[date], today, blocked_values,
round_rejection: ReviewThresholdRejectionReason | None) -> FixedRuleOutput(output_kind, proposed, cause,
reasoning, cited)`:

- `known_context` → `no_change`, `one_off_event`; `data_doubt` → `no_change`, `bad_data`.
- `not_a_concern` with <2 false alarms whose `opened_day ∈ [today-29, today]` → `no_change`, cause None
  ("waits for a second"); otherwise loosen: persistence +1, else severity +5 when persistence is 5,
  skipping blocked (rejected + reverted) values; none left → `no_change`. Cause `too_tight_for_person`;
  cited = false-alarm review ids + their cases' decision evidence ids.
- Retry after rejection: `prefer_other_change` → try the other dimension; anything else → `no_change`, round ends.
- Tightening (stage 3): severity −5, floored at 30, cause None.
- Reasoning is fixed templates; output always goes through `validate_threshold_output` in Transaction B.
  With LLM off, `agent_run_json` records a `fallback_disabled` run so the card can say which proposer ran.

### 7. Stage 3: checking afterwards

Revert triggers write `reverted`, restoring the previous approved value (pop), effective next day:

- **`reached_too_late`**: a review with `reached_too_late=True` on this run's case while the live
  approval is loosened, at any time. Written in Transaction A (**stage 1**).
- **`far_more_severe`**: in the advance write phase, a case newly created within
  `CHECKING_PERIOD_DAYS` of a loosened approval's `effective_from_day` whose opening
  `abs(min(0, delta_percent)) >= 60` or `decided_by_gate == REVIEW_FLOOR`.
- **`shadow_check`**: answer 2, any time; reverts to DEFAULT (**stage 1**).

`reached_too_late` with nothing loosened live starts a tightening round (fixed-rule, or agent if
enabled) through normal approval. Checking-period close on advance where
`D == approval.effective_from_day + 14` and still live: `check_confirmed` if no false-alarm reviews on
cases opened on/after `effective_from_day` and no trigger fired, else `check_unresolved`.

**Write-up**: after Transaction A of `review_case` or after `advance()` commits, for each revert of an
agent/fixed-rule approval: read session → `write_up_reversal` with no session (fixed template if LLM
off/fails) → insert `output_kind="write_up"`, `write_up_for_decision_id=<revert id>` (unique ⇒
idempotent). Fed back through `get_threshold_history`; guardrail rule 6 blocks re-proposing reverted values.

### 8. Senior notice

`PersonState.review_threshold_notice: ReviewThresholdNotice | None = None`, computed read-only in
`_evaluate`: latest decision that is a loosening `approved`, or a `reverted`/`expired` whose after-value
is stricter than before, with `decided_on_day <= current_day < decided_on_day + 7`. No notice for approved
tightenings. No server-side dismissal. Fixed wording in `review_threshold.py`:

- `later`: "Your care team has changed when Care+ lets them know about a quieter stretch. Because
  your activity naturally varies from week to week, Care+ will now wait a little longer before
  letting them know."
- `sooner`: "Your care team has changed when Care+ lets them know about a quieter stretch.
  Care+ will now let them know a little sooner again, as it did before."

Pytest pins both against the senior vocabulary regex
`\b(stable|watch|review|\d+%|\d+ steps|time\(s\)|of \d+|anchor|they|their)\b`. Rendered as a plain card
near the top of `senior-view.tsx` inside `.senior-shell`.

**[lead]** Demo surfacing: Option A — the Care Team threshold card previews the exact notice text; the
real senior-shell rendering is proven by an e2e on Mdm Lim (auth-off `/senior` always loads Mdm Lim).
Whether `/senior?person=` should work with auth off is an open decision.

### 9. Coordinator routes, replay, identity, cap

All `Coordinator` dependency, tag `coordinator`. `KeyError` → 404, `ValueError` → 422, new
`ReviewThresholdConflict(ValueError)` → 409 (cooldown, cap, stale `shown_on_day`, already decided);
duplicate insert `IntegrityError` → 409.

| Method | Path                                                                                         | Request                           | Response                          |
| ------ | -------------------------------------------------------------------------------------------- | --------------------------------- | --------------------------------- |
| GET    | `/v1/coordinator/people/{person_id}/review-threshold`                                        | —                                 | `ReviewThresholdState`            |
| GET    | `/v1/coordinator/people/{person_id}/review-threshold/replay?severity_pct=&persistence_days=` | —                                 | `ReviewThresholdReplay`           |
| POST   | `…/review-threshold/proposals/{proposal_id}/approve`                                         | `ReviewThresholdApproveRequest`   | `ReviewThresholdDecisionResponse` |
| POST   | `…/review-threshold/proposals/{proposal_id}/reject`                                          | `ReviewThresholdRejectRequest`    | `ReviewThresholdDecisionResponse` |
| POST   | `…/review-threshold/manual`                                                                  | `ReviewThresholdManualSetRequest` | `ReviewThresholdDecisionResponse` |
| POST   | `…/review-threshold/confirm-starting`                                                        | `ReviewThresholdShownRequest`     | `ReviewThresholdDecisionResponse` |
| POST   | `…/review-threshold/decisions/{decision_id}/reconfirm`                                       | `ReviewThresholdShownRequest`     | `ReviewThresholdDecisionResponse` |

Approve / manual / reconfirm require `shown_on_day == current_day`, recompute the replay server-side into
`replay_json`, and re-run the guardrail (cooldown, consent). Approving a loosening with
`cause_confirmed=False` → 422. Manual set only when the latest round has 3 rejected proposals; writes a
`proposer=coordinator` proposal + `approved` decision atomically. Starting-setting confirmation is a
`proposer=starting_setting` row at 40/3 and gates nothing.

**Replay** `replay_thresholds(days, *, current, candidate) -> list[EpisodeReplay]` over the last 56 stored
days, split into episodes: first review day under `current` and under `candidate` (including floor and
simulated shadow); `days_later = candidate - current` (negative = sooner); `candidate_review_day=None`
when the episode recovered inside the grace period. Summaries `reviews_with_current`,
`reviews_with_candidate`, `max_days_later`, disclosure "Calculated by code from stored synthetic history;
not written by a model."

**Identity**: `decided_by = current_user.sub`; `reported_by` = reviewing coordinator's `sub` (auth off:
`"coordinator"`; UI "Approved by coordinator account <sub>"). Weekly cap counts `output_kind='proposal'`
rows with `reported_by == sub` and `proposed_at >= now - 7 days` (wall clock) on active runs.

**Consent**: `set_consent(active=False)` and `consent_revoked` write `rejected`
(`decided_by="system"`, `rejection_reason="consent_withdrawn"`) for any open proposal; approve, reject,
manual set and calibrate refuse while consent is inactive.

### 10. Care Team UI

> Superseded for layout and labels by "Care Team and demo surfaces after the UX redesign (2026-09-16)"
> below.

- New section in `components/care-team-view.tsx` after the queue, before "Follow-through, person by
  person": "Review setting, person by person", with its own `PersonaSwitcher`.
- New `components/silverloop/review-threshold-card.tsx`: live value and source; checking status
  (stage 3); expiry day + reconfirm; open proposal (current vs proposed, cause with confirm/dispute,
  reasoning, citations, replay table from the replay route, approve, reject-with-reason); manual set
  (only when allowed); confirm starting setting; history (proposals, no-change, reverts with trigger,
  write-ups); senior notice preview.
- Review form: `view-models.ts` adds `not_a_concern: 'Not a concern for this person'` to
  `OVERRIDE_REASON_LABELS` and the options array — **existing labels unchanged**; `review-card.tsx` adds
  checkbox "This should have reached me sooner"; `ReviewDecision.reachedTooLate?: boolean` through
  `care-team-view.review()`; re-fetch that person's threshold card after a review.
- Agent run (stage 2): generalise `AgentRunCard` to accept `agent?: AgentRecord | null` plus `title`,
  `modeLabels`, `toolLabels`, `framing`; outreach defaults unchanged; transport badge.
- Gate map: `view-models.ts` maps `review_floor` and `shadow_check` to the `severity_persistence` rung,
  with `decidingGateDetail` sentences. Must land in the same commit as client generation.

### 11. Demo plumbing

- **Per-person reset**: `main.py` `reset_demo(request, repository, person_id: str | None = None)` →
  `repository.reset(person_id=person_id or DEMO_PERSON_ID)`; unknown id → 422. Facade `reset(personId?)`;
  `scenario-data.ts` `resetScenario(api, personId?)`; `decision-simulator.tsx` passes the persona.
- **Sixth persona** in `fixtures.py`: `mdm-wong`, "Mdm Wong", "English / Cantonese", 72, context note
  "Synthetic profile; activity naturally swings a lot from week to week.", `seed_offset=25000`,
  `baseline_steps=5800`, `step_std=1620.0`, `weekend_multiplier=0.70`, `history_days=90`,
  `tracker_adherence=0.97`, `is_playbook_persona=False`, notes "SYNTHETIC -- not in the product playbook;
  no research or interview basis. Invented to exercise the review-threshold calibrator: a routine whose
  ordinary swings cross the default review threshold." Update `test_personas.py`, web `PERSONAS`, and
  `product-loop.spec.ts:421` ("1 of 6"). No scenarios ⇒ evaluation artifacts unchanged.
- **Guided scenario** `a-false-alarm-teaches-silverloop` on `mdm-wong` (titled "A coordinator adjusts
  future review timing" since 2026-09-16; the id is unchanged); `GuidedScenarioStep.interlude?:
string` rendered before a step. E1 `activity_declines`×3 → interlude (resolve on Care Team as override
  → Not a concern for this person, fixed demo note; approve a proposal if one appears) → `recovery`;
  E2 same (offline: second false alarm → fixed-rule proposal); E3 `activity_declines`×3 → `recovery`
  (quiet); E4 `activity_declines`×4 → interlude (mark "This should have reached me sooner"). Interludes
  come **before** `recovery` (recovery auto-closes the case). Pin actual per-day decisions offline in
  `tests/test_review_threshold_demo.py`; adjust event counts there if the rolling baseline shifts.
- **Replay backup** (stage 3): `record_threshold(out, *, inner_kind, model)` in
  `evaluation/ranking_llm/synthesise.py` drives the guided sequence on in-memory SQLite via new
  `SqlAlchemyRepository(threshold_client_factory=...)`; no Supabase needed. `THRESHOLD_RECORDINGS =
RECORDINGS_ROOT / "review_threshold"`; commit `scripted.json` (synthetic banner); the user adds
  `live_demo.json`. `tests/test_review_threshold_recording.py` replays scripted (`mode=="agent"`,
  `transport=="recorded"`) and checks `live_demo.json` when present. `test_recorded_client.py` untouched.

### 12. Evaluation (minimum honest change)

No scenario YAML added or edited; digest, holdout and `docs/evaluation/*` byte-identical. Ladder mirror +
extended equivalence test. New `tests/test_review_threshold_properties.py` over core `scenarios/` ×
`ALLOWED_THRESHOLDS`: floor always reviews when consent/quality/confidence/scale permit; bounded delay
≤ F+3 (or recovered / blocked); every guardrail rule pinned pass and fail; generated sequences (constant
42% for 10 days; 62% for 3 days). "Reviews per senior" and "days later vs default" computed by
`replay_thresholds` and asserted in tests; a markdown report is optional polish.

Note: "missed escalation stays zero with loosened thresholds" is false by construction (40/4 delays by
design); the honest claim is "delay ≤ 3 days, floor always fires", and the committed default M3 stays 0.

## Contract changes (one `pnpm client:generate`, in stage 1)

**Enums**: `OverrideReason.NOT_A_CONCERN`; `PolicyGate.REVIEW_FLOOR="review_floor"`,
`PolicyGate.SHADOW_CHECK="shadow_check"`; `ReviewThresholdCause` (`too_tight_for_person`, `one_off_event`,
`bad_data`, `worked_as_intended`); `ReviewThresholdProposer` (`agent`, `fixed_rule`, `coordinator`,
`starting_setting`); `ReviewThresholdOutputKind` (`proposal`, `no_change`, `write_up`);
`ReviewThresholdDecisionKind` (`approved`, `rejected`, `reverted`, `expired`, `reconfirmed`,
`check_confirmed`, `check_unresolved`); `ReviewThresholdRevertTrigger` (`shadow_check`, `reached_too_late`,
`far_more_severe`); `ReviewThresholdRejectionReason` (`cause_disputed`, `need_more_evidence`,
`prefer_other_change`, `other`, `consent_withdrawn` — system only, refused by the request validator);
`ReviewThresholdNoticeKind` (`later`, `sooner`).

**Models**:

- `ReviewThresholdValue {severity_pct: int 30..55, persistence_days: int 3..5}`
- `ReviewThresholdBounds {default, minimum, maximum, floor: ReviewThresholdValue; severity_step_pct, persistence_step_days, grace_days, checking_period_days, expiry_days, cooldown_days, weekly_proposal_cap, proposals_per_round: int}`
- `ReviewThresholdProposal {proposal_id, output_kind, proposer, round_id?, round_index?, previous, proposed?, cause?, reasoning, cited_evidence_ids, trigger_case_id?, trigger_review_ids, reported_by?, coordinator_reason?: OverrideReason, write_up_for_decision_id?, proposed_on_day, status: Literal["open","approved","rejected","not_applicable"], agent_run?: dict[str, Any]}`
- `ReviewThresholdDecisionRecord {decision_id, kind, proposal_id?, ends_approval_id?, affects_decision_id?, revert_trigger?, before, after?, decided_by, rejection_reason?, note?, cause_confirmed?, replay?: ReviewThresholdReplay, trigger_case_id?, trigger_review_id?, decided_on_day, effective_from_day, decided_at}`
- `ReviewThresholdReplayEpisode {first_low_day, current_review_day?, candidate_review_day?, days_later?, candidate_reached_via?: Literal["threshold","floor","shadow_check"]}`
- `ReviewThresholdReplay {current, candidate, window_start_day, window_end_day, episodes, reviews_with_current, reviews_with_candidate, max_days_later?, disclosure}`
- `ReviewThresholdCheck {approval_decision_id, checking_until_day, false_alarms_since, status: Literal["checking","confirmed","unresolved","reverted"]}`
- `ReviewThresholdState {person_id, current_day, consent_active, live, live_source: Literal["starting_setting","approved","reverted","expired"], live_decision_id?, starting_setting_confirmed, expires_on_day?, cooldown_until_day?, bounds, open_proposal?, round_rejections, manual_set_allowed, proposals_this_week_by_you, check?, proposals, decisions, senior_notice_preview?: ReviewThresholdNotice}`
- Requests: `ReviewThresholdApproveRequest {cause_confirmed, shown_on_day, note?: ≤500}`, `ReviewThresholdRejectRequest {reason, note?: ≤500}`, `ReviewThresholdManualSetRequest {threshold, note: 2..500, shown_on_day}`, `ReviewThresholdShownRequest {shown_on_day}`
- `ReviewThresholdDecisionResponse {state, decision, audit_event: AuditEvent}`; `ReviewThresholdNotice {notice_id, kind, message, shown_from_day}`
- Existing: `PersonState.review_threshold_notice?`; `ReviewRequest.reached_too_late` (+ validator); `ReviewAction.reached_too_late: bool | None`.

**Python**: `policy.decide(..., review_threshold, shadow_review_since)` mirrored in `make_ladder`;
`SqlAlchemyRepository.__init__(..., threshold_client_factory=None)`; `review_case(..., reached_too_late)`;
repository methods `review_threshold_state(person_id, *, viewer_sub)`, `review_threshold_replay(person_id,
candidate)`, `approve_threshold_proposal`, `reject_threshold_proposal`, `set_threshold_manually`,
`confirm_starting_threshold`, `reconfirm_threshold`, all on the `SilverLoopRepository` Protocol.

**HTTP**: the seven routes; `POST /v1/demo/reset?person_id=`; review body `reached_too_late`.

**Facade** `libs/api-client/src/index.ts`: `reset(personId?)`; `reviewCase(..., overrideReason?,
reachedTooLate?)`; `reviewThreshold(personId)`; `reviewThresholdReplay(personId, severityPct,
persistenceDays)`; `approveThresholdProposal(personId, proposalId, causeConfirmed, shownOnDay, note?)`;
`rejectThresholdProposal(personId, proposalId, reason, note?)`; `setThresholdManually(personId,
severityPct, persistenceDays, note, shownOnDay)`; `confirmStartingThreshold(personId, shownOnDay)`;
`reconfirmThreshold(personId, decisionId, shownOnDay)`.

## Comments that become false (reworded with ADR 0008)

`HumanAction` docstring (`models.py` ~94), `CaseReviewRow` comment (`db_models.py` ~289–292),
`review_case` audit `learning_boundary` (`sql_repository.py` ~7958), WAYFINDER F16 constraint
(`docs/WAYFINDER.md` ~1199), the "safety thresholds" guardrail in `suggestions.md`. The ranking boundary
(`learning.py`) is unchanged.

## Risks

1. Byte-identity: default rationale must render "40%" and "three"; exhaustive TS `PolicyGate` maps must
   update in the same commit as generation.
2. Recovery auto-closes the case: the false-alarm review must precede `recovery`.
3. Demo numbers drift with the rolling median: pin by test.
4. Replay determinism: aliases not uuids, fixed demo note, `LLM_MODEL` = recorded id. Under
   `LLM_PROVIDER=recorded` other loops miss honestly.
5. Model latency inside the review request: timeouts fall back; stale snapshot ⇒ discard and audit.
6. Shadow read cost: only for loosened seniors, ≤28 `analyse_signal` calls.
7. Low-wear gaps can break a persistence run; rain/stated gates can then return NO_ACTION that day
   (existing gap semantics; documented in the ADR).
8. Two-level expiry chain: fold pops repeatedly; unit-tested.
9. Concurrency: unique `proposal_id` and `ends_approval_id`; calibration skipped (audited) while a proposal is open.
10. Consent withdrawn mid-round: system rejections; Transaction B re-checks.
11. Audit redaction: no note, reasoning or write-up text in `audit_events.detail_json`.
12. Migration: SQLite triggers on new tables; `case_reviews` triggers survive downgrade; mirror hand-applied only.

## Stages and acceptance criteria

### Stage 1 — fixed-rule calibrator (commit `feat: fixed-rule review-threshold calibrator`)

Builds: `review_threshold.py`, `review_threshold_replay.py`, policy + ladder rungs, migration + mirror,
the **full** contract + client + facade, false-alarm and reached-too-late capture, shadow and
reached-too-late reverts, expiry, reconfirm, fixed-rule proposer, approve/reject/manual/confirm routes,
senior notice, persona, per-person reset, guided scenario, Care Team card and review form.

- With the default threshold every scenario, `--check` artifact, `AUTHORED_LABEL_DIGEST` and the holdout
  are unchanged; pytest green apart from deliberately updated persona, table-count and revision pins.
- Equivalence holds for all 14 allowed settings × shadow flag × contact counts.
- For every allowed threshold a ≥60% / ≥3-day signal with consent on and interpretable data yields
  `COORDINATOR_REVIEW` (`review_floor` whenever the personal rung did not fire); consent off →
  `SUPPRESS`/`consent`; failed quality → `NO_ACTION`/`data_quality`.
- No allowed threshold delays a review more than 3 days past the default's first firing day in an
  unfinished, consented, interpretable episode; constant 42% under 45/3 reviews on F+3 via
  `shadow_check`, and the next day's live threshold is the default.
- Reading state, the roster, `GET /v1/coordinator/priorities` or the senior-home preview any number of
  times writes no row (extend `test_reading_the_board_writes_nothing` with a loosened live threshold);
  the shadow revert is written exactly once by `advance`.
- Under a loosened setting a shadow-check or floor case shows `REACH_OUT_TODAY` on the care-priority
  board; the `test_triage.py` ceiling passes for all 14 allowed settings.
- Demo Tools `/screen-preview` passes §13's criteria.
- LLM off: two `resolved + override + not_a_concern` reviews within 30 scenario days produce exactly one
  fixed-rule +1-day proposal; `known_context` → `no_change/one_off_event`; `data_doubt` →
  `no_change/bad_data`; nothing loosens for any other reason whatever the note says.
- Guardrail rejects, each pinned: out of range, multi-step, cooldown, unknown/foreign evidence, repeated
  rejected/reverted value, loosening with wrong cause, loosening with wrong coordinator reason; tightening
  is not blocked by cooldown **[lead]**.
- Approve records `decided_by == sub` and non-null `replay_json`; second approve 409; loosening with
  `cause_confirmed=false` 422; stale `shown_on_day` 409; cooldown and 5/week cap enforced server-side.
- Three rejections enable manual set; before that 409.
- `reached_too_late=true` while loosened writes `reverted/reached_too_late` in the same request, restoring
  the previous approved value from the next day.
- A loosening approved on day D expires on D+1+60 unless reconfirmed.
- Withdrawing consent rejects the open proposal (`consent_withdrawn`); approve and calibrate refuse.
- `PersonState.review_threshold_notice` appears after a loosening approval and after a revert/expiry for
  7 simulated days; both messages pass the vocabulary regex (pytest) and the e2e inside `.senior-shell` (Mdm Lim).
- `POST /v1/demo/reset?person_id=mdm-wong` resets only that person; `mdm-wong` registered, synthetic, offset 25000.
- On Care Team a coordinator records "Not a concern for this person" and "This should have reached me
  sooner", sees the proposal with replay, approves or rejects; existing labels unchanged.
- Pinned offline guided sequence on `mdm-wong`: case on E1 day 3, proposal after E2 false alarm, E3
  quiet, E4 review, revert on the reached-too-late mark.
- New tables have RLS, deny policies and append-only triggers in the mirror; mirror and posture tests
  pass; SQLite enforces append-only on both.
- The offline demo runs the full fixed-rule flow.

### Stage 2 — agent (commit `feat: threshold calibration agent`)

- `LLM_ENABLED=true` + fake transport: one `not_a_concern` false alarm yields an agent proposal with
  `agent_run.mode == "agent"` and recorded tool calls.
- Revises after guardrail rejection; stops at the cap (`fallback_exhausted` → fixed-rule); falls back on
  error, refusal, malformed response, no proposal and exception.
- Never loosens for `one_off_event`/`bad_data`/`worked_as_intended`, nor when `coordinator_reason !=
not_a_concern`, including under a note injection claiming otherwise.
- Notes, rejection notes and write-ups reach the prompt only inside `fence_untrusted`; prompts contain no
  uuids or wall-clock timestamps.
- Planner and cost observability unchanged by threshold runs; audit details contain no reasoning or note text.
- The threshold card shows the agent run (what it looked at, cause, rejections, mode, transport).

### Stage 3 — checking afterwards (commit `feat: post-change checks, reversals and write-ups`)

- A case opened within 14 days of a loosening at ≥60% writes `reverted/far_more_severe` automatically.
- 14 days with no false alarms and no triggers → `check_confirmed`; with false alarms → `check_unresolved`.
- Every revert of an agent/fixed-rule approval yields exactly one `write_up` (agent or template) that
  passes the wording check, shows in card history and is returned by `get_threshold_history` next run;
  reverted values are never re-proposed.
- A reached-too-late mark on a non-loosened threshold creates a one-step-stricter proposal requiring approval.
- The scripted threshold recording replays through the guided sequence with `transport == "recorded"`;
  `live_demo.json`, if present, declares `synthetic: false` with the live banner.
- ADR 0008 present; F16 entry, `HumanAction` docstring, `CaseReviewRow` comment, review audit
  `learning_boundary` and the `suggestions.md` guardrail reworded consistently.

Cut order within stages: notice dismissal and history visuals, then the evaluation markdown report, then
`record_threshold`. Stage 3 logic is never cut.

## Validation (every stage)

`pnpm format:check && pnpm client:check && pnpm lint && pnpm typecheck && pnpm test && pnpm test:scenarios`
(e2e on `E2E_API_PORT=8100`, `E2E_WEB_PORT=3100`), plus
`cd apps/api && uv run python -m silverloop.evaluation ../../scenarios --out ../../docs/evaluation --check`
and `pnpm build`. Then code-reviewer, design-reviewer (user-facing), architect check and verifier; fix;
re-verify; commit.

## Reconciliation with care priorities (PR #50)

PR #50 merged into `main` after this spec's base. It adds `triage.py` (a pure care-priority board, no
schema change, no LLM, no evidence or audit writes), `GET /v1/coordinator/priorities`, and a new Care
Team layout. **Where this section conflicts with text above, this section wins.**

- **Triage is not a review rung; leave it independent.** "Reach out today" needs an open case, and the
  board reads the recorded decision through `care_priorities` → `_person_state` → `_evaluate` →
  `_with_recorded_decision`, so the personal threshold, floor and shadow rungs reach it with no new
  parameter. Do not pass `ReviewThreshold` into `triage.py`. `REVIEW_FLOOR` and `SHADOW_CHECK` must not be
  added to `triage._OUTREACH_HOLDING_GATES`, `triage._UNREADABLE_GATES` or `sql_repository._READ_TIME_HOLDS`.
  Threshold changes being effective next day keeps recorded and read-time decisions consistent.
- **Documented behaviour:** under a loosened setting a decline between 40% and the personal setting is
  answered by lower rungs (the board may show `CHECK_IN_WITHIN_48H` or `KEEP_AN_EYE_ON`) until the
  personal rung, floor or shadow check fires, at most 3 days later.
- **One `triage.py` change (track B):** `THRESHOLD_REFERENCES[0].rule` becomes "Only while a review case is
  waiting. Care+'s policy opens one when activity has stayed below their own usual past their review
  setting: more than 40% for at least three valid-wear days, unless a coordinator has approved a change
  for that person within fixed bounds, and always at 60% or more for three days." Tests in
  `test_triage.py`: (1) parametrise `SEVERITY_PERSISTENCE`/`REVIEW_FLOOR`/`SHADOW_CHECK` ×
  `COORDINATOR_REVIEW`: with an open case → `REACH_OUT_TODAY`, without → `KEEP_AN_EYE_ON`;
  (2) `test_personal_review_setting_never_lifts_the_board_past_the_ladder` over `ALLOWED_THRESHOLDS ×
shadow ∈ {None, day} × delta ∈ {-35,-45,-62} × sustained 2..5 × consent × open case`, same ceiling
  assertions as the existing grid (which stays unchanged).
- **Terminology:** coordinator copy says "review setting", never a bare "threshold"; the board keeps
  "thresholds" for its own disclosure. Contract enums carry the `ReviewThreshold` prefix (renamed above).
- **Care Team placement (track D):** order is `FollowUpFirstCard` → Care queue → `CaseloadPriorityList` →
  queue block → **Review setting, person by person** (`PersonaSwitcher id="review-threshold-persona"`) →
  Follow-through. Nothing from the review setting enters `CarePriorityRow`, `take_note` or
  `FollowUpFirstCard`. Threshold actions don't refresh the board (effective next day); `review()` also
  re-fetches the threshold card when the reviewed person matches. Reword the Care queue line "Kept for
  review and evaluation only — a coordinator's decision never changes how suggestions are ranked." to "A
  coordinator's decision never changes how suggestions are ranked. Choosing 'Not a concern for this
  person' can lead Care+ to propose a change to that person's review setting, which a coordinator
  approves." In `review-card.tsx` keep PR #50's root `Card` `id="case-…"` and `scroll-mt` classes.
- **Repository placement (track C):** no function is edited by both sides. New `SqlAlchemyRepository`
  and Protocol methods go **after** `review_case`; new coordinator routes after
  `/v1/cases/{case_id}/review`. `care_priorities` calls `_evaluate` per active run, so a loosened senior
  adds ≤28 `analyse_signal` calls per board load and must write nothing.
- **Client:** one `pnpm client:generate` after the merge; generated files are only ever regenerated;
  `libs/api-client/src/index.ts` is hand-merged (keeps `coordinatorPriorities`).
- **e2e (track D):** the persona count assertion (`1 of 5 demo personas are currently seeded`, ~473) →
  `1 of 6`. **No e2e advances or resets `mdm-wong`**: e2e resets only `mdm-lim` on one SQLite database, and a
  live `mdm-wong` run breaks the seeding disclosure and the board's empty-state assertions. The guided
  sequence is pinned in pytest only. Tests reading "Your seniors" use the window labels.
- **Stage 2 privacy (from PR #50's precedent "nothing the senior told Care+ reaches a coordinator
  surface"):** `get_context_evidence` returns rain and holiday context only — no stated explanation,
  context answer or disputed day, neither content nor existence — because the agent's reasoning is shown
  to a coordinator. Guardrail rule 9 also rejects `told`, `explained`, `said they`, `disputed`.
- **Docs that become false (lead, stage 3):** `docs/care-priorities.md` "Reach out today" rows and "The
  policy ladder itself (`policy.py`) is untouched"; add a `CLAUDE.md` API-internals bullet for
  `review_threshold.py` (stage 1).
- PR #50 changed no scenario or evaluation artifact; digest and holdout stay byte-identical.

## 13. Demo Tools senior-screen preview

Decision (user, 2026-09-15): `/senior` stays pinned to the default demo persona when auth is disabled; no
query-string identity selection on the real senior route. Persona switching is an isolated, read-only
Demo Tools surface.

**Web route and nav (track D):** `apps/web/app/(platform)/screen-preview/page.tsx` (deliberately not under
`/senior…`). Nav label "What a Senior Sees", eyebrow "Demo tools · Senior screen preview", one `h1` "What a
Senior Sees". `apps/web/app/nav.tsx`: add `{ href: '/screen-preview', label: 'What a Senior Sees', icon: Eye }`
to `DEMO_TOOLS` after `/ranker`; hide from coordinators like `/simulator` and `/ranker`; update the
`PlatformNav` docstring. `apps/web/middleware.ts`: add `'/screen-preview'` to `PROTECTED_PREFIXES`.

**API (track C; model by track A):** `GET /v1/evaluator/people/{person_id}/senior-home`,
`response_model=SeniorHomePreview`, tag `evaluator`, `current_user: DemoOperator`, responses 401/403/404/409,
placed after `ranker_presets` in `main.py`. The handler composes existing read-only
`repository.person_state(person_id=…)` and `repository.list_interventions(person_id=…)[:1]`; no repository
or Protocol change. `KeyError` → 404; unseeded run → 409 via the existing handler. Demo operator only
(a demo operator can already read any persona's state via `/v1/simulation/latest`); coordinator and senior 403.

```python
class SeniorHomePreview(BaseModel):
    """One persona's senior home content for an evaluator. Read-only; not the senior's own screen."""
    person_id: str
    state: PersonState
    latest_intervention: Intervention | None = None
    disclosure: str  # "Preview for evaluation. This is not the senior's own screen; nothing here can be answered or recorded."
```

Facade `seniorHomePreview(personId)` in the single stage-1 generation.

**Composition (track D) — no second identity path, `/senior` untouched:** new
`apps/web/components/senior-screen-preview/senior-screen-preview-view.tsx` using
`createApiClient(getAccessToken, onUnauthorized)` like `useRankerApi`; persona only from `PersonaSwitcher`
(`id="screen-preview-persona"`); never calls `api.me()`, `useSeniorApi` or any senior route; stale-response
guard. Outside the frame an `Alert role="note"` "Preview, not the senior's own screen" — "Read-only. Replies
and controls are switched off, and nothing on this page is sent or recorded." — plus a line naming what is
not previewed (Ask Care+, questions and prompts, week and goals, preferences, nearby activity, "that day
wasn't right"). Inside `<section aria-label="Senior home preview" data-testid="senior-home-preview">`, reusing
senior components but **not** the `.senior-shell` class: greeting (`greetingFor` + `display_name`); shared
`components/senior/review-threshold-notice.tsx` (also used by `senior-view.tsx`); headline/subline from a pure
helper `components/senior/home-headline.ts` moved out of `SeniorView`; `SuggestionCard` with new optional
`previewOnly` prop (response buttons disabled, default false); "How things look" via
`describeRecentActivity(state)` without `DayDispute` (since 2026-09-16 that sentence is the "Your week"
card, `YourWeekCard`, after Today; the preview leads with the frame and moves the not-previewed list
into a "What this preview leaves out" disclosure). 404/409 → "{name} is not set up in this database yet."
The preview never seeds or resets.

**Tests:** pytest `test_auth_rbac.py` (demo operator 200, coordinator 403, senior 403); `test_api.py` (`state`
equals the state route, `latest_intervention` equals `list_interventions()[0]`, unknown 404, reads write no
events, cases or threshold rows). e2e `apps/e2e/tests/senior-screen-preview.spec.ts` on Mdm Lim only: Demo
tools menu reaches the page; after one `activity_declines` advance the note is visible, greeting names Mdm
Lim, response buttons disabled, frame text passes `SENIOR_SHELL_VOCABULARY`, no non-GET API request while on
the page; choosing Mdm Siti shows the not-set-up state and Care Team still reads `1 of 6`. The Mdm Lim notice
e2e also asserts the same notice text inside the preview frame. Add `'/screen-preview'` to the narrow-viewport
route loop.

## Stage 1 review amendments (2026-09-15)

From code-reviewer, architect check (PASS), design-reviewer and the web code review. **These override
conflicting text above.**

- **No mixed settings (re-review round 2).** A setting is on the loosening side (at least 40% and at
  least 3 low days) or the tightening side (3 low days and at most 40%). Severity 30% and 35% exist only
  with 3 low days, so there are 14 allowed settings, not 18. Persistence cannot go below 3, so tightening is
  severity-only; forbidding mixed values keeps every setting comparable with the starting setting in both
  dimensions, which is what makes "going back never asks later" provable.
- **Reverts and expiry never ask later.** A reached-too-late revert walks the live stack from the top and
  ends at the first point whose restored value asks sooner or equal in both dimensions and sooner in one;
  the starting setting counts only if it passes; if nothing qualifies, no revert is written (audited). No
  senior notice for a revert of an approval that never became live.
- **Manual set needs a current round:** every proposal in it started from today's live value, nothing was
  approved, reverted or expired after it, and its opening false alarm is within 30 days. A "cause disputed"
  rejection never counts toward, and blocks, a manual loosening.
- **Every threshold writer locks the run row.** The weekly cap is per coordinator across runs; concurrent
  reviews of different seniors could exceed it on PostgreSQL (known proof-of-concept limitation).
- **"Loosened" means "has an expiry clock":** the approved value is looser than the starting setting or than
  the value it replaced. The senior notice still compares against the replaced value.
- **Reached-too-late revert only ever asks sooner.** The restored value is computed by folding the facts plus
  the revert at the next day, never copied from `approval.previous`. If that restored value would be looser
  than live in either dimension, the revert clears to the starting setting (as the shadow revert does). A
  loosening approved today and pending tomorrow is ended too.
- **Manual set keeps ADR 0008 §3.** A manual loosening needs the round's trigger reason "not a concern for
  this person", at least one rejected proposal in the round naming "too tight for this person", and a value
  never reverted away from. Manual tightening is unrestricted within range and one step. Manual set is
  offered when no proposal is open, nothing is pending tomorrow, and either the round has 3 coordinator
  rejections or it ended in no-change after at least one "prefer the other change" rejection (so it is
  reachable with the fixed rule alone).
- **System rejections** (`consent_withdrawn`, new `superseded`) never block a value and never count toward a
  round. A revert or expiry rejects open proposals whose starting value no longer matches tomorrow's setting
  as `superseded`.
- **False alarms count only from cases opened on or after the live setting's effective day**, trigger
  included. A cause is required for every non-fixed-rule output.
- **Replay** marks the trailing unfinished episode `ongoing` ("not yet", never "recovered"), and makes no
  savings claim from it.
- **State** carries `senior_notice_if_approved`, so the approval screen shows what the senior will read
  before the coordinator approves. Consent inactive on any threshold action is a 409 (reload), not a 422.
- **Robustness:** reverts and expiry write inside a savepoint (a unique `ends_approval_id` collision means
  "already ended"); the weekly cap is re-counted under a row lock in Transaction B; an error after
  Transaction A commits is audited as discarded and never fails the request.
- **UI:** after a review the "Review setting" section switches to the reviewed person; approval lists its
  consequences; no "shadow check" or "floor" jargon in coordinator copy; guided-scenario interludes sit
  beside the Run button and need an explicit confirmation.

## Care Team and demo surfaces after the UX redesign (2026-09-16)

From `docs/ux-audit-2026-09-16.md`, delivered with calibration trust (`docs/calibration-trust-spec.md`,
ADR 0009). **These override §10, the Care Team placement bullet in the PR #50 reconciliation, and the
demo steps above where they conflict.** The behaviour, contract and guarantees are unchanged.

- **Terminology.** The web UI says "review timing". API text, contract names and backend docs still say
  "review setting" (`CONTEXT.md`).
- **Roster.** Care Team is one roster grouped as "Needs your judgement", "Waiting for senior response",
  "Care+ is handling" and "No attention needed" (collapsed). The `FollowUpFirstCard`, its top-3/5/10
  control and the always-present "Review setting, person by person" section are gone. "When each person
  should reach you" at the foot of the roster links to each person's review timing, and a row shows a
  prompt while a proposal is waiting.
- **Case page** `/care-team/cases/[caseId]`. It covers why you are seeing this, what changed, what
  Care+ knows, what it already did, what happens if you do nothing, then "What do you want to
  record?". The decisions are **Keep open — Care+ keeps monitoring** (`acknowledged`) and **Close case** (`resolved`).
  The human actions are "Agree with the suggested next step", "Not acting on it yet" and **Choose a
  different next step** (`override`). After recording, "What Care+ learned from this review"
  shows the lesson, and the case page also carries the context-gap tally.
- **Review timing page** `/care-team/review-timing/[personId]` ("Review timing for …"). It holds the
  review-threshold card (proposal, replay, approve or reject, history, receipt) and the context-gap
  tally.
- **Guided scenario.** "A false alarm teaches Care+" is now **A coordinator adjusts future review
  timing**. Its interludes use the labels above. The simulator also gained **A plan that can no longer
  happen** (replanning, Mdm Lim).
- **Evaluation.** `/evidence?tab=audit|evaluation|health`, with `/operations` landing on `health`. The
  calibration card sits inside Policy Evaluation's "Review-setting calibration" section
  (`#calibration`).
- **Stale demo state.** A snapshot from an older contract shows "Stored demo state is out of date" with
  **Reset local synthetic demo**, not "API unavailable".

## Known stage 1 limitations (carried forward)

- A shadow-check revert clears the whole stack but its row ends only the top approval, so lower looser
  values are not recorded as "reverted away from" (loosening-only impact). Revisit with stage 3.
- The decision clock is clamped after the newest decision, not the newest proposal; proposals written
  by an instance with a lagging clock could sort before an older proposal.
- An `event_id` retry still pays for the context fetch before finding its stored response, and an
  in-flight duplicate advance is not idempotent (pre-existing; the web never reuses an `event_id`).
- When the fixed rule's own fallback is also refused at save time after an agent run, its violations are
  appended to the agent record's rejection list, so the card lists them under what the agent could not get
  past (rare; would need a separate field to distinguish).
- Tightening after a false alarm is refused only inside the calibrate loop; the pure validator still allows
  it for stage-3 tightening and manual set.
- The weekly proposal cap is locked per run, so one coordinator reviewing different seniors
  concurrently could exceed it on PostgreSQL.

## Open decisions

- None. Closed 2026-09-15 (user): `/senior` stays pinned; persona switching via the Demo Tools preview (§13).
