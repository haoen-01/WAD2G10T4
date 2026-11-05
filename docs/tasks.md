# Shared tasks

A task is a one-off, daily or weekly reminder for the senior ("Water the plants", "Blood pressure
tablet"), kept by their family group. The senior and the family see the same list: on the senior's
screen, on family Home (the Tasks panel, the day timeline and the week ahead) and on the Calendar.
New groups start with no tasks. Care+ generates no medical advice or medication schedules: a
medicine task is a label the family writes.

## Storage

Tasks are stored by the API (`silverloop.family_tasks`, tables `tasks` and `task_ticks`), under the
**family group**, so a group keeps its tasks before its senior is linked and nothing carries over
when they are. A repeating task is one row; its days are worked out when read. A tick is one day
of a task ticked done (one row per task and day); un-ticking deletes it.

Nothing in `advance`, the policy, review cases or outreach reads a task. A missed tick triggers
nothing, and ticks are not written to the family activity feed.

- Routes: see `docs/api.md` (Tasks).
- Rules on the server: `server/src/silverloop/family_tasks.py`, tested in
  `server/tests/test_family_tasks.py`.
- Rules in the browser (pure, tested in `lib/tasks.test.ts`): `client/src/lib/tasks.ts`.
- Shared reactive state: `client/src/composables/useTasks.ts`. It reads from the same place as
  the calendar (`calendarSourceFor`): the senior their own list, a family member the group they
  picked. It reads again when a screen opens, when the day timeline refreshes (every 30 s and when
  the tab comes back) and after every change.
- Screens: `components/home/TaskPanel.vue` (Home), `components/senior/SeniorTaskList.vue`
  (Senior), `components/home/DayTimeline.vue`, the Calendar grid and day list
  (`views/CalendarView.vue`, `components/calendar/CalendarDay.vue`, `DayAgenda.vue`) and
  `components/home/WeekAhead.vue`.

## Behaviour

- Active family members add, edit and delete tasks (Home and the Calendar). The senior's screen
  ticks today's tasks off but cannot add or change them; the API refuses a senior with 403.
- Tasks run once, every day, or every seven days from their first date. An optional last date is
  inclusive. Each date is ticked off separately.
- No one can tick a future day. The senior ticks today only; a family member can also tick a past
  day ("she told me she took it yesterday"). "Today" is the Singapore date on the server and the
  device's date on screen; if they disagree around midnight the tick is refused and undone.
- A tick or edit shows at once and is undone, with a message, if the API refuses it.
- Editing changes the whole schedule; days already ticked off stay ticked off (a tick that is no
  longer one of the task's days is kept but not shown). Deleting removes the task, all its repeats
  and its ticks. When two members edit at once, the last save wins.
- On the Calendar, tasks show as dashed chips beside appointments and can be ticked off in the
  day list. They need nobody to go along, so they never count towards "needs a helper", and the
  **Needs helper** filter hides them.

## The demo

With sign-in off, the demo reset gives Mdm Lim's group five sample tasks every day from the reset
day (`family_tasks.DEMO_TASKS`), with no ticks.
