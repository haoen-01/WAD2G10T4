/**
 * The rules for a day's family notes, apart from the screen: what may be posted, what a failed
 * request means, and whether a reply is still wanted. Pure, so `lib/appointment-notes.test.ts` runs
 * it under Node.
 */

export const NOTE_MAX_LENGTH = 500;
export const NOTES_FULL_MESSAGE =
  'This day already has as many notes as it can hold (100). Delete one to add another.';

/** A note as it will be sent: trimmed, 1 to 500 characters. `null` when it cannot be posted. */
export function cleanNote(text: string): string | null {
  const clean = text.trim();
  return clean.length >= 1 && clean.length <= NOTE_MAX_LENGTH ? clean : null;
}

/** The HTTP status a failed request carried, or `null` when it carried none. */
export function statusOf(caught: unknown): number | null {
  if (caught && typeof caught === 'object' && 'status' in caught) {
    const status = (caught as { status: unknown }).status;
    return typeof status === 'number' ? status : null;
  }
  return null;
}

/** A 409 on add means the day holds 100 notes already. */
export function isDayFull(caught: unknown): boolean {
  return statusOf(caught) === 409;
}

/**
 * What a failed delete means: `gone` (404: someone already deleted it, so just drop it from the
 * list), `forbidden` (403: not yours) or `other`.
 */
export function removeOutcome(caught: unknown): 'gone' | 'forbidden' | 'other' {
  const status = statusOf(caught);
  if (status === 404) return 'gone';
  if (status === 403) return 'forbidden';
  return 'other';
}

/** A reply belongs to the screen only if nothing was switched since its request began. */
export function isCurrent(requestGeneration: number, currentGeneration: number): boolean {
  return requestGeneration === currentGeneration;
}
