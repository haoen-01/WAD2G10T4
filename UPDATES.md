# UPDATES

A running log of every change made to this folder, newest first, so teammates can see what has been
worked on without reading diffs. (The auto-commit tool saves everything as a commit called `edits`,
so commit messages tell you nothing. This file does.)

**Add an entry whenever you change something:** code, config, docs, tests, deletions. Say what
changed and why, list the files, and note anything others must do.

---

## 2026-10-23: The 5 failing browser tests fixed (tests only)

The whole e2e suite now passes (51 of 51). Only test files changed; the app is unchanged.

- `interface.spec.ts` (:64, :85): the "Needs helper" filter button is found by its exact name,
  since appointment cards that need a helper say "Needs helper" too.
- `tasks.spec.ts` (:16): the senior ticks a task by tapping its label, which is drawn on top of
  the real checkbox, as a person would.
- `tasks.spec.ts` (:61): a task with no name is now stopped by the browser (the Name box is
  `required`), so the test checks that instead of the old "Please give the task a name." message.
- `shared-look.spec.ts` (:29): the phone menu test scrolls the Calendar, as Home is now too short
  on a phone to scroll the brand row away.

---

## 2026-10-23: Clear sign-up page and easy way to the family group page (Person E)

- **One sign-up page at `/signup`** (`SignUpView.vue`). Three numbered steps: 1. "I am the senior"
  or "I am family or a caregiver" (big cards; the chosen one shows "✓ Chosen", not colour alone), 2. name and email, 3. password twice with "Show password". It asks only what Care+ keeps (role,
  name, email, password); nothing else is stored, so nothing else is asked. `/signup/family` and
  `/signup/senior` still work and tick the choice already. In the offline demo the form is shown
  but disabled, with a note that sign-up needs a `.env` with Supabase.
- **Sign-in leads to sign-up:** `/login` has a "Create an account" button; each sign-in page shows
  "New to Care+? Create an account", now in the demo too (`LoginChooserView.vue`, `LoginView.vue`).
- **The family group page is easy to find:** a "Join or create a family group" button at the top of
  `/family`, and `/groups` now goes to `/groups/start` (`router/index.ts`).
- With sign-in on, visiting any page already sends you to `/login` first (unchanged). The offline
  demo still opens pages directly, as before, so no one else's tests change.
- `isLoginPath` counts `/signup` as a sign-in page (`lib/view-mode.ts` + test).
- **Not E's files, edited for this:** `LoginChooserView.vue`, `LoginView.vue`, `SignUpView.vue`,
  `router/index.ts`, `lib/view-mode.ts`. Small changes only; shout if they clash with yours.
- e2e: two new tests in `groups.spec.ts` (sign-in → sign-up and back; Family → group page and
  `/groups`). Full run: 42 pass; the same 5 fail on `dev` without this change (listed below).

---

## 2026-10-22: Family group page + group sign-up (Person E)

From the user-testing feedback (work-split §2, E). **One small backend change (link-code time), no
contract change**: `SENIOR_LINK_TTL` is not in the OpenAPI, so no `pnpm client:generate`.

- **Separate "Join a group" and "Create a group" buttons** (`GroupStartView.vue`). Two big buttons
  first; pressing one opens only that form, with a Back button. Creating a group lists the three
  steps in short lines ("The senior signs in… taps Add a family member… type the code here").
