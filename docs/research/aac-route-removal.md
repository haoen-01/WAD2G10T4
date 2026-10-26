# AAC route removal (step 7): confirmed list

- Date: 26 Oct 2026
- Branch: `dev`, commit `34f243d`
- Question: GitHub issue #21. Settled decisions: issue #10 (delete the routes no screen uses and
  the modules nothing else needs, with their tests; keep every module `advance` uses; keep
  review-case writing; drop no tables).
- Sources: the code on `dev` only. Paths are relative to the repo root; `main.py`,
  `sql_repository.py` etc. are under `apps/api/src/silverloop/`.

How this was derived. Routes were enumerated from the `@application.<verb>(` decorators in
`main.py` and `family_routes.py` and cross-checked against `openapi/silverloop.json`. Web calls
were read from `apps/web/src/services/careApi.ts`. "Is this code still needed?" was answered with
a static call graph over `sql_repository.py` (Python `ast`; a function depends on the top-level
helpers it names and on every method whose name it calls through `self.`). Roots were the
repository methods that kept routes and the CLI tools call. Matching `self.` calls by name
overcounts, so "kept" may include more than is strictly needed. It never wrongly marks needed code
as removable.

## Summary

| Count | What |
| ----- | ---- |
| 85 | API operations in `openapi/silverloop.json` (61 in `main.py`, 24 in `family_routes.py`). The decorators and the snapshot agree. |
| 29 | Operations the web app calls: 28 in `careApi.ts` (4 in `main.py`, all 24 in `family_routes.py`) and `GET /v1/auth/me` through the generated client (`apps/web/src/composables/useAuth.ts:43`, the only `SilverLoopClient` call in the web app). |
| 56 | Operations the web app never calls (85 − 29). |
| 4 | Of those, infrastructure and demo-tooling routes that are clearly outside the inventory: `GET /health`, `GET /ready`, `POST /v1/demo/reset`, `POST /v1/simulation/advance`. |
| **52** | 56 − 4. **This matches the 26 Oct inventory.** It is the most likely way the 52 was counted (inferred; the inventory is not in the repo). |
| 1 | Of the 52, kept because e2e uses it: `POST /v1/people/{person_id}/consent` (`apps/e2e/tests/loop.spec.ts:90`). |
| **51** | **Routes to remove**: 30 route-only (Table A) and 21 full removals (Table B). |
| 8 | Modules that can be deleted outright: `triage.py`, `case_delta.py`, `ranker_inspector.py`, `evaluator_presets.py`, `intent.py`, `activity_rerank.py`, `outreach_content.py`, `agent/intent_planner.py`. One more, `review_lessons.py`, is a candidate (open question 5). |
| 2 | Modules the issue lists for full removal that **must stay**: `world_model.py` and `follow_up.py`. Both are used by `repository.metrics()`, which `supabase_smoke.py:44` calls. |
| 0 | Tables dropped. |

## Table A: route-only removals

The route handler goes. The code behind it that `advance` (`sql_repository.py:2573`) or another
kept caller uses stays. The repository method behind each route is used only by that route
(call-graph result), so it can go with the handler. Whether to keep some of them anyway so tests
can still set up state is open question 4.

