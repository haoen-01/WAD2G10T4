# Day timeline

Frontend edits only

## What it is

A new **"{Senior}'s day"** panel at the top of the family Home page. It lays out one day of the
senior's care by the hour, in three lanes:

| Lane               | What sits on it                                                       |
| ------------------ | --------------------------------------------------------------------- |
| **Appointments**   | Calendar appointments as bars (start to end), with who is going along |
| **Tasks**          | The senior's tasks at their scheduled time, filled in once done       |
| **Family updates** | Each family update (check-ins, "took", notes) at the time it was made |

Inspired by Life360's day view and Caring Village's shared care calendar: one glance answers
"what is on today, what is done, who is helping, and who has been in touch?"

## How it helps the app

- **One place to see the whole day.** Before, appointments, tasks and family updates were in three
  separate panels and the calendar page. Now they line up on one time axis.
- **Live, not a snapshot.** A red **Now** line moves with the clock (every 30 s). The calendar is
  re-read every 30 s while the tab is visible, and again when you come back to the tab. Ticking a
  task in the Tasks panel shows on the timeline at once. A tab left open past midnight moves on to
  the new day by itself.
- **Act where you look.** Tap anything to see details in the card below the timeline:
  - **I'll go** on an appointment that still needs someone.
  - **You're going** with a lasting **Can't go** button, so you can change your mind days later
    without hunting for the Undo toast or going to the Calendar.
  - **No one else needed** with **I'll go too**, when someone is already going but you want to join.
  - **Mark done / Not done** on today's tasks.
- **Family updates are not misleading.** If someone taps "I'll go" and steps back within 5 minutes
  (for example, Undo), both lines are left out of the feed for everyone, so nobody reads that they
  are going when they are not. A step back later than that stays, because the family needs to know
  the appointment needs someone again.
- **Earlier days are a record.** Going back with ‹ shows **What {senior} did** (tasks done, not
  ticked off, appointments and who went) and **Family in touch** (who checked in). Days up to six
  ahead show what is planned. **Today** brings you back.
- **Honest and accessible.** Sample data is labelled "Sample". Markers are buttons with full screen
  reader labels, work by keyboard, and the layout fits phones (375 px) without sideways scrolling.
  Nothing here diagnoses, detects falls or contacts anyone.

## Files changed

| File                                            | Change                                                                                                                                                                         |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/web/src/lib/day-timeline.ts`              | **New.** Pure rules: clock times, Singapore day/minute of a timestamp, sorting, the drawn window (7 am–10 pm, widened), "now / next / latest", day summary and past-day record |
| `apps/web/src/lib/day-timeline.test.ts`         | **New.** Unit tests for the above                                                                                                                                              |
| `apps/web/src/components/home/DayTimeline.vue`  | **New.** The panel: header and day arrows, three lanes, Now line, details card with the actions, past-day record, live sync                                                    |
| `apps/web/src/views/HomeView.vue`               | Shows `<DayTimeline>` under the hero                                                                                                                                           |
| `apps/web/src/lib/family-feed.ts`               | **Added** `withoutUndone()`: hides a "took" + "stepped back" pair from the same member, same appointment day, within 5 minutes (`UNDO_WINDOW_MS`)                              |
| `apps/web/src/lib/family-feed.test.ts`          | Tests for `withoutUndone()`                                                                                                                                                    |
| `apps/web/src/composables/useFamilyActivity.ts` | The feed's `entries` go through `withoutUndone()`, so the Family updates panel and the timeline both use it                                                                    |
| `apps/e2e/tests/day-timeline.spec.ts`           | **New.** Browser tests: take an appointment then "Can't go"; tick a task; an earlier day's record and the Today button                                                         |

## Where the data comes from (all existing)

- Appointments and helpers: `useFamily()` (the family calendar, saved through the API).
  "I'll go" / "Can't go" call the existing `family.volunteer()` / `family.stepBack()`.
- Tasks: `useTasks()` (kept by the family group in the API; see `docs/tasks.md`).
- Family updates: `useFamilyActivity()` (the existing activity feed, polled every 30 s).
- Clock: `useNow()`; dates in Singapore time.

## How to check it

```bash
pnpm --dir apps/web typecheck
pnpm --dir apps/web test
pnpm --dir apps/web build
pnpm exec playwright test apps/e2e/tests/day-timeline.spec.ts
```

Then on Home (signed in as family): tap the doctor's appointment, press **I'll go**, see
**You're going / Can't go**, press **Can't go**, and see Family updates stay accurate.

## Known limits / next steps

- Other parts of Home and the Calendar still take "today" from when the page was opened
  (`composables/useFamily.ts`, `const today = todayIso()`), so after midnight they show the
  previous day until a reload. The timeline itself already follows the live clock.
- The backend still records both the "took" and "stepped back" entries; the 5-minute pairing is a
  display rule in the frontend. A real delete would need a backend change.
- Steps are a daily total in this app, so the timeline does not draw an hour-by-hour step line.
