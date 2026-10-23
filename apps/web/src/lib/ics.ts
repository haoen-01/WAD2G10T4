/**
 * Turning one appointment into something a family member can take away: a calendar file (`.ics`,
 * which every phone and email calendar opens) and a short plain-text message to paste into a chat.
 * Pure and free of Vue, so `lib/ics.test.ts` can run it under Node's type stripping. The browser
 * part (saving the file, the share sheet) lives in the details panel.
 */
import type { Appointment } from './family';
import { formatClockTime, formatIsoDay } from './format-date';

const CRLF = '\r\n';

/** RFC 5545 text: backslash, semicolon and comma escaped, line breaks as `\n`. */
export function escapeIcsText(value: string): string {
  return value
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r?\n/g, '\\n');
}

/** `2026-10-11` + `10:00` → `20261011T100000`, a Singapore wall-clock time. */
function localStamp(day: string, time: string): string {
  return `${day.replace(/-/g, '')}T${time.replace(':', '')}00`;
}

/** A moment in UTC, as iCalendar writes it: `20261010T024200Z`. */
function utcStamp(moment: Date): string {
  return moment
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}/, '');
}

/**
 * Lines longer than 75 octets are folded with a leading space (RFC 5545 §3.1). Counted in
 * characters, which is the same for the plain English this app writes.
 */
function fold(line: string): string {
  const parts: string[] = [];
  for (let index = 0; index < line.length; index += 74) parts.push(line.slice(index, index + 74));
  return parts.join(`${CRLF} `);
}

/**
 * A complete one-event calendar file. Times carry Singapore's zone, which has no daylight saving,
 * so its definition is a single fixed offset.
 */
export function appointmentToIcs(
  appointment: Appointment,
  elderName: string,
  helperNames: readonly string[],
  now: Date = new Date(),
): string {
  const helping = helperNames.length
    ? `Helping: ${helperNames.join(', ')}`
    : 'Nobody has said they will help yet.';
  const description = [appointment.notes, helping].filter(Boolean).join('\n\n');
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Care+//Family calendar//EN',
    'CALSCALE:GREGORIAN',
    'BEGIN:VTIMEZONE',
    'TZID:Asia/Singapore',
    'BEGIN:STANDARD',
    'DTSTART:19700101T000000',
    'TZOFFSETFROM:+0800',
    'TZOFFSETTO:+0800',
    'TZNAME:+08',
    'END:STANDARD',
    'END:VTIMEZONE',
    'BEGIN:VEVENT',
    `UID:${appointment.id}-${appointment.date}@silverloop.local`,
    `DTSTAMP:${utcStamp(now)}`,
    `DTSTART;TZID=Asia/Singapore:${localStamp(appointment.date, appointment.start)}`,
    `DTEND;TZID=Asia/Singapore:${localStamp(appointment.date, appointment.end)}`,
    `SUMMARY:${escapeIcsText(`${elderName}: ${appointment.title}`)}`,
    ...(appointment.location ? [`LOCATION:${escapeIcsText(appointment.location)}`] : []),
    `DESCRIPTION:${escapeIcsText(description)}`,
    'END:VEVENT',
    'END:VCALENDAR',
  ];
  return lines.map(fold).join(CRLF) + CRLF;
}

/** A tidy file name: `mdm-lim-doctor-s-appointment-2026-10-11.ics`. */
export function icsFileName(appointment: Appointment, elderName: string): string {
  const slug = `${elderName} ${appointment.title}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  return `${slug}-${appointment.date}.ics`;
}

/** A few lines for a family chat: what, when, where, and who is helping. */
export function shareText(
  appointment: Appointment,
  elderName: string,
  helperNames: readonly string[],
): string {
  const when = `${formatIsoDay(appointment.date)}, ${formatClockTime(appointment.start)} to ${formatClockTime(appointment.end)}`;
  return [
    `${elderName}: ${appointment.title}`,
    when,
    appointment.location,
    helperNames.length ? `Helping: ${helperNames.join(', ')}` : 'Still needs someone to help.',
    appointment.notes ? `Note: ${appointment.notes}` : undefined,
  ]
    .filter(Boolean)
    .join('\n');
}
