import type { FamilyActivityEntry } from '@silverloop/api-client';

import { formatIsoDay, formatMomentDay } from './format-date';

/**
 * The family feed in words. The API sends structured fields only; this file writes the sentences,
 * so the wording lives in one tested place. Pure and relative-import only, for `node --test`.
 *
 * Nothing here says Care+ contacted anyone: a check-in is a family member telling the group they
 * were in touch. And how long ago the last check-in was is never framed as a warning.
 */

export type FeedIcon =
  'phone' | 'walk' | 'chat' | 'calendar' | 'users' | 'check' | 'note' | 'clock';

export interface FeedLine {
  /** "You" or the member's name. */
  actor: string;
  /** The rest of the sentence, so the whole line reads `${actor} ${rest}`. */
  rest: string;
  /** A check-in's or note's own words, shown quoted under the sentence. */
  note: string | null;
  icon: FeedIcon;
}

export interface FeedOptions {
  /** What the group calls the senior, for "called Mdm Lim". */
  elder?: string;
}

const CHECK_IN_VERB = { called: 'called', visited: 'visited', messaged: 'messaged' } as const;
const CHECK_IN_ICON = { called: 'phone', visited: 'walk', messaged: 'chat' } as const;

export function actorOf(entry: Pick<FamilyActivityEntry, 'is_me' | 'actor_name'>): string {
  return entry.is_me ? 'You' : entry.actor_name || 'A family member';
}

function when(entry: FamilyActivityEntry): string | null {
  return entry.on_date ? formatIsoDay(entry.on_date) : null;
}

/** "Physio on Tue, 28 Oct", or "Physio" for a whole repeating series (no day). */
function titled(entry: FamilyActivityEntry, joiner: 'on' | 'for' = 'on'): string {
  const title = entry.appointment_title || 'an appointment';
  const day = when(entry);
  return day ? `${title} ${joiner} ${day}` : title;
}

/** The feed line for one entry. An unknown kind gets a generic line, never an error. */
export function feedLine(entry: FamilyActivityEntry, options: FeedOptions = {}): FeedLine {
  const actor = actorOf(entry);
  const elder = options.elder || 'your senior';
  const line = (rest: string, icon: FeedIcon, note: string | null = null): FeedLine => ({
    actor,
    rest,
    note,
    icon,
  });
  const day = when(entry);
  const note = entry.note?.trim() ? entry.note.trim() : null;

  switch (entry.kind) {
    case 'group_created':
      return line(`started the care group for ${elder}`, 'users');
    case 'member_approved':
      return line(`let ${entry.subject_name || 'a new member'} into the group`, 'users');
    case 'member_declined':
      // Defensive: the API never sends a subject name for declines.
      return line(
        entry.subject_name
          ? `declined ${entry.subject_name}’s request to join`
          : 'declined a request to join',
        'users',
      );
    case 'appointment_added':
      return line(
        entry.on_date
          ? `added ${titled(entry)}`
          : `added ${entry.appointment_title || 'an appointment'} (repeating)`,
        'calendar',
      );
    case 'appointment_changed':
      return line(
        entry.on_date
          ? `changed ${titled(entry)}`
          : `changed ${entry.appointment_title || 'an appointment'} (every day it repeats)`,
        'calendar',
      );
    case 'appointment_removed':
      return line(
        entry.on_date
          ? `removed ${titled(entry)}`
          : `removed ${entry.appointment_title || 'an appointment'} (every day it repeats)`,
        'calendar',
      );
    case 'helper_joined':
      return line(
        entry.on_date
          ? `took ${titled(entry)}`
          : `took ${entry.appointment_title || 'an appointment'} every time`,
        'check',
      );
    case 'helper_stepped_back':
      return line(
        entry.on_date
          ? `stepped back from ${titled(entry)}`
          : `stepped back from ${entry.appointment_title || 'an appointment'} (every time)`,
        'check',
      );
    case 'availability_updated':
      return line(day ? `updated free times for ${day}` : 'updated free times', 'clock');
    case 'check_in': {
      const kind = entry.check_in_kind;
      if (!kind || !(kind in CHECK_IN_VERB)) return line(`checked in with ${elder}`, 'phone', note);
      return line(`${CHECK_IN_VERB[kind]} ${elder}`, CHECK_IN_ICON[kind], note);
    }
    case 'note_added':
      return line(
        entry.appointment_title ? `added a note on ${titled(entry)}` : 'added a note',
        'note',
        note,
      );
    default:
      return line('updated the group', 'users', note);
  }
}

