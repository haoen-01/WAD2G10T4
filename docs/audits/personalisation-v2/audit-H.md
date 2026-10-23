# Audit H — Care Team / Coordinator UX + Operations + Evaluator surface

Worktree: /Users/ianpong/Projects/ismoggers-v2 @ 010aa96. Read-only. All paths below are relative
to that worktree unless absolute. Probe script and output:
`(scratch)/h_probe.py`
(run with `cd apps/api && LLM_ENABLED=false ADAPTER_MODE=fixture uv run python .../h_probe.py`).

## Scope covered

- Web: `apps/web/components/care-team-view.tsx`, `silverloop/review-card.tsx`,
  `silverloop/outreach-history-card.tsx`, `silverloop/outreach-history-labels.ts`,
  `silverloop/outreach-history-follow-up.tsx`, `silverloop/effectiveness-panel.tsx`,
  `silverloop/personal-world-model.tsx`, `silverloop/person-card.tsx`, `case-timeline.tsx`,
  `overview-view.tsx`, `evidence-view.tsx`, `decision-simulator.tsx`, `lib/view-models.ts`,
  `lib/scenario-data.ts`, route pages under `apps/web/app/(platform)/`.
- API: `main.py` coordinator/metrics/events routes; `sql_repository.py` `_create_case`,
  `_to_case`, `list_cases`, `get_case`, `review_case`, `_close_open_cases_for_*`,
  `list_outreach_summaries`, `follow_up_observation`, `metrics`, `_resolve_unanswered_outreach`;
  `policy.py`; `quality.py`; `models.py` case/review/metrics models.
- Docs: `docs/demo-runbook.md`, `docs/adr/0001-consent-scope-model.md`, `docs/api.md`,
  `docs/architecture.md`, `docs/WAYFINDER.md` (F16, aggregate-only decision, dedup note).
- Tests: `apps/api/tests/test_case_dedup.py`, `test_case_terminal_state.py`,
  `test_consent_boundary.py`, `test_multi_person.py`, `apps/e2e/tests/product-loop.spec.ts`.

## Coordinator questions — scorecard

| Question                    | Today                                                                                                                                                                 | Finding |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| Who needs attention         | Only people with a `ReviewCase`. No roster. Five counts, none of them people.                                                                                         | 2       |
| Why (evidence chain)        | Three fixed policy strings + one sentence with a raw "56% below ... across 4 days". No link to what preceded it.                                                      | 9       |
| What Care+ already did | Not on the case. Only in a separate per-person "outreach, end to end" card that defaults to Mdm Lim regardless of which case is on screen.                            | 9       |
| What the senior said        | Aggregated enums only (good). Decline reasons labelled. Raw notes redacted. But a disputed day never reaches the case.                                                | 10      |
| What remains uncertain      | Data-basis label exists on Overview only. Case card has no data-quality line, no `self_reported_conflict`, no "device suspected".                                     | 7, 10   |
| Why a human is needed       | One fixed recommendation string for every case.                                                                                                                       | 9       |
| Outcome / follow-through    | Strong. Outreach history card is honest, denominators visible, no rates.                                                                                              | —       |
| Duplicate cases             | **Broken after Acknowledge** — verified.                                                                                                                              | 1       |
| Case history                | Append-only rows exist; card shows status + note only, no timestamps, no reviewer, no "day N".                                                                        | 4, 9    |
| Privacy boundaries          | Docs say counts-only; Overview and Simulator render every `PersonFact` under a "for care coordinators" banner (auth-off demo). Under auth-on, the 403 is mislabelled. | 5       |
| Human override memory       | Not stored. UI sends two canned notes; no structured human action / reason / disagreement flag. WAYFINDER F16 "NOT STARTED".                                          | 3       |
| Case clock                  | `opened_at` wall-clock only; nothing else. Refresh does not bump anything; no `next_review_at`; resolution reason only in a free-text system note.                    | 4       |
| Device pathway              | `device_suspected=True` is computed, then dropped: NO_ACTION, band `stable`, nothing to senior, nothing to coordinator.                                               | 7       |
| Normal seniors visible      | No. They exist only as a "No action needed" _decision_ count, not a person.                                                                                           | 2       |

---

## Findings

### 1. Acknowledging a case then one more declining day opens a duplicate case — P0

**Evidence.** Probe section A (repository, SQLite, fixture):

```
after 3 declines: [('case_1890812', 'open', 4)]
-- review_case(ACKNOWLEDGED) --
decision day4: coordinator_review created_case: case_66420a6
cases now: [('case_66420a6', 'open',  "Activity is 56% below Mdm Lim's personal baseline across 4 days."),
            ('case_1890812', 'acknowledged', "Activity is 56% below Mdm Lim's personal baseline across 3 days.")]
metrics.open_cases: 1
```

