import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  DAY_PARTS,
  checkWindow,
  compareAppointments,
  dayPartOf,
  fromCalendar,
  describeWindow,
  helperIds,
  respondTo,
  statusBadge,
  statusFor,
  stepBackFrom,
  volunteerFor,
} from './family';
import type { Answers, Appointment, AvailabilityEntry } from './family';

const DOCTOR: Appointment = {
  id: 'doctor',
  title: 'Doctor’s appointment',
  kind: 'medical',
  date: '2026-09-22',
  start: '10:00',
  end: '12:00',
};

const NONE: Answers = { availability: [], assignments: [] };

const slot = (
  memberId: string,
  start: string,
  end: string,
  status: AvailabilityEntry['status'],
  date = DOCTOR.date,
): AvailabilityEntry => ({
  id: `${memberId}-${start}-${status}`,
  memberId,
  date,
  start,
  end,
  status,
});

describe('statusFor', () => {
  it('is unknown until the person says something', () => {
    assert.equal(statusFor([], 'sarah', DOCTOR), 'unknown');
  });

  it('counts a window that covers the whole appointment as available', () => {
    assert.equal(
      statusFor([slot('sarah', '00:00', '23:59', 'available')], 'sarah', DOCTOR),
      'available',
    );
    assert.equal(
      statusFor([slot('sarah', '10:00', '12:00', 'available')], 'sarah', DOCTOR),
      'available',
    );
  });

  it('does not count a window that covers only part of it: someone free at 10 cannot do until 12', () => {
    assert.equal(
      statusFor([slot('sarah', '08:00', '11:00', 'available')], 'sarah', DOCTOR),
      'unknown',
    );
  });

  it('counts any not-available window that shares time with it as unavailable', () => {
    assert.equal(
      statusFor([slot('emily', '11:30', '13:00', 'unavailable')], 'emily', DOCTOR),
      'unavailable',
    );
    assert.equal(
      statusFor([slot('emily', '00:00', '23:59', 'unavailable')], 'emily', DOCTOR),
      'unavailable',
    );
    // Ending exactly when it starts is not sharing time.
    assert.equal(
      statusFor([slot('emily', '08:00', '10:00', 'unavailable')], 'emily', DOCTOR),
      'unknown',
    );
  });

  it('lets not-available beat available when a person has said both', () => {
    const both = [
      slot('sarah', '00:00', '23:59', 'available'),
      slot('sarah', '11:00', '13:00', 'unavailable'),
    ];
    assert.equal(statusFor(both, 'sarah', DOCTOR), 'unavailable');
  });

  it('ignores other days and other people', () => {
    const others = [
      slot('sarah', '00:00', '23:59', 'available', '2026-09-23'),
      slot('john', '00:00', '23:59', 'available'),
    ];
    assert.equal(statusFor(others, 'sarah', DOCTOR), 'unknown');
  });

  it('puts a person’s own answer for the appointment above any window', () => {
    const answered = respondTo(NONE, DOCTOR, 'sarah', 'available', 'a1').availability;
    const busyAllDay = [...answered, slot('sarah', '00:00', '23:59', 'unavailable')];
    assert.equal(statusFor(busyAllDay, 'sarah', DOCTOR), 'available');
  });
});

