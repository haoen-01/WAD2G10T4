# Handover: Care+ UI redesign (`feat/ui-redesign`)

> **For Claude Code:** read this file in full, then `CLAUDE.md` and `AGENTS.md`. Then run the
> "Before you start" checks below, report the current status to the user in a few lines, and propose
> the next step. Do not start building until the user says go. Work **one step at a time** and stop
> after each one so it can be committed on its own.

## 1. Where things stand

Branch: `feat/ui-redesign` (based on `dev`). Everything below is committed; the tree was clean at
handover.

| Step  | What                                                                                   | Status   | Commit(s)                       |
| ----- | -------------------------------------------------------------------------------------- | -------- | ------------------------------- |
| 0     | Repo cleanup (stale docs, evaluation harness, unused web files)                        | Done     | `8459cc8`                       |
| 1     | Navigation shell: bottom tab bar (phone), header pill (desktop), Settings menu, tokens | Done     | `ae6dc6a`                       |
| 2     | Backend: family activity feed + check-ins                                              | Done     | `df4f589`, `5cb025a`, `7ce26f6` |
| 3     | Backend: per-day appointment notes                                                     | Done     | `c3c4ae1`                       |
| **4** | **Family Home redesign (feed, check-ins, motion)**                                     | **Next** |                                 |
| 5     | Calendar redesign (week strip, agenda, bottom sheet, notes)                            | To do    |                                 |
| 6     | Family page redesign                                                                   | To do    |                                 |
| 7     | Senior screen polish (CSS only)                                                        | To do    |                                 |
| 8     | Sign-in and onboarding screens                                                         | To do    |                                 |
| 9     | Final review, clean-up, delete this file                                               | To do    |                                 |

The backend for the whole redesign is finished. **Steps 4–9 are frontend only** (`apps/web`,
`apps/e2e`, docs). Do not change `models.py`, the database or the contract unless a step below says
so.

## 2. The vision

Care+ has two sides:

- **Family side** (Home, Calendar, Family; used by adult children caring for a senior). It should
  feel like a polished, interactive **mobile care app**, not a dashboard, and make a strong first
  impression on the professors who grade it. References for feel (not to copy): Life360, Jointly,
  Caring Village, Medisafe, MyChart, Healthy 365, Google Maps. Think: cards that animate in,
  bottom sheets that slide up and can be dragged down, swipeable stacks with button equivalents,
  numbers that count up, avatars, a live-feeling feed, quick one-tap actions.
- **Senior side** (one screen, "My day"). Must stay **simple and intuitive**: big text, big buttons
  (56px+), almost no motion (gentle fades only), nothing that needs a swipe, **no new features**.

Design system decisions already made (do not reopen without the user):

- **Bootstrap 5 + existing tokens** in `apps/web/src/styles/theme.css` (light and dark), font
  Atkinson Hyperlegible Next. Rules Bootstrap can't express go in the component's `<style scoped>`.
