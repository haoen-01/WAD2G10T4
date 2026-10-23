# Shared tasks

Home and Senior show the same per-person task list, and every task also appears on the Calendar
and in Home's week ahead. The previous hardcoded medicine checklist is no longer displayed. New
profiles start with no tasks; the app generates no medical advice or medication schedules.

## Storage

The API has no tasks yet, so tasks are kept **in this browser only** (`localStorage`, key
`careplus.tasks.v1.<person_id>`). Another browser or device has its own list, and clearing site
data removes it. Other tabs of the same browser pick up changes straight away. If storage is
blocked (some private windows), tasks last until the page is closed.

- Rules (pure, tested in `lib/tasks.test.ts`): `apps/web/src/lib/tasks.ts`.
- Shared reactive state and storage: `apps/web/src/composables/useTasks.ts`.
- Screens: `components/home/TaskPanel.vue` (Home and Senior), the Calendar grid and day list
  (`views/CalendarView.vue`, `components/calendar/CalendarDay.vue`, `DayAgenda.vue`) and
  `components/home/WeekAhead.vue`.

## Behaviour

- Family members can add, edit and delete tasks on Home. The senior's screen can tick tasks off
  but not manage them.
- Tasks run once, every day, or every seven days from their first date. An optional last date is
  inclusive. Each date is ticked off separately.
- Future dates can be viewed but not ticked off until the day arrives.
- Editing changes the whole schedule; days already ticked off stay ticked off. Deleting removes
  the task, all its repeats and its ticks, from the calendar too.
- On the Calendar, tasks show as dashed chips beside appointments and can be ticked off in the
  day list. They need nobody to go along, so they never count towards "needs a helper", and the
  "Only ones without a helper" filter hides them.
- "Today" is the device's own date, the same as the calendar's.