describe('answering and volunteering', () => {
  it('replaces an earlier answer instead of adding a second one', () => {
    const first = respondTo(NONE, DOCTOR, 'sarah', 'available', 'a1');
    const second = respondTo(first, DOCTOR, 'sarah', 'unavailable', 'a2');
    assert.equal(second.availability.length, 1);
    assert.equal(statusFor(second.availability, 'sarah', DOCTOR), 'unavailable');
  });

  it('keeps one person’s answer from touching another’s', () => {
    const both = respondTo(
      respondTo(NONE, DOCTOR, 'sarah', 'available', 'a1'),
      DOCTOR,
      'emily',
      'unavailable',
      'a2',
    );
    assert.equal(statusFor(both.availability, 'sarah', DOCTOR), 'available');
    assert.equal(statusFor(both.availability, 'emily', DOCTOR), 'unavailable');
  });

  it('lets several people take the same appointment, in the order they volunteered', () => {
    const shared = volunteerFor(volunteerFor(NONE, DOCTOR, 'sarah', 'a1'), DOCTOR, 'john', 'a2');
    assert.deepEqual(helperIds(shared.assignments, DOCTOR.id), ['sarah', 'john']);
  });

  it('counts volunteering as being available, and never lists the same person twice', () => {
    const once = volunteerFor(NONE, DOCTOR, 'sarah', 'a1');
    const twice = volunteerFor(once, DOCTOR, 'sarah', 'a2');
    assert.deepEqual(helperIds(twice.assignments, DOCTOR.id), ['sarah']);
    assert.equal(twice.availability.length, 1);
    assert.equal(statusFor(twice.availability, 'sarah', DOCTOR), 'available');
  });

  it('takes a person off the appointment when they say they cannot make it', () => {
    const helping = volunteerFor(NONE, DOCTOR, 'sarah', 'a1');
    const changedMind = respondTo(helping, DOCTOR, 'sarah', 'unavailable', 'a2');
    assert.deepEqual(helperIds(changedMind.assignments, DOCTOR.id), []);
  });

  it('keeps a person on the appointment when they confirm they are available', () => {
    const helping = volunteerFor(NONE, DOCTOR, 'sarah', 'a1');
    const confirmed = respondTo(helping, DOCTOR, 'sarah', 'available', 'a2');
    assert.deepEqual(helperIds(confirmed.assignments, DOCTOR.id), ['sarah']);
  });

  it('lets a person step back without erasing that they were available', () => {
    const helping = volunteerFor(volunteerFor(NONE, DOCTOR, 'sarah', 'a1'), DOCTOR, 'john', 'a2');
    const assignments = stepBackFrom(helping.assignments, DOCTOR.id, 'sarah');
    assert.deepEqual(helperIds(assignments, DOCTOR.id), ['john']);
    assert.equal(statusFor(helping.availability, 'sarah', DOCTOR), 'available');
  });

  it('only changes the appointment it was asked about', () => {
    const other = { ...DOCTOR, id: 'other' };
    const helping = volunteerFor(NONE, DOCTOR, 'sarah', 'a1');
    assert.deepEqual(helperIds(helping.assignments, other.id), []);
    assert.deepEqual(stepBackFrom(helping.assignments, other.id, 'sarah'), helping.assignments);
  });
});

describe('checkWindow', () => {
  it('accepts a real day with a start before the end', () => {
    assert.equal(checkWindow({ date: '2026-09-25', start: '12:00', end: '17:00' }), null);
  });

  it('asks for what is missing or wrong', () => {
    assert.match(checkWindow({ date: '', start: '12:00', end: '17:00' }) ?? '', /date/);
    assert.match(checkWindow({ date: '2026-02-30', start: '12:00', end: '17:00' }) ?? '', /date/);
    assert.match(
      checkWindow({ date: '2026-09-25', start: '', end: '17:00' }) ?? '',
      /start and end/,
    );
    assert.match(checkWindow({ date: '2026-09-25', start: '17:00', end: '12:00' }) ?? '', /after/);
    assert.match(checkWindow({ date: '2026-09-25', start: '12:00', end: '12:00' }) ?? '', /after/);
  });
});