- **Motion:** add `motion-v@2.6.0` (Motion for Vue) with its peer `@vueuse/core@14.4.0`, **exact
  pins**, in step 4. Patterns are inspired by 21st.dev (animated tabs, number ticker, stacked cards,
  bottom sheet), rebuilt as Vue components (21st.dev itself is React + Tailwind; don't add Tailwind).
- **Import motion-v only from lazily loaded views/components, never from `AppLayout.vue`** or
  anything the senior or sign-in screens load. The nav indicator is CSS only and must stay so.
- **Reduced motion is mandatory:** every motion component checks `prefers-reduced-motion` (via a
  `useReducedMotion` composable wrapping `usePreferredReducedMotion` from `@vueuse/core`) and falls back
  to instant or opacity-only. The global CSS rule in `theme.css` only covers CSS transitions, not JS
  animations.
- **Swipe/drag is never the only way:** always a visible button for the same action.
- Product boundary (`AGENTS.md`): no diagnosis, no emergency features, no contacting anyone without
  consent. UI copy must never suggest Care+ contacted someone, or that time since the last check-in
  is a risk signal.
- **Map / senior location:** out of scope. It belongs to the `feat/maptracker` branch. Step 6 only
  leaves an empty placeholder. (If that branch ships live location, it must be opt-in by the senior,
  labelled as simulated, and not framed as an emergency feature, or it contradicts `AGENTS.md`.)

Bundle baseline (gzip, before step 1): entry `index-*.js` 91.24 kB, entry `index-*.css` 35.09 kB.
After step 1: 92.27 kB / 36.17 kB. Budget for the rest: entry JS +5 kB at most; the motion chunk
should load only with the family views.

## 3. How to work (every step)

This follows `CLAUDE.md`'s engineering workflow. The role briefs are in `.agents/*.md`; they are not
registered agent types, so launch each as a `general-purpose` agent with that file's text as the
brief (model: sonnet for implementer/frontend-engineer/reviewers/verifier, opus for architect).

1. **Implement**: `frontend-engineer` (`.agents/frontend-engineer.md`) with the step spec below.
   One owner per file at a time. Tell it: no commits, no new deps beyond what the step allows.
2. **Validate** (section 5) yourself, not just trusting the agent's report.
3. **Review** in parallel: `code-reviewer` and `design-reviewer` (give the design reviewer
   screenshots, see section 5). Reviews are read only; they never fix.
4. **Fix** valid, evidence-based findings by sending them back to the same implementer. Ignore
   speculative ones. Re-review only the areas the fixes touched.
5. **Verify**: `verifier` against the step's acceptance criteria, running the real app.
6. **Stop and hand to the user for the commit** (section 4). Never start the next step until the
   user confirms the commit.

Tell every agent the **port rule** (section 6) and to keep long commands in the background so it
doesn't stall (two agents stalled after 10 minutes of silence during step 3).

## 4. Commit protocol (sequential, one commit per step)

- Each step is exactly **one commit**, made only after the step is verified and the user agrees.
- Before committing, show the user: what changed, the validation results, the full file list from
  `git status --short` (including **new untracked files**), and a conventional commit message.
- Commit only when the user says so. Stage **explicit paths** (not `git add .`), and include every
  new file of the step. After committing, run `git status --short`; it must be empty. Step 2 was
  first committed without its regenerated contract, docs and Supabase file, which needed two
  follow-up commits; avoid that.
- Messages: `feat(web): …`, `test(e2e): …`, `docs: …`. End with the attribution lines the session
  asks for, if any.
- Never push, rebase, amend or force anything unless the user asks.

## 5. Validation commands (Windows; Bash tool = Git Bash)

`pnpm verify` does not work on Windows (it calls `.sh` scripts and `python3`). Run the gates one by
one from the repo root:

```bash
pnpm exec prettier --check . '!**/.claude/**'
bash scripts/check-contract.sh          # only meaningful when the contract is committed
pnpm lint
pnpm --filter ./apps/web typecheck
pnpm --filter ./apps/web test           # web unit tests (node --test over src/lib/*.test.ts)
pnpm --filter ./apps/web exec vite build   # report entry js/css gzip sizes
pnpm test:scenarios
cd apps/api && uv run pytest -q -p no:warnings   # ~5–20 min; run in the background
E2E_API_PORT=8400 E2E_WEB_PORT=3400 pnpm exec playwright test --config apps/e2e/playwright.config.ts
```

Screenshots for the design reviewer: a small Playwright script in the session scratchpad (not the
repo) against a server on a free port, capturing each changed screen at 375×812 and 1280×800, in
light and dark mode, and the senior screen at 375×812. Look at them yourself too.

## 6. Known issues and gotchas

- **Ports:** the user runs `pnpm dev` on 3000/8000. Agents must use other ports (e.g. 3400/8400,
  3500/8500) and stop **only processes they started, by PID** whose command line they checked. Never
  kill by port. (Once during step 1 the user's dev server ended up stopped; the cause wasn't confirmed.)
- **Pre-existing failures (not from this work):**
  - `ruff format --check` fails on `apps/api/src/silverloop/triage.py`. Leave it unless the user asks.
  - Flaky e2e: `family.spec.ts` "painting busy hours, clearing them, and using the keyboard" fails
    on and off (it also failed on the code before the redesign). `tasks.spec.ts` "caregiver creates a
    daily task…" failed once. Rerun alone before calling anything broken. Step 6 restyles the
    painter: worth fixing the flake there if the cause is found.
  - The `family_routes.py` docstring says the senior link PIN lasts 15 minutes; the code is 10.
    Fixing it changes the OpenAPI text (needs `bash scripts/generate-contract.sh`).
- **Contract:** `bash scripts/generate-contract.sh` regenerates `openapi/silverloop.json` and
  `libs/api-client/src/generated`. `check-contract.sh` diffs against git, so it fails until the
  regenerated files are committed. New types must also be re-exported by hand in
  `libs/api-client/src/index.ts`.
- **PostgreSQL tests** (`test_postgres_integration.py`) need `SILVERLOOP_POSTGRES_TEST_URL` and have
  not been run for steps 2–3. Run them if a test database is available.
- **Line endings:** git warns "CRLF will be replaced by LF". That's autocrlf; the diffs are clean.
- `vite.config.ts` has `optimizeDeps.include`; a dependency missing from it causes "optimized
  dependencies changed, reloading" during e2e runs. Add `motion-v` and `@vueuse/core` in step 4.

## 7. What the backend already gives you (steps 2–3)

All routes use the family auth dependency; only **active members** of the care group get data
(others 404; a signed-in senior gets 403). With sign-in off, the demo user is picked by the
`X-Demo-Sub` header (`demo-family` = Sarah, `demo-john`, `demo-emily`; `demo-senior` is not a member),
which `services/http.ts` already sends. The senior's screens must **never** call these routes.

**Activity feed:** `GET /v1/groups/{group_id}/activity?limit=20&before=<activity_id>` →
`FamilyActivityPage { entries: FamilyActivityEntry[], next_before: string | null }`, newest first.
`limit` 1–50. Entry fields: `activity_id, kind, at, actor_member_id, actor_name, is_me,
subject_name, appointment_id, appointment_title, appointment_kind, on_date, occurrence_id,
check_in_kind, note, origin ('live' | 'demo_seed')`.
Kinds: `group_created, member_approved, member_declined, appointment_added, appointment_changed,
appointment_removed, helper_joined, helper_stepped_back, availability_updated, check_in,
note_added`. Notes:

- The server returns structured fields only; **the browser writes the sentences** (e.g. "Sarah
  took Physio on Tue 28 Oct", "You called Mum · "She sounded cheerful""). Handle an unknown kind with a
  generic line.
- `occurrence_id` is set only if that day still exists; link it to `/calendar?appointment=<id>`.
  Repeating-appointment entries have `on_date: null` (series-level).
- `origin: 'demo_seed'` entries must show a small **"Sample"** tag.
- Entries are immutable, so polling = re-fetch the first page and merge by `activity_id`.

**Check-ins:** `POST /v1/groups/{group_id}/check-ins` body `{ kind: 'called' | 'visited' |
'messaged', note?: string (≤200) }` → 201 `FamilyActivityEntry`. A family member telling the group
they were in touch; Care+ sends nothing.

**Appointment notes** (per day of an appointment, author-only delete):

- `GET /v1/groups/{gid}/appointments/{aid}/notes?date=YYYY-MM-DD` → `AppointmentNote[]` oldest first
  (`note_id, appointment_id, occurrence_id, member_id, author_name, is_mine, text, created_at`).
- `POST` same path, body `{ date, text (1–500) }` → 201 `AppointmentNote`. 409 when the day already
  has 100 notes.
- `POST /v1/groups/{gid}/notes/{note_id}/delete` → 204; another member's note → 403.
- The appointment's existing `notes` field is different: it's the appointment's "details / what to
  bring". Label the two clearly in the UI (e.g. "Details" vs "Family notes").

Demo reset (`POST /v1/demo/reset`, which every e2e test calls) seeds 6 sample feed entries and one
sample note by Sarah on the doctor's visit.

## 8. Remaining steps in detail

### Step 4: Family Home redesign

Files: `apps/web/package.json` + `pnpm-lock.yaml` (add `motion-v@2.6.0`, `@vueuse/core@14.4.0`
exactly), `vite.config.ts` (`optimizeDeps.include`), `src/views/HomeView.vue`,
`src/components/home/*` (new `ActivityFeed.vue`, `CheckInCard.vue`), `src/components/motion/*`
(new, only the primitives this step uses, e.g. `NumberTicker.vue`, `StaggerList.vue`,
`PressScale.vue`), `src/composables/useReducedMotion.ts`, `src/composables/useFamilyActivity.ts`
(new), `src/lib/family-feed.ts` + `family-feed.test.ts` (new), `src/lib/motion.ts` + test (tokens,
pure, no motion-v import), `src/services/careApi.ts` (add `getGroupActivity`, `checkIn` only;
nothing else may call `http`), `src/composables/useFamily.ts` (refresh hook), e2e specs.

Build:

- Hero "Today with Mdm Lim" card with the existing activity ring; the percentage uses a
  `NumberTicker` (animated digits `aria-hidden`, real value in visually hidden text; final value
  instantly under reduced motion).
- `ActivityFeed`: entries animate in (stagger), relative times, "You" vs names, "Sample" tag, links
  to calendar occurrences, "Show more" using `next_before`, empty and error states.
- `CheckInCard`: three big buttons (Called / Visited / Messaged) plus an optional note; optimistic
  prepend, rolled back with a toast on error.
- `useFamilyActivity`: module singleton like `useFamily`; keyed by group id and demo sub; polls
  every 30 s with `useIntervalFn`, refreshes on window focus/visibility, pauses when hidden;
  ref-counted subscribers, one in-flight request, one interval per app.
- After `useFamily`'s save queue drains, refresh the feed, **guarded by family mode and a non-null
  group id** (the senior screen also uses `useFamily`; calling family routes from it would 403).

Keep (existing e2e depends on them): h1 "Care+…" area, `watch-status`, `watch-battery`,
`charge-reminder`, the section headed "Needs someone to go along" with its links and "I'll go with
… to …" button, `#home-week` with "No one going", the "Steps on each of the last days" group with 14
`aria-pressed` buttons, `.chart-readout`, `task-panel`, `weather-card`, `weather-forecast`, the Area
select. If structure changes, keep roles and names; change only purely structural selectors.

Acceptance criteria:

- Deps pinned exactly; motion-v absent from the entry chunk (check the build output).
- Seeded feed visible with "Sample" tags; a check-in "Called" with a note appears at once and
  survives a reload; switching "Viewing as" to John shows Sarah's check-in as hers, not "You".
- Feed refreshes on focus and every 30 s (e2e can drive time with `page.clock`).
- **No request to `/activity` in senior mode** (assert in e2e).
- Reduced motion: ticker shows the final value at once; add one spec with
  `page.emulateMedia({ reducedMotion: 'reduce' })` (`test.use({ reducedMotion })` did not take effect
  in this setup).
- `family-feed.test.ts` covers every kind's sentence, "You" vs a name, and an unknown kind.
- All existing Home e2e tests pass unchanged; full gates green.
- Commit: `feat(web): animated family Home with activity feed and check-ins`

### Step 5: Calendar redesign

Files: `src/views/CalendarView.vue`, `src/components/calendar/*` (new `WeekStrip.vue`,
`AppointmentNotes.vue`; `DetailsSheet.vue` replaced by a new `src/components/motion/BottomSheet.vue`),
`src/composables/useFocusTrap.ts`, `src/composables/useAppointmentNotes.ts` (per open sheet, not a
singleton), `careApi.ts` (add `getAppointmentNotes`, `addAppointmentNote`, `deleteAppointmentNote`),
e2e specs.

Build:

- Phone: swipeable week strip + agenda list; tapping an appointment opens a `BottomSheet` with the
  details, who's helping, and the day's family notes (add; delete own).
- `BottomSheet`: `<Teleport to="body">`, `role="dialog"`, `aria-modal="true"`, `aria-labelledby`
  the heading; hand-written focus trap (no new package); focus to the heading on open and back to
  the opener on close; Escape and backdrop click close; `inert` on `#app` and body scroll lock while
  open; drag down to dismiss (motion-v `drag="y"`, dismiss past 30% height or 500 px/s, else spring
  back); always a visible close button; z-index above the tab bar (nav is 1030, sheet 1045+);
  reduced motion = no slide or spring.
- **Desktop (≥ lg) keeps the month grid** with `data-iso` / `data-appt` and the non-modal side
  panel. The drag-to-move e2e test runs at 1280px and needs that grid. The week strip is phone only.

Keep: `details()` = an `article` containing an h2 title, the "Back" button, "Coming up" h2 section,
appointment buttons named after the appointment, "I'll help", "Step back", "I can't make it", "I'm
available", list rows "Available"/"Not available"/"Helping", "Needs helper" text and toggle, "Show
all", the "Medical visit" legend `aria-pressed`, `?appointment=` deep link, arrow-key navigation with
the long-day h2, `add-appointment`, `add-title`, Date/From/To labels, `add-repeat`, "Add"/"Save",
toasts "Added X"/"Deleted X"/"Moved to", `remove-appointment` with the native `confirm` dialog (or
switch the test to an in-app confirm that tests the same thing), `.cal-day.heat`, `free-then`,
`edit-appointment`, "Add to my calendar" download, Undo.

Acceptance: phone sheet is a real dialog (trap, Escape, focus return, drag to close, close
button); notes add/delete as Sarah, John sees the note without a delete button (new e2e); desktop
grid and drag-to-move unchanged; existing calendar e2e passes with at most locator-only changes.
Commit: `feat(web): calendar week strip, agenda and bottom sheet with family notes`

### Step 6: Family page redesign

Files: `src/views/FamilyView.vue`, `src/components/family/*`.

Build: avatar cluster for the care group; restyled free-times painter; animated invite PIN card
(all 6 digits readable as text from the first render; animation is decoration only); an empty
`<div data-slot="senior-location">` placeholder card for the map branch.

Keep: `.painter [data-day][data-slot]` with classes `available` / `unavailable` / `empty`,
"Free"/"Busy" buttons, "I'm John" button, the member card with h3 "John" and "You", list items like
"3:00 pm to 5:00 pm", "Remove …" and Undo; `group-panel` "Caring for Mdm Lim", `new-join-pin`,
`pending-member` with "Let in", `add-family-member`, `show-family-code`.

Acceptance: `family.spec`, `groups.spec`, `interface.spec` "removing a shared time" pass; the slot
exists; try to fix the "painting busy hours" flake while in this code.
Commit: `feat(web): family page with avatars, painter and invite card`

### Step 7: Senior screen polish

Files: `src/views/SeniorView.vue`, `src/components/senior/*`. **CSS only. No motion-v. No new
features or data.**

Build: calmer, larger layout; the suggestion as one big card with large "Yes" / "Not today"
buttons (56px+); clear today's plan; gentle fades at most.

Open decision for the user: the senior header still has a single "My day" nav row (a reviewer
flagged it as unnecessary). Ask before removing it; e2e checks it today.

Keep: "Your activity" heading, `steps-today`, "Today's activities", the "Yes…" button, `thanks`,
`activity-status`, no `switch` on the screen, "Consent withdrawn".

Acceptance: no motion-v under `components/senior` or `SeniorView`; targets ≥ 56px for the main
actions; senior e2e unchanged and passing; 390px no-overflow check passes.
Commit: `feat(web): calmer senior screen with larger actions`

### Step 8: Sign-in and onboarding

Files: `LoginChooserView`, `LoginView`, `SignUpView`, `WelcomeView`, `GroupStartView`. Restyle to
match (glass, tokens, subtle motion only if lazily loaded; these screens must stay light).

Keep every test id and text: `choose-family`, `choose-senior`, `continue-*`, `signup-link`,
`signin-link`, `to-groups`, `choose-join`, `choose-create`, `senior-pin-input`, `join-pin-input`,
"Create your account" h1, "I am the senior", "I am family or a caregiver", `role=note` "switched
off", "It works once, for 10 minutes.", "Start the group", "Ask to join", `role=alert`.

Acceptance: `groups.spec` and `views.spec` pass; sign-in-off notes still shown.
Commit: `feat(web): restyled sign-in and onboarding`

### Step 9: Final review and clean-up

- Full gates (section 5) plus `pnpm test:postgres` if a database is available.
- Reviews across the whole branch (`git diff dev...HEAD`): code-reviewer, design-reviewer (all
  screens, phone and desktop, light and dark, plus senior), architect final check, verifier against
  every step's criteria. Fix, re-review, re-verify.
- Record bundle sizes vs the baseline in section 2.
- Update `CLAUDE.md` (motion-v, components/motion, nav shell), `docs/architecture.md` (web section),
  `docs/testing.md` (new specs), `README.md` screen descriptions if they changed.
- **Delete this file** (`HANDOVER-UI-REDESIGN.md`) in the final commit so it doesn't reach `main`.
- Commit: `docs: update docs for the UI redesign` (and remove the handover).
- Then the user opens a PR from `feat/ui-redesign` to `dev`. Don't merge or push yourself.

## 9. Before you start (Claude: run these first)

```bash
git branch --show-current          # expect feat/ui-redesign
git log --oneline -6               # expect c3c4ae1 at or near the top
git status --short                 # expect empty
pnpm install                       # then: cd apps/api && uv sync
```

Then tell the user: which step is next (4 unless the log shows later commits), anything unexpected
in the log or the working tree, and the plan for that step. Wait for their go-ahead.
