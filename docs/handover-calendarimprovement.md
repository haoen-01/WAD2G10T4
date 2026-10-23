# Handover: Calendar page, (Person C)


## Where things stand

- All of the work is in one commit, `d944773` "feat: calendar page feedback round 2 (Person C,
  frontend only)", on top of `dev` at `d6f5742`.
- **Frontend only.** No backend, API, database, OpenAPI or generated-client files were changed.
- **Only Person C's files**, as `work-split.md` asks: `views/CalendarView.vue`,
  `components/calendar/*`, `lib/coverage.ts` (+ its test), and a section at the top of
  `UPDATES.md`. No other person's files were touched.
- **Stack:** HTML, CSS, TypeScript, Bootstrap 5 and Vue 3 only. No new dependencies.
- 11 files changed, 547 lines added, 74 removed.

## What changed and how it helps

### 1. "View as" moved to the top right

The "Viewing as" picker used to sit beside the "Calendar" title. It now sits in the top right
of the header, beside "+ Add" (`CalendarView.vue`, `.head-tools`).

- **Helps:** the title reads cleanly, and the two controls a family member reaches for (who am
  I, add something) are together in the usual place for page actions.

### 2. One thing per row: calendar, Today, Coming up

The calendar used to share a row with the day's list and "Coming up", which squeezed all three.
Now each has its own full-width row (`CalendarView.vue`):

1. **The calendar**, full width, so day cells are bigger and easier to read and tap.
2. **The chosen day**, with a green **Today** tag when it is today (`DayAgenda.vue`). Its
   appointments and tasks are cards side by side, as many as fit.
3. **Coming up**, also as a row of cards (`UpcomingList.vue`).

Two things keep working as before:

- While adding or editing an appointment, the form sits **beside** the calendar on wide screens
  (`col-xl-7` / `col-xl-5`), so a day can still be tapped to pick it, with the "who is free"
  shading.
- An appointment's details open in their own row **under the calendar** on wide screens (scrolled
  into view), and as a sheet over the page on phones and tablets.

- **Helps:** nothing is squeezed, there is less scrolling sideways in a narrow column, and the
  page reads top to bottom: month, the day you picked, what is next.

### 3. Events colour-coded by type, with a legend

The legend chips (`KindFilter.vue`) used to have their own hard-coded colours. They now use the
shared `.kind-*` colours from `theme.css`, the same ones the calendar cells and cards use.

- **One source of colour.** When Person A adds the new, colour-blind-safe event colours to
  `theme.css`, the legend, the calendar and the cards all pick them up with no change here.
- **Never colour alone:** every chip shows the type's name next to its colour, as the team rules
  ask.
- **Tasks are in the legend** too ("Task", drawn with the same dashed edge as task chips on the
  calendar). It is a key only, not a filter.
- **Helps:** a family member can tell a medical visit from an errand at a glance, and knows what
  the dashed items are.

### 4. "Not every event needs a helper" (the frontend part)

Some events need nobody to go along (a phone check-in, something the senior does alone). They
should never show as "Needs a helper".

What is in place (`lib/coverage.ts`):

- `needsHelper(appointment)`: false only when an appointment says `needsHelper: false`.
- `stillNeedsHelper(assignments, appointment)`: needs a helper **and** nobody has taken it.
- `needingHelp()` and `coverageOf()` now leave out events that do not need a helper.

Because these shared functions are used by every screen, the rule applies everywhere at once: the
Calendar's "Needs helper" filter, the coral markers on days, the "x/y covered" count, Home's
"Needs someone to go along" list and the Family page's counts. Cards say "No helper needed" and
the details say "No one needs to go along" (`AppointmentCard.vue`, `AppointmentDetails.vue`).

The add/edit form has a **"Someone needs to go along"** tick box (`AddAppointmentForm.vue`), but
it is **hidden** for now behind `NEEDS_HELPER_SAVED = false` in `lib/coverage.ts`. The API does
not store the flag yet and silently ignores unknown fields, so a visible tick box would look saved
and then reset on reload.

- **Helps:** once switched on, families stop being nagged about events nobody needs to attend,
  so the real "needs a helper" alerts stand out.
- **Today nothing changes on screen**: every appointment still needs a helper until the backend
  sends the flag (see Next steps).

### 5. A calendar the senior can see (`SeniorCalendar.vue`)

A new, view-only week calendar for the Senior page, made for older readers:

- Big text, one week at a time (this week, up to three weeks ahead with the arrows).
- Each day says "Today", "Tomorrow" or the weekday, then each event's time, name, type (dot and
  word), place, and **who is coming** in plain words ("Sarah is coming with you"), with avatars.
  An event still being arranged says "Your family is arranging who comes".
- Nothing can be changed here; the family does that on the Calendar page.
- It reads the family calendar itself (`useFamily()`), so the Senior page only needs one line:
  `<SeniorCalendar />`.

- **Helps:** the senior can see their own week and who is coming with them, which was asked for
  in the feedback, without the busy family controls.

### 6. Tests

`lib/coverage.test.ts` has 3 new tests: events need a helper unless they say otherwise; events
that do not need one never count as still needing someone; and they are left out of the coverage
count. All 178 web unit tests pass.

## Next steps for others (also in `UPDATES.md`)

| Who                      | What                                                                                                                                                                                                                      |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend owner            | Add `needs_helper: bool = True` to `AppointmentRequest` and `AppointmentOccurrence` (`models.py`), store it (DB column + Alembic migration, `family_routes.py`), then `pnpm client:generate` and commit what it produces. |
| **E** (`lib/family.ts`)  | In `fromCalendar`, copy the flag across: `needsHelper: occurrence.needs_helper`.                                                                                                                                          |
| **C** (us)               | Then set `NEEDS_HELPER_SAVED = true` in `lib/coverage.ts` to show the tick box. The form already sends `needs_helper` when it is on.                                                                                      |
| **B** (`SeniorView.vue`) | Add `<SeniorCalendar />` to the Senior page.                                                                                                                                                                              |
| **D** (`WeekAhead.vue`)  | Switch its own "Needs a helper" check to `stillNeedsHelper()` from `lib/coverage.ts`. Home's "Needs someone" list already follows (it uses `needingHelp()`).                                                              |
| **A** (`theme.css`)      | New event colours in `.kind-*` (with dark-mode versions) apply to the calendar and legend automatically.                                                                                                                  |

## Checks done

- `pnpm --dir apps/web typecheck`, `pnpm --dir apps/web test` (178 pass), `pnpm --dir apps/web
build` and Prettier: all pass.
- Clicked through in a browser at 1280 px, 1024 px and phone width (375 px): the header, the
  three rows, the form beside the calendar, details under the calendar and as a sheet. No
  sideways scrolling, also at 150% zoom.
- **Not yet checked:** `SeniorCalendar` on a real page (no page uses it until B adds it), these
  screens in dark mode, and the Playwright browser tests (Playwright's browser is not installed on
  the machine used).