describe('day parts and badges', () => {
  it('names a window that is exactly a preset, and no other', () => {
    assert.equal(dayPartOf({ start: '08:00', end: '12:00' })?.short, 'Morning');
    assert.equal(dayPartOf({ start: '00:00', end: '23:59' })?.short, 'All day');
    assert.equal(dayPartOf({ start: '09:00', end: '12:00' }), null);
  });

  it('describes a window by its day part, or else by its times', () => {
    assert.equal(describeWindow({ start: '08:00', end: '12:00' }), 'Morning');
    assert.equal(describeWindow({ start: '09:00', end: '11:30' }), '9:00 am to 11:30 am');
  });

  it('offers presets that are each a valid window', () => {
    for (const part of DAY_PARTS) {
      assert.equal(
        checkWindow({ date: '2026-09-25', start: part.start, end: part.end }),
        null,
        part.key,
      );
    }
  });

  it('gives words to available and not available, and none to not having answered', () => {
    assert.equal(statusBadge('available')?.label, 'Available');
    assert.equal(statusBadge('unavailable')?.label, 'Not available');
    assert.equal(statusBadge('unknown'), null);
  });
});

describe('compareAppointments', () => {
  it('orders by day, then by start time, then by title', () => {
    const at = (date: string, start: string, title: string): Appointment => ({
      ...DOCTOR,
      date,
      start,
      title,
    });
    const sorted = [
      at('2026-09-23', '08:00', 'B'),
      at('2026-09-22', '15:00', 'B'),
      at('2026-09-22', '09:00', 'B'),
      at('2026-09-22', '09:00', 'A'),
    ].sort(compareAppointments);
    assert.deepEqual(
      sorted.map((a) => `${a.date} ${a.start} ${a.title}`),
      ['2026-09-22 09:00 A', '2026-09-22 09:00 B', '2026-09-22 15:00 B', '2026-09-23 08:00 B'],
    );
  });
});

describe('fromCalendar', () => {
  it('turns the API calendar into the screens’ shapes, with the signed-in member as the viewer', () => {
    const { appointments, state } = fromCalendar({
      person_id: 'p1',
      senior_name: 'Mdm Tan',
      group_id: 'g1',
      from_date: '2026-11-01',
      to_date: '2026-11-30',
      members: [
        {
          member_id: 'm1',
          display_name: 'Wei Ling',
          relationship: 'Daughter',
          colour: 0,
          is_me: false,
        },
        { member_id: 'm2', display_name: 'Jun', relationship: 'Son', colour: 1, is_me: true },
      ],
      appointments: [
        {
          occurrence_id: 'a1@2026-11-09',
          appointment_id: 'a1',
          title: 'Physio',
          kind: 'therapy',
          date: '2026-11-09',
          start: '14:00',
          end: '15:00',
          location: null,
          notes: 'Green folder',
          repeat: 'weekly',
        },
        {
          occurrence_id: 'a1@2026-11-02',
          appointment_id: 'a1',
          title: 'Physio',
          kind: 'therapy',
          date: '2026-11-02',
          start: '14:00',
          end: '15:00',
          location: null,
          notes: 'Green folder',
          repeat: 'weekly',
        },
      ],
      availability: [
        {
          entry_id: 'e1',
          member_id: 'm1',
          date: '2026-11-02',
          start: '14:00',
          end: '15:00',
          status: 'available',
          occurrence_id: 'a1@2026-11-02',
        },
        {
          entry_id: 'e2',
          member_id: 'm2',
          date: '2026-11-03',
          start: '09:00',
          end: '12:00',
          status: 'unavailable',
          occurrence_id: null,
        },
      ],
      assignments: [{ occurrence_id: 'a1@2026-11-02', member_id: 'm1' }],
    });

    assert.deepEqual(
      appointments.map((a) => a.id),
      ['a1@2026-11-02', 'a1@2026-11-09'],
    );
    assert.equal(appointments[0].seriesId, 'a1');
    assert.equal(appointments[0].location, undefined);
    assert.equal(state.currentMemberId, 'm2');
    assert.equal(state.availability[0].appointmentId, 'a1@2026-11-02');
    assert.equal('appointmentId' in state.availability[1], false);
    assert.deepEqual(helperIds(state.assignments, 'a1@2026-11-02'), ['m1']);
    assert.equal(statusFor(state.availability, 'm1', appointments[0]), 'available');
  });
});