/** The whole line as one string (for tests and screen-reader text). */
export function feedSentence(entry: FamilyActivityEntry, options: FeedOptions = {}): string {
  const { actor, rest, note } = feedLine(entry, options);
  return note ? `${actor} ${rest}: “${note}”` : `${actor} ${rest}`;
}

/** Where an entry's day lives on the calendar, or `null` when that day no longer exists. */
export function feedLink(entry: FamilyActivityEntry): string | null {
  return entry.occurrence_id
    ? `/calendar?appointment=${encodeURIComponent(entry.occurrence_id)}`
    : null;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "just now", "5 min ago", "3 h ago", "Yesterday", "3 days ago", then "Thu, 20 Aug". */
export function relativeTime(at: string, now: Date): string {
  const then = new Date(at).getTime();
  if (Number.isNaN(then)) return '';
  const diff = now.getTime() - then;
  if (diff < MINUTE) return 'just now'; // includes a clock a little ahead of the server's
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)} min ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)} h ago`;
  if (diff < 2 * DAY) return 'Yesterday';
  if (diff < 7 * DAY) return `${Math.floor(diff / DAY)} days ago`;
  return formatMomentDay(at, { fallback: '' });
}

/**
 * Merges a freshly read page into what is shown, by `activity_id` (entries never change, so the
 * incoming copy simply wins). Newest first, ties broken by id, as the API orders them.
 */
export function mergeActivity(
  current: readonly FamilyActivityEntry[],
  incoming: readonly FamilyActivityEntry[],
): FamilyActivityEntry[] {
  const byId = new Map<string, FamilyActivityEntry>();
  for (const entry of current) byId.set(entry.activity_id, entry);
  for (const entry of incoming) byId.set(entry.activity_id, entry);
  return [...byId.values()].sort((a, b) => {
    const diff = new Date(b.at).getTime() - new Date(a.at).getTime();
    if (diff !== 0) return diff;
    return a.activity_id < b.activity_id ? 1 : a.activity_id > b.activity_id ? -1 : 0;
  });
}

/** How soon a step back counts as undoing "I'll go" rather than real news for the family. */
export const UNDO_WINDOW_MS = 5 * 60_000;

/**
 * The feed without "I'll go" moments that were undone: when a member takes an appointment and
 * steps back from the same day within `UNDO_WINDOW_MS`, both lines are left out, so nobody reads
 * that they are going when they are not. A step back later than that stays, because the family
 * needs to know the appointment needs someone again. Every viewer gets the same filtered list.
 */
export function withoutUndone(entries: readonly FamilyActivityEntry[]): FamilyActivityEntry[] {
  const sameDay = (a: FamilyActivityEntry, b: FamilyActivityEntry) =>
    a.actor_member_id === b.actor_member_id &&
    a.appointment_id === b.appointment_id &&
    a.on_date === b.on_date;
  const oldestFirst = [...entries].sort(
    (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime(),
  );
  const hidden = new Set<string>();
  for (const back of oldestFirst) {
    if (back.kind !== 'helper_stepped_back') continue;
    const backAt = new Date(back.at).getTime();
    // The latest "took" before this step back that is not already paired with one.
    const joined = oldestFirst
      .filter(
        (entry) =>
          entry.kind === 'helper_joined' &&
          !hidden.has(entry.activity_id) &&
          sameDay(entry, back) &&
          new Date(entry.at).getTime() <= backAt,
      )
      .pop();
    if (joined && backAt - new Date(joined.at).getTime() <= UNDO_WINDOW_MS) {
      hidden.add(joined.activity_id);
      hidden.add(back.activity_id);
    }
  }
  return entries.filter((entry) => !hidden.has(entry.activity_id));
}