| # | Method | Path | Handler | Repository method | Why the code behind it stays |
| - | ------ | ---- | ------- | ----------------- | ---------------------------- |
| 1 | GET | `/v1/coordinator/people/{person_id}/review-threshold` | `main.py:1713` | `review_threshold_state` `sql_repository.py:12787` | **Review setting.** `_evaluate` passes the live threshold to `policy.decide` (`sql_repository.py:2218`, `:2231`; `policy.py:81`). `advance` runs `_apply_review_threshold_daily_checks` (`:2953`, def `:11994`) and `_run_threshold_follow_ups` (`:3022`, def `:10848`), which call `agent/threshold_planner.py`, `agent/threshold_tools.py`, `agent/threshold_guardrails.py` and `review_threshold_replay.py` (`day_signals`, `shadow_review_since`, `review_fires`, `variability_summary`). `review_threshold.py` is imported by `policy.py:6`. |
| 2 | GET | `…/review-threshold/replay` | `main.py:1728` | `review_threshold_replay` `:12792` | Same. Only `review_threshold_replay.replay_thresholds` (`review_threshold_replay.py:252`, used only at `sql_repository.py:12745`) becomes dead. |
| 3 | POST | `…/review-threshold/proposals/{proposal_id}/approve` | `main.py:1758` | `approve_threshold_proposal` `:12807` | Same. `advance` still writes proposals (`_store_write_up` `:11191`, `_store_threshold_output` `:11730`) and decisions (`_add_threshold_decision` `:10006`). |
| 4 | POST | `…/review-threshold/proposals/{proposal_id}/reject` | `main.py:1784` | `reject_threshold_proposal` `:12920` | Same. `_reject_open_threshold_proposals_for_consent` (`:11967`, called at `:2743`) stays. |
| 5 | POST | `…/review-threshold/manual` | `main.py:1805` | `set_threshold_manually` `:13049` | Same. |
| 6 | POST | `…/review-threshold/confirm-starting` | `main.py:1829` | `confirm_starting_threshold` `:13175` | Same. |
| 7 | POST | `…/review-threshold/decisions/{decision_id}/reconfirm` | `main.py:1846` | `reconfirm_threshold` `:13252` | Same. |
| 8 | GET | `/v1/coordinator/queue` | `main.py:1634` | `list_cases` `:9310` (**kept**) | **Review cases.** `scenarios.py:35` calls `list_cases`. `advance` writes cases through `_create_case` (`:2949`, def `:3875`). Only the route-local helpers `_parse_queue_statuses` / `_ordered_queue` / `_QUEUE_STATUS_RANK` / `_DEFAULT_QUEUE_STATUSES` (`main.py:318-376`) go. |
| 9 | GET | `/v1/cases/{case_id}` | `main.py:1651` | `get_case` `:9327` | Same. This route and #10 are the only `include_since_last_review=True` callers (`:9332`, `:9848`). See `case_delta` in Table B. |
| 10 | POST | `/v1/cases/{case_id}/review` | `main.py:1665` | `review_case` `:9649` | Same. `CaseReviewRow` is still written by `_close_open_cases_for_consent` (`:2361`) and `_close_open_cases_for_recovery` (`:2401`). `_demo_script_actor` / `DEMO_SCRIPT_*` (`main.py:330-343`) are used only here and by #3, so they go. |
| 11 | GET | `/v1/people/{person_id}/week` | `main.py:1112` | `week_plan` `:8549` | **Week plans.** `advance` reads `WeekPlanEntryRow` directly (`:2777`, `:2799`). |
| 12 | POST | `/v1/people/{person_id}/week` | `main.py:1122` | `plan_activity` `:8554` | Same. This is the only writer of `WeekPlanEntryRow` (`_plan_activity_in_session` `:8578`). See open question 4. |
| 13 | POST | `/v1/people/{person_id}/week/{plan_id}/follow-through` | `main.py:1144` | `record_planned_follow_through` `:7119` | Same. The only writer of `PlanFollowThroughRow`, which kept code still reads. |
| 14 | POST | `/v1/people/{person_id}/week/{plan_id}/enjoyment` | `main.py:1180` | `record_planned_enjoyment` `:7193` | Same. The only writer of `PlanEnjoymentRow`. |
| 15 | GET | `/v1/people/{person_id}/replan-notices` | `main.py:1255` | `replan_notices` `:8811` | **Replanning.** `advance` calls `_expire_open_replan_offers` (`:2868`, def `:8683`) and `_record_replan_offers` (`:2869`, def `:8714`), which call `replanning.notices_for`. Only `replanning.notice_for_offer` (used at `:8854`) becomes dead. |
| 16 | POST | `/v1/people/{person_id}/week/{plan_id}/replace` | `main.py:1272` | `replace_planned_activity` `:6988` | Same. |
| 17 | POST | `/v1/people/{person_id}/replan-offers/{offer_id}/decline` | `main.py:1309` | `decline_replan_offer` `:7077` | Same. |
| 18 | GET | `/v1/people/{person_id}/preferences` | `main.py:747` | `list_candidate_preferences` `:5197` | **Preferences.** `advance` reads `CandidatePreferenceRow` through `_suppressed_candidate_keys` (`:3376`) ← `_intervention_candidates` (`:3474`) ← `_resolve_decision_state` (`:2522`). `_suppress_after_repeated_declines` (`:4744`) still writes it. |
| 19 | POST | `/v1/people/{person_id}/preferences/{candidate_key}` | `main.py:759` | `set_candidate_preference` `:5209` | Same. |
| 20 | GET | `/v1/people/{person_id}/activity-preferences` | `main.py:933` | `activity_preferences` `:5722` | `_record_replan_offers` uses `_activity_preferences_model` (`:5574`), with `preferences.resolve` and `SENIOR_STATEMENT_SOURCE`. `_persist_dimension_preferences` (`:5632`) still writes. |
| 21 | PUT | `/v1/people/{person_id}/activity-preferences/{dimension}/{value}` | `main.py:1214` | `state_preference` `:7284` | Same. |
| 22 | GET | `/v1/people/{person_id}/goals` | `main.py:1079` | `list_goals` `:8397` | **Goals.** `_active_goals` (`:5614`) ← `_activity_preferences_parts` (`:5592`) ← `_record_replan_offers` (in `advance`). |
| 23 | POST | `/v1/people/{person_id}/goals` | `main.py:1091` | `set_goal` `:8407` | Same. This is the only writer of `ActivityGoalRow`. |
| 24 | POST | `/v1/people/{person_id}/day-dispute` | `main.py:788` | `record_day_dispute` `:5282` | **Senior inputs.** `_evaluate` (`:2154`) loads `DayDisputeRow` through `_RunReads` (`:580`). This is the only writer. |
| 25 | GET | `/v1/people/{person_id}/proposed-memories` | `main.py:991` | `list_proposed_memories` `:7566` | Senior inputs. **Nothing kept reads or writes `ProposedMemoryRow`** (call-graph result). The table becomes unused but is not dropped. |
| 26 | POST | `/v1/people/{person_id}/proposed-memories/{proposal_id}` | `main.py:1003` | `decide_proposed_memory` `:7718` | Same. |
| 27 | POST | `/v1/people/{person_id}/context-answer` | `main.py:1027` | `answer_context_question` `:7821` | Senior inputs. `_evaluate` calls `context_question.question_for` and reads `ContextQuestionAnswerRow` (`_RunReads`). `context_question.memory_from_answer` / `OPTION_VALUES` become dead. |
| 28 | POST | `/v1/people/{person_id}/baseline-confirmation` | `main.py:1053` | `decide_baseline_confirmation` `:7944` | Senior inputs. `_evaluate` calls `baseline_confirmation.question_for` (imported at `sql_repository.py:84`) and reads `BaselineConfirmationRow`. |
| 29 | GET | `/v1/metrics` | `main.py:502` | `metrics` `:13777` (**kept**) | `supabase_smoke.py:44` and many unit tests call `repository.metrics()`. Only the route and `_require_metrics` (`main.py:1868`) go. |
| 30 | GET | `/v1/programmes` | `main.py:1342` | `list_programmes` `:5378` | **Not named in issue #21**, but no screen calls it. `advance` uses programmes through `_programme_models` (`:5366`) in `_resolve_decision_state`. `_require_any` (`main.py:1880`) is used only by this route and Table B #3-4, so it goes too. |

