import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  addTask,
  isRepeating,
  oneOffTasksByDay,
  parseShowRepeating,
  repeatingCountByDay,
  checkTask,
  deleteTask,
  emptyStore,
  occursOn,
  setCompleted,
  storeFromList,
  tasksByDay,
  tasksOn,
  updateTask,
} from './tasks';
import type { TaskInput, TaskSchedule } from './tasks';

const input = (over: Partial<TaskInput> = {}): TaskInput => ({
  title: 'Take medicine',
  start_date: '2026-10-15',
  time: '09:00',
  repeat: 'none',
  repeat_until: null,
  notes: '',
  ...over,
});
const schedule = (over: Partial<TaskInput> = {}): TaskSchedule => ({
  ...input(over),
  task_id: 't1',
});

describe('when a task happens', () => {
  it('happens once on its first day only', () => {
    const task = schedule();
    assert.equal(occursOn(task, '2026-10-15'), true);
    assert.equal(occursOn(task, '2026-10-16'), false);
    assert.equal(occursOn(task, '2026-10-14'), false);
  });

  it('repeats every day from the first day up to the last day', () => {
    const task = schedule({ repeat: 'daily', repeat_until: '2026-10-17' });
    assert.equal(occursOn(task, '2026-10-14'), false);
    assert.equal(occursOn(task, '2026-10-15'), true);
    assert.equal(occursOn(task, '2026-10-17'), true);
    assert.equal(occursOn(task, '2026-10-18'), false);
  });

  it('repeats every week on the same weekday, across a month end', () => {
    const task = schedule({ repeat: 'weekly' });
    assert.equal(occursOn(task, '2026-10-22'), true);
    assert.equal(occursOn(task, '2026-11-05'), true);
    assert.equal(occursOn(task, '2026-10-23'), false);
  });

  it('keeps repeating with no last day', () => {
    assert.equal(occursOn(schedule({ repeat: 'daily' }), '2027-03-01'), true);
  });
});

describe('a day of tasks', () => {
  it('lists the day earliest first, with what was ticked off that day', () => {
    let store = addTask(emptyStore(), input({ title: 'Evening walk', time: '18:00' }), 'a');
    store = addTask(store, input({ title: 'Medicine', repeat: 'daily' }), 'b');
    store = setCompleted(store, 'b', '2026-10-15', true);
    const day = tasksOn(store, '2026-10-15');
    assert.deepEqual(
      day.map((task) => [task.title, task.completed]),
      [
        ['Medicine', true],
        ['Evening walk', false],
      ],
    );
    // Ticking off one day of a repeating task leaves the next day open.
    assert.equal(tasksOn(store, '2026-10-16')[0].completed, false);
  });

  it('groups by day for the calendar, leaving out empty days', () => {
    const store = addTask(emptyStore(), input({ repeat: 'weekly' }), 'a');
    const days = tasksByDay(store, ['2026-10-15', '2026-10-16', '2026-10-22']);
    assert.deepEqual(Object.keys(days), ['2026-10-15', '2026-10-22']);
  });
});

describe('changing tasks', () => {
  it('ticks off and back on without doubling up', () => {
    let store = addTask(emptyStore(), input(), 'a');
    store = setCompleted(store, 'a', '2026-10-15', true);
    store = setCompleted(store, 'a', '2026-10-15', true);
    assert.deepEqual(store.completions.a, ['2026-10-15']);
    store = setCompleted(store, 'a', '2026-10-15', false);
    assert.deepEqual(store.completions.a, []);
  });

  it('edits the schedule and keeps the days already done', () => {
    let store = addTask(emptyStore(), input({ repeat: 'daily' }), 'a');
    store = setCompleted(store, 'a', '2026-10-15', true);
    store = updateTask(store, 'a', input({ title: 'New name', repeat: 'daily' }));
    assert.equal(store.schedules[0].title, 'New name');
    assert.deepEqual(store.completions.a, ['2026-10-15']);
  });

  it('deletes a task with its ticks', () => {
    let store = addTask(emptyStore(), input(), 'a');
    store = setCompleted(store, 'a', '2026-10-15', true);
    store = deleteTask(store, 'a');
    assert.deepEqual(store, emptyStore());
  });

  it('trims the name and drops a last day on a one-off task', () => {
    const store = addTask(
      emptyStore(),
      input({ title: '  Call  ', repeat_until: '2026-12-01' }),
      'a',
    );
    assert.equal(store.schedules[0].title, 'Call');
    assert.equal(store.schedules[0].repeat_until, null);
  });
});