Two cards for one concern, one person; the queue card says "2 cases for 1 senior"
(`care-team-view.tsx:257-260`) while `metrics.open_cases` says 1 (`sql_repository.py:6112-6122`
counts `OPEN` only). Every further declining day refreshes the _new_ open case, so the acknowledged
one is frozen at "3 days" forever.

**Root cause.** `_create_case` dedups only against `CaseStatus.OPEN`
(`sql_repository.py:2619-2632`). `ACKNOWLEDGED` is a non-terminal status the dedup does not
recognise. `test_case_dedup.py:103-129` pins resolved→new case (correct) but has no acknowledged
path. `docs/WAYFINDER.md:1604` already notes "dedups only against `CaseStatus.OPEN`" in a different
context.

**Existing substrate.** `_create_case` refresh branch; `CaseReviewRow`; `_close_open_cases_for_*`
already treat "unresolved" as `status != RESOLVED` (`sql_repository.py:1240-1243, 1282-1285`).

**Proposed design.** In `_create_case`, select `ReviewCaseRow.status != CaseStatus.RESOLVED.value`
(same predicate the closers use), refresh summary/evidence/decision_evidence_id, and **keep** the
existing status (an acknowledged case stays acknowledged; the coordinator's acknowledgement was of
the concern, not of one day's number). Return `None` on refresh as today.

**Files.** `apps/api/src/silverloop/sql_repository.py` (`_create_case`). Effort **S**. Schema: no.

**Test to pin.** `test_case_dedup.py::test_acknowledging_a_case_and_declining_again_refreshes_it`:
3 declines → acknowledge → 1 decline → `len(list_cases()) == 1`, status `acknowledged`, summary
says 4 days.

### 2. Seniors who are fine are invisible to the care team — P1

**Evidence.** `care-team-view.tsx` renders `CountTile`s (lines 216-245) then `ReviewCard`s from
`cases` only. The "No action needed" tile is `fleet.noActionDecisions`
(`scenario-data.ts:222`, summed `metrics.no_action_decisions` = a count of _decision rows_,
`sql_repository.py:6124-6135`), not people. `fleet.peopleMonitored` is `count(PersonRow)`
(`sql_repository.py:6079`). There is no "list people" endpoint — the web hard-codes `PERSONAS`
(`scenario-data.ts:32-38`, comment admits it). `AttentionBand` is computed per person
(`sql_repository.py:1119-1139`, `models.py:22-26`, labels `Normal/Monitoring/Needs review` in
`view-models.ts:92-96`) but only reachable via `GET /v1/people/{id}/state`, which is
`Senior`-scoped (`main.py:375-387`); ADR 0001 §Context item 4 (`docs/adr/0001-...md:64-78`)
confirms a real coordinator cannot read it. The empty-queue state (`care-team-view.tsx:248-256`)
says "No one needs human review right now" — a coordinator cannot see _who_ is fine, whether
anyone's tracker is dark, or whether anyone is currently being nudged.

**Root cause.** The queue is case-centric; the roster concept was never built. Care Team was
designed to lead "with who needs attention" (component docblock) but has no per-person row at all.

**Existing substrate.** `PersonState.attention_band`, `consent_active`, `last_decision`,
`signal.quality.device_suspected`, `metrics.awaiting_reply`; `PersonCard` +
`StatusBadge({kind:'attention'})` already render a band; `list_cases()` already unions active runs.

**Proposed design.** New coordinator-scoped read, aggregate-shaped per person (no numbers):

```python
class CoordinatorPersonRow(BaseModel):
    person_id: str
    display_name: str
    attention_band: AttentionBand          # stable | watch | review
    consent_active: bool
    reading_interpretable: bool            # False => "Tracker may not have synced"
    open_case_id: str | None
    awaiting_reply: int                    # offers inside the response window
    last_observed_day: date | None
```

`GET /v1/coordinator/people` (`Coordinator` dep) → `repository.list_coordinator_roster()` built
from `_resolve_decision_state` per active run. Care Team renders it as a roster grouped
Needs review / Monitoring / Tracker not synced / Normal, with a `StatusBadge` per row, and the
five tiles become people counts derived from the same array (the component's own "never
disagree with what is on screen" rule). Replace `PERSONAS` with this list; keep `personaLabel`
as a fallback only.

**Boundary note (needs a human decision, per ADR 0001 §A).** A band per named person is
per-person derived data. The ADR already accepts that the queue necessarily shows one person's
derived summary; a roster row that shows only a band word and no figure is the same class as a
case card and far less than `FollowUpObservation` already exposes. Record the decision in ADR 0001
rather than silently extending it.

**Files.** `models.py` (+ `pnpm client:generate`), `main.py`, `sql_repository.py`,
`repository.py` Protocol, `care-team-view.tsx`, `scenario-data.ts`. Effort **M**. Schema: no.

**Tests.** API: roster lists every active-run person with the band `person_state` would return;
coordinator 200, senior 403. e2e: after `low_wear` the roster shows "Tracker may not have synced"
for Mdm Lim and she is still listed under a non-alarming heading.

### 3. Human override memory does not exist — P1

**Evidence.** `ReviewRequest` is `{status, reviewer_note}` (`models.py:527-530`).
`review_case` stores status, reviewer (`current_user.sub`), note, timestamp, and an audit event
with `decision_evidence_id` (`sql_repository.py:5714-5786`, detail at 5756-5770). The UI never
lets a coordinator type: `care-team-view.tsx:159-165` sends one of two canned strings
("Coordinator resolved the synthetic case; no autonomous outreach performed." /
"Coordinator acknowledged the evidence and retained human control."). There is no field for what
the human decided to _do_, whether it agreed with `ReviewCase.recommendation`, or why. Nothing
reads reviews back for evaluation (`test_learning_weights.py:376` pins that a closure moves the
ranker by zero — correct — but there is no query over overrides). `docs/WAYFINDER.md:1177-1185`
lists this as **F16 — Override memory, NOT STARTED**.

**Root cause.** Review was built as an audit checkbox, not as a decision record.

**Existing substrate.** `CaseReviewRow` (append-only), `case_reviewed` audit event carrying
`decision_evidence_id`, `OutcomeKind.COORDINATOR_RESOLVED`, `ReviewCard.action_history`.

**Proposed design.** Structured, deterministic, no LLM:

```python
class CoordinatorAction(StrEnum):
    NO_FURTHER_ACTION = "no_further_action"
    PERMITTED_CHECK_IN = "permitted_check_in"     # the thing recommendation already names
    WATCH_ANOTHER_WEEK = "watch_another_week"
    REFER_TO_AAC_STAFF = "refer_to_aac_staff"

class OverrideReason(StrEnum):
    KNOWN_CONTEXT = "known_context"               # "she told us she's away"
    DATA_DOUBT = "data_doubt"                     # tracker/ingest suspected
    RECENT_CONTACT = "recent_contact"             # already spoken to them
    OTHER = "other"

class ReviewRequest(BaseModel):
    status: CaseStatus
    human_action: CoordinatorAction
    override_reason: OverrideReason | None = None  # required when action != recommended
    reviewer_note: str = Field(min_length=2, max_length=500)
```

`ReviewAction` gains `human_action`, `agent_recommendation: str` (frozen copy of
`row.recommendation` at review time), `override_reason`. `CaseReviewRow` gains three nullable
columns (Alembic + the hand-mirrored Supabase SQL). `OperationalMetrics` gains
`coordinator_reviews: int`, `coordinator_overrides: int` (counts, denominator beside). `ReviewCard`
replaces the two buttons with a small radio group + optional reason + note. Learning boundary
unchanged: overrides feed audit and evaluation only (F16's own constraint).

**Files.** `models.py`, `db_models.py`, new Alembic revision, `infra/supabase/*.sql` mirror,
`sql_repository.py` (`review_case`, `_to_case`, `metrics`), `review-card.tsx`,
`care-team-view.tsx`, `docs/api.md`. Effort **M**. Schema: **yes**.

**Tests.** `test_case_terminal_state.py`-style: a review with `human_action != recommended` and no
`override_reason` → 422; audit detail carries `agent_recommendation`, `human_action`,
`override_reason`; `metrics().coordinator_overrides` increments; `learning` snapshot unchanged.

### 4. The case has no clock and no resolution semantics — P1

**Evidence.** `ReviewCaseRow` has only `opened_at` (wall-clock, `db_models.py:246`); refresh
(`sql_repository.py:2627-2631`) updates summary/evidence but records no `last_refreshed_*`. No
`next_review_at`. Nothing advances time except `POST /v1/simulation/advance` (allowed events
`sql_repository.py:1439-1449`; no scheduler anywhere — grep `scheduler|cron|BackgroundTasks` in
`apps/api/src/silverloop/*.py` returned nothing). A NO_ACTION day only touches a case when it is a
_genuine recovery_ (`sql_repository.py:1707-1715`: NO_ACTION ∧ interpretable ∧
`sustained_low_days == 0`) — a low-wear day, a rainy day, or a small-baseline NO_ACTION leaves the
case exactly as it was, silently. Auto-resolution reason lives only in a free-text `note` with
`reviewer="system"` (`sql_repository.py:1250-1259, 1293-1302`), rendered on the card as
"Resolved — Closed automatically: ..." with no timestamp (`review-card.tsx:80-93`; no
`recorded_at`/`opened_at`/`reviewer` anywhere in the file). "Acknowledged" means nothing to the
system: it does not snooze, it does not set a review-by day, and (finding 1) it does not even
stop a duplicate.

**Root cause.** Case = row + status; the lifecycle was never modelled beyond three statuses.

**Existing substrate.** Simulated-day clock already exists for the response window
(`RESPONSE_WINDOW_DAYS`, `_awaiting_reply_until`, `sql_repository.py:213, 845-867`) and is the
right clock for cases too. `_close_open_cases_for_recovery` / `_for_consent` are the resolution
paths.

**Proposed design.**

```python
class CaseResolution(StrEnum):
    COORDINATOR = "coordinator"
    RECOVERED = "recovered"
    CONSENT_WITHDRAWN = "consent_withdrawn"

class ReviewCase(BaseModel):
    ...
    opened_day: date            # simulated day (from the opening DecisionEvidenceRow.observed_at)
    last_refreshed_day: date    # simulated day of the latest COORDINATOR_REVIEW that refreshed it
    days_in_review: int         # last_refreshed_day - opened_day + 1
    resolution: CaseResolution | None
    review_by_day: date | None  # opened_day + CASE_REVIEW_WINDOW_DAYS while open
```

`opened_day`, `last_refreshed_day`, `days_in_review` are **derivable** today from
`decision_evidence_id` → `DecisionEvidenceRow.observed_at` (no schema). `resolution` is derivable
from the last `CaseReviewRow` (reviewer `system` + note prefix) but should be stored honestly
(`CaseReviewRow.resolution` column) rather than string-matched. `review_by_day` needs a column or
a constant; treat it as "Care+ will re-surface this" (case card copy), never a deadline shown
to a senior. Card: show `opened_day`, `days_in_review`, per-action `recorded_at` + reviewer, and
"Closed: activity recovered / consent withdrawn / by coordinator" as a `StatusBadge` variant.

**Files.** `models.py`, `sql_repository.py` (`_to_case`), `db_models.py` + Alembic + Supabase
mirror (for `resolution`), `review-card.tsx`, `view-models.ts` (`caseResolutionLabel`). Effort
**S** for derived fields, **M** with the column.

**Tests.** `_to_case` after 4 declines → `days_in_review == 2` (opened day 3, refreshed day 4);
after `recovery` → `resolution == RECOVERED`; after `consent_revoked` → `CONSENT_WITHDRAWN`.

### 5. Privacy labelling: coordinator-labelled surfaces show per-person facts; docs say counts only — P1

**Evidence.**

- `overview-view.tsx:104-122` renders `CoordinatorScopeNotice` ("This view is for care
  coordinators") for senior accounts, and lines 162 / 300-304 fetch `api.worldModel(personId)` and
  render `<PersonalWorldModel>` — every `PersonFact.statement` with provenance
  (`personal-world-model.tsx:35-58`). `decision-simulator.tsx` does the same (`api.worldModel` at
  ~460 and ~515, `<PersonalWorldModel>` at ~855).
- API and docs say the opposite: `main.py:716-730` (`person_world_model`, `Senior` dep,
  docstring "never reach a coordinator in content"), `docs/api.md:343-344` ("Only the senior may
  read it; the coordinator's `/v1/metrics` carries `world_model_quality` counts and never a fact"),
  `docs/architecture.md:449-450`, `docs/WAYFINDER.md:583` ("Aggregate only"), and
  `care-team-view.tsx:224-228` comment.
- With `AUTH_ENABLED=false` (the only way the demo runs) the scope check is disabled
  (`main.py:1262-1268`), so the "coordinator" Overview shows Mdm Lim's likes/dislikes and fixture
  biography. With auth on, a real coordinator gets 403 and the panel says "The world model has not
  loaded for this persona yet" (`personal-world-model.tsx:118-121`) — an outage sentence for a
  permission boundary, and the daily chart falls back to "Only today's reading is available"
  (`overview-view.tsx:281-286`) for the same reason (`/v1/people/{id}/metrics` is `Senior`,
  `main.py:390-405`).
- ADR 0001 (`docs/adr/0001-...md:79-99, 280-320`) already records that
  `GET /v1/coordinator/people/{id}/outreach-history` returns per-person `FollowUpObservation`
  step/percentage changes with no scope or consent check, and that consent-withdrawn cases stay
  readable with their derived summary (probe section E confirms: status `resolved`,
  `consent_active: False`, summary "Activity is 56% below ..."). It flags the outreach-history
  question as needing a human decision; it does **not** mention the world-model panel on Overview
  and Simulator. That is the new item.

**Root cause.** Overview/Simulator are evaluator screens wearing a coordinator label; the
demo-mode auth bypass makes the label false.

**Proposed design (no consent-model work).**

1. Label honestly: `PersonalWorldModel` on Overview/Simulator gets a kicker "Evaluator view —
   not part of the care-team surface" and is hidden when `currentUser.role === 'coordinator'`
   (the web already has `useAuth().currentUser`). Better: move it to `/evidence?tab=audit` and
   keep Overview to `PersonCard` + story + chart + counts.
2. Replace the "has not loaded" copy with a role-aware line: "Not shown to coordinators — see the
   senior's own Privacy page" when the failure is a 403 (`isExpectedScopeError` already exists,
   `scenario-data.ts:52-54`).
3. Outreach history for coordinators: keep the loop (offered / said / did) but drop the
   `FollowUpObservation` numbers from `OutreachSummary` on the coordinator route, returning only
   `follow_up.available` + `returned_toward_usual` + `caveat` (a description, not a figure), or
   make the figures a `demo_operator`-only read. This is the ADR §A option "(a)/(c)" family; pick
   it in the ADR.
4. `list_cases` for a person whose consent is inactive: return the case with `summary` redacted to
   "Closed when consent was withdrawn" (the audit row still holds the full text). Small change in
   `_to_case`.

**Files.** `overview-view.tsx`, `decision-simulator.tsx`, `personal-world-model.tsx`,
`sql_repository.py` (`list_outreach_summaries`, `_to_case`), `docs/adr/0001` decision block.
Effort **S** (1–2), **M** (3–4). Schema: no.

**Tests.** `test_auth_rbac.py`: coordinator token on outreach-history gets no `steps_after`
figure; component test: role `coordinator` → no `PersonalWorldModel` in Overview DOM.

### 6. Evaluator policy-gate ladder has drifted from `policy.py` — P1

**Evidence.** `policy.py` has two rungs the UI does not know: the small-baseline gate
(`MINIMUM_INTERPRETABLE_BASELINE`, `policy.py:~90-105`, NO_ACTION with rationale "typical
activity is too low for a percentage change to carry meaning") and the accepted-outreach cooldown
inside `_contact_guard` (`policy.py:27-56`, SUPPRESS with rationale "took up a suggestion within
the last few days"). `explainPolicyGates` (`view-models.ts:267-405`) reconstructs six gates only.
Consequences a judge would see on `/evidence?tab=audit`:

- A cooldown SUPPRESS renders the contact-cap gate as "Weekly contact cap reached; the
  notification-fatigue guard suppressed this otherwise-warranted action." (`view-models.ts:386-392`)
  — factually wrong for that decision.
- A small-baseline NO_ACTION renders "That remains within the range the ladder treats as
  normal" (`view-models.ts:361-371`) for a person who may be 100% below.
- The boundary note (`evidence-view.tsx:386-391`) and the file comment (`view-models.ts:222-226`,
  "keep this in sync") state a six-gate order that is no longer the ladder.

**Root cause.** The gate that fired is not on the contract; the UI re-derives it and drifted.

**Existing substrate.** `PolicyResult.rationale` strings; `PersonState.rationale`;
`DecisionTraceStep(stage="policy_gate")`.

**Proposed design.** Put it on the contract, deterministically:

```python
class PolicyGate(StrEnum):
    CONSENT = "consent"; DATA_QUALITY = "data_quality"; CONFIDENCE = "confidence"
    RAIN_CONTEXT = "rain_context"; SMALL_BASELINE = "small_baseline"
    SEVERITY_PERSISTENCE = "severity_persistence"; CONTACT_CAP = "contact_cap"
    ACCEPTED_COOLDOWN = "accepted_cooldown"; WITHIN_RANGE = "within_range"

@dataclass(frozen=True)
class PolicyResult:
    decision: Decision; support_priority: int; rationale: list[str]; decided_by: PolicyGate
```

`PersonState.decided_by_gate: PolicyGate` (+ `pnpm client:generate`). `explainPolicyGates`
becomes a pure render over the ordered gate list with `decided_by` marking the stop; delete the
reconstruction. Also add `SMALL_BASELINE`/`ACCEPTED_COOLDOWN` to `GATE_LABELS`.

**Files.** `policy.py`, `models.py`, `sql_repository.py` (state build ~1141-1160),
`view-models.ts`, `evidence-view.tsx`, `openapi/silverloop.json` + `libs/api-client`. Effort
**S**. Schema: no (contract yes).

**Tests.** `test_policy.py`: each rung asserts `decided_by`; scenario YAML may add
`expected_gate`; web unit test that every `PolicyGate` has a label.

### 7. The device pathway stops at a chip nobody acts on — P2

**Evidence.** Probe section C after `low_wear`: `decision: no_action band: stable safe: False
device_suspected: True`, `created_intervention: None`, rationale "Tracker wear-time was 2.1
hours; at least 8 hours is required." `quality.py:26-49` authors a good sentence
("...did not sync; this looks like a device issue rather than a wellbeing signal") into
`device_suspected_reason`. The only renderer is the `ContextChip kind="device-support"`
("Tracker issue suspected", `context-chip.tsx:45-48`) on `DecisionStoryCard`
(`decision-story-card.tsx:172-176`), i.e. Overview/Simulator. Care Team has no tile, no roster
(finding 2), and `metrics` has no `uninterpretable_days`/`device_suspected` counter
(`models.py:1358-1443`). The senior surface renders nothing from decision state at all (grep for
`rationale|attention_band|last_decision|device_suspected|safe_to_interpret` in
`senior-view.tsx` and `senior/*.tsx` → no matches), so a senior whose tracker did not sync is never
told. `docs/WAYFINDER.md:1190-1196` (F17) already sketches `DEVICE_TASK` as a cost-1 action.

**Root cause.** Data quality is a _gate_ only; there is no non-wellbeing action class.

**Proposed design (two layers, second is a policy change).**

- Layer 1, no ladder change: `OperationalMetrics.uninterpretable_days: int` and
  `device_suspected_days: int` (counts for the run); Care Team tile "Tracker may not have synced"
  (tone `data`, not `watch`); roster row flag (finding 2); case card line when the latest reading is
  uninterpretable ("Today's reading could not be interpreted — tracker wear 2.1 h").
- Layer 2 (needs scenario + reviewer per CLAUDE.md): a `Decision.DEVICE_SUPPORT` /
  `Intervention` of class `device_check` — a neutral senior-facing line "We couldn't read your
  tracker today. If it's charged and worn, nothing else is needed." — permitted by consent,
  exempt from the contact cap, never counted as outreach. Update `scenarios/03_low_wear.yaml`,
  `11_irregular_sync.yaml`, `holdout/h01_*` expectations; `policy.py` returns it from the data
  quality rung only when `device_suspected`.

**Files.** Layer 1: `models.py`, `sql_repository.py::metrics`, `care-team-view.tsx`,
`scenario-data.ts`. Layer 2: `policy.py`, `models.py`, `sql_repository.py::_finalize_intervention`,
`outreach_content.py`, scenarios, `senior-view.tsx`. Effort **S** / **M**. Schema: no.

**Tests.** Layer 1: `metrics().device_suspected_days == 1` after `low_wear`. Layer 2: scenario
`03_low_wear.yaml` expects `device_support` and no case; contact-cap test proves it does not
spend the weekly budget.

### 8. Queue hygiene: resolved cases interleave with open ones forever — P2

**Evidence.** `list_cases` has no status filter and orders `priority.desc(), opened_at.desc()`
(`sql_repository.py:5690-5705`); `priority` is hard-coded 4 for every case
(`sql_repository.py:2640`), so the order is purely newest-first regardless of status. The Care
Team heading counts them all: "N cases for M seniors" (`care-team-view.tsx:257-260`); the
"Needs review" tile counts `status === 'open'` only (line 208). After one recovery the queue shows
two resolved cards (probe A). No `?status=` param, no pagination (`main.py:1186-1193`).

**Proposed design.** `GET /v1/coordinator/queue?status=open,acknowledged` (default) and
`?status=resolved&limit=20`; order open → acknowledged → resolved, then by `last_refreshed_day`
desc. Care Team: open+acknowledged as cards; resolved behind a "Recently closed" `<details>`.
Drop the fixed `priority` from the card ("4 of 5" for every case is noise, `review-card.tsx:103-106`)
or derive it: `5` if `days_in_review >= 7`, `4` otherwise.

**Files.** `main.py`, `sql_repository.py`, `repository.py`, `care-team-view.tsx`,
`review-card.tsx`. Effort **S**. Schema: no.

**Test.** `test_multi_person.py`: default queue excludes resolved; `status=resolved` includes only
resolved.

### 9. The case card cannot tell the story: no time, no actor, no "what Care+ already did" — P2

**Evidence.** `ReviewCard` shows: person, fixed title ("Sustained activity decline requires human
review", `sql_repository.py:2639`), `summary` (a raw percentage sentence, `2602-2606`), consent,
"Human actions: N", and behind a disclosure: three fixed policy strings as "Evidence", a fixed
recommendation ("Review context and consent, then decide whether a permitted check-in is
needed.", `2646-2648`), action history as status + note, evidence IDs. Missing: `opened_at`,
`recorded_at`, reviewer name (`review-card.tsx` has none), the day-1 nudge and day-2 suggestion
that _preceded_ the review and what the senior said to them (that lives in a separate card keyed
to a persona switcher defaulting to `mdm-lim`, `care-team-view.tsx:292-300` — it does not follow
the case), data-basis / uninterpretable-day context, and whether rain/holiday were in play.
"Why a human is needed" is the same sentence for everyone.

**Proposed design.** Extend `ReviewCase` (derived in `_to_case`, no schema):

```python
class PriorOutreach(BaseModel):
    decision: Decision; title: str; day: date; outcome: str | None; follow_through: str | None

class ReviewCase(BaseModel):
    ...
    prior_outreach: list[PriorOutreach]     # interventions in this run before opened_day
    context_flags: list[str]                # ["rain on 2 of 4 days", "1 day disputed by senior"]
    why_human: str                          # authored from decided_by_gate + prior_outreach:
                                            # "Two lighter steps were tried (check-in day 1,
                                            #  suggestion day 2); neither was answered."
```

Card layout: person + band → one-line why_human → prior outreach as three chips (offered /
said / did, reusing `outreach-history-labels.ts`) → actions with `recorded_at` + reviewer →
disclosure for evidence IDs. The persona switcher for "Follow-through, person by person" stays but
defaults to the person of the case in view.

**Files.** `models.py`, `sql_repository.py::_to_case`, `review-card.tsx`, `care-team-view.tsx`.
Effort **M**. Schema: no.

**Test.** After the guided "A decline that persists" run, `get_case().prior_outreach` has two
entries (gentle_nudge, programme_suggestion) with `outcome` `no_response` / `None`.

### 10. What the senior said is aggregated correctly, but a disputed day never reaches the case — P2

**Evidence (compliance, confirmed).** Outreach history exposes only `outcome`/`outcome_reason`/
`follow_through` enums (`models.py:440-460`); labels are honest (`outreach-history-labels.ts`:
"Asked to see more ... not a completed activity", `unable` phrased against the suggestion).
Free-text notes are kept on their own rows and the audit says only `note_present`
(`sql_repository.py:3300-3312`; `test_audit_redaction.py`). Ask Care+ raw text: the
`activity_search` audit detail carries `parsed_by`, counts, ranking and agent evidence — not
`raw_text` (`sql_repository.py:4104-4128`) — and the events route is `DemoOperator`, not
coordinator (`main.py:1115-1129`). Good.

**Gap.** `DataQualityAssessment.self_reported_conflict` (`models.py:160-163`; "I was already
active" / day dispute) is not in `ReviewCase`; `_create_case` copies `state.rationale` only. A
coordinator reads "56% below across 4 days" without knowing the person disputed one of them.

**Proposed design.** Part of finding 9's `context_flags` ("1 of 4 days disputed by
{display_name}"); no raw note text. Effort **S**. Test: dispute day 2, decline to day 3 → case
`context_flags` contains the disputed-day line.

### 11. Contract and SDK loose ends on the coordinator path — P2

**Evidence.**

- `GET /v1/cases/{id}` exists (`main.py:1195-1207`) but the SDK has no `getCase`
  (`libs/api-client/src/index.ts`: only `queue` 309, `followUp` 404,
  `coordinatorOutreachHistory` 422, `reviewCase` 703) and no page deep-links a case.
- Care Team's "Look at the days after" button calls `api.followUp` →
  `/v1/interventions/{id}/follow-up`, a **`Senior`**-scoped route (`main.py:519-537`). It is
  dead code today because `list_outreach_summaries` always populates `follow_up`
  (`sql_repository.py:3400`; probe D shows `fu.available: False` with a reason, never `None`) —
  but if it ever fired under auth it would 403 for a coordinator.
- `fetchFleetMetrics` makes five `/v1/metrics` calls against a hard-coded persona list and takes
  `people` from the first fulfilled result (`scenario-data.ts:205-232`).

**Proposed design.** Add `getCase` to the SDK and `/care-team?case=` deep link; remove the lazy
`onRequestFollowUp` wiring from `care-team-view.tsx:147-151` and the prop; replace client-side
fleet aggregation with `GET /v1/coordinator/metrics` (one query, real caseload). Effort **S** /
**M**. Schema: no.

### 12. Evaluator surface (`evidence-view.tsx`): a judge cannot tell AI on/off from the health tab — P2

What a judge **can** tell today, and where:

| Judge question | Answered? | Where                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| -------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Deterministic? | Yes       | Gate ladder (audit tab), "Policy engine: Deterministic ladder, policy vX" (`evidence-view.tsx:1140-1146`), timeline title "Policy decision"                                                                                                                                                                                                                                                                                                      |
| Uses AI?       | Partly    | Only via `AgentRunCard` on the Simulator (`agent-run-card.tsx:44-52` mode labels) and the planner card on the Evaluation tab (`evidence-view.tsx:632-720`). The System Health "Agent" row says "Running" whenever the DB is ready (`1131-1139`), with no LLM on/off. `HealthResponse.llm_enabled` exists (`models.py:539-543`) and is fetched nowhere in the web.                                                                                |
| Learns?        | Yes       | "Expected fit" card with the ranking-only boundary (`evidence-view.tsx:790-845`); timeline "Learn" stage.                                                                                                                                                                                                                                                                                                                                        |
| Synthetic?     | Yes       | Provenance card (`1197-1245`), "Not clinical evidence" alert (`963-972`), Ravi card states fixture value.                                                                                                                                                                                                                                                                                                                                        |
| Measured?      | Partly    | Policy comparison is from the committed artifact with seed/digest/mtime (`1050-1075`). The ranking evaluation (`docs/evaluation/ranking-evaluation.md/.json`) is not surfaced at all (grep `ranking-evaluation` in `apps/web` → none). "Senior responses: Scenario-driven, from the deterministic demo events" (`1218-1221`) is stale now that seniors respond live; follow-up figures are honest ("count of descriptions, not a success rate"). |

**Proposed design.** (a) Fetch `/health` in `SystemHealthPanel`; render the "Agent" row as
"Outreach planner — model **off**, deterministic ranker in use" / "model on (name), guardrail
active" from `llm_enabled` plus `metrics.planner_fallback_modes`. (b) Load
`docs/evaluation/ranking-evaluation.json` through the same server-side loader pattern as
`lib/policy-comparison.ts` and add a "Ranking evaluation" card with its headline metrics and
denominators. (c) Fix the provenance line to "Scenario-driven for the outreach loop; live senior
taps in this session where recorded". (d) Finding 6 fixes the ladder text. Effort **S**. Schema:
no. Test: e2e asserts the health tab contains "model off" when `LLM_ENABLED=false`.

### 13. Docs vs code disagreements to record — P2

- `docs/api.md:343-344`, `docs/architecture.md:449-450`, `main.py:727-728` ("counts only") vs
  `overview-view.tsx:300-304` / `decision-simulator.tsx:~855` rendering facts (finding 5).
- `view-models.ts:222-226` and `evidence-view.tsx:386-391` (six gates) vs `policy.py` (eight
  rungs) (finding 6).
- `docs/demo-runbook.md:87-93` ("Open Care Team: consent, why it reached a human, action history,
  then explicitly acknowledge or resolve") describes the flow that produces finding 1 if the demo
  driver acknowledges and then advances another day; the runbook should say "resolve, or
  acknowledge and stop advancing" until fixed.
- `docs/api.md:36-60` documents `/v1/simulation/latest|history|events` as `demo_operator`; the
  Overview/Evidence pages that call them are labelled coordinator screens. Under auth-on a real
  coordinator sees "No scenario recorded yet" on Overview for everyone (`fetchPersonaOverview`
  swallows the 403, `scenario-data.ts:110-125`). Not a bug in the demo; worth a sentence in the
  runbook.

---

## Ranked improvement list (value ÷ effort)

| #   | Improvement                                                          | Sev | Effort | Schema | Needs                                          |
| --- | -------------------------------------------------------------------- | --- | ------ | ------ | ---------------------------------------------- |
| 1   | Dedup cases against `!= RESOLVED` (finding 1)                        | P0  | S      | no     | `_create_case` predicate                       |
| 6   | `decided_by_gate` on the contract; UI stops reconstructing           | P1  | S      | no     | `policy.py`, `models.py`, client regen         |
| 4a  | Derived `opened_day`/`days_in_review`, timestamps + reviewer on card | P1  | S      | no     | `_to_case`, `review-card.tsx`                  |
| 5a  | Hide/relabel `PersonalWorldModel` for coordinators; honest 403 copy  | P1  | S      | no     | `overview-view.tsx`, `decision-simulator.tsx`  |
| 2   | Coordinator roster with bands, tracker flag, "Normal" people         | P1  | M      | no     | new `GET /v1/coordinator/people` (+ ADR note)  |
| 3   | Structured override memory                                           | P1  | M      | yes    | `ReviewRequest`, `CaseReviewRow` cols, metrics |
| 9   | Case carries prior outreach + context flags + authored why_human     | P2  | M      | no     | `_to_case`                                     |
| 8   | Queue status filter + ordering + drop fixed priority                 | P2  | S      | no     | queue route param                              |
| 7a  | Tracker counts on metrics + Care Team tile                           | P2  | S      | no     | `metrics`                                      |
| 12  | Health tab shows model on/off; surface ranking evaluation            | P2  | S      | no     | `/health` fetch, JSON loader                   |
| 4b  | Stored `CaseResolution` + `review_by_day`                            | P2  | M      | yes    | column + mirror                                |
| 5b  | Coordinator outreach-history without per-person figures              | P2  | M      | no     | ADR 0001 decision                              |
| 11  | SDK `getCase`, deep link, drop dead follow-up path, fleet endpoint   | P2  | S/M    | no     | SDK regen                                      |
| 7b  | `DEVICE_SUPPORT` action class                                        | P3  | M      | no     | ladder change + scenarios + reviewer           |

## What NOT to build

- A per-person "risk score", percentage, or ranking of seniors on Care Team. Bands and counts
  only; the senior-surface rule (no scores/deadlines) and the aggregates decision both point the
  same way.
- Per-person `PersonFact`/`DimensionPreference` content on any coordinator route — the fix is to
  stop showing it under a coordinator label, not to make it official.
- An LLM-authored case summary or recommendation. `why_human` (finding 9) is a deterministic
  template over `decided_by_gate` and prior outreach; keep it that way so the reviewer can be
  sure a human is reading policy output, not a model's.
- A wall-clock scheduler / cron for the case clock. The simulated day is the product's clock;
  `review_by_day` and `days_in_review` should be counted in it like the response window is.
- Auto-resolving on Acknowledge, or an "escalate / dispatch" button. A case closes on recovery,
  consent withdrawal, or a coordinator's explicit decision — nothing else.
- Overrides feeding the ranker or the policy. F16's own constraint: audit and evaluation only.
- A consent-model redesign. Report the read-side leak (finding 5, ADR §A) and let the ADR decide.
- Emergency, fall, or medical framing anywhere in the roster ("Tracker may not have synced" is
  the strongest wording the device pathway should ever use).
