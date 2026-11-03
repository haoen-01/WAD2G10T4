import type { AppointmentDraft } from '@silverloop/api-client';

import { writtenBy } from './agent';

/**
 * The "Describe it" box on the appointment form (see `components/calendar/AddAppointmentForm.vue`).
 * Pure, so `node --test` can check it: what to say under the form once it has been filled in.
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

function list(names: string[]): string {
  const words = names.map((name) => FIELD_WORDS[name] ?? name);
  if (words.length <= 1) return words.join('');
  return `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
}

/** Who filled in the form. Never claims a model did when a plain parser did, or that a replay was live. */
export function draftSource(draft: Pick<AppointmentDraft, 'mode' | 'source'>): string {
  switch (writtenBy(draft)) {
    case 'live':
      return 'Filled in by the Care+ assistant.';
    case 'recorded':
      return 'Filled in from a recorded assistant run (not a live model).';
    default:
      return 'Filled in by Care+ from the words it recognised.';
  }
}

/** The lines under the form: what to fill in, what was guessed, what it clashes with. */
export function draftNotes(
  draft: Pick<AppointmentDraft, 'missing' | 'assumed' | 'clashes'>,
): string[] {
  const notes: string[] = [];
  if (draft.missing.length) notes.push(`Still to fill in: ${list(draft.missing)}.`);
  if (draft.assumed.length) notes.push(`Guessed, so please check: ${list(draft.assumed)}.`);
  if (draft.clashes.length) notes.push(`At the same time as: ${draft.clashes.join(', ')}.`);
  notes.push('Nothing is saved until you press Add.');
  return notes;
}