describe('checking a task', () => {
  it('accepts a complete task', () => {
    assert.equal(checkTask(input()), null);
  });

  it('asks for a name, a day and a time', () => {
    assert.equal(checkTask(input({ title: '  ' })), 'Please give the task a name.');
    assert.equal(checkTask(input({ start_date: '' })), 'Please choose the first day.');
    assert.equal(checkTask(input({ time: '' })), 'Please choose a time.');
  });

  it('refuses a last day before the first day', () => {
    assert.equal(
      checkTask(input({ repeat: 'daily', repeat_until: '2026-10-01' })),
      'The last day must be on or after the first day.',
    );
  });
});

describe("reading the API's list", () => {
  it('turns the ticks into the days each task was ticked off', () => {
    const store = storeFromList({
      tasks: [{ ...input({ repeat: 'daily' }), task_id: 'a' }],
      ticks: [
        { task_id: 'a', day: '2026-10-15' },
        { task_id: 'a', day: '2026-10-16' },
      ],
    });
    assert.deepEqual(store.completions, { a: ['2026-10-15', '2026-10-16'] });
    assert.equal(tasksOn(store, '2026-10-16')[0].completed, true);
    assert.equal(tasksOn(store, '2026-10-17')[0].completed, false);
  });

  it('keeps the medicine tag and fills in what the API may leave out', () => {
    const store = storeFromList({
      tasks: [
        {
          task_id: 'a',
          title: 'Tablet',
          kind: 'medicine',
          start_date: '2026-10-15',
          time: '08:00',
        },
      ],
      ticks: [],
    });
    assert.deepEqual(store.schedules[0], {
      task_id: 'a',
      title: 'Tablet',
      kind: 'medicine',
      start_date: '2026-10-15',
      time: '08:00',
      repeat: 'none',
      repeat_until: null,
      notes: '',
    });
  });
});

describe('repeating tasks on the month grid', () => {
  type Row = { repeat: 'none' | 'daily' | 'weekly'; title: string };
  const daily: Row = { repeat: 'daily', title: 'Tablet' };
  const weekly: Row = { repeat: 'weekly', title: 'Shop' };
  const once: Row = { repeat: 'none', title: 'Call' };

  it('leaves out daily and weekly tasks, and days left with nothing', () => {
    assert.deepEqual(
      oneOffTasksByDay({ '2026-11-02': [daily, once], '2026-11-03': [weekly, daily] }),
      { '2026-11-02': [once] },
    );
  });

  it('keeps one-off tasks as they are', () => {
    assert.deepEqual(oneOffTasksByDay({ '2026-11-02': [once] }), { '2026-11-02': [once] });
    assert.equal(isRepeating(once), false);
    assert.equal(isRepeating(daily), true);
  });

  it('counts the repeating tasks left out of each day', () => {
    assert.deepEqual(
      repeatingCountByDay({
        '2026-11-02': [daily, once],
        '2026-11-03': [weekly, daily],
        '2026-11-04': [once],
      }),
      { '2026-11-02': 1, '2026-11-03': 2 },
    );
  });

  it('remembers "show them" only when it was saved as on', () => {
    assert.equal(parseShowRepeating('on'), true);
    assert.equal(parseShowRepeating('off'), false);
    assert.equal(parseShowRepeating(null), false);
    assert.equal(parseShowRepeating('true'), false);
  });
});
