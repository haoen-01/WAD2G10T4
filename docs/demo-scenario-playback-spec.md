# Demo scenario playback: spec (2026-09-17)

Branch `feat/demo-scenario-playback`, stacked on `ui/product-redesign`.

## Objective

Presenting the review-timing arc means about 20 day clicks plus tab switching. Cut it to a handful of
stops, while keeping every day visible and every action honest.

## The arc (Mdm Wong, verified on the offline demo)

Days and decisions below come from running the API on 2026-09-17 (offline, LLM off, fixed rule).

| Chapter                       | Steps (event)                                               | Expected                                                                               | Action needed before the next step                                                                                                         |
| ----------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 1. A swing asks a person      | declines ×3                                                 | nudge → programme suggestion → **case opens**                                          | Review: override `not_a_concern`, status `resolved`                                                                                        |
| 2. Rain, and a second swing   | recovery; `rain_explains_decline` ×1; recovery; declines ×3 | no action; **no action (rain_context)**; no action; nudge → programme → **case opens** | Review: override `not_a_concern`, `resolved`. Then **approve** the fixed-rule proposal (40%/3 days → 40%/4 days) on the review-timing page |
| 3. The next swing stays quiet | recovery; declines ×3; recovery                             | setting is 40%/4 from the recovery day; three low days, **no case**                    | none                                                                                                                                       |
| 4. A real change still asks   | declines ×4                                                 | case opens on day 4                                                                    | Review: `agree`, `resolved`, `reached_too_late: true`                                                                                      |
| (end)                         | recovery                                                    | setting back to 40%/3 days from this day                                               | none                                                                                                                                       |

Exactly **one** rain day: a second consecutive rain day is decided by the weekly contact cap, not the
rain.

## API (implementer)

1. `ReviewRequest.recorded_by_demo_script: bool = False`, and the same field on the review-threshold
   proposal **approve** request body.
   - When `true` and `settings.auth_enabled` is true, respond **403** ("Demo script actions are only
     available with sign-in off.").
   - When `true` and sign-in is off, record the actor (`reviewer` / `decided_by`) as `"demo-script"`,
     never `"system"`, which means a system closure in `review_lessons`.
   - The audit event detail records `recorded_by_demo_script: true`. A demo-script review still counts
     as a human review for calibration; that is the point of skipping a chapter. Document this on the
     field.
2. Replace the pinned sequence in `apps/api/tests/test_review_threshold_demo.py` with the arc above,
   asserting the per-day decisions and gates, case openings, the proposal, the live setting after
   approval (from the next day), the quiet chapter, and the revert. Add a test that a demo-script
   review records `reviewer == "demo-script"` and is refused (403) with sign-in on.
3. `pnpm client:generate`, commit both artifacts. `ruff`, full API pytest, `pnpm client:check`.

## Web (frontend-engineer)

All in the simulator unless stated. Offline and deterministic. Reuse `components/ops` primitives.

1. **Scenario model** (`lib/guided-scenarios.ts`): add optional `chapters` (title plus the step
   index range) and a machine-readable `action` on a step's interlude:
   `{ kind: 'review', request: { human_action, override_reason?, status, reached_too_late? } }` or
   `{ kind: 'approve_proposal' }`. Keep the human-readable interlude text, updated to current button
   names. Replace Mdm Wong's steps with the arc above. Other scenarios keep working; a scenario with no
   chapters is one implicit chapter.
2. **Play to next stop.** Primary button "Play to next stop"; secondary "Run one day"; "Pause" while
   playing.
   - Days run sequentially about 600 ms apart (no added delay under `prefers-reduced-motion`).
   - It stops when the next step needs an action, when a day opened a case, or at a chapter end.
   - Show "Stop n of m" and a one-line stop reason ("A case opened. Review it before the next day.").
3. **Day strip.** A compact, accessible list of every day run so far: simulated date, % against her
   usual (`state.signal.delta_percent`, one decimal, "below usual" / "above usual"), and a plain
   decision label: Gentle suggestion · Programme suggestion · Case opened · No action · No action,
   rain explains it · Held back, weekly contact limit · Suppressed. Each row can open that day's full
   story. `aria-live="polite"` announces only the latest day. Horizontal overflow never reaches the
   page body at 390 px.
4. **Stops link to the work.**
   - A case stop links to `/care-team/cases/{created_case.case_id}?returnTo=<simulator url>`.
   - An approve stop links to `/care-team/review-timing/{personId}?returnTo=…`.
   - The case page and review-timing page show **Back to the scenario** when `returnTo` is a safe
     internal `/simulator` path (sanitise: same origin, path starts with `/simulator`, no protocol, no
     `//`).
   - The simulator accepts `?scenario=<id>` and restores progress from `sessionStorage` (keyed by
     scenario id). The stored progress is valid only if the person's latest simulated day matches;
     otherwise it offers "Continue from where {name} is now" or "Start again".
   - Instead of trusting a checkbox, the player **verifies** the action: the case is no longer open
     (review), or `open_proposal` is gone and `live` changed (approve). The "I've done this"
     checkbox stays as a fallback.
5. **Chapters.**
   - A chapter list with "Start from chapter n" (sign-in off only).
   - It resets the person, runs every earlier step instantly, and performs earlier actions through
     the generated client with `recorded_by_demo_script: true` and the note "Recorded by the demo
     script to skip ahead. Not a coordinator's judgement."
   - It then stops at the start of chapter n, with a progress line while it works and a calm error
     if anything fails.
6. **Presenter keys.** **N** runs one day and **P** plays or pauses. Ignore them when focus is in an
   input, textarea, select or contenteditable element, or when a modifier key is held. Show a
   one-line hint.
7. **Labelling.** Anywhere a review or decision's actor is shown (case action history, review-timing
   history), `demo-script` reads "Recorded by the demo script".
8. **Tests.**
   - Unit: stop logic, chapter plan builder, `returnTo` sanitiser, key guard, decision labels.
   - e2e (`apps/e2e/tests/simulator-playback.spec.ts`): start Mdm Wong from chapter 2 → play to the
     case stop → open the case via the stop link → record Not a concern → Back to the scenario → play
     → approve on review timing → back → play chapter 3 and assert no case opened.

## Out of scope

Live-LLM playback (each day waits on the model); changing policy or calibration rules; new routes
beyond the flag.
