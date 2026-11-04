import type { AppointmentDraft, AppointmentKind, RepeatRule } from '@silverloop/api-client';

import { writtenBy } from './agent';

/**
 * The "Describe it" box on the appointment form (see `components/calendar/AddAppointmentForm.vue`).
 * Pure, so `node --test` can check it: how a draft fills in the form without overwriting what the
 * person typed themselves, what to say under the form, and what to say when filling in fails.
 */

const FIELD_WORDS: Record<string, string> = {
  title: 'what it is',
  kind: 'the category',
  date: 'the day',
  start: 'the start time',
  end: 'the end time',
  location: 'the place',
  repeat: 'how often it repeats',
};

function list(names: readonly string[]): string {
  const words = names.map((name) => FIELD_WORDS[name] ?? name);
  if (words.length <= 1) return words.join('');
  return `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
}

/** Appointment titles as they were typed, each with "the", joined with "and" ("the Physio and
 *  the Eye check-up"). */
function joinTitles(titles: readonly string[]): string {
  const named = titles.map((title) => `the ${title}`);
  if (named.length <= 1) return named.join('');
  return `${named.slice(0, -1).join(', ')} and ${named[named.length - 1]}`;
}

/** The form fields a draft can fill in. Notes are never filled in from a description. */
export interface DraftableFields {
  title: string;
  kind: AppointmentKind;
  date: string;
  start: string;
  end: string;
  location: string;
  repeat: RepeatRule;
}
export type DraftableField = keyof DraftableFields;

type DraftValues = Pick<
  AppointmentDraft,
  'title' | 'kind' | 'date' | 'start' | 'end' | 'location' | 'repeat'
>;

/**
 * The form after a draft: each field the description gave fills in, unless the person has typed
 * into that field themselves (`edited`) and it holds something different, which is kept. Fields
 * the description did not give are left as they are; nothing is invented. A repeat of `none` is
 * "not said", not an instruction to clear one.
 */
export function applyDraft(
  current: DraftableFields,
  draft: DraftValues,
  edited: ReadonlySet<DraftableField>,
): { next: DraftableFields; filled: DraftableField[]; kept: DraftableField[] } {
  const next: DraftableFields = { ...current };
  const filled: DraftableField[] = [];
  const kept: DraftableField[] = [];
  const offered: Partial<DraftableFields> = {
    title: draft.title ?? undefined,
    kind: draft.kind ?? undefined,
    date: draft.date ?? undefined,
    start: draft.start ?? undefined,
    end: draft.end ?? undefined,
    location: draft.location ?? undefined,
    repeat: draft.repeat !== 'none' ? draft.repeat : undefined,
  };
  for (const field of Object.keys(offered) as DraftableField[]) {
    const value = offered[field];
    if (value === undefined || value === '') continue;
    const mine = String(current[field] ?? '').trim();
    if (edited.has(field) && mine !== '' && mine !== value) {
      kept.push(field);
      continue;
    }
    (next as unknown as Record<DraftableField, string>)[field] = value;
    filled.push(field);
  }
  return { next, filled, kept };
}

/** Who filled in the form. Never claims a model did when a plain parser did, or that a replay was live. */
export function draftSource(draft: Pick<AppointmentDraft, 'mode' | 'source'>): string {
  switch (writtenBy(draft)) {
    case 'live':
      return 'Filled in by the Care+ assistant.';
    case 'recorded':
      return 'Filled in from a recorded assistant run (not a live model).';
    default:
      // Says the AI part was unavailable when it was, so a plainer result is not a mystery.
      return draft.mode === 'fallback_disabled'
        ? 'Filled in by Care+ from the words it recognised.'
        : 'AI filling-in was unavailable just now, so Care+ filled in the words it recognised.';
  }
}

/** The lines under the form: what was kept, what to fill in, what was guessed, what it clashes with. */
export function draftNotes(
  draft: Pick<AppointmentDraft, 'missing' | 'assumed' | 'clashes'>,
  kept: readonly string[] = [],
  filled: readonly string[] | null = null,
): string[] {
  const notes: string[] = [];
  if (filled !== null && filled.length === 0 && kept.length === 0) {
    notes.push('No details could be picked out of that. Please fill in the form below.');
  }
  if (kept.length) notes.push(`Kept what you had typed for ${list(kept)}.`);
  if (draft.missing.length) notes.push(`Still to fill in: ${list(draft.missing)}.`);
  if (draft.assumed.length) notes.push(`Guessed, so please check: ${list(draft.assumed)}.`);
  if (draft.clashes.length) notes.push(`Same time as ${joinTitles(draft.clashes)}.`);
  notes.push('Nothing is saved until you press Add.');
  return notes;
}

function statusOf(caught: unknown): number | null {
  if (caught && typeof caught === 'object' && 'status' in caught) {
    const status = (caught as { status: unknown }).status;
    if (typeof status === 'number') return status;
  }
  return null;
}

function messageOf(caught: unknown): string {
  return caught instanceof Error ? caught.message : String(caught ?? '');
}

/** Why "Fill in the form" failed, as a kind (for the log) and words (for the person). The form
 *  itself is untouched by any failure, and every message says how to carry on by hand. */
export function draftFailure(caught: unknown): {
  kind: 'timeout' | 'network' | 'session' | 'forbidden' | 'invalid' | 'server';
  message: string;
} {
  const status = statusOf(caught);
  const text = messageOf(caught).toLowerCase();
  if ((status === 0 || status === null) && /timeout|timed out|aborted/.test(text)) {
    return {
      kind: 'timeout',
      message:
        'Filling in took too long, so nothing was changed. Try again, or fill in the form below.',
    };
  }
  if (status === 0 || status === null) {
    return {
      kind: 'network',
      message:
        'Care+ could not be reached, so nothing was changed. Check the connection, or fill in the form below.',
    };
  }
  if (status === 401) {
    return { kind: 'session', message: 'Your session has ended. Please sign in again.' };
  }
  if (status === 403 || status === 404) {
    return {
      kind: 'forbidden',
      message: 'Only members of this family group can add appointments here.',
    };
  }
  if (status === 422) {
    return {
      kind: 'invalid',
      message:
        'Please describe it in a few words (up to 300 characters), or fill in the form below.',
    };
  }
  return {
    kind: 'server',
    message:
      'Care+ had a problem reading that, so nothing was changed. Please fill in the form below.',
  };
}