## Table B: full removals

"Importers checked" lists every file that imports the module (`grep` over `apps/api/src`,
`apps/api/tests` and `scripts`). "Removed-only" means that inside `sql_repository.py`, only code
reachable from removed routes uses the module.

| # | Method | Path | Handler | Repository method(s) | Module(s) deleted | Importers checked |
| - | ------ | ---- | ------- | -------------------- | ----------------- | ----------------- |
| 1 | GET | `/v1/coordinator/priorities` | `main.py:1587` | `care_priorities` `:9497`, `_care_context` `:9408`, `_runs_with_open_threshold_proposal` `:9475` | **`triage.py`** | `main.py:133` (only `DEFAULT_TOP_K`, `MAX_TOP_K` for this route), `sql_repository.py:342` (removed-only), `tests/test_triage.py`, `tests/test_care_team_group.py`. Not imported by `advance`, `policy.py`, `agent/`, `seed.py`, `scenarios.py` or `smoke.py`. |
| 2 | POST | `/v1/evaluator/ranker/inspect` | `main.py:1454` | `inspect_ranker` `:6045` | **`ranker_inspector.py`** | `main.py:118-122` (exceptions for this route only), `sql_repository.py:23` (removed-only), `tests/test_ranker_inspector.py`, `tests/test_ranking_trace.py`. |
| 3 | GET | `/v1/evaluator/ranker/presets` | `main.py:1489` | `ranker_presets` `:6290` | **`evaluator_presets.py`** | `ranker_inspector.py:66`, `sql_repository.py:135` (removed-only), `tests/test_ranker_inspector.py`. |
| 4 | POST | `/v1/activities/search` | `main.py:816` | `search_activities` `:5810`, `_plan_intent_safely` `:5727`, `_plan_activity_ranking_safely` `:5764` | **`intent.py`**, **`activity_rerank.py`**, **`agent/intent_planner.py`** | `intent.py`: `ranker_inspector.py:72`, `sql_repository.py:145` (removed-only), plus tests. `activity_rerank.py`: `ranker_inspector.py:35`, `sql_repository.py:24` (removed-only), `tests/test_ranking_trace.py`. `agent/intent_planner.py`: `agent/__init__.py:16` (re-export of `plan_intent`), `sql_repository.py:54` (removed-only), tests. **`activity_search.py` stays**: `replanning.py:38` and `advance` (`_activity_engagement` `:6338` ← `_record_replan_offers`) use `ActivityEngagement`, `count_engagement`, `engagement_by_series`, `series_keys_for`, `filter_candidates` and `rank_candidates`. `rank_with_trace` and `RANKING_WEIGHTS` become dead. |
| 5 | POST | `/v1/activities/{activity_id}/response` | `main.py:849` | `respond_to_activity` `:6695` | (none) | This is the only writer of `ActivityOfferResponseRow`, which `metrics()` still reads (`:13800`). |
| 6 | GET | `/v1/activities` | `main.py:888` | `list_activities` `:5457` | (none) | The catalogue (`ActivityCandidateRow`) is still refreshed by `advance` (`_refresh_stale_activities`, `:2862`). |
| 7 | GET | `/v1/activities/{activity_id}` | `main.py:899` | `get_activity` `:5461` | (none) | |
| 8 | GET | `/v1/people/{person_id}/world-model` | `main.py:917` | `world_model` `:8171` | **None. `world_model.py` must stay.** | `metrics()` builds `world_model_quality` through `_world_models` (`:8182`, called at `:13829`) → `build_world_model`. `metrics()` is kept (Table A #29). See open question 3. |
| 9 | GET | `/v1/interventions/{intervention_id}/detail` | `main.py:663` | `outreach_detail` `:4890` | **`outreach_content.py`** | `sql_repository.py:264` (only `detail_for`, used at `:4910`), `tests/test_outreach_content.py`, `tests/test_follow_through_api.py`. |
| 10 | POST | `/v1/interventions/{intervention_id}/follow-through` | `main.py:682` | `record_follow_through` `:4912` | (none) | This is the only writer of `InterventionFollowThroughRow`, which `advance` still reads (`_load_run_interventions` `:2008`). |
| 11 | GET | `/v1/interventions/{intervention_id}/follow-up` | `main.py:714` | `follow_up_observation` `:5014`, `_observe` `:5000` | **None. `follow_up.py` must stay.** | `observe_effect` is used by `metrics()` through `_follow_through_observability` (`:13704`, `:13741`). |
| 12 | GET | `/v1/interventions/history` | `main.py:734` | `list_outreach_summaries` `:5050` | (none) | Shared with #15. |
| 13 | POST | `/v1/interventions/{intervention_id}/enjoyment` | `main.py:951` | `record_enjoyment` `:7443` | (none) | This is the only writer of `InterventionEnjoymentRow`, which `advance` still reads (`_preference_rows` `:3259` ← `_resolve_unanswered_outreach`). In effect this is route-only. |
| 14 | GET | `/v1/coordinator/people` | `main.py:1567` | `list_coordinator_roster` `:9365`, `_active_runs` `:9335`, `_latest_unresolved_cases` `:9347` | (none) | |
| 15 | GET | `/v1/coordinator/people/{person_id}/outreach-history` | `main.py:1524` | `list_outreach_summaries` `:5050` | (none) | |
| 16 | GET | `/v1/coordinator/people/{person_id}/activity-relative` | `main.py:1542` | `activity_relative_to_usual` `:5022` | (none; trim `analytics.py`) | `analytics.activity_relative_to_usual` (`analytics.py:188`) and `ACTIVITY_RELATIVE_*` (`:184-185`) are used only by this route (`main.py:15`, `repository.py:6`, `sql_repository.py:77-79`). The rest of `analytics.py` stays. |
| 17 | GET | `/v1/coordinator/metrics` | `main.py:1618` | `coordinator_metrics` `:13891` | (none) | |
| 18 | GET | `/v1/evaluator/people/{person_id}/senior-home` | `main.py:1499` | `senior_home` `:4460` | (none) | `SENIOR_HOME_PREVIEW_DISCLOSURE` (`main.py:135`) goes. |
| 19 | GET | `/v1/simulation/history` | `main.py:1433` | `simulation_history` `:3042` | (none; trim `stored_state.py`) | `stored_state.load_stored_history_entry` (`stored_state.py:110`) is used only at `sql_repository.py:3065`. `load_stored_advance` stays (the idempotent `advance` replay). |
| 20 | GET | `/v1/simulation/latest` | `main.py:1417` | `latest_advance` `:3025` | (none) | |
| 21 | GET | `/v1/simulation/events` | `main.py:1401` | `list_events` `:3991` | (none) | |
| (no route) | | case delta | (reached from Table A #9-10) | `_since_last_review` `:9108` | **`case_delta.py`** | Imported only by `sql_repository.py:85` and `tests/test_case_delta.py`. `_to_cases` (`:8987`) still names `_since_last_review` (`:9099-9103`), but only when `include_since_last_review=True`. The only callers that set it are `get_case` (`:9332`) and `review_case` (`:9848`). `list_cases` (`:9325`) and `_create_case` (`:3955`) use the default `False`. So removing `case_delta.py` also means removing that parameter and branch from `_to_cases` / `_to_case` (`:8980`). The `ReviewCase.since_last_review` field (`models.py:665`) is in the kept contract through `AdvanceResponse.created_case`; see open question 2. |

Other code that goes with these routes:

- **`main.py`**: the exception handlers for `ReviewThresholdNotFound` (`:397`) and
  `ReviewThresholdConflict` (`:446`). Every raise site is inside the removed review-setting
  methods (`sql_repository.py:12753-13291`). Also the `review_threshold` bound constants imported at
  `main.py:124-130`, the `RankerInspectorDefect`/`RankerPersonNotFound`/`RankerRequestError` import,
  and the triage/analytics constant imports.
- **`sql_repository.py`**: about 100 functions are reachable only from removed routes, among them
  `RankingInputs` (`:899`), `_ThresholdRound` (`:1005`), the two exception classes (`:997`,
  `:1095`), `_threshold_state` (`:12564`) and its helpers through `:12785`, and `_review_lesson`
  (`:9862`). The full list is easy to regenerate with the call-graph method described at the top.
- **`repository.py`**: the Protocol methods at `:103-109`, `:125-173`, `:179-343` (except
  `set_consent` `:175`) and `:347-411`. Keep `list_cases` `:345`, `metrics` `:413`, and the rest.
- **`agent/`**: the activity-ranking loop (`plan_activity_ranking` `agent/planner.py:387`,
  `ActivityPlanRun` `:253`, `planner_transport` `:246`, plus `ActivityRankingContext`, the
  `activity_tool_definitions`, `validate_activity_order`) is reached only from
  `search_activities` / `inspect_ranker`. `plan_outreach` (`:843`) is what `advance` uses
  (`_plan_outreach_safely` `sql_repository.py:3720`). Trimming is optional; see open question 6.
- **`libs/api-client/src/index.ts`** (hand-written facade, not generated: `scripts/generate-contract.sh`
  writes only `src/generated`). It imports 50 SDK functions for removed operations (`:3-63`) and
  wraps them as methods (`:535-1215`: `queue`, `getCase`, `coordinatorPeople`, … `reconfirmThreshold`).
  These must go, or `pnpm typecheck` fails after `pnpm client:generate`. Keep `me`, `state`,
  `personMetrics`, `reset`, `advance`, `interventions`, `readiness`, `health`, `updateConsent` and
  `recordOutcome`. `programmes` and `metrics` go with their routes.

## Routes flagged as used by e2e, smoke or demo tooling (not removed)

| Route | Used by | Decision |
| ----- | ------- | -------- |
| `GET /health` | `apps/e2e/playwright.config.ts:47` (webServer probe), `smoke.py:9` | Keep |
| `GET /ready` | Liveness and readiness contract (`docs/observability.md`); tests in `test_api.py`, `test_rls_posture_startup.py` | Keep |
| `POST /v1/demo/reset` | `apps/e2e/tests/support.ts:25`, `smoke.py:11`, `apps/api/project.json:103` (`pnpm demo:reset`) | Keep |
| `POST /v1/simulation/advance` | `apps/e2e/tests/support.ts:47` | Keep |
| `POST /v1/people/{person_id}/consent` | `apps/e2e/tests/loop.spec.ts:90` ("consent withdrawn through the API still shows on the home overview") | **Keep.** It is in the 52 but not removable without changing e2e. |
| `GET /v1/people/{person_id}/state` | `smoke.py:12` (also called by the web app) | Keep |

Non-HTTP tool use of repository methods (these stay): `scenarios.py:25-59` (`create_schema_for_tests`,
`reset`, `advance`, `list_cases`, `list_interventions`, `close`); `supabase_smoke.py:29-56`
(`reset`, `readiness`, `advance`, `record_outcome`, **`metrics`**); `seed.py:24` (`reset`);
`setup_demo_accounts.py:184`, `family_groups.py:130-502`, `family_routes.py:106,458`,
`auth.py:247,354`. `scripts/demo-offline.mjs` and `tools/` call no API routes. The e2e suite calls
no route being removed.

## Pydantic models to delete

After removal, `pnpm client:generate` takes **189 of 270** `components.schemas` out of
`openapi/silverloop.json`. That is everything reachable only from the 51 removed operations,
computed from the snapshot's `$ref` graph. Not all of those can leave `models.py`, because some are
still used internally.

**Safe to delete from `models.py`** (no reference from any kept module, kept `sql_repository.py`
function or kept route; checked over `models.py`'s own field references). There are 128 names. By
group, with `models.py` line:

- Triage / care priorities: `CoordinatorPersonRow` 668, `FollowUpWindow` 707, `PriorityHold` 721,
  `CareNoteKind` 728, `CareNote` 739, `CareTeamGroup` 747, `CareTeamGroupReason` 758,
  `CarePriorityRow` 777, `ThresholdReference` 816, `CarePriorityBoard` 822.
- Review cases / lessons / review setting: `ReviewLessonKind` 227, `ReviewLessonReason` 240,
  `ReviewReceiptStatus` 262, `ReviewReceiptExclusion` 270, `ReviewRequest` 1151, `ReviewLesson` 1216,
  `CaseReviewResponse` 1230, `ReviewThresholdProposal` 1300, `ReviewThresholdDecisionRecord` 1362,
  `ReviewThresholdCheck` 1383, `ReviewReceiptEntry` 1390, `ReviewSettingReceipt` 1409,
  `ContextGapCount` 1431, `ContextGapTally` 1437, `ReviewThresholdState` 1446,
  `ReviewThresholdApproveRequest` 1475, `ReviewThresholdRejectRequest` 1488,
  `ReviewThresholdManualSetRequest` 1505, `ReviewThresholdShownRequest` 1511,
  `ReviewThresholdDecisionResponse` 1515.
- Outreach extras: `OutreachStep` 936, `OutreachDetail` 943, `FollowThroughRequest` 970,
  `FollowThroughResponse` 977, `OutreachSummary` 1018, `EnjoymentRequest` 2231, `EnjoymentResponse` 2236.
- Senior inputs / preferences / goals / week / replan: `CandidatePreferenceRequest` 1108,
  `CandidatePreferenceResponse` 1113, `DayDisputeRequest` 1118, `DayDisputeResponse` 1132,
  `PreferenceStance` 2173, `PreferenceStatementRequest` 2188, `PreferenceStatementResponse` 2195,
  `MemoryDecision` 2250, `MemoryDecisionRequest` 2276, `MemoryDecisionResponse` 2280,
  `ContextAnswerRequest` 2335, `ContextAnswerResponse` 2341, `BaselineConfirmationRequest` 2379,
  `BaselineConfirmationResponse` 2383, `ActivityGoalRequest` 2417, `PlannedFollowThroughRequest` 2449,
  `PlannedFollowThroughResponse` 2454, `PlannedEnjoymentRequest` 2461, `PlannedEnjoymentResponse` 2466,
  `WeekPlan` 2518, `PlanActivityRequest` 2528, `ReplacePlannedActivityRequest` 2606.
- Activity search: `ActivityQueryRequest` 1932, `ActivityQueryResponse` 1939,
  `ActivityResponseRequest` 2485, `ActivityResponseResponse` 2502.
- Coordinator / evaluator views: `SeniorHomePreview` 1521, `CoordinatorFleetMetrics` 2841.
- Ranker inspector and trace (`models.py:2875-3606`): `RankerRequestCounterfactual`,
  `RankerWorldModelCounterfactual`, `RankerWorldCounterfactual`, `RankerCounterfactual`,
  `RankerFeedbackKind`, `RankerFeedbackPreview`, `RankerInspectRequest`, `TracePerson`, `TraceRequest`,
  `TraceIntentAxis`, `TraceParsedIntent`, `FactProvenance`, `FactNotUsedReason`, `TraceFact`,
  `UnknownAxis`, `TracePersonContext`, `TraceRetrieval`, `TraceFilterOutcome`, `TraceFiltering`,
  `TraceSortKey`, `TraceUnknownReason`, `TraceRequestAxis`, `TracePreferenceAxis`,
  `TraceEngagementCounts`, `TraceEngagement`, `IntegrityClass`, `SilentByDesign`, `IntegrityFinding`,
  `ReasonWithoutPositiveFactor`, `CandidateIntegrity`, `TraceStagePositions`, `CandidateTrace`,
  `TraceSortKeyField`, `TraceScoring`, `TraceSort`, `TraceSeriesDeferral`, `TraceSeriesDedupe`,
  `TraceVarietyConsidered`, `TraceVarietySwap`, `TraceVariety`, `TracePostProcessing`, `TraceToolCall`,
  `TracePlannerMovement`, `TraceIntentPlanner`, `LlmStageStatus`, `TraceLlmRerank`,
  `TraceRecommendation`, `TraceWebCard`, `TraceFinalRecommendations`, `TraceIntegrity`,
  `TraceCatalogueUnknown`, `TraceScriptedEvent`, `TraceScriptedHistory`, `TraceWorldModelEffect`,
  `TraceLearningPreview`, `TraceApplied`, `ActivityRankingTrace` 3509, `RankChange` 3536,
  `RankerInspectResponse` 3569, `RankerPresetEvent` 3575, `RankerHistoryPreset` 3585,
  `RankerCounterfactualControls` 3592, `RankerPresetsResponse` 3606.

**Can be deleted only after trimming dead functions in kept modules:**
`SimulationHistoryEntry` 892 (`stored_state.load_stored_history_entry`); `ReviewThresholdReplay`
1341 and `ReviewThresholdReplayEpisode` 1327 (`review_threshold_replay.replay_thresholds`);
`ActivityRelativeToUsual` 1062 and `ActivityRelativeDay` 1053 (`analytics.activity_relative_to_usual`);
`SinceLastReview*` 598 (only if `ReviewCase.since_last_review` is dropped; open question 2).

**Leave the contract but stay in `models.py`** (kept code uses them): for example
`OperationalMetrics` 2710 and `WorldModelQuality` 2685 (`metrics()`), `PersonWorldModel` 2701
(`world_model.py`), `FollowUpObservation` 987 (`follow_up.py`), `ReplanNotice` 2580 /
`ReplanOffer` 2561 (`replanning.py`), `ProposedMemory` 2256 (`context_question.py`), `Programme`
833, `ActivityCandidate` and the activity-ontology enums (`activity_search.py`, `preferences.py`,
`fixtures.py`). Removing operations changes the contract, so `pnpm client:generate` has to run and
both `openapi/silverloop.json` and `libs/api-client/src/generated` have to be committed. `pnpm
client:check` enforces this.

## Tests to delete or update

The numbers are tests that touch the removed surface over the file's total `def test_` count. A
test counts as touching it if it calls a removed route, calls a removed repository method, imports a
removed module, or uses a helper that does. All files are in `apps/api/tests/`.

**Delete the whole file** (its subject is the removed surface):

| File | Hits | Reason |
| ---- | ---- | ------ |
| `test_triage.py` | 28/29 | `triage` |
| `test_care_team_group.py` | 5/18, imports `triage` | Care-team groups are a `triage.py` concept. The other 13 tests import it too, so the file cannot run. |
| `test_case_delta.py` | 14/21, imports `case_delta` | Module deleted |
| `test_case_since_last_review_api.py` | 7/7 | `GET /v1/cases/{id}` |
| `test_ranker_inspector.py` | 47/47 | |
| `test_ranking_trace.py` | 10/37, imports `ranker_inspector`, `activity_rerank`, `intent` | The file cannot import |
| `test_intent.py` | 56/57 | `intent.py` |
| `test_intent_planner.py` | 13/19, imports `intent_planner` | |
| `test_outreach_content.py` | 10/12, imports `outreach_content` | |
| `test_simulation_history.py` | 5/5 | |
| `test_coordinator_queue_filters.py` | 5/5 | |
| `test_coordinator_roster.py` | 5/5 | |
| `test_activity_relative.py` | 14/14 | |
| `test_baseline_confirmation_api.py` | 4/4 | Route. (`test_baseline_confirmation.py`, the pure module, stays.) |
| `test_baseline_confirmation_repository.py` | 6/7 | `decide_baseline_confirmation` |
| `test_activity_responses.py` | 69/70 | User-initiated loop |
| `test_search_ranking_golden.py` (+ `golden/search_detail_ranking.jsonl`, `golden/search_scenarios_golden.jsonl`) | 2/2 | Pins `POST /v1/activities/search` |
| `test_replan_loop.py` | 20/20 | Replace and decline routes. **Check first** that `advance`'s replan-offer writing still has coverage somewhere (see `test_replan_offers.py`). |
| `test_follow_through_ownership.py` | 11/11 | |
| `test_review_override_memory.py` | 7/7 | `review_case` |
| `test_review_threshold_demo.py` | 5/5 | Coordinator and cases routes |
| `test_review_lessons_contract.py` | 5/6 | Only if `review_lessons.py` goes (open question 5) |
| `test_review_setting_receipt.py` | 16/19 | Receipt = `review_threshold_state` and `review_lessons` |

**Update** (mixed files where most tests still cover kept behaviour; drop or rewrite the hits):

`test_activity_catalogue_migration.py` 3/3 (uses `list_activities` only to read the catalogue, so
switch to a direct query), `test_activity_planner.py` 4/26, `test_activity_search.py` 7/86 (also
imports `intent`), `test_agent_integration.py` 4/14, `test_api.py` 7/17 (`/v1/metrics`, simulation
latest/history/events), `test_audit_redaction.py` 8/9, `test_auth_rbac.py` 36/65 (the coordinator,
evaluator, metrics, programmes and simulation rows), `test_case_clock.py` 2/4, `test_case_dedup.py` 2/7,
`test_case_terminal_state.py` 4/4 (uses `review_case`/`get_case` as setup; rewrite against
`list_cases`), `test_catalogue_reset_anchor.py` 3/7, `test_consent_boundary.py` 1/7,
`test_context_explanation_api.py` 6/7, `test_context_wiring.py` 3/8, `test_error_handling.py` 3/9,
`test_failure_paths.py` 1/4, `test_follow_through_api.py` 25/40 (imports `outreach_content`),
`test_intervention_outcome_ownership.py` 1/3, `test_multi_person.py` 1/22, `test_persistence.py` 2/13,
`test_postgres_integration.py` 2/12, `test_preferences.py` 1/92 (imports `intent`),
`test_prompt_injection.py` 3/14 (imports `intent`), `test_query_counts.py` 6/8,
`test_recorded_client.py` 5/31 (imports `intent`, `intent_planner`), `test_replan_offers.py` 11/11
(it tests `advance` writing offers, but sets up with `plan_activity`; it needs a direct
`WeekPlanEntryRow` fixture), `test_response_clock.py` 8/14, `test_review_context_gap_contract.py` 6/9,
`test_review_threshold_api.py` 27/65, `test_review_threshold_postgres.py` 1/2,
`test_second_answer_programme.py` 9/10, `test_stale_run_boundary.py` 10/14,
`test_stored_state_compat.py` 13/22, `test_threshold_planner.py` 26/53 (calibration runs inside
`advance`, but the tests seed coordinator reviews with `review_case` and approve proposals with
`approve_threshold_proposal`), `test_world_model.py` 9/51 (`world_model.py` stays; drop the route
tests).

`apps/e2e/tests/`: **nothing to change.** No spec calls a removed route. The routes e2e does call
are listed above.

## Scenarios

**No change.** `scenarios.py` uses only `create_schema_for_tests`, `reset`, `advance`,
`list_cases` and `list_interventions` (`scenarios.py:25-59`), all kept. The YAML files in
`scenarios/` and `scenarios/holdout/` hold events and expected decisions, cases and outcomes only;
none refers to a removed route or module. `pnpm test:scenarios` and `test_scenarios.py` should pass
unchanged.

## Docs to update

- `docs/api.md`: "What the web app uses" (`:12-22`); the Demo routes table rows `:59-73`; the
  sections "The follow-through loop (no screen)" (`:320`, table `:327-334`), "The user-initiated
  loop (no screen)" (`:392`, table `:402-420`, and `:521` "The closed loop"), "The Activity Ranker
  Inspector" (`:772`), "The review-threshold calibrator" (`:866`, table `:881-887`) and "What each
  review teaches" (`:897`). The note at `:9-10` about the `index.ts` facade stays true but should be
  checked.
- `docs/architecture.md`: the module map entries for `intent.py` (`:168`), `outreach_content.py`
  (`:188`) and `agent/intent_planner.py` (`:224`); the decision trace (`:345`, simulation
  latest/history); the activity-planning subsystem (`:458-470`); the world model (`:537-550`, which
  stays as a module but loses its route); replanning (`:581-594`).
- `CLAUDE.md`: "API surface with no screen" (`:275-283`). Rewrite it to say the routes are gone and
  which modules stay because `advance` needs them. (Only the human edits this file.)
- `agenticlayer.md`: `:308` (`agent/intent_planner.py` row), §11 "The other two loops" (`:353-440`).
- `docs/testing.md`: `:23-24` (coordinator metrics / priorities), `:139` (`test_outreach_content.py`),
  `:164-171` (search golden files), `:219-225` (`test_review_lessons_contract.py`,
  `test_case_delta.py`, `test_case_since_last_review_api.py`).
- `docs/observability.md`: `:21` (`/v1/simulation/events`), `:46` and `:70` (`/v1/metrics`), `:54`
  (`/v1/coordinator/queue`).
- `docs/care-priorities.md` (whole doc describes `triage.py` and `/v1/coordinator/priorities`):
  mark it as removed or delete it.
- `docs/review-threshold-spec.md` (`:358-404`, coordinator routes and replay) and
  `docs/calibration-trust-spec.md`: mark the routes as removed.
- `docs/personalisation-v2-decisions.md:149` (mentions `intent.py`).
- ADRs `docs/adr/0001`, `0004`, `0005`, `0006`, `0009` mention removed routes. ADRs are a historical
  record, so add a status note ("routes removed in step 7") rather than rewriting them. Whether to do
  that at all is the human's call.

## Tables: none dropped

No table is dropped and no migration is written. Every table in `db_models.py` stays. After the
removal, these tables still exist and are still read by kept code, but **nothing in the app writes
them any more**: their only writers were the removed methods.

| Table (class, `db_models.py`) | Only writer (removed) | Still read by |
| ----------------------------- | --------------------- | ------------- |
| `WeekPlanEntryRow` :861 | `_plan_activity_in_session` `sql_repository.py:8578` | `advance` `:2777` |
| `ActivityGoalRow` :839 | `set_goal` `:8407` | `_active_goals` `:5614` (in `advance`) |
| `DayDisputeRow` :216 | `record_day_dispute` `:5282` | `_RunReads` (in `_evaluate`) |
| `ContextQuestionAnswerRow` :773 | `answer_context_question` `:7821` | `_RunReads` |
| `BaselineConfirmationRow` :811 | `decide_baseline_confirmation` `:7944` | `_RunReads` |
| `InterventionEnjoymentRow` :716 | `record_enjoyment` `:7443` | `_preference_rows` `:3259` |
| `InterventionFollowThroughRow` :164 | `record_follow_through` `:4912` | `_load_run_interventions` `:2008` |
| `ActivityOfferResponseRow` :631 | `respond_to_activity` `:6695` | `metrics()` `:13800` |
| `PlanFollowThroughRow` :673 / `PlanEnjoymentRow` :696 | `record_planned_follow_through` `:7119` / `record_planned_enjoyment` `:7193` | `metrics()` via `_attended_series_for` `:6502` |
| `ProposedMemoryRow` :743 | `answer_context_question` `:7821` | **nothing kept** |

These tables still have kept writers: `CandidatePreferenceRow` (`_suppress_after_repeated_declines`
`:4744`), `ActivityDimensionPreferenceRow` (`_persist_dimension_preferences` `:5632`),
`CaseReviewRow` (system closures `:2361`, `:2401`), `ReviewThresholdProposalRow` (`:11191`,
`:11730`), `ReviewThresholdDecisionRow` (`:10006`), `ReplanOfferRow` (`:8714`) and `ReviewCaseRow`
(`_create_case` `:3875`). The schema, Alembic history and `infra/supabase` SQL are untouched.

## `list_cases` and review-case writing: kept

- `list_cases` (`sql_repository.py:9310-9325`) stays. It is called by `scenarios.py:35` and stays
  on the Protocol (`repository.py:345`). It goes through `_to_cases` without
  `include_since_last_review`, so removing `case_delta` does not change what it returns
  (`since_last_review` is already `None` there, `:9099-9103`).
- Review-case writing inside `advance` stays. `_create_case` is called at `:2949` (def `:3875`),
  and the system closures `_close_open_cases_for_consent` (`:2740`, def `:2361`) and
  `_close_open_cases_for_recovery` (`:2926`, def `:2401`) stay. `AdvanceResponse.created_case` (a
  `ReviewCase`) stays in the contract, and e2e reads it (`apps/e2e/tests/support.ts:33-37`).
- What goes is the human side of a case only: `get_case`, `review_case` and the queue route.

## Open questions

1. **52 vs 56.** The re-derived count is 56 un-called operations. 52 matches if the inventory left
   out `/health`, `/ready`, `/v1/demo/reset` and `/v1/simulation/advance`. That is inferred; please
   confirm. `POST /v1/people/{id}/consent` is in the 52 but e2e uses it, so this list keeps it (51
   removals). Removing it means changing `loop.spec.ts:84-98` first.
2. **`case_delta.py` and `ReviewCase.since_last_review`.** The module can go only if
   `include_since_last_review` and the `_since_last_review` branch come out of `_to_cases`. That
   leaves `ReviewCase.since_last_review` (`models.py:665`) always `None` in the kept contract
   (through `AdvanceResponse.created_case`). Drop the field, which also removes the `SinceLastReview*`
   models, or keep it as an always-null field?
3. **`world_model.py` and `follow_up.py` cannot be fully removed** as the issue lists, because
   `repository.metrics()` (kept for `supabase_smoke.py:44` and the route-only `/v1/metrics`
   decision) builds `world_model_quality` and the follow-through counters from them. Either accept
   them as kept modules, or drop those fields from `OperationalMetrics` (a contract change) and
   then delete them.
4. **Dormant `advance` branches.** Route-only removal strips the only writers of ten tables (see
   Tables). The `advance` code that reads them (replanning against week plans, goals in activity
   preferences, day disputes and context answers in `_evaluate`, enjoyment in the learners,
   coordinator reviews and approvals in the threshold calibrator) stays. Nothing in the running app
   can feed it any more, so in practice it only ever sees empty tables. That matches "keep every
   module `advance` uses", but tests that set up these paths through the removed repository methods
   (`test_replan_offers.py`, `test_threshold_planner.py`, `test_case_terminal_state.py`, …) need
   either direct row fixtures or repository write methods kept without routes. Which one?
5. **`review_lessons.py`** is used only by `review_case`, `_review_lesson` and `_threshold_state`,
   all removed (`sql_repository.py:9681`, `:9864`, `:12634-12661`). It is not on the issue's
   full-removal list, and `CLAUDE.md:277` groups it with the coordinator tools. Delete it in step 7
   (with `test_review_lessons_contract.py`), or keep it?
6. **The `agent/` activity-ranking loop** (`plan_activity_ranking`, `ActivityPlanRun`, the activity
   tools and `validate_activity_order`) serves only search and the inspector. Deleting
   `agent/intent_planner.py` is clean. Trimming `agent/planner.py`, `agent/tools.py` and
   `agent/guardrails.py` touches the outreach planner's own files. Do it in step 7 or leave it for
   later?
7. **The `Coordinator` role.** After removal no route requires `Coordinator` (`auth.py:362`). The
   role stays in `AuthRole` and `setup_demo_accounts.py`. `test_auth_rbac.py` loses its coordinator
   rows. Is that fine, or should the role's purpose be documented?
8. **`libs/api-client/src/index.ts`** is hand-written and must be edited in the same change.
   `CLAUDE.md` says not to hand-edit `libs/api-client`, but that rule is about `src/generated`. Please
   confirm the facade can be edited.
