import type { DailyMetric, WearableStatus } from '@silverloop/api-client';
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  careTimeline,
  compareToUsual,
  easeInOutCubic,
  easeOutCubic,
  hoursLabel,
  median,
  nearestTurn,
  watchFrame,
  watchPoints,
  weekdayOf,
  wrapAngle,
} from './watch';

describe('full-screen watch framing', () => {
  it('keeps the case centred and contained at 375px', () => {
    for (const id of [
      'steps',
      'active',
      'sleep',
      'wear',
      'battery',
      'connection',
      'water',
    ] as const) {
      const frame = watchFrame(id, 375, 812);
      assert.equal(frame.x, 187.5);
      assert.equal(frame.y, 218);
      assert.ok(frame.scale * 260 < 375);
      assert.ok(frame.scale > 0);
    }
  });

  it('frames different desktop features individually and leaves room for details', () => {
    const screen = watchFrame('steps', 1440, 960);
    const crown = watchFrame('connection', 1440, 960);
    const sleep = watchFrame('sleep', 1440, 960);
    assert.ok(screen.x > 1440 * 0.65);
    assert.ok(crown.x > screen.x);
    assert.ok(crown.scale > screen.scale);
    assert.ok(sleep.y > screen.y);
  });

  it('adapts on resize rather than retaining desktop magnification on a phone', () => {
    assert.ok(watchFrame('wear', 1440, 960).scale > watchFrame('wear', 375, 812).scale);
    assert.ok(watchFrame('wear', 1440, 700).scale < watchFrame('wear', 1440, 960).scale);
    assert.ok(Number.isFinite(watchFrame('battery', 992, 600).scale));
  });
});

function day(index: number, overrides: Partial<DailyMetric> = {}): DailyMetric {
  return {
    day: `2026-08-${String(5 + index).padStart(2, '0')}`,
    steps: 5000,
    active_minutes: 30,
    sleep_hours: 7,
    wear_hours: 12,
    ...overrides,
  };
}

const watch: WearableStatus = {
  connected: true,
  last_synced_at: '2026-08-18T06:00:00Z',
  battery_percent: 81,
  charging: false,
  source: 'synthetic',
};

const points = (overrides: Partial<Parameters<typeof watchPoints>[0]> = {}) =>
  watchPoints({
    steps: 5720,
    usualSteps: 5747,
    metrics: Array.from({ length: 14 }, (_, index) => day(index)),
    wearable: watch,
    syncedAgo: '2 min ago',
    elder: 'Mdm Lim',
    ...overrides,
  });
const point = (id: string, list = points()) => list.find((item) => item.id === id)!;

describe('numbers in words', () => {
  it('takes the median of the finite values', () => {
    assert.equal(median([3, 1, 2]), 2);
    assert.equal(median([4, 1, 3, 2]), 2.5);
    assert.equal(median([]), null);
  });

  it('compares a day only with the senior’s own usual', () => {
    assert.equal(compareToUsual(5720, 5747), 'About the same as usual');
    assert.equal(compareToUsual(8000, 5000), 'More than usual');
    assert.equal(compareToUsual(2000, 5000), 'Less than usual');
    assert.equal(compareToUsual(2000, null), null);
  });

  it('writes hours as hours and minutes', () => {
    assert.equal(hoursLabel(7.4), '7 h 24 min');
    assert.equal(hoursLabel(8), '8 h');
    assert.equal(hoursLabel(0.5), '30 min');
  });

  it('names the weekday of a calendar day', () => {
    assert.equal(weekdayOf('2026-08-18'), 'Tue');
    assert.equal(weekdayOf('nonsense'), '');
  });
});

