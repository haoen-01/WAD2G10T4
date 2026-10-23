import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  coverageOf,
  hasHelper,
  helperLoad,
  loadWarning,
  needingHelp,
  needsHelper,
  stillNeedsHelper,
  upcomingWithin,
} from './coverage';
import type { Appointment, Assignment, FamilyMember } from './family';

const appointment = (id: string, date: string): Appointment => ({
  id,
  title: id,
  kind: 'activity',
  date,
  start: '10:00',
  end: '11:00',
});

const appointments = [
  appointment('a', '2026-10-09'),
  appointment('b', '2026-10-10'),
  appointment('c', '2026-10-13'),
  appointment('d', '2026-10-20'),
];

const members: FamilyMember[] = [
  { id: 'sarah', name: 'Sarah', relationship: 'Daughter', colour: 0 },
  { id: 'john', name: 'John', relationship: 'Son', colour: 1 },
];

const assignments: Assignment[] = [
  { appointmentId: 'b', memberId: 'sarah' },
  { appointmentId: 'c', memberId: 'sarah' },
  { appointmentId: 'c', memberId: 'john' },
];

describe('upcomingWithin', () => {
  it('keeps today through the last day, inclusive', () => {
    assert.deepEqual(
      upcomingWithin(appointments, '2026-10-10', 3).map((a) => a.id),
      ['b', 'c'],
    );
  });
});

describe('needingHelp and hasHelper', () => {
  it('finds the appointments nobody has taken', () => {
    assert.equal(hasHelper(assignments, 'b'), true);
    assert.deepEqual(
      needingHelp(appointments, assignments).map((a) => a.id),
      ['a', 'd'],
    );
  });
});

describe('coverageOf', () => {
  it('counts covered appointments', () => {
    assert.deepEqual(coverageOf(appointments, assignments), { total: 4, covered: 2, ratio: 0.5 });
  });

  it('treats an empty list as fully covered', () => {
    assert.deepEqual(coverageOf([], assignments), { total: 0, covered: 0, ratio: 1 });
  });
});

describe('appointments that do not need a helper', () => {
  // `needsHelper: false` is how an appointment says nobody needs to go along.
  const alone = { ...appointment('e', '2026-10-21'), needsHelper: false } as Appointment;
  const all = [...appointments, alone];

  it('need a helper unless they say otherwise', () => {
    assert.equal(needsHelper(appointment('x', '2026-10-21')), true);
    assert.equal(needsHelper(alone), false);
  });

  it('never count as still needing someone', () => {
    assert.equal(stillNeedsHelper(assignments, alone), false);
    assert.equal(stillNeedsHelper(assignments, appointment('a', '2026-10-09')), true);
    assert.equal(stillNeedsHelper(assignments, appointment('b', '2026-10-10')), false);
    assert.deepEqual(
      needingHelp(all, assignments).map((a) => a.id),
      ['a', 'd'],
    );
  });

  it('are left out of the coverage count', () => {
    assert.deepEqual(coverageOf(all, assignments), { total: 4, covered: 2, ratio: 0.5 });
    assert.deepEqual(coverageOf([alone], assignments), { total: 0, covered: 0, ratio: 1 });
  });
});

describe('helperLoad', () => {
  it('counts each member’s appointments, busiest first', () => {
    const loads = helperLoad(members, assignments, appointments);
    assert.deepEqual(
      loads.map((load) => [load.member.name, load.count]),
      [
        ['Sarah', 2],
        ['John', 1],
      ],
    );
  });

  it('only counts the appointments it is given', () => {
    const loads = helperLoad(members, assignments, [appointments[1]]);
    assert.deepEqual(
      loads.map((load) => load.count),
      [1, 0],
    );
  });
});

describe('loadWarning', () => {
  it('stays quiet while the share is fair', () => {
    assert.equal(loadWarning(helperLoad(members, assignments, appointments)), null);
  });

  it('speaks up when one person has most of a busy schedule', () => {
    const heavy: Assignment[] = [
      { appointmentId: 'a', memberId: 'sarah' },
      { appointmentId: 'b', memberId: 'sarah' },
      { appointmentId: 'c', memberId: 'sarah' },
      { appointmentId: 'd', memberId: 'john' },
    ];
    assert.equal(
      loadWarning(helperLoad(members, heavy, appointments)),
      'Sarah is helping with 3 of 4. Could someone else take one?',
    );
  });
});
