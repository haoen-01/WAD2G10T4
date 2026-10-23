import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import type { Appointment } from './family';
import { appointmentToIcs, escapeIcsText, icsFileName, shareText } from './ics';

const doctor: Appointment = {
  id: 'appt-doctor',
  title: 'Doctor’s appointment',
  kind: 'medical',
  date: '2026-10-11',
  start: '10:00',
  end: '12:00',
  location: 'Neighbourhood polyclinic',
  notes: 'Bring her NRIC; registration closes at 9:45 am, so aim to arrive by 9:30.',
};

describe('escapeIcsText', () => {
  it('escapes the characters iCalendar reserves', () => {
    assert.equal(escapeIcsText('a, b; c\\d\ne'), 'a\\, b\\; c\\\\d\\ne');
  });
});

describe('appointmentToIcs', () => {
  const ics = appointmentToIcs(doctor, 'Mdm Lim', ['Sarah'], new Date('2026-10-10T02:42:00Z'));
  const unfolded = ics.replace(/\r\n /g, '');

  it('is one event in Singapore time with CRLF line endings', () => {
    assert.ok(ics.startsWith('BEGIN:VCALENDAR\r\n'));
    assert.ok(ics.endsWith('END:VCALENDAR\r\n'));
    assert.match(unfolded, /DTSTART;TZID=Asia\/Singapore:20261011T100000\r\n/);
    assert.match(unfolded, /DTEND;TZID=Asia\/Singapore:20261011T120000\r\n/);
    assert.match(unfolded, /DTSTAMP:20261010T024200Z\r\n/);
    assert.match(unfolded, /TZOFFSETTO:\+0800/);
  });

  it('names the senior, the place and who is helping', () => {
    assert.match(unfolded, /SUMMARY:Mdm Lim: Doctor’s appointment/);
    assert.match(unfolded, /LOCATION:Neighbourhood polyclinic/);
    assert.match(unfolded, /Helping: Sarah/);
    assert.match(unfolded, /Bring her NRIC\\; registration closes at 9:45 am\\, so/);
  });

  it('folds long lines', () => {
    for (const line of ics.split('\r\n')) assert.ok(line.length <= 75, line);
  });

  it('says when nobody is helping yet', () => {
    assert.match(appointmentToIcs(doctor, 'Mdm Lim', []).replace(/\r\n /g, ''), /Nobody has said/);
  });
});

describe('icsFileName', () => {
  it('makes a readable, safe file name', () => {
    assert.equal(icsFileName(doctor, 'Mdm Lim'), 'mdm-lim-doctor-s-appointment-2026-10-11.ics');
  });
});

describe('shareText', () => {
  it('reads as a short chat message', () => {
    assert.equal(
      shareText({ ...doctor, notes: undefined }, 'Mdm Lim', []),
      [
        'Mdm Lim: Doctor’s appointment',
        'Sun, 11 Oct, 10:00 am to 12:00 pm',
        'Neighbourhood polyclinic',
        'Still needs someone to help.',
      ].join('\n'),
    );
  });

  it('includes helpers and the note', () => {
    const text = shareText(doctor, 'Mdm Lim', ['Sarah', 'John']);
    assert.match(text, /Helping: Sarah, John/);
    assert.match(text, /^Note: Bring her NRIC/m);
  });
});