- **Smaller family-group cards** (`GroupPanel.vue`, `FamilyMemberCard.vue`). Members are small
  chips; "Members" and "Invite family" sit side by side; anyone waiting to join is shown first in a
  yellow box with Let in / Turn down. Member cards are one compact row ("Son · Helping with 1
  visit").
- **More side by side, less scrolling on `/family`** (`FamilyView.vue`). Painter beside "Family
  availability"; group panel beside "Who helps" (the group panel now appears once, not twice);
  sharing beside the two-week grid. Someone not in a group yet still sees the group row first.
  Sections have ids `#family-group`, `#availability`, `#sharing` for SectionNav.
- **Link code lasts 10 minutes, not 15** (`family_groups.py`), the §4 suggestion: 5 is tight for
  an older person typing a code. Two new API tests: the code lasts 10 minutes, and an expired code
  is refused.
- **Dark mode:** two hard-coded colours swapped for theme tokens (`AvailabilitySelector.vue`'s
  "No" background, `AvailabilityPainter.vue`'s key ring). `/family` and `/groups/start` checked in
  dark mode.
- **Sign-up works like a normal sign-up** (`SignUpView.vue`): "Type the password again" box, a
  "Show password" tick box, and plain-word checks (name filled in, 8+ characters, passwords match)
  before the account is made. `SignUpView` was not on anyone's list in work-split §1; tell E if
  that clashes with your work.

### What teammates need to know

- **B:** please change `components/senior/FamilyCodeCard.vue` line 29 to "It works once, for 10
  minutes." (or drop the time; the countdown already shows it). I did not touch your file.
- **A:** when `SectionNav` is merged, `/family` needs one line at the top:
  _Free times (`#availability`) · Group (`#family-group`) · Sharing (`#sharing`)_. Not added yet,
  because the component does not exist on `dev`.
- **Not done, waiting on §3/§4:** "group first, then the senior joins". It needs a team decision on
  how the senior approves, and C's backend PR (`needs_helper`) to merge first.
- **e2e:** `groups.spec.ts` now clicks "Join a group" / "Create a group" before using a form, and
  has a new test for the two choices. `family.spec.ts`'s `paint()` helper scrolls the hour into
  view first (the painter is no longer level with "I'm John").

### Files

- Changed: `views/GroupStartView.vue`, `views/FamilyView.vue`, `views/SignUpView.vue`,
  `components/family/GroupPanel.vue`, `FamilyMemberCard.vue`, `AvailabilityList.vue` (one column,
  as it now sits beside the painter), `AvailabilityPainter.vue`, `AvailabilitySelector.vue`.
- API: `apps/api/src/silverloop/family_groups.py`, `apps/api/tests/test_family_groups.py`.
- e2e: `apps/e2e/tests/groups.spec.ts`, `apps/e2e/tests/family.spec.ts`.

### Checked

- API family-group tests (16, Ruff clean), web typecheck, 178 web unit tests, Prettier, Vite build.
- e2e: 40 pass. 5 fail, and the same 5 fail on `dev` without this change: `interface.spec`
  :64, :85, :155 (calendar "Needs helper" / Home) and `tasks.spec` :16, :61.
- Looked at a phone-width window and dark mode.

---

## 2026-10-22: UI redesign (branch `feat/ui-redesign`)

### Second pass: simpler, more alive (feedback: "it looks very dashboard")

The first pass below felt like a finance dashboard (sidebar, dark banners, boxes everywhere). This
pass replaces those parts. Still frontend only, still no new dependency.

- **No sidebar.** `AppLayout` is one light header: the brand, a glass pill menu, the text size and
  light/dark controls, sign out. The header turns to frosted glass once the page scrolls under it.
  On phones the family's menu floats at the bottom; the senior's single "My day" stays on top. The
  logo's orange arc turns slowly.
- **Aurora heroes instead of dark banners** (`.sl-hero` in `theme.css`): big type over four soft
  blobs of colour that drift slowly, plus a faint dot grid. Light in light mode, deep in dark mode.
  Key words use moving gradient text (`.sl-gradient-text`).
- **Motion.**
  - A hello that waves once, and hero lines that rise in one after another (`.sl-stagger`).
  - Numbers that count up (new `components/ui/CountUp.vue`; screen readers get the final number).
  - A ring that draws itself in a gradient (`LoopRing` takes an optional `gradient`), on a glass
    disc that breathes slowly.
  - Cards that rise into view as you scroll: CSS scroll-driven animation, no script; browsers
    without it, like Firefox, just show the cards.
  - A soft spotlight that follows the mouse across cards (one pointer listener in `AppLayout`).
  - Tiles and buttons that spring when pointed at.
  - On the senior's watch, a battery that fills up, with a shine and a pulsing ⚡ while charging.
  - All of it stops for readers whose device asks for less motion (the existing rule at the end of
    `theme.css`).
- **Fewer boxes**: softer borders and shadows, more space, bigger corners. The week ahead on family
  Home shows one "0/5 tasks" chip per day instead of listing every task (the calendar still lists
  them).
- **Senior watch card**: centred, a bigger battery, and the words say what the number means
  ("Charging", "Plenty of charge", "Getting low", "Needs charging") instead of repeating it.
- Files: `styles/theme.css`, `layouts/AppLayout.vue`, `components/ui/CountUp.vue` (new),
  `components/ui/LoopRing.vue`, `components/home/HomeHero.vue`, `components/home/WeekAhead.vue`,
  `components/senior/SeniorStatus.vue`, `components/senior/SeniorWatch.vue`,
  `views/SeniorView.vue`, `views/LoginChooserView.vue`, `views/LoginView.vue`.
- Checked: type check clean, 178 unit tests pass, Prettier clean. Browser tests: 38 of 45 pass. The
  same 6 known failures, plus "painting busy hours", which fails only in the full run and passed 3
  of 3 times on its own. Screens checked while scrolling at 1280px (light and dark) and 390px at
  150% text size: no sideways scrolling, no console errors.
- Note for anyone taking screenshots: a full-page capture shows cards below the fold as blank,
  because they only appear when scrolled to. Scroll the page instead.

### First pass

A new look for both the family and senior views. **Frontend only: no backend, contract or new
dependency.** It borrows from Medisafe (today's list as big tick rows), Audible (a warm orange
accent, near-black dark mode), Google Maps (white cards floating on a pale page, a floating tab bar
on phones), Personal Capital (a dark summary banner with one big number, a sidebar) and
21st.dev/shadcn-style components (hairline borders with soft shadows, segmented controls, a glow
and faint grid on banners). 21st.dev components are React + Tailwind, so their styling was redone
in plain CSS over Bootstrap instead of being installed.

- **New palette and design tokens** (`styles/theme.css`): indigo primary, orange accent, green for
  "done/good", coral for warnings, on a cool grey page. Light and dark are both redone. The old
  `--sl-jade*` / `--sl-coral*` / `--sl-sun*` names are kept (most components read them) but now
  carry the new colours, so "jade" now means "primary". New tokens: `--sl-accent`,
  `--sl-accent-text`, `--sl-good`, `--sl-good-soft`, `--sl-surface-2`, `--sl-shadow`,
  `--sl-shadow-hover`, `--sl-hero-*`. New classes: `.sl-hero` (dark banner), `.sl-eyebrow`,
  `.sl-icon-tile`. The Atkinson Hyperlegible font stays, for low-vision readers.
- **Layout** (`layouts/AppLayout.vue`): the family gets a left sidebar on wide screens (menu,
  "Caring for", text size, light/dark, sign out) and a floating tab bar on phones and tablets. The
  senior and the sign-in pages get one simple top bar. With sign-in off and no view chosen, the top
  bar's links move to their own row on phones (they made the page wider than a 390px screen).
- **Text size and light/dark kept**, restyled as a segmented control (`A− 100% A+`) plus a round
  theme button. Same buttons, labels and test ids.
- **Family Home**: the top (`HomeHero`) is now a dark summary banner with the ring, the facts beside
  it, the watch and battery chips, the badges and "Why this status?".
- **Senior page, made simpler** (`views/SeniorView.vue`): the greeting and status line in a banner,
  a new **My watch** card beside it (`components/senior/SeniorWatch.vue`: a big battery, its
  percentage in words, connected or not, and "Please charge your watch." when it is low), then four
  big shortcut tiles (My tasks, Today, My calendar, My walking) that jump down the page, then one
  section per row. The page is capped at 64rem wide so lines stay short.
- **Tasks** (`TaskPanel`): round Medisafe-style ticks, taller rows, done rows turn green.
- **Sign-in**: the chooser has a banner and two coloured choice cards; the sign-in page's art panel
  uses the banner style.
- **Icons**: `watch`, `steps` and `tasks` added to `Icon.vue`.
- Old greens hard-coded in `DetailsSheet`, `DayAgenda` and `AvailabilitySelector` now use the new
  palette.

### Files

- New: `components/senior/SeniorWatch.vue`.
- Changed: `styles/theme.css`, `layouts/AppLayout.vue`, `views/SeniorView.vue`,
  `views/LoginChooserView.vue`, `views/LoginView.vue`, `components/home/HomeHero.vue`,
  `components/home/TaskPanel.vue`, `components/senior/SeniorStatus.vue`,
  `components/ui/DisplayControls.vue`, `components/ui/Icon.vue`, `components/calendar/DayAgenda.vue`,
  `components/calendar/DetailsSheet.vue`, `components/family/AvailabilitySelector.vue`.

### Checked

- Type check clean, 178 unit tests pass, Prettier clean on `apps/web/src`.
- Browser tests: 39 of 45 pass. The 6 that fail (`family.spec.ts` 1, `interface.spec.ts` 3,
  `tasks.spec.ts` 2) are the same ones listed as failing on 2026-10-19, and they fail on wording,
  duplicate button names and data, not layout. A second `family.spec.ts` test (painting busy hours)
  failed once and passed on other runs, so it looks flaky.
- Screenshots of every screen at 1280px and 390px, light and dark, and at 150% text size on a phone:
  no sideways scrolling and no console errors.

### Not done / for teammates

- `TaskChecklist.vue` is not used anywhere; it was left as it is.
- Calendar and Family screens were not restructured. They pick up the new colours, cards and
  buttons through the theme only.
- Week-ahead cards on family Home are still very long when every day has 5 tasks.
- With sign-in off and no view chosen, `/` shows the family Home with a top bar (no sidebar), which
  is expected.

---

## 2026-10-19: Senior page

From the user-testing feedback. **Frontend only, no backend or contract changes.**

- **Fewer words, one status line at the top** (feedback: fewer words, plain-word status). The old
  "Nothing needs your attention right now" box is gone. `SeniorStatus` says how the latest day
  compares with a usual day in plain words with an icon ("All looks good!", "Keep it up!", "A bit
  less active than usual"), and which day the readings are from. Describes the numbers only.
- **Shorter wording everywhere** (feedback: fewer words). Today's activities says "With Sarah" and
  "Family is arranging a helper", with clock, pin and people icons. Empty text is "Nothing planned
  today."
- **Show my family** (feedback: show family). New "My family" panel: a card per member with their
  initial, name and relation. Read only. Groups, photos and a "Caregiver" label are allowed for,
  but stay hidden until the API sends them; nothing is made up.
- **Link code with a countdown** (feedback: countdown). `PinDisplay` now counts down ("Expires in
  14:59") from the API's `expires_at`, strikes the code through and says "Code expired" at 0.
  Screen readers hear it only at one minute left and at 0. The code now sits behind an "Add a
  family member" button near the bottom of the page.
- **Simpler activity section** (feedback: fewer words). "Your activity" shows steps and active
  minutes, then last week, usual and change as three numbers ("About the same as usual", "Up
  12%"). The week's bars (`SeniorWeekChart`, plain HTML/CSS, tap or hover for a tooltip) are behind
  a "See my week" button.
- **Layout:** status, then today's tasks beside Today's activities and My family, then **My
  calendar** (`SeniorCalendar`, full width), Your activity, Add a family member. The "Care+ only
  suggests…" line is last and styled as the first line of the footer.
- **The senior can add and edit their own tasks** on their page: `TaskPanel` is given `can-manage`
  (it was `:can-manage="false"`), so "Add task" and "Edit" show for the senior too.

### What teammates need to know

- **Calendar (`SeniorCalendar`):** it is on the Senior page as its own full-width row (it was too
  tall for the side column). It is long because every empty day still gets a full card.
  Suggestions: hide or group empty days, a 7-column grid on wide screens, shorter day labels, and
  the `calendar` icon on its "My calendar" heading like the other panels. It opens on today plus
  the next six days (not Monday to Sunday); a "current week" option would help. Its "Today" box
  repeats Today's activities: a prop to hide today would let the Senior page drop one.
- **Link code:** `groups.spec.ts` now clicks "Add a family member" before "show the code". The
  countdown no longer assumes a duration, but `components/senior/FamilyCodeCard.vue` (line 29)
  still says "It works once, for 15 minutes." Could that line drop the "15 minutes"?
- **Tasks panel:** "Kept in this browser." still shows under the tasks on the Senior page
  (`TaskPanel`, always on). Could it be hidden there (a prop, say)? The senior does not need it.
- **Icons and footer:** Icon.vue has no icon for these, so they are emoji (all `aria-hidden`): 🚶
  walking (status), 👟 steps, ⬆️ ⬇️ ➡️ change arrows, ⏳ no data yet. Happy to switch if icons are
  added. Also: could the layout have a footer slot? The "Care+ only suggests…" line copies the
  footer's styles and pulls itself down with negative margins to look attached.
- **Demo data:** the step data ends on 18 Aug, so the Senior page shows "Your latest day: Tue 18
  Aug" under today's date. Whoever owns the demo data could shift its dates relative to today.

### Files

- New: `components/senior/SeniorStatus.vue`, `MyFamily.vue`, `LinkFamily.vue`,
  `SeniorWeekChart.vue`.
- Changed: `views/SeniorView.vue`, `components/senior/TodayStats.vue`, `OutingsList.vue` (both now
  `<script setup>`), `components/family/PinDisplay.vue`.
- e2e: `groups.spec.ts` (clicks "Add a family member" before showing the code), `loop.spec.ts`
  (after replying, checks the suggestion is gone and the status line shows, instead of the removed
  "Nothing needs your attention" text).

### Checked

- Web: type check clean, 178 unit tests pass, Prettier clean on changed files.
- Browser: 38 of 44 e2e tests pass. The 6 that fail (`family.spec.ts` 1, `interface.spec.ts` 3,
  `tasks.spec.ts` 2) fail the same way with the calendar change taken out. Not yet checked against
  `dev`.
- Screenshots and measurements at 1280, 1440, 150% zoom and 390 px, light and dark: no sideways
  scrolling.

### Not done yet / known issues

- **`tasks.spec.ts` is out of date:** line 37 still expects the senior not to see "Add task". The
  senior can now add tasks, so that check needs updating to match.
- No unit tests for the countdown (`PinDisplay.vue`) or the week numbers (`TodayStats.vue`): the
  logic is kept inside the `.vue` files.
- Waiting on: calendar length, icon and today repeat; hiding "Kept in this browser."; the link-code
  wording; icons and a footer slot.

---

## 2026-10-18: Removed four old planning docs

Old planning and handover docs that nothing in the app, tests or main docs points to (only other
old docs mentioned them). **No code changes.** `suggestions.md` stays.

- `docs/review-threshold-spec.md` named `handover-review-threshold.md` as a source; it now says the
  file was removed. Code and tests that say "opportunity-matrix row" were left as they are.
- All four are in git history, e.g. `git show c5b4099:docs/personalisation-v2-final-report.md`.

### Files

- Removed: `docs/personalisation-v2-final-report.md`,
  `docs/personalisation-v2-opportunity-matrix.md`,
  `docs/current-state-before-personalisation-v2.md`, `docs/handover-review-threshold.md`.
- Changed: `docs/review-threshold-spec.md` (one line).

---

## 2026-10-18: Removed the Ranker Inspector spec doc

The Ranker Inspector page was dropped from the web app, so its design spec no longer described
anything the app shows. **No code changes.** The backend's ranker-inspector endpoint
(`ranker_inspector.py`) is still there and still tested.

- Kept on purpose: `docs/evaluation/*`. `pnpm evaluate:check` (run by `pnpm verify` and CI) and the
  API tests compare these files byte-for-byte, so deleting them would fail CI.
- `docs/adr/0006-preference-resolution-and-ordinal-axes.md` still mentions the spec by name. It is
  in git history if needed (`git show c5b4099:docs/ranker-inspector-spec.md`).

### Files

- Removed: `docs/ranker-inspector-spec.md`.

---

## 2026-10-18: Calendar page, feedback round 2 (Person C, frontend only)

From the user-testing feedback in `work-split.md`, Person C's list. **No backend changes.**

- **"View as" is top right** of the header, beside "+ Add".
- **One thing per row:** the calendar, then the chosen day ("Today" tag when it is today), then
  "Coming up". The two lists are now rows of cards side by side. While adding or editing, the form
  still sits beside the calendar on wide screens, so a day can be tapped to pick it. An
  appointment's details open under the calendar on wide screens, and as a sheet on phones.
- **Events colour-coded by type, with a legend.** The legend chips now read the shared `.kind-*`
  colours from `theme.css` (no colours hard-coded in `KindFilter.vue` any more), so A's new event
  colours apply here and on the calendar with no change. Tasks are in the legend too. Every colour
  comes with its name.
- **"Not every event needs a helper" (frontend part).** `lib/coverage.ts` has `needsHelper()` and
  `stillNeedsHelper()`: an appointment with `needsHelper: false` never counts as "needs a helper"
  (not in the "Needs helper" filter, the day markers, the "x/y covered" count, or `needingHelp()`,
  which Home and Family use). Cards say "No helper needed" and details say "No one needs to go
  along". The add/edit form has a "Someone needs to go along" tick box, **hidden** behind
  `NEEDS_HELPER_SAVED = false` in `lib/coverage.ts`.
- **`SeniorCalendar.vue`:** a view-only week for the Senior page, in big text: each day, what is
  on, when, and who is coming ("Sarah is coming with you"). Earlier/later week buttons.

### What teammates need to know

- **Today nothing changes for "needs a helper"**: the API does not send the flag yet, so every
  appointment still needs one. To switch it on, three steps by whoever does the backend:
  1. Backend: add `needs_helper: bool = True` to `AppointmentRequest` and `AppointmentOccurrence`
     (`models.py`), store it (DB column + Alembic migration, `family_routes.py`), then
     `pnpm client:generate` and commit what it produces.
  2. **E (`lib/family.ts`)**: in `fromCalendar`, copy it across: `needsHelper: occurrence.needs_helper`.
  3. **C**: set `NEEDS_HELPER_SAVED = true` in `lib/coverage.ts` to show the tick box (the form
     already sends `needs_helper` when it is on).
- **B:** `SeniorCalendar` is ready. Add `<SeniorCalendar />` to `SeniorView.vue` (it reads
  `useFamily()` itself; no props needed).
- **D:** `needingHelp()` already leaves out appointments that do not need a helper, so Home's
  "Needs someone" list follows automatically once the flag exists. `WeekAhead.vue` (yours) still
  shows "Needs a helper" from its own check; switch it to `stillNeedsHelper()` from
  `lib/coverage.ts` when you can.

### Files

- Changed: `views/CalendarView.vue`, `components/calendar/AddAppointmentForm.vue`,
  `AppointmentCard.vue`, `AppointmentDetails.vue`, `DayAgenda.vue`, `KindFilter.vue`,
  `UpcomingList.vue`, `lib/coverage.ts`, `lib/coverage.test.ts` (3 new tests).
- New: `components/calendar/SeniorCalendar.vue`.

---

## 2026-10-18: Shared look (feedback round 2, part A): colours, icons, menu, SectionNav

Feedback said almost everything was green, and the phone menu was hard to find at the bottom. This
adds colour-blind-safe colours, the icons B to E asked for, a menu that lives in the top bar on
phones too, and a "jump to" row for long pages. Only HTML, CSS, JavaScript and Vue; no new packages.

### New colours (`theme.css`)

- **Blue, purple and orange** join jade and coral. Each has four tokens: `--sl-blue` (fills, dots,
  borders), `--sl-blue-on` (text on that fill), `--sl-blue-deep` (coloured text) and `--sl-blue-soft`
  (pale background). Same for `purple` and `orange`. Jade and coral gained `-on` tokens too.
- **Colour-blind safe:** they differ in lightness as well as hue (blue dark, orange mid, purple a
  light pink-purple), and were checked with red-green colour-blindness simulation. Still always add
  an icon or a word; colour is never the only signal.
- **Dark mode:** every new token has a dark version in `:root[data-bs-theme='dark']`.
- **Tones for sections:** put `sl-tone-blue` (or `jade`, `coral`, `purple`, `orange`) on an element
  and use `var(--tone)`, `var(--tone-on)`, `var(--tone-deep)`, `var(--tone-soft)` inside it. Ready-made
  pieces that follow it: `sl-icon-chip` (round tinted icon), `sl-tag` (coloured pill of words) and
  `sl-panel-accent` (coloured strip on top of an `sl-panel`). For example
  `<div class="sl-panel sl-panel-accent sl-tone-purple">`.
- For coloured **text** use the `-deep` token, never the plain colour (in dark mode jade stays dark for
  button fills, so `var(--sl-jade)` text is too dark there).

### Appointment colours (`.kind-*`, for C)

- One clearly different colour per kind: **medical blue, therapy purple, activity jade, errand
  orange**, task grey. Light and dark. Inside `kind-<name>` you get `--kind`, `--kind-on`,
  `--kind-deep`, `--kind-soft`, and `--chip`, so `<button class="sl-chip kind-medical">` colours itself.
- `.kind-badge` now uses `--kind-on` for its text, so it reads on the lighter purple and orange.

### Icons (`Icon.vue`)

- 47 new icons, 79 in all. People and contact: `people`, `user-check`, `user-x`, `phone`, `chat`,
  `mail`, `hand`, `thumbs-up`, `smile`, `heart`. The day: `medicine`, `stethoscope`, `walk`, `water`, `meal`,
  `bag`, `car`, `watch`, `battery`, `timer`, `bell`, `star`, `trend-up`, `trend-down`. Actions:
  `plus`, `minus`, `edit`, `trash`, `copy`, `link`, `key`, `lock`, `search`, `list`, `checklist`,
  `menu`, `question`, arrows and chevrons.
- **One icon per appointment kind, with the same name:** `medical`, `therapy`, `activity`,
  `errand`, `task`. So `<Icon :name="appointment.kind" />` works.
- Need another? Ask A, or add it in a tiny PR that only touches `Icon.vue`.

### Menu in the top bar on phones too (`AppLayout.vue`)

- The phone menu is no longer docked to the bottom. It is the top bar's second row: one tab per
  screen, icon and word. While scrolling, the brand row slides away and **the menu row stays pinned
  at the top**, so every screen is always one tap away. The current tab has a tint and an underline
  (shape as well as colour).
- On small phones the Sign out button shows only its icon (it is still called "Sign out" for screen
  readers and tests), and the Family/Senior chip is hidden, so the bar fits at 320 px and 150% zoom.
- Toasts no longer leave room for the old bottom menu.
- The layout keeps `--sl-pinned-height` (the height pinned at the top) up to date; `theme.css`
  uses it so `#links` stop below the menu, not under it.

### `SectionNav.vue` (new, for B, D and E)

A row of "jump to" buttons for the top of a long page:

```vue
<script setup lang="ts">
import SectionNav from '@/components/ui/SectionNav.vue';
</script>

<SectionNav
  :items="[
    { id: 'tasks', label: 'Tasks', icon: 'checklist', tone: 'blue' },
    { id: 'week', label: 'This week', icon: 'calendar', tone: 'purple' },
  ]"
/>
<section id="tasks">…</section>
<section id="week">…</section>
```

- Each button scrolls to the section with that `id` (below the pinned menu), moves keyboard focus
  there and puts `#tasks` in the address. The section you are reading is highlighted as you scroll.
- Optional: `sticky` keeps the row on screen under the menu; `label` names it for screen readers
  (default "On this page"). On narrow screens the row scrolls sideways instead of widening the page.
- An `id` on a component (e.g. `<TaskPanel id="tasks" />`) works when the component has one root.

### Contrast

- Scanned every text element on Home, Calendar, Family and My day in light and dark (desktop and
  phone): all pass 4.5:1 (3:1 for large text) except one, listed below. Every token pair (buttons,
  alerts, badges, tabs, tags, kind badges) passes in both modes; the task grey was nudged to pass.
- Purple and orange fills are light so dark text reads on them; on a white panel they pass 3:1, but
  for thin lines or small dots straight on the grey page use the `-deep` token.
- In the brand name, dark mode now uses mint instead of dark jade.

### For other owners (found while checking; not changed, as the files are yours)

- **C:** `KindFilter.vue` hard-codes the old kind colours, so the legend no longer matches the
  calendar. Replace `:style="{ '--chip': KIND_COLOURS[kind] }"` with ``:class="`kind-${kind}`"`` and
  delete `KIND_COLOURS`. At 320 px and 150% zoom the "Viewing as" select in the Calendar header
  pushes the page sideways (43 px; it did before this change too).
- **E:** `AvailabilityPainter.vue` line ~269 uses `color: var(--sl-jade)` for text, which is 3.1:1 in
  dark mode; use `var(--sl-jade-deep)`. On `/family`, at 150% zoom, the member cards (320 px) and the
  two-week availability grid (768 px) push the page sideways (both before this change too).
- **D:** at 1024 px and 150% zoom the task Edit buttons on Home stick out by 54 px (before this
  change too).
- **Everyone:** these e2e tests already failed on this branch before this change and still do:
  `family.spec.ts` (sharing when free; painting busy hours), `interface.spec.ts` (calendar "only
  needs a helper"; Home's needs-someone list), `tasks.spec.ts` (both tests).

### Files

- Changed: `apps/web/src/styles/theme.css`, `apps/web/src/components/ui/Icon.vue`,
  `apps/web/src/layouts/AppLayout.vue`.
- New: `apps/web/src/components/ui/SectionNav.vue`, `apps/web/src/lib/section-spy.ts` (+
  `section-spy.test.ts`, 6 tests), `apps/e2e/tests/shared-look.spec.ts` (3 tests).

### Checked

- Web: type check clean, 181 unit tests pass, build succeeds, Prettier clean for these files.
- Browser: the 3 new tests pass, as do the existing top bar, zoom, theme, views and phone-width
  tests. No new sideways scrolling at 320, 375, 768 and 1024 px, at 100% and 150%, light and dark.

---

---

## 2026-10-17: Feedback round 2, D (Family home page `/`)

User testing said Home was wordy, "in 7 days" was unhelpful, and taking a visit meant a trip to the
calendar. Home now:

- **"I'll go" on each visit that needs someone.** One tap takes it, using the existing
  `useFamily().volunteer` (saved through the API, same as the calendar's "I'll help"), with an Undo
  toast. The button only shows to someone in the group, so it is never a dead button.
- **The actual day and times** in that list: "Sun, 18 Oct, 10:00 am – 12:00 pm", not "Tomorrow" or
  "In 7 days". When nothing is left it says "Everyone is covered" instead of vanishing.
- **Start–end time on every appointment** in the week ahead.
- **Visits with no one going stand out** in the week ahead: coral dashed edge, warning icon and the
  words "No one going" (the kind colour stays on the left edge, so colour is never the only cue).
- **"Why this status?" is one line** under the badges (the API's first reason, plus rain / air
  quality / holiday if any). The toggle and the separate panel are gone.
- Fewer words: icons on the section headings, the "Tap a day" subtitle dropped, a one-sentence
  footer with a shield icon.

Files: `views/HomeView.vue`, `components/home/{HomeHero,StatusWhyPanel,NeedsHelperList,WeekAhead}.vue`,
`lib/today.ts` (+ `timeRange`, `visitWhen`) and `lib/today.test.ts`, `apps/e2e/tests/interface.spec.ts`
(the Home heading test was already failing on a stale heading; fixed, plus an "I'll go" test).

### What teammates need to know

- **A:** Home's sections already have ids for `SectionNav`: `home-needs`, `home-tasks`, `home-week`.
  Once `SectionNav.vue` is merged, D adds it at the top of Home (one line).
- **C:** once `needs_helper` is merged, D filters `needs_helper = false` out of "Needs someone" and
  the "No one going" badge (one line each in `HomeView.vue` / `WeekAhead.vue`).
- The senior's own simpler task form is still waiting on the §4 decision; nothing built yet.
- No backend, contract or dependency changes.

---

## 2026-10-14: Home shows the senior's watch and its battery (replaces "Backend connected")

The "Backend connected" badge on Home was a developer check, meaningless to families. In its place
Home now shows the senior's watch: **connected or not, when it last synced, and its battery**, so
the family can remind the senior to charge it.

- Battery colours follow what phones use: **green** at 50% and above, **amber** from 20% to 49%
  ("getting low"), **red** below 20% ("needs charging"), green while charging. The level is always
  written out too, never colour alone. At red, Home adds: "The watch battery is low. Remind <name>
  to charge the watch."
- Connected shows a green dot, not connected a grey one.

### What teammates need to know

- **It is simulated, and labelled "Simulated watch".** There is no real device yet. The API works
  the status out from the clock, the same for the same person and time: charging overnight (22:00
  to 06:00 Singapore time), full in the morning, low by the evening. A real source (for example
  Google Health) only has to replace `silverloop/wearable_status.py`; the screen and contract stay.
- New endpoint `GET /v1/people/{id}/wearable` (the senior and their active family members; anyone
  else gets 404). Commit the regenerated contract.

### Files

- API, new: `silverloop/wearable_status.py`, `tests/test_wearable_status.py` (5 tests).
- API, changed: `models.py` (`WearableStatus`), `family_routes.py` (the route).
- Contract: `openapi/silverloop.json`, `libs/api-client/src/generated/*`,
  `libs/api-client/src/index.ts`.
- Web, new: `components/home/WatchStatus.vue`, `lib/wearable.ts` (+ `wearable.test.ts`, 4 tests).
- Web, changed: `components/home/HomeHero.vue` (watch instead of the backend badge),
  `views/HomeView.vue`, `services/careApi.ts`.
- e2e: `loop.spec.ts` ("Backend connected" test replaced; new low-battery test).

### Checked

- Browser: 38 of 38 e2e tests pass. Web: type check clean, 149 unit tests pass, build succeeds.
  Screenshots of the green, amber, red and charging states (1280 and 390 px).

---

## 2026-10-14: The privacy switch is gone from the senior's screen

Decision (2026-10-14): the senior's "Your privacy" switch is removed from "My day". The senior
screen now shows the day, the suggestion, today's activities and "Link your family".

### What teammates need to know

- **Consent itself is unchanged on the server.** It is still stored per senior (on by default),
  still the first check in the decision rules (`policy.py`), and Home still shows "Consent
  withdrawn" when it is off. Only the button for the senior to change it is gone: it can now only be
  changed through the API (`POST /v1/people/{id}/consent`), not from the app.
- Nothing to run.

### Files

- Deleted: `apps/web/src/components/senior/ConsentSwitch.vue`.
- Changed: `apps/web/src/views/SeniorView.vue`, `apps/web/src/services/careApi.ts` (removed
  `updateConsent`), `apps/e2e/tests/loop.spec.ts` (the two switch tests become "the senior screen
  has no privacy switch" and "consent withdrawn through the API still shows on Home").

### Checked

- Web type check clean; 16 of 16 e2e tests in `loop`, `views`, `responsive` and `groups` pass.
  Screenshot of the senior screen at 390 px.

---

## 2026-10-14: Family see their senior, pick between seniors, and the calendar is on the server

Branch `feat/senior-care-giver`. Follows the family-groups entry below; closes the gaps it listed.

### What changed

- **Family can read their senior's activity.** `/v1/people/{id}/state` and `/metrics` now answer
  the senior themselves **and any active member of that senior's family group**. A pending member,
  an outsider or another senior gets 404; coordinators still get 403. Decision (2026-10-14): the
  privacy switch does **not** hide this from family. The senior entering their code is the
  agreement. (The switch itself was later removed from "My day"; see the entry above.)
- **Home shows your own senior**, not always Mdm Lim.
- **Senior picker in the navbar** for someone in more than one family group (only shown then).
  The choice is remembered in the browser. The Family page links to `/groups/start` to add another.
- **The calendar is stored by the API** for the whole family group: appointments, when each member
  is free, and who is helping. Nothing about it is kept in the browser any more.
  - **Add to the calendar** (Calendar page): name, kind (colour), day, times, place, notes, and
    **repeats** none / every day / every week / every month, with an optional last day. A
    repeating appointment is stored once; each day of it has its own answers and helpers.
  - **Remove from the calendar** (in an appointment's details) removes every day of it.
  - "I'll help", "I'm available", "I can't make it", "Step back" and shared free times work as
    before, now saved for everyone.
  - The senior's "Today's activities" come from the same calendar.
- **Demo (sign-in off):** the API seeds Mdm Lim's family (Sarah, John, Emily, as accounts
  `demo-family`, `demo-john`, `demo-emily`) and the same sample schedule as before, relative to
  today. `/v1/demo/reset` puts all of it back. "Viewing as" / "I'm John" still switch person, **in
  the demo only**; with sign-in on you are always yourself.
- **Removed:** the browser-only "Join the group" form (joining is by PIN now), "Reset the sample
  family data", `lib/family-sample.ts`, and the unused `createMember` / `parseState`.

### What teammates need to know

- **Hari:** colour coding (by kind), adding, removing and repeating appointments now exist on both
  the API and the Calendar page (`AddAppointmentForm.vue`). The API can also **edit** one
  (`PUT /v1/groups/{id}/appointments/{appointment_id}`), but there is no edit screen yet, nor
  "skip just this one day" of a repeat. Restyle or extend freely.
- **Elkan:** the senior picker is done (`layouts/AppLayout.vue`, `useMe().selectGroup`).
- **Supabase:** apply `infra/supabase/migrations/202610140022_family_calendar.sql` by hand after
  `202610140021` (see `docs/supabase.md`).
- **Commit the regenerated contract** (`openapi/silverloop.json`,
  `libs/api-client/src/generated`). On Windows run `bash scripts/generate-contract.sh`.
- Not tried with a real Supabase sign-in, and the senior picker could not be shown in the demo
  (the demo family has one senior). Both are covered by API tests only.

### Files

- API, new: `silverloop/family_calendar.py` (repeats, reading, appointments, availability,
  helping, demo seed), `alembic/versions/b9d3e5f71a26_add_family_calendar.py`,
  `tests/test_family_calendar.py` (12 tests).
- API, changed: `family_routes.py` (calendar routes, `check_reader`, demo reset), `auth.py`
  (`require_person_reader`), `main.py` (`/state` and `/metrics` use it; demo reset also resets the
  family), `family_groups.py` (all demo family accounts), `models.py`, `db_models.py` (3 tables);
  tests: `test_api.py`, `test_postgres_integration.py`, `test_persistence.py` (38 tables),
  `test_family_groups_migration.py`.
- Supabase: `infra/supabase/migrations/202610140022_family_calendar.sql`,
  `infra/supabase/rls_posture_apply.sql`, `docs/supabase.md`.
- Contract: `openapi/silverloop.json`, `libs/api-client/src/generated/*`,
  `libs/api-client/src/index.ts`.
- Web, new: `components/calendar/AddAppointmentForm.vue`.
- Web, changed: `composables/useFamily.ts` (API instead of `localStorage`), `composables/useMe.ts`
  (chosen senior), `composables/useViewMode.ts` (demo "Viewing as"), `services/careApi.ts`,
  `lib/family.ts` (+ test: `fromCalendar`), `layouts/AppLayout.vue`, `views/CalendarView.vue`,
  `views/FamilyView.vue`, `views/HomeView.vue`, `components/calendar/AppointmentDetails.vue`,
  `components/family/FamilyMemberCard.vue`, `components/family/GroupPanel.vue`.
- Deleted: `lib/family-sample.ts`, `components/family/JoinGroupForm.vue`.
- e2e: `family.spec.ts` (reset first; "John shares when he is free" replaces the old join test; new
  weekly-appointment test), `interface.spec.ts` (links use the demo ids), `support.ts`.

### Checked

- Browser: 37 of 37 e2e tests pass. Web: type check clean, 145 unit tests pass (12 removed with the
  deleted helpers, 1 added), production build succeeds.
- Python: see the full-suite note below; only the 9 recorded-LLM tests that already failed before
  this work still fail.

---

## 2026-10-14: Sign-up, and family groups stored on the server (joined with 6-digit PINs)

Branch `feat/senior-care-giver`. Care+ is now for **families caring for a senior**, not AAC
workers. This is phase 1 of that change: accounts and family groups, saved by the API in the
database (not in the browser).

### How it works

1. **Sign up** at `/signup/family` or `/signup/senior` (linked from each sign-in page as "Create an
   account"). Supabase keeps the email and password; the API records whether you are the senior or
   family. If Supabase asks people to confirm their email first, that choice is made on `/welcome`
   after the first sign-in.
2. A **senior** gets their own record with **synthetic** activity data (no real watch yet; Google
   Health is a possible future source). On "My day" they tap **Show a code for my family**: a
   6-digit code that works **once, for 15 minutes**. Showing it is how the senior agrees to be
   linked.
3. A **family member** who is not in a group is sent to `/groups/start`:
   - **Start a family group** with the senior's code. They become its owner. A senior can only
     have one group; a second attempt is told to ask for the join PIN.
   - **Join a family group** with a **join PIN** from someone already in it (Family page, "Show a
     join PIN"; works for 7 days, a new one replaces the old). They then wait as **pending** until
     any member taps **Let in** (or **Turn down**) on the Family page.
4. Five wrong PINs in 15 minutes locks PIN entry for that account. PINs are stored hashed.

### What teammates need to know

- **New API role `family`.** Self-registered accounts keep their role in the new `accounts` table
  instead of Supabase `app_metadata`; the demo accounts still use `app_metadata`.
- **Offline demo / e2e (sign-in off):** the API seeds `demo-family` ("Sarah", owner of Mdm Lim's
  group) and `demo-senior` (Mdm Lim). The browser sends `X-Demo-Sub` to say which one it is; the
  API only reads that header when sign-in is off.
- **Supabase:** apply `infra/supabase/migrations/202610140021_family_groups.sql` by hand to the live
  project (see `docs/supabase.md`). The API also creates the tables itself on start.
- **Commit the regenerated contract** (`openapi/silverloop.json`, `libs/api-client/src/generated`);
  `client:check` fails until it is committed. On Windows `pnpm client:generate` cannot start the
  script; run `bash scripts/generate-contract.sh` instead.
- **Still to do (phase 2+):** Home still shows Mdm Lim for every family, and the API still lets only
  the senior read `/state` and `/metrics`, so a signed-in family account gets 403s on Home's status
  and chart. Next: let active group members read their senior's data (gated by the senior's
  privacy switch) and a dropdown to pick between seniors. Availability and helpers on the Family page
  are still browser-only sample data, now labelled as such.
- A real Supabase sign-up was not tested (no project credentials here).

### Files

- API, new: `silverloop/family_groups.py` (all rules: accounts, PINs, groups, approval, demo seed),
  `silverloop/family_routes.py` (`GET /v1/me`, `POST /v1/me/onboard`, `POST /v1/me/link-pin`,
  `POST /v1/groups`, `POST /v1/groups/join`, `GET /v1/groups/{id}`, `POST /v1/groups/{id}/join-pin`,
  `POST /v1/groups/{id}/members/{member_id}/approve|decline`),
  `alembic/versions/a4f6c2e81d37_add_family_groups.py`, `tests/test_family_groups.py` (14 tests),
  `tests/test_family_groups_migration.py` (new head; upgrade and downgrade).
- API, changed: `auth.py` (role from `accounts` when the token has none; `require_family`,
  `require_identity`), `db_models.py` (5 tables), `models.py` (`family` role, request/response
  models), `main.py` (wires it up; seeds the demo group when sign-in is off), `tests/test_api.py`,
  `tests/test_postgres_integration.py` and `tests/test_review_context_gap_migration.py` (new
  migration head), `tests/test_persistence.py` (35 tables).
- Supabase: `infra/supabase/migrations/202610140021_family_groups.sql`,
  `infra/supabase/rls_posture_apply.sql`, `docs/supabase.md`.
- Contract: `openapi/silverloop.json`, `libs/api-client/src/generated/*`,
  `libs/api-client/src/index.ts` (re-exports the new types).
- Web, new: `views/SignUpView.vue`, `views/WelcomeView.vue`, `views/GroupStartView.vue`,
  `components/family/GroupPanel.vue`, `PinInput.vue`, `PinDisplay.vue`,
  `components/senior/FamilyCodeCard.vue`, `composables/useMe.ts`.
- Web, changed: `router/index.ts` (new routes; guard sends un-set-up accounts to `/welcome` and
  family members without a group to `/groups/start`), `services/careApi.ts`, `services/http.ts`,
  `composables/useAuth.ts` (`refreshCurrentUser`), `composables/useViewMode.ts` (`demoSub`),
  `lib/view-mode.ts` (+ test), `views/LoginView.vue`, `views/SeniorView.vue` (uses the signed-in
  senior's own record), `views/FamilyView.vue`.
- e2e: `apps/e2e/tests/groups.spec.ts` (3 tests).

### Checked

- Python: full suite (see below), including 14 new tests. Web: type check clean, 156 unit tests
  pass. Browser: 36 of 36 e2e tests pass (33 existing + 3 new). Screenshots of the senior code card,
  the Family page group panel and `/groups/start` at 1280 and 390 px.
- 15 of 15 YAML safety scenarios pass; the web production build succeeds.
- **Already failing before this change** (the same 9 fail on an untouched copy of the previous
  commit): the recorded-LLM tests, 7 in `test_ranking_llm_arm.py`, plus
  `test_recorded_client.py::test_the_adversarial_recording_exercises_rejection_then_revision` and
  `test_review_threshold_recording.py::test_the_guided_sequence_replays_as_recorded_agent_runs`
  (their recordings no longer match the requests). Not touched here. Everything else passes.
- `ruff format --check` flags `silverloop/triage.py`, which was already like that and is not touched
  here.

---

## 2026-10-14: Separate family and senior views, each with its own sign-in page

Branch `feat/senior-care-giver`. The app is now two views:

- **Family view**: navbar shows **Home, Calendar, Family**. The senior screen is not reachable
  (going to `/senior` lands on Home).
- **Senior view**: navbar shows only **My day** (`/senior`). The screen shows a simple overview of
  her activity (steps today, her usual day, active minutes today, the last week as bars), the
  suggested activity (or "nothing needs your attention"), **today's** activities from the family
  calendar, and her privacy switch. Going to `/`, `/calendar` or `/family` lands back on `/senior`.

Sign-in:

- `/login` now asks "Who is signing in?" and links to **`/login/family`** or **`/login/senior`**.
- With sign-in **on**, each page takes email + password and checks the account's role. A senior
  account on the family page (or the other way round) is refused with a message pointing at the
  right page, and signed out. Every screen, including Home, now needs a session.
- **The API has no "family" role**, so a family account is a **`coordinator`** account (the
  `demo_operator` also gets the family view). No backend or contract change.
- With sign-in **off** (the offline demo, and `VITE_AUTH_ENABLED=false` in `.env`) there is no
  password: each page has a **"Continue as family / the senior"** button. The choice is kept in this
  browser; **Sign out** clears it. Until you choose, every screen is open, as before (the existing
  e2e tests rely on that).

### What teammates need to know

- Nothing to run. To try it, open `/login`.
- **Known gap with sign-in on:** the API only lets the `senior` role read
  `/v1/people/{id}/state` and `/metrics`, so a family (coordinator) account will get 403s on Home's
  status card and chart. This was already true before this change. Fixing it means letting the family
  read the senior's data, which needs the senior's consent and a backend reviewer.
- A real Supabase sign-in was not tested (no account passwords here).

### Files

- New: `apps/web/src/lib/view-mode.ts` (+ `view-mode.test.ts`): which view a role gets and which
  screens each view may open. `apps/web/src/composables/useViewMode.ts`: the current view, and the
  demo choice when sign-in is off. `apps/web/src/views/LoginChooserView.vue`.
  `apps/web/src/components/senior/TodayStats.vue`. `apps/e2e/tests/views.spec.ts` (3 tests).
- Changed: `router/index.ts` (new login routes; guard keeps each view to its screens),
  `views/LoginView.vue` (one page per audience, role check, demo button), `layouts/AppLayout.vue`
  (navbar per view; "Senior" link renamed "My day"; Sign out in demo too),
  `views/SeniorView.vue` (stats + today's activities), `components/senior/OutingsList.vue` (title
  and empty text props), `components/home/ActivityChart.vue` + `lib/activity.ts` (can say "your
  usual day" on the senior screen), `composables/useAuth.ts` (sign-out/401 handling covers the new
  login paths and Home), `lib/activity.test.ts`.

### Checked

- Type check clean; 156 unit tests pass; 33 of 33 browser tests pass (30 existing + 3 new).
- Screenshots of the chooser, sign-in and senior screens at 1280 and 390 px.
- The 7 files `prettier --check .` flags (`docs/*`, `agenticlayer.md`, `.claude/settings.local.json`)
  were not touched here.

---

## 2026-10-13: `pnpm dev` no longer says "terminal too small"

Nx's full-screen task view refused to start in VS Code's terminal panel, even maximised, so
`pnpm dev` (and any other Nx command) stopped before running anything. `nx.json` now turns that
view off (`"tui": { "enabled": false }`), so Nx prints plain scrolling logs, as
`pnpm demo:offline` already did. Nothing else changes.

- Files: `nx.json`.

---

## 2026-10-13: `CAREPLUS_RUNTIME_PROFILE` replaces `SILVERLOOP_RUNTIME_PROFILE` in `.env`

The runtime-profile setting (`shared` = Supabase, `offline` = local SQLite) can now be written as
`CAREPLUS_RUNTIME_PROFILE`. The old `SILVERLOOP_RUNTIME_PROFILE` still works when the new one is
not set, so existing `.env` files keep working. If both are set, `CAREPLUS_` wins.

### What teammates need to know

- **Nothing to do.** Optionally rename the line in your own `.env` to `CAREPLUS_RUNTIME_PROFILE`.
- `pnpm demo:offline` and the Playwright config now set both names to `offline`. They have to:
  otherwise a `CAREPLUS_RUNTIME_PROFILE=shared` line in `.env` would beat their old-name setting
  and the offline demo would refuse to start. If you ever force the profile from a script or shell,
  set both names for the same reason.
- The code still calls the setting `silverloop_runtime_profile`; no API, contract or database change.

### Files

- `apps/api/src/silverloop/config.py`: reads either name.
- `apps/api/tests/test_runtime.py`: four new tests (new name, old-name fallback, new name wins,
  launchers beat `.env`); the subprocess helpers set both names.
- `scripts/demo-offline.mjs`, `apps/e2e/playwright.config.ts`: set both names.
- `.env.example`, `CLAUDE.md`, `docs/architecture.md`, `docs/setup.md`, `docs/supabase.md`: new name.

---

## 2026-10-13: Logic check, and layouts that reflow with Bootstrap's grid (branch `feat/axios-components`)

### Layout: Bootstrap grid classes at every screen size

Checked every page at 320, 375, 768, 1024, 1200 and 1440px. Phones and wide screens were fine;
tablets and small laptops (768 to 1199px) squeezed content into narrow columns. Now:

| Page     | Phone         | Tablet / small laptop (md, lg)                                                                                                                        | Wide (xl, 1200px+)                                                       |
| -------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Home     | one column    | chart full width, then **weather and tasks side by side** (`col-md-6`, equal height with `h-100`)                                                     | chart and visits left, weather and tasks right (`col-xl-7` / `col-xl-5`) |
| Home     | one day a row | the week ahead in **two columns** (`row-cols-sm-2`) instead of seven squeezed ones                                                                    | all seven days in a line                                                 |
| Calendar | as before     | calendar **full width** (day cells readable), the day's list and "Coming up" **side by side** under it (`col-lg-6`); details open as the bottom sheet | calendar beside the list or details                                      |
| Family   | as before     | members **three to a row** (`row-cols-lg-3`); share of care and the two-week grid each full width, so the grid no longer scrolls sideways             | share and grid side by side                                              |

Also: the Home hero and the Calendar header now use Bootstrap `row`/`col` (`col-lg` +
`col-lg-auto`, `col-md` + `col-md-auto`) instead of custom CSS grids/flex.

Files: `HomeView.vue`, `home/HomeHero.vue`, `home/WeekAhead.vue`, `CalendarView.vue`,
`FamilyView.vue`.

### Logic fixes

| Problem                                                                                                                          | Fix                                                                                                                                |
| -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Public holidays: a slow answer for one year could mark another year as loaded (briefly showing "No public holidays this month"). | `PublicHolidays.vue` works out loading / failed / ready from the year on screen only.                                              |
| Public holidays: the few days of the next or previous year shown in a December or January grid were never marked.                | It also fetches the neighbouring year for January and December.                                                                    |
| Weather: a forecast whose entries were all malformed showed an empty area picker.                                                | `lib/weather.ts` treats that as "no forecast", so the card shows its "could not be loaded" message (unit test added).              |
| Senior's privacy switch stayed flipped when saving the change failed, although nothing was saved (from before this branch).      | `ConsentSwitch.vue` shows the saved value again when the save finishes. New browser test in `loop.spec.ts`.                        |
| Family: a past date typed into the availability form said "Saved", but past times are never listed (from before this branch).    | `AvailabilitySelector.vue` refuses it with "Please choose today or a later day." Added to the validation test in `family.spec.ts`. |

Checked and found sound: the family rules (`lib/family.ts`), coverage counts, "next task", step
comparisons, the calendar maths, the `.ics` export, the Axios error handling and interceptors.

**Known, not changed:** "today" is worked out once when the app loads, so a tab left open past
midnight keeps yesterday's date until reloaded.

### Checked

- 146 web unit tests, typecheck and Prettier clean; browser suite 30 of 30 (one new test).

---

## 2026-10-13: The four pages split into smaller components (branch `feat/axios-components`)

The Home, Senior, Calendar and Family pages held most of their markup and styling in one file
each. Each visual block is now its own component, so the page files keep only what is really "the
page" (loading data, filters, what is selected). **Nothing on screen changed**: every page was
screenshotted before and after (10 states, desktop and 375px phone) and all 20 matched pixel for
pixel. The browser tests were not edited and all 29 pass.

### What teammates need to know

- **Nothing to install or regenerate.** No new packages, no API changes.
- **New components use the Options API** (`props`, `emits`, `data`, `computed`, `watch`,
  `methods`, lifecycle hooks), as taught in WAD2. The pages stay `<script setup>`.
- **If you were editing one of the four pages, expect a merge conflict:** most of its markup has
  moved into the components below.

| Page (lines before → after) | New components                                                                                               | Vue features they show                                                                         |
| --------------------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| Home (606 → 128)            | `home/HomeHero`, `StatusWhyPanel`, `FortnightPanel`, `NeedsHelperList`, `TaskChecklist`                      | `v-model:why-open`, `v-model` on a component (ticked tasks), emits `retry`, `RouterLink` query |
| Senior (411 → 186)          | `senior/SuggestionCard`, `ConsentSwitch`, `OutingsList`                                                      | emits with arguments, `beforeUnmount`, `v-model` bound to a writable `computed` that saves     |
| Calendar (402 → 296)        | `calendar/ViewingAsPicker`, `CoverageSummary`, `DayAgenda`, `UpcomingList`, `DetailsSheet`                   | `v-model`, default **slot**, `<Transition>`, several root nodes                                |
| Family (300 → 175)          | `family/JoinGroupForm`, `AvailabilityList`                                                                   | two `v-model`s on one component (`v-model:name`, `v-model:relationship`), computed grouping    |
| Shared                      | `ui/BasePanel` (the white panel: `title` prop, `#title` and `#actions` **named slots**), `ui/LoadingSpinner` | named slots, attribute fall-through (`class="mb-4"` lands on the panel)                        |

`WeatherCard` now uses `BasePanel` too (its Refresh button is the `#actions` slot).

### Also changed

- `lib/family.ts`: new `describeWindow()` ("Afternoon", or "9:00 am to 11:30 am"), shared by the
  availability list and the Family page's Undo toast, with a test in `lib/family.test.ts`.

### Checked

- 146 web unit tests pass; `pnpm --filter web typecheck` and Prettier are clean.
- Full browser suite 29 of 29, unchanged test files. Screenshot comparison as above (a temporary
  test, not committed).
- **Not run:** the Python tests and the full `pnpm verify` (no backend code changed).

---

## 2026-10-13: Axios for API calls, a weather card and public holidays (branch `feat/axios-components`)

To show more of what WAD2 covers: the screens now call our API with **Axios**, and two new Vue
components call **free public APIs** straight from the browser.

### What teammates need to know

- **Run `pnpm install`** after pulling: `axios` (1.12.2) is a new dependency of `apps/web`.
- **Project rule changed** (`CLAUDE.md`, `docs/architecture.md`): the web app no longer has to
  use the generated client for every call. It uses Axios through `services/careApi.ts`, still
  typed with the generated client's types. It may also call display-only public APIs, sending
  nothing about the senior. Sign-in (`useAuth.ts`, `LoginView.vue`) still uses the generated client.
- **No API or contract changes.** `pnpm client:generate` is not needed.
- The two new components use the **Options API** (`data`, `computed`, `watch`, `methods`,
  `mounted`, `props`, `emits`), as taught in the course. Everything else stays `<script setup>`.

### A. Axios for our own API

- `apps/web/src/services/http.ts`: one `axios.create()` instance with the API's base URL, a
  request interceptor that adds the sign-in token, and a response interceptor that turns failures
  into `ApiHttpError` (so the existing plain-language error messages still apply) and sends the
  person to sign in on a 401.
- `apps/web/src/services/careApi.ts`: `getPersonState`, `getPersonMetrics`, `getInterventions`,
  `recordOutcome`, `updateConsent`, each a plain `http.get` / `http.post`.
- `HomeView.vue` and `SeniorView.vue` now call these. `composables/useApi.ts` is deleted.

### B. Public APIs from the browser

| Component                                | API                                    | What it does                                                                                                                            |
| ---------------------------------------- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `components/home/WeatherCard.vue`        | data.gov.sg (NEA) 2-hour forecast      | On Home: the forecast for an area chosen with a `v-model` select (remembered in this browser), and one line on whether to plan indoors. |
| `components/calendar/PublicHolidays.vue` | Nager.Date public holidays (Singapore) | Under the calendar: this month's holidays. Emits `loaded` so the grid marks those days and the chosen day says "Public holiday: …".     |

- Calls are in `services/publicApis.ts` (a separate Axios instance, so our sign-in token is never
  sent to them). The JSON is cleaned up by pure helpers in `lib/weather.ts` and `lib/holidays.ts`.
- If either API is down, the card says so with a "Try again" button; the rest of the page works.
- Also changed: `Calendar.vue` and `CalendarDay.vue` take the holidays as a prop; `Icon.vue` has a
  new `sun` icon.

### Tests

- New unit tests `lib/weather.test.ts`, `lib/holidays.test.ts` (145 web unit tests, all pass).
- New `apps/e2e/tests/public-apis.spec.ts` (4 tests). It answers both public APIs with fixed data,
  so it never depends on the network: forecast shown and area remembered; Home works when the
  forecast fails; a holiday is marked and listed; the calendar works when holidays fail.
- Full browser suite: 29 of 29 pass. `pnpm --filter web typecheck` and Prettier are clean.
  Checked by screenshot against the real public APIs (desktop and 375px phone).
- **Not run:** the Python tests and the full `pnpm verify` (no backend code changed).

---

## 2026-10-13: Calendar helper filter fix, and leftover docs removed

### Fixed: "Only ones without a helper" could look empty

The filter itself was right, but turning it on left two things on screen that hid the result:
open details for an appointment that already has a helper (on a wide screen the details replace
the lists), and a chosen day with nothing left on it ("Nothing matches the filters on this day"),
with the matching visits pushed down into "Coming up". Now, when a filter changes, details for an
appointment the filters hide are closed, and if the chosen day is empty the calendar moves to the
first upcoming day that matches. The same applies to `/calendar?help=1`.

- Files: `apps/web/src/views/CalendarView.vue`, `apps/e2e/tests/interface.spec.ts` (the filter
  test now expects the move to tomorrow, plus a new test for the open-details case).

### Removed: files left over from the previous project

All still in git history (`git log --all -- <file>`). None is referenced by code or tests.

- `docs/ux-redesign-2026-09-17/` (16 files), `docs/ux-audit-2026-09-16.md`,
  `docs/ux-audit-2026-09-17-ops-console.md`: audits of the old React screens, which are gone.
- `docs/mvp-presentation-spec.md`: the hackathon pitch spec.
- `docs/supabase-region-move.md`: notes on moving the previous team's Supabase project.
- `docs/failure-path-results.md`: the August Next.js-era test record; `docs/testing.md` no longer
  links to it.
- `package-lock.json`: a stray npm lockfile. This repo uses pnpm (`pnpm-lock.yaml`).

---

## 2026-10-13: The app is now called Care+

Every place the app shows its name now says **Care+** instead of SilverLoop: the header logo (the
"+" is in the logo's gold), the browser tab title, the footer, the senior screen's consent switch
and explanations, the "Why Care+ says this" panel on Home, error messages, the calendar file
(.ics) and the API copy a senior can see (suggestion safety notes, the "treat this as your normal"
question, the old-saved-data message).

### What teammates need to know

- **Only the name people see changed.** Code names stay as they were (`silverloop` Python package,
  `@silverloop/*` packages, `SilverLoopClient`, the `silverloop.*` browser storage keys, the
  "SilverLoop API" OpenAPI title), so nothing needs regenerating and saved browser data still loads.
- Docs, evaluation reports and comments outside the files below still say SilverLoop.
- `apps/e2e/tests/loop.spec.ts` now looks for "Care+".
- Files: `apps/web/index.html`, `apps/web/src/layouts/AppLayout.vue`, `views/HomeView.vue`,
  `views/SeniorView.vue`, `lib/api-errors.ts`, `lib/ics.ts`, three comment-only files,
  `apps/api/src/silverloop/{outreach_content,baseline_confirmation,stored_state}.py`.

---

## 2026-10-12: Removed the hackathon brainstorm and team playbook

Tidy-up ahead of moving to our own Supabase project. The two long-form docs from the previous
hackathon are gone; they planned the hackathon build and no longer describe this project.

### What teammates need to know

- **Docs only.** No code, API or contract changes; nothing to install or regenerate.
- Both files are still in git history if you need them (`git log --all -- <file>`).

### Removed

- `hackathon_brainstorm.md`: hackathon idea ranking and MVP pitch notes.
- `silverloop-technical-execution-and-team-playbook.md`: the 19 Aug - 7 Sep 2026 hackathon build
  contract.

### Changed

| File              | Change                                                   |
| ----------------- | -------------------------------------------------------- |
| `README.md`       | Dropped the "implemented against the playbook" sentence. |
| `CLAUDE.md`       | Dropped the playbook from "Further reading".             |
| `.prettierignore` | Dropped the ignore entries for the two deleted files.    |

---

## 2026-10-10: `pnpm demo:offline` explains a failed first run

`scripts/demo-offline.mjs` now checks the two things that most often stop a first run before it
starts Nx, instead of leaving only a red cross next to `api:dev`:

- If `uv` is not installed, it prints the one-line install command for Windows and macOS/Linux.
- If the API's Python packages are missing (`apps/api/.venv`), it runs `uv sync` itself.
- If `node_modules` is missing, it says to run `pnpm install`.

Nothing else about the run changed. Tested by hiding `uv` from the PATH and by deleting `.venv`.

---

## 2026-10-10: Interface redesign (interaction layer), no behaviour removed

Every screen in `apps/web` has been redesigned for interaction and readability, using only Vue 3,
Bootstrap 5, plain CSS and browser JavaScript (no new dependencies). Everything the app did before
still works the same way and calls the same API routes; the original e2e specs pass unchanged.

### What teammates need to know

- **Try it:** `pnpm demo:offline`, then open <http://127.0.0.1:3000/>.
- **Nothing to install or regenerate.** No new packages, no API or contract changes.
- **New font files** live in `apps/web/public/fonts/` (Atkinson Hyperlegible Next, SIL Open Font
  Licence, licence file alongside). They are served locally, so the offline demo still works.
- **Labels the tests rely on were kept** (button names, form labels, headings, `data-testid`).
  If you rename visible text, run `pnpm test:e2e` first.

### The design

- One idea throughout, "closing the loop": progress shows as a ring that closes (today's steps
  against a usual day, today's tasks, visits that have a helper). Coral is kept for "needs a
  helper" and for days more than 20% below usual.
- Typeface chosen for low-vision readers; every text colour pair passes WCAG AA; 44px minimum
  touch targets; visible focus ring; motion respects `prefers-reduced-motion`.
- On phones the main menu docks to the bottom of the screen; nothing scrolls sideways at 320px,
  even at the largest text size.

### Added (interaction features)

| Where    | Feature                                                                                                                      |
| -------- | ---------------------------------------------------------------------------------------------------------------------------- |
| All      | Text-size control (standard / large / largest), remembered in this browser.                                                  |
| All      | Toasts for actions with nowhere else to confirm, with **Undo** for stepping back and removing a time.                        |
| Home     | Steps ring and plain-language sentence; "Why this status?" shows the API's own `rationale` and data-quality reasons.         |
| Home     | 14-day step chart from the existing `GET /v1/people/{id}/metrics`; each bar is a button, with arrow-key support.             |
| Home     | "Still needs someone to go along" list; each links straight to that appointment in the calendar.                             |
| Home     | Week-ahead strip; each day opens the calendar on that day. Today's tasks show progress and what is next.                     |
| Senior   | "Read this to me" (browser speech), large reply buttons, "Coming up for you" with who is going along, clearer privacy state. |
| Calendar | Legend chips filter by kind; "Only ones without a helper" filter; 30-day coverage ring.                                      |
| Calendar | Keyboard date-grid navigation (arrows, Home/End, Page Up/Down); swipe to change month on phones; month slide transition.     |
| Calendar | Details: "Add to my calendar" (.ics file), "Share these details" (share sheet or copy); opens as a bottom sheet on phones.   |
| Calendar | Links from Home: `/calendar?day=YYYY-MM-DD`, `/calendar?appointment=<id>`, `/calendar?help=1`.                               |
| Family   | "Sharing the care" bars with a nudge when one person carries most visits; 14-day availability grid (tablet and up).          |
| Family   | Live avatar preview when joining; one-tap day picks for availability; list grouped by day.                                   |
| Sign in  | Show/hide password; Caps Lock warning.                                                                                       |

### Files

New: `components/ui/` (Icon, LoopRing, ToastHost, TextSizeControl), `components/home/`
(ActivityChart, WeekAhead), `components/calendar/KindFilter.vue`, `components/family/CareShare.vue`,
`components/family/AvailabilityGrid.vue`, `composables/useTextSize.ts`, `useToast.ts`, `useNow.ts`,
`lib/activity.ts`, `lib/coverage.ts`, `lib/ics.ts`, `lib/today.ts` (each with a `.test.ts`),
`public/fonts/`. Rewritten: `styles/theme.css`, `layouts/AppLayout.vue`, `App.vue`, every view, and
the calendar and family components.

### Tests

- 35 new unit tests across `lib/activity.test.ts`, `coverage.test.ts`, `ics.test.ts`,
  `today.test.ts` (136 in total, all passing).
- New `apps/e2e/tests/interface.spec.ts` (9 browser tests): text size persists; both calendar
  filters; arrow keys move days; undo for step back and for removing a time; the .ics download;
  Home's links open the right appointment; the chart reads out the chosen day.
- Full suite: 20 of 20 e2e tests passing; `pnpm typecheck`, Prettier and `vite build` clean.

### Notes and boundaries

- The 20% line on the chart is the policy's first rung (`policy.py`); the UI only describes it.
- No browser call goes anywhere but the API (CLAUDE.md invariant). The proposal's Open-Meteo
  weather idea would need a backend route first.
- Tasks ticked on Home are still not saved, as before.

---

## 2026-09-23: IS216 syllabus-alignment pass -- stale-doc fixes, README testing/credentials section, a real responsive test

Checked the repo against the IS216 group-project syllabus (working app, responsive design, backend
data store, an external public API, testing, README setup/run/test instructions). Most requirements
were already met or exceeded (see the conversation record for the full comparison); this pass fixes
the concrete gaps: docs that still described removed screens, a README missing explicit test/run
instructions and a credentials note, and a checklist claim about responsive coverage that had no
test behind it.

**Deliberately out of scope:** anything requiring a judgement only the team can make -- specifically,
the syllabus's AI/LLM usage disclosure. Per direction, this branch adds no such section and stays
within the syllabus's allowed AI uses (doc fixes, README instructions, a generated test case),
not core business logic or problem-solving.

### What teammates need to know

- **Try it:** `pnpm demo:offline`, verified against the running app for real (responsive check,
  screenshots, and the full `apps/e2e` suite on isolated ports 3101/8101 -- 15/15 pass).
- **No API/contract changes.** `pnpm client:generate` is not needed.

### Changed

| File                          | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/demo-script.md`         | Act 1 and its troubleshooting section no longer reference the removed Simulator screen; a day is now advanced via the API docs (`/docs` → `POST /v1/simulation/advance`), matching what `apps/e2e` already does.                                                                                                                                                                                                                                                                       |
| `docs/demo-runbook.md`        | The top disclaimer banner now also names the Simulator screen as removed (it previously listed Simulator as still current, which was itself stale); the pre-demo checklist's route list and reset step no longer reference `/simulator`. The long screen-by-screen pitch narrative below is left as is -- already disclaimed, and rewriting it accurately would need re-verifying claims about screens (Ask SilverLoop, Care Team, review-timing UI) this pass didn't otherwise touch. |
| `docs/manual-ui-checklist.md` | Removed a bullet claiming automated Simulator coverage; the "390 × 844 viewport, no horizontal overflow" bullet now points at the test that actually backs it (see Added).                                                                                                                                                                                                                                                                                                             |
| `docs/testing.md`             | Two bullets in "What the tests establish" still described the Simulator/Care Team screens directly (the file's own later, accurate description of the current browser suite was correct; these two weren't updated when the screens were removed). Reworded to match.                                                                                                                                                                                                                  |
| `README.md`                   | Added a "Testing" section (`pnpm test`, `test:e2e`, `test:scenarios`, `test:postgres`, `verify`, linking to `docs/testing.md`) and a note that the offline demo needs no username/password, since sign-in is off.                                                                                                                                                                                                                                                                      |

### Added

- `apps/e2e/tests/responsive.spec.ts`: four tests (one per product route) asserting no horizontal
  overflow at a 390×844 viewport -- the exact claim `manual-ui-checklist.md` was already making with
  no test behind it. Run for real on isolated ports: 4/4 pass.

### Checked

- Manually verified responsive layout with a throwaway Playwright script (not committed) across
  375/576/768/992/1200/1400px on all four routes against the running offline demo: zero horizontal
  overflow, no console errors, screenshots reviewed at 375px and 1200px.
- `pnpm exec prettier --check` on every changed/added file: clean.
- Full `apps/e2e` suite (`family.spec.ts`, `loop.spec.ts`, `responsive.spec.ts`) run for real on
  isolated ports (8101/3101): 15/15 pass.
- **Not run:** `pnpm verify` end-to-end, the Python API tests, `pnpm test:postgres`, `pnpm lint`,
  `pnpm typecheck`. No code paths outside the new test file and docs were touched, so these are
  lower risk, but not a substitute for actually running them before this branch merges.

---

## 2026-09-22: Simulator removed, Home is now a daily overview

The Simulator screen is gone. Home (`/`) is no longer a marketing/"how it works" page: it now shows
the demo senior's activity metrics, a brief look at today's (and the next few days') calendar, and a
sample checklist of today's tasks and medicine.

### What teammates need to know

- **Try it:** `pnpm demo:offline`, then open <http://127.0.0.1:3000/>. No sign-in needed offline.
- **Nothing to install or regenerate.** No new dependencies, no API or contract changes, so
  `pnpm client:generate` is not needed.
- **The backend's simulate-a-day capability is untouched.** `POST /v1/simulation/advance` still
  exists and still backs the safety-scenario tests; only the frontend page that drove it by hand is
  gone. `apps/e2e/tests/support.ts`'s `advance()` helper now calls it directly for the browser tests
  that used to click through the Simulator.
- **Home shows real data from a public route.** `/` was already public (unauthenticated), used only
  for the "how it works" copy. It now also renders the seeded demo person's steps/attention/decision
  and the sample family calendar. The demo person (`mdm-lim`) is synthetic, so there's no real senior
  data at risk, but if this ever carries a real person's data, `/` should move behind sign-in like
  `/senior`, `/calendar` and `/family` (`lib/route-guard.ts`).

### Removed

| File                                   | Why                                                                      |
| -------------------------------------- | ------------------------------------------------------------------------ |
| `apps/web/src/views/SimulatorView.vue` | The Simulator screen (pick an event, watch the ten-step decision trace). |

Also removed because only the Simulator used them, in `apps/web/src/lib/labels.ts` (and their
tests): `SIMULATION_EVENTS`, `plainTrace`, `traceStatusBadge`, `TRACE_STATUS`, `ENGINEERING_DETAIL`.
The route (`/simulator`), its nav link, and its entry in `PROTECTED_PREFIXES` are gone too.

### Added

- `apps/web/src/lib/daily-tasks.ts` (+ `daily-tasks.test.ts`): a small, pure sample-data module —
  today's medicine and to-do reminders for the demo senior — in the same spirit as
  `lib/family-sample.ts`. No persistence: checking a task off on Home is a display convenience only
  and is not saved.
- `apps/web/src/views/HomeView.vue` now has three sections: "Today's overview" (metrics from
  `GET`-ing the person's state — attention band, last decision, consent, steps vs baseline),
  "Calendar" (today's appointments and a short look-ahead, reusing `useFamily()` and
  `AppointmentCard.vue`, with an "Open" link to `/calendar`), and "Today's tasks" (the sample
  checklist above).

### Changed

| File                                       | Change                                                                                                                                                         |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/web/src/router/index.ts`             | `/simulator` route removed.                                                                                                                                    |
| `apps/web/src/layouts/AppLayout.vue`       | Menu: Home, Senior, Calendar, Family (Simulator removed).                                                                                                      |
| `apps/web/src/lib/route-guard.ts`          | Protected sections are now `/senior`, `/calendar`, `/family`.                                                                                                  |
| `apps/web/src/views/LoginView.vue`         | The `demo_operator` role now lands on `/` after signing in (was `/simulator`).                                                                                 |
| `apps/web/src/composables/useRouteA11y.ts` | Fixed a comment that named two already-removed views as examples.                                                                                              |
| `apps/e2e/tests/support.ts`                | `advance()` now returns the decoded response so a test can read it without a results panel.                                                                    |
| `apps/e2e/tests/loop.spec.ts`              | The three tests that drove the Simulator by hand now call `advance()` directly. The persistent-decline test now asserts on the API response alone (see Tests). |

### Tests

- Trimmed `apps/web/src/lib/labels.test.ts` (removed the Simulator-only cases); new
  `apps/web/src/lib/daily-tasks.test.ts`. `route-guard.test.ts` no longer expects `/simulator` to be
  protected.
- `apps/e2e/tests/loop.spec.ts`: same five tests, rewritten to not need the Simulator screen. The
  "engineering detail is hidden" assertion (no `ranker`/`llm_enabled`/`planner` wording) is gone with
  the screen that rendered the loop trace; nothing else on the web app shows that trace today. The
  persistent-decline test no longer visits the senior screen: three cumulative declining days also
  leave the first day's `gentle_nudge` suggestion still pending there (a real, pre-existing behaviour,
  not a regression), so "nothing needs attention" would not actually be true. The test now checks the
  `POST /v1/simulation/advance` response directly — `coordinator_review`, a `created_case`, no
  `created_intervention` — which is what the original Simulator-driven version checked too.
- Ran `apps/e2e/tests/loop.spec.ts` for real against `pnpm demo:offline`'s servers (on ports
  3100/8100, beside the running demo): 5/5 pass.

### Decisions worth knowing about

1. **The backend's simulation feature is not touched.** `silverloop.scenarios`, the `/v1/simulation`
   routes and every Python test that exercises them are unaffected. This change is frontend-only.
2. **The loop-trace viewer (ten stages, engineering-detail scrubbing) has no home now.** It only
   existed on the Simulator. If a future screen needs to show _why_ a decision was made step by
   step, that display logic (`plainTrace`, `traceStatusBadge` — deleted here) will need rebuilding.
3. **"Today's tasks" is invented, not derived from anything real.** There is no medicine or to-do
   concept in the API. Say so if this should instead reuse the calendar's `medical` appointment kind
   or become a real backend feature.
4. **Home stayed a public route.** See "What teammates need to know" above.

### Checked

- `apps/web`: unit tests (101 pass, `node:test`), `pnpm --filter web typecheck` (`vue-tsc`, unused
  imports as errors), `pnpm --filter web build` (production `vite build`), and `prettier --check`
  over the changed files — all clean.
- Ran `pnpm demo:offline` for real and drove it with a headless Chromium script: the nav bar has no
  Simulator link, `/simulator` now 404s (`NotFoundView`), Home renders "Today's overview", "Calendar"
  and "Today's tasks" with real data from the running API, and no console/page errors. Screenshot
  reviewed at 1280 px wide.
- `apps/e2e/tests/loop.spec.ts` run for real (see Tests): 5/5 pass.
- **Not run:** `pnpm verify` end-to-end, the Python API tests, `pnpm test:postgres`, the family
  browser spec (`family.spec.ts`, untouched by this change), or a narrow-viewport check of the new
  Home layout. No separate reviewer or verifier agents were used, so this was checked by the author
  only.

### Also stale from before this change (not fixed here, same as the last entry's note)

`docs/demo-script.md` (Act 1 is built entirely around the Simulator screen), `docs/demo-runbook.md`,
`docs/manual-ui-checklist.md`, `docs/mvp-presentation-spec.md`, and parts of `docs/testing.md` below
the paragraph fixed here still describe the Simulator and/or the already-removed Care Team screen.
None of these affect behaviour; they need a rewrite of their own.

---

## 2026-09-21: family coordination (calendar + family group), Care Team removed

The next version now focuses on helping a family coordinate care for an elderly relative. The app is
otherwise the same: same design, same Vue + Bootstrap setup, same Simulator and Senior screens.

### What teammates need to know

- **Try it:** `pnpm demo:offline`, then open <http://127.0.0.1:3000/calendar> and `/family`. No
  sign-in, API key or `.env` is needed for the offline demo.
- **Nothing to install or regenerate.** No new dependencies. The API, the OpenAPI snapshot and the
  generated client are untouched, so `pnpm client:generate` is not needed.
- **The Care Team page is gone.** `/care-team` and `/care-team/...` now redirect to `/calendar`.
- **The calendar and family screens have no backend yet.** They run on made-up sample data kept in
  the browser (`localStorage`). Each browser has its own copy, so two family members on two
  devices do not see each other's changes yet. See
  [What a real backend would have to store](#what-a-real-backend-would-have-to-store).

### Removed

| File                                  | Why                                                                                              |
| ------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `apps/web/src/views/CareTeamView.vue` | The Care Team page (the list of review cases).                                                   |
| `apps/web/src/views/CaseView.vue`     | The case detail page. It was only reachable from Care Team and its back link said "← Care Team". |

Also removed because only those two pages used them: `caseStatusBadge` and `CASE_DECISIONS` in
`apps/web/src/lib/labels.ts` (and their tests), and the old Care Team browser test.

The backend still creates and serves review cases exactly as before; the web app just no longer has
a screen for them. To bring the screens back, restore the two files from commit `c3a4c66`.

### Added

**Screens** (routes `/calendar` and `/family`, both in the menu, both behind sign-in when sign-in is on)

- `apps/web/src/views/CalendarView.vue`: a month calendar of Mdm Lim's activities and
  appointments, a list for the chosen day, a "Coming up" list, and an appointment details panel.
  A "Viewing as" menu picks which family member is using the screen.
- `apps/web/src/views/FamilyView.vue`: who is in the family group, a form to join it, a form to
  share availability, and everyone's availability.

**Components** (`apps/web/src/components/`)

| Component                         | What it is                                                                                          |
| --------------------------------- | --------------------------------------------------------------------------------------------------- |
| `calendar/Calendar.vue`           | The month grid: month heading, Previous / Today / Next, weekday row, the kinds legend.              |
| `calendar/CalendarDay.vue`        | One day cell: dots on narrow screens, appointment titles on wide ones.                              |
| `calendar/AppointmentCard.vue`    | One appointment in a list: when, where, its kind, who is helping (or "Needs a helper").             |
| `calendar/AppointmentDetails.vue` | The details panel: when, where, notes, who is helping, and the buttons to help or say you cannot.   |
| `calendar/AssignmentList.vue`     | Every family member with their status for one appointment: Helping, Available, Not available, none. |
| `calendar/KindBadge.vue`          | The coloured, worded label for a kind (Medical visit, Therapy, Activity, Errand).                   |
| `family/FamilyMemberCard.vue`     | One member: name, relationship, how much they are helping, "You" or "I'm <name>".                   |
| `family/AvailabilitySelector.vue` | The form to add availability: a date, a time of day (All day, Morning, ...) and can / cannot help.  |
| `family/MemberAvatar.vue`         | A coloured initial. Always shown next to the person's name, never on its own.                       |

**Logic**

- `apps/web/src/composables/useFamily.ts`: the shared reactive state (a singleton, like `useAuth`),
  saved to `localStorage` under the key `silverloop.family.v1`.
- `apps/web/src/lib/family.ts`: the model and all the rules, as plain functions with no Vue in
  them: who is available for an appointment, volunteering, stepping back, joining, validating a
  window, reading saved data back safely.
- `apps/web/src/lib/family-sample.ts`: the made-up family, schedule and answers, always dated
  relative to today so something is always coming up.
- `apps/web/src/lib/calendar.ts`: day arithmetic, the month grid (Sunday first), and clock helpers.

### Changed

| File                                   | Change                                                                                                                                             |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/web/src/router/index.ts`         | Added `calendar` and `family` routes; `care-team/...` redirects to `/calendar`.                                                                    |
| `apps/web/src/layouts/AppLayout.vue`   | Menu: Home, Simulator, Senior, **Calendar**, **Family** (Care Team removed). With sign-in on, the coordinator role sees Home, Calendar and Family. |
| `apps/web/src/lib/route-guard.ts`      | Protected sections are now `/simulator`, `/senior`, `/calendar`, `/family`.                                                                        |
| `apps/web/src/views/LoginView.vue`     | A coordinator lands on `/calendar` after signing in (was `/care-team`).                                                                            |
| `apps/web/src/views/HomeView.vue`      | Step 3 is now "The family coordinates" and links to `/calendar` (was "A person reviews" / Care Team).                                              |
| `apps/web/src/views/SimulatorView.vue` | After a persistent decline it now says "A person would be asked to review this: ..." with no link (the case page is gone).                         |
| `apps/web/src/lib/format-date.ts`      | Added `formatClockTime` ("10:00 am"), `formatMonthYear` ("September 2026"); exported the weekday name lists.                                       |
| `apps/web/src/styles/theme.css`        | Added the four appointment-kind colours (`.kind-medical`, `.kind-therapy`, `.kind-activity`, `.kind-errand`, `.kind-badge`).                       |

### Tests

- New, run by `pnpm test` in `apps/web`: `lib/calendar.test.ts`, `lib/family.test.ts`. Extended:
  `lib/format-date.test.ts`, `lib/route-guard.test.ts`. Trimmed: `lib/labels.test.ts`.
- New browser spec `apps/e2e/tests/family.spec.ts` (6 tests): Care Team gone and old links
  redirect; the calendar lists appointments and opens details; taking an appointment (kept after a
  reload, a second person can also help, stepping back); saying you cannot make it; joining the
  group and sharing availability (and seeing it on the calendar); availability validation.
- `apps/e2e/tests/loop.spec.ts`: the Care Team test is replaced by one checking that a persistent
  decline says a person would be asked to review it, with no link to a removed screen.

### Docs

- `README.md`, `docs/architecture.md`: describe the current screens, and say the calendar and family
  screens run on browser-only sample data.
- `docs/demo-script.md`: Act 3 is now the family flow (Calendar, then Family); the "hand over to a
  person" moment moved into Act 1 as an aside; troubleshooting updated.
- `docs/demo-runbook.md`: the note at the top and the tab list now say Calendar instead of Care Team.
  **The long sections below the note still describe screens that no longer exist** (Care Team, the
  case page, review timing). They were already partly out of date, and are not rewritten here.
- `CLAUDE.md`: the `apps/web` line in the layout section lists the current screens and flags the
  browser-only data.

### How it behaves

- **Availability** is either a window ("free Friday afternoon") or an answer about one appointment.
  An answer about the appointment wins over a window. A "not available" window that overlaps the
  appointment makes the person unavailable. An "available" window only counts if it covers the
  whole appointment; anything less is shown as "Has not replied yet", never guessed.
- **"I'll help"** takes the appointment and also records the person as available. Several people can
  help with one appointment. **"Step back"** takes only that person off and leaves their
  availability alone. Saying **"I can't make it"** replaces any earlier answer.
- **Joining** adds a member with a name and relationship, and switches the screen to them. A name
  already in the group is refused (any capitalisation), so nobody is mistaken for someone else.
- **Sample data** (Mdm Lim; Sarah, John and Emily) matches the example in the brief: for the
  doctor's appointment Sarah and John are available, Emily is not, and nobody is helping yet.
  **Family > "Reset the sample family data"** puts it all back.

### What a real backend would have to store

Today all of this is `FamilyState` and the sample appointments in `apps/web/src/lib/family.ts`. To
make it real (and shared between family members), the API needs:

| Entity                 | Today                                                                  | A backend also needs                                                                                                         |
| ---------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Elderly profile        | A name ("Mdm Lim")                                                     | The link to the existing person (`person_id`), and **the senior's consent to share their schedule with family**.             |
| Family group           | One implied group                                                      | A group per elderly person, an invite link or code, and who may invite or remove members.                                    |
| Family member          | id, name, relationship, avatar colour                                  | A real account that signs in, with a role (the API has no `family` role today), and a membership linking account to group.   |
| Appointment / activity | id, title, kind, date, start, end, location, notes                     | Who created or changed it, repeating events, and the time zone (Asia/Singapore). The AAC activity catalogue could feed this. |
| Availability           | id, member, date, start, end, available / not, optional appointment id | One row per window or per-appointment answer, unique per (member, appointment).                                              |
| Assignment             | appointment id + member id                                             | Unique per (appointment, member), when it was made, an audit trail, and protection when two people claim at the same moment. |

The rules in `lib/family.ts` (`statusFor`, `respondTo`, `volunteerFor`, `createMember`,
`checkWindow`) are pure functions written to be moved to the API as they are.

### Decisions worth knowing about

1. **Care Team meant two pages, and both went.** The list and the case detail page. Say so if you
   would rather keep the case page (it would need a new home and a way to reach it).
2. **No backend for this yet, on purpose.** The brief said to use the existing frontend approach when
   the API has no support. **This does not meet the repo rule that "FastAPI owns every domain state
   transition and every domain DB write"**, so treat it as a prototype until it moves to the API.
3. **Nothing here contacts anyone.** No notifications or messages. The product boundary says no
   caregiver contact without consent; if "notify the family" is ever added, it needs the senior's
   consent first.
4. **Appointments are not saved, only the family's choices.** Appointments are rebuilt from today on
   every load (so the sample never goes stale); members, availability and assignments are saved.
5. **No calendar library, no new dependency.** The calendar is a plain `<table>` of buttons, styled
   with Bootstrap classes plus scoped CSS. Sunday is the first column.
6. **Family members do not sign in yet.** "Viewing as" (Calendar) and "I'm <name>" (Family) choose who
   is acting. With sign-in on, the API has no family role, so the coordinator role is the one that
   sees Calendar and Family.

### Checked

- Unit tests: 101 pass (`apps/web`, Node's test runner). Type check (`vue-tsc`), `prettier --check .`
  and the production build are clean.
- Browser tests (Playwright, real API, run on ports 3100/8100 to sit beside a running demo): 11 of 11
  pass, 6 of them new.
- A scripted run through every item in the brief (36 checks) on the running app: Care Team gone,
  calendar and details, joining, availability, assigning, reload keeps the changes, and Home,
  Simulator and Senior still work. No Vue warnings or console errors. Screens reviewed at 1280, 768
  and 375 px wide, with no sideways scrolling.
- With sign-in on: `/care-team` and `/care-team/cases/x` end at `/login?next=%2Fcalendar`,
  `/calendar` and `/family` are guarded, and `/` is public.
- **Not run:** the Python API tests, the full `pnpm verify`, `pnpm client:check` (the API is
  untouched), the Postgres/Supabase modes, or a real Supabase sign-in (no credentials here). No
  separate reviewer or verifier agents were used, so this was checked by the author only.

### Known limitations and next steps

- Appointments cannot be added, edited or removed yet; they come from the sample.
- Data lives in one browser. Sharing between family members needs the backend above.
- "Today" is the browser's own date, not fixed to Asia/Singapore time.
- In a narrow month cell, one very long word (for example "Physiotherapy") can still split; the
  full title is in the list, the details and the screen-reader label.

### Also changed in the folder (not part of this feature)

- `.env.example`: `AUTH_ENABLED` changed from `true` to `false` by hand before this work began. The
  app only reads `.env`, never `.env.example`, so it has no effect; it is the shared template, so
  consider reverting it.
