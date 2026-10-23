import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import type { AvailabilityEntry, FamilyMember } from './family';
import {
  PAINT_SLOTS,
  freeMembers,
  heatFor,
  paintChanges,
  slotStatuses,
  windowsFromSlots,
} from './planner';
import type { SlotStatus } from './planner';

const DAY = '2026-10-17';
const entry = (over: Partial<AvailabilityEntry>): AvailabilityEntry => ({
  id: 'w1',
  memberId: 'sarah',
  date: DAY,
  start: '09:00',
  end: '12:00',
  status: 'available',
  ...over,
});
const member = (id: string): FamilyMember => ({
  id,
  name: id,
  relationship: 'Daughter',
  colour: 0,
});
/** Slots from 8 am, one per hour: F free, B busy, . nothing. */
const slots = (pattern: string): SlotStatus[] =>
  pattern
    .padEnd(PAINT_SLOTS.length, '.')
    .split('')
    .map((c) => (c === 'F' ? 'available' : c === 'B' ? 'unavailable' : null));

describe('the paint grid', () => {
  it('has an hour slot from 8 am to 9 pm', () => {
    assert.equal(PAINT_SLOTS.length, 13);
    assert.deepEqual(PAINT_SLOTS[0], { start: '08:00', end: '09:00', label: '8 am' });
    assert.equal(PAINT_SLOTS[4].label, '12 pm');
    assert.equal(PAINT_SLOTS.at(-1)?.end, '21:00');
  });

  it('shows saved windows as slots, busy beating free', () => {
    const saved = [
      entry({}),
      entry({ id: 'w2', start: '11:00', end: '13:00', status: 'unavailable' }),
      entry({ id: 'w3', memberId: 'john' }),
      entry({ id: 'w4', appointmentId: 'a1', start: '15:00', end: '16:00' }),
    ];
    assert.deepEqual(slotStatuses(saved, 'sarah', DAY), slots('.FFBB'));
  });

  it('shows an all-day window as every slot', () => {
    const saved = [entry({ start: '00:00', end: '23:59' })];
    assert.deepEqual(slotStatuses(saved, 'sarah', DAY), slots('FFFFFFFFFFFFF'));
  });
});

describe('painted slots into windows', () => {
  it('joins each run of the same status into one window', () => {
    assert.deepEqual(windowsFromSlots(DAY, slots('.FFB.F')), [
      { date: DAY, start: '09:00', end: '11:00', status: 'available' },
      { date: DAY, start: '11:00', end: '12:00', status: 'unavailable' },
      { date: DAY, start: '13:00', end: '14:00', status: 'available' },
    ]);
  });

  it('gives nothing for an empty day', () => {
    assert.deepEqual(windowsFromSlots(DAY, slots('')), []);
  });
});

describe('saving a painted day', () => {
  it('changes nothing when the painting matches what is saved', () => {
    const saved = [entry({})];
    assert.deepEqual(paintChanges(saved, 'sarah', DAY, slots('.FFF')), { remove: [], add: [] });
  });

  it("replaces only that person's windows on that day", () => {
    const saved = [
      entry({}),
      entry({ id: 'other', memberId: 'john' }),
      entry({ id: 'x', date: '2026-10-18' }),
    ];
    const change = paintChanges(saved, 'sarah', DAY, slots('FF'));
    assert.deepEqual(change.remove, ['w1']);
    assert.deepEqual(
      change.add.map((w) => [w.start, w.end, w.status]),
      [['08:00', '10:00', 'available']],
    );
  });

  it('removes everything when the day is erased', () => {
    const change = paintChanges([entry({})], 'sarah', DAY, slots(''));
    assert.deepEqual(change, { remove: ['w1'], add: [] });
  });
});

describe('who is free', () => {
  const members = [member('sarah'), member('john'), member('emily')];
  const saved = [
    entry({ memberId: 'sarah', start: '08:00', end: '12:00' }),
    entry({ id: 'j', memberId: 'john', start: '10:00', end: '11:00' }),
    entry({ id: 'e', memberId: 'emily', start: '08:00', end: '12:00', status: 'unavailable' }),
  ];

  it('counts only people free for the whole time', () => {
    assert.deepEqual(
      freeMembers(saved, members, DAY, '09:00', '11:00').map((m) => m.id),
      ['sarah'],
    );
    assert.deepEqual(
      freeMembers(saved, members, DAY, '10:00', '11:00').map((m) => m.id),
      ['sarah', 'john'],
    );
  });

  it('gives each day its own list', () => {
    const heat = heatFor(saved, members, [DAY, '2026-10-18'], '10:00', '11:00');
    assert.equal(heat[DAY].length, 2);
    assert.equal(heat['2026-10-18'].length, 0);
  });
});
