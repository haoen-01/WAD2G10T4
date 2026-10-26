import assert from 'node:assert/strict';
import test from 'node:test';
import {
  adjacentTab,
  readTab,
  saveTab,
  sevenDays,
  stepProgress,
  stepWords,
  sortSeniorTasks,
  nextSeniorTask,
  TAB_KEY,
} from '../components/senior/senior-view.js';
test('ring caps only the visual fill, preserves over-usual labels, and handles missing baselines', () => {
  assert.deepEqual(stepProgress(1200, 1000), { percent: 120, fill: 100 });
  assert.deepEqual(stepProgress(0, 1000), { percent: 0, fill: 0 });
  assert.deepEqual(stepProgress(100, 0), { percent: null, fill: 0 });
  assert.deepEqual(stepProgress(NaN, 1000), { percent: null, fill: 0 });
  assert.equal(stepWords(1000, 1000), 'About the same as usual');
  assert.equal(stepWords(1200, 1000), 'More than usual');
  assert.equal(stepWords(700, 1000), 'A bit less than usual');
});
test('tabs restore valid values and remain usable when storage fails', () => {
  assert.equal(readTab({ getItem: () => 'family' }), 'family');
  assert.equal(readTab({ getItem: () => 'unknown' }), 'today');
  assert.equal(readTab({ getItem: () => null }), 'today');
  assert.equal(
    readTab({
      getItem: () => {
        throw new Error();
      },
    }),
    'today',
  );
  const saved = [];
  saveTab(
    {
      setItem: (key, value) => {
        saved.push(key, value);
      },
    },
    'calendar',
  );
  assert.deepEqual(saved, [TAB_KEY, 'calendar']);
  assert.doesNotThrow(() =>
    saveTab(
      {
        setItem: () => {
          throw new Error();
        },
      },
      'family',
    ),
  );
});
test('arrow keys wrap tabs and Home and End reach the endpoints', () => {
  assert.equal(adjacentTab('family', 'ArrowRight'), 'today');
  assert.equal(adjacentTab('today', 'ArrowLeft'), 'family');
  assert.equal(adjacentTab('family', 'Home'), 'today');
  assert.equal(adjacentTab('today', 'End'), 'family');
  assert.equal(adjacentTab('today', 'Tab'), null);
});
test('seven-day strip anchors to latest data and preserves missing days', () => {
  const reading = { day: '2026-08-18', steps: 5720 };
  const days = sevenDays([reading], '2026-08-18');
  assert.equal(days.length, 7);
  assert.equal(days[0].day, '2026-08-12');
  assert.equal(days[0].reading, null);
  assert.equal(days[6].reading, reading);
});
const task = (id, time, completed = false) => ({
  task_id: id,
  title: id,
  time,
  completed,
  date: '2026-10-25',
  start_date: '2026-10-25',
  repeat: 'none',
  repeat_until: null,
  notes: '',
});
test('task sorting keeps completed tasks in time order without changing the shared source', () => {
  const tasks = [task('done', '08:00', true), task('later', '17:00'), task('earlier', '09:00')];
  assert.deepEqual(
    sortSeniorTasks(tasks).map((item) => item.task_id),
    ['done', 'earlier', 'later'],
  );
  assert.equal(tasks[0].task_id, 'done');
  assert.equal(nextSeniorTask(tasks, '10:00'), 'later');
  assert.equal(nextSeniorTask(tasks, '18:00'), null);
  assert.equal(nextSeniorTask([], '09:00'), null);
});

test('ticking and unticking a task leaves its position unchanged', () => {
  const tasks = [task('later', '17:00'), task('earlier', '09:00')];
  const before = sortSeniorTasks(tasks).map((item) => item.task_id);
  const ticked = tasks.map((item) => ({ ...item, completed: item.task_id === 'earlier' }));
  assert.deepEqual(
    sortSeniorTasks(ticked).map((item) => item.task_id),
    before,
  );
  assert.equal(nextSeniorTask(ticked, '08:00'), 'later');
  const unticked = ticked.map((item) => ({ ...item, completed: false }));
  assert.deepEqual(
    sortSeniorTasks(unticked).map((item) => item.task_id),
    before,
  );
  assert.equal(nextSeniorTask(unticked, '08:00'), 'earlier');
});