describe('watchPoints', () => {
  it('has the seven points, and never heart rate', () => {
    assert.deepEqual(
      points().map((item) => item.id),
      ['steps', 'active', 'sleep', 'wear', 'battery', 'connection', 'water'],
    );
    assert.equal(
      points().some((item) => /heart|bpm/i.test(JSON.stringify(item))),
      false,
    );
  });

  it('reads steps from today and compares them with the usual day', () => {
    const steps = point('steps');
    assert.equal(steps.value, '5,720 today');
    assert.equal(steps.note, 'About the same as usual');
    assert.equal(steps.bars.length, 14);
  });

  it('says when sleep was not recorded rather than inventing it', () => {
    const metrics = Array.from({ length: 14 }, (_, index) => day(index, { sleep_hours: null }));
    const sleep = point('sleep', points({ metrics }));
    assert.equal(sleep.value, 'Not recorded');
    assert.equal(sleep.bars.length, 0);
  });

  it('counts the days worn long enough, and draws the 8-hour line', () => {
    const metrics = [day(0, { wear_hours: 6 }), day(1), day(2, { wear_hours: 5 })];
    const wear = point('wear', points({ metrics }));
    assert.equal(wear.guide, 8);
    assert.equal(wear.note, 'Under 8 h, so the day is not counted');
    assert.equal(wear.facts[0].value, '1 of the last 3');
  });

  it('asks the family to remind the senior when the battery is low, not when charging', () => {
    const low = point('battery', points({ wearable: { ...watch, battery_percent: 12 } }));
    assert.equal(low.note, 'Remind Mdm Lim to charge it');
    const charging = point(
      'battery',
      points({ wearable: { ...watch, battery_percent: 12, charging: true } }),
    );
    assert.equal(charging.label, 'Charging');
    assert.equal(charging.note, 'Charging now');
  });

  it('labels the water resistance as example device information', () => {
    assert.equal(point('water').example, true);
  });

  it('copes with no data at all', () => {
    const empty = points({
      steps: null,
      usualSteps: null,
      metrics: [],
      wearable: null,
      syncedAgo: null,
    });
    assert.equal(point('steps', empty).value, 'Not available');
    assert.equal(point('connection', empty).value, 'Checking…');
  });
});

describe('careTimeline', () => {
  it('says how the watch is today, then the general tips', () => {
    assert.equal(careTimeline(watch)[0].what, 'All good');
    assert.equal(careTimeline({ ...watch, battery_percent: 10 })[0].what, 'Needs charging');
    assert.equal(careTimeline({ ...watch, connected: false })[0].what, 'Not connected');
    assert.equal(careTimeline(watch).length, 4);
  });
});

describe('turning', () => {
  it('eases from 0 to 1', () => {
    for (const ease of [easeOutCubic, easeInOutCubic]) {
      assert.equal(ease(0), 0);
      assert.equal(ease(1), 1);
      assert.equal(ease(2), 1);
    }
    assert.ok(easeOutCubic(0.5) > 0.5);
  });

  it('wraps angles and takes the short way round', () => {
    assert.equal(wrapAngle(190), -170);
    assert.equal(wrapAngle(-180), 180);
    assert.equal(nearestTurn(350, 10), 370);
    assert.equal(nearestTurn(10, 350), -10);
  });
});

describe('the battery view', () => {
  it('turns to the charger only when the watch is charging', () => {
    assert.equal(point('battery').view, 'front');
    assert.equal(point('battery', points({ wearable: { ...watch, charging: true } })).view, 'back');
  });

  it('does not claim battery health, a charging duration or a guaranteed runtime', () => {
    const battery = JSON.stringify(point('battery'));
    assert.doesNotMatch(battery, /battery health|time to full|lasts about a day|overnight/i);
    assert.match(battery, /General care tip/);
  });
});

describe('detail rows', () => {
  it('each row has a little more to say when it is opened', () => {
    for (const item of points()) {
      for (const fact of item.facts) assert.ok(fact.more, `${item.id}: ${fact.label}`);
    }
  });

  it('uses the mockup’s care steps after today', () => {
    assert.deepEqual(
      careTimeline(watch).map((step) => step.when),
      ['Today', '3 months', '6 months', '12 months'],
    );
  });
});
