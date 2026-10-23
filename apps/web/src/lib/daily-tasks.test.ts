import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { TASK_KIND_LABELS, sampleDailyTasks } from './daily-tasks';

describe('sampleDailyTasks', () => {
  it('gives every task a time, a label and a known kind', () => {
    const tasks = sampleDailyTasks();
    assert.ok(tasks.length > 0);
    for (const task of tasks) {
      assert.match(task.time, /^([01]\d|2[0-3]):[0-5]\d$/);
      assert.ok(task.label.length > 0);
      assert.ok(task.kind === 'medicine' || task.kind === 'task');
    }
  });

  it('sorts by time of day, earliest first', () => {
    const times = sampleDailyTasks().map((task) => task.time);
    assert.deepEqual(times, [...times].sort());
  });

  it('includes at least one medicine reminder', () => {
    assert.ok(sampleDailyTasks().some((task) => task.kind === 'medicine'));
  });

  it('names every kind in plain words', () => {
    assert.deepEqual(TASK_KIND_LABELS, { medicine: 'Medicine', task: 'To do' });
  });
});
