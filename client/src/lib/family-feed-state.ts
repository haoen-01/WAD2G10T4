import type { FamilyActivityEntry } from '@silverloop/api-client';

import { mergeActivity } from './family-feed';

/**
 * The feed's state changes as pure functions, so `useFamilyActivity` only does the I/O and the
 * tests can pin every transition. Relative imports only, for `node --test`.
 */

export const PENDING_PREFIX = 'pending-';

export const isPending = (entry: Pick<FamilyActivityEntry, 'activity_id'>): boolean =>
  entry.activity_id.startsWith(PENDING_PREFIX);

export interface FeedState {
  entries: FamilyActivityEntry[];
  /** The cursor for "Show more": `null` once the oldest entry is showing. */
  nextBefore: string | null;
  /** Whether a first page has been read, so `nextBefore` is real (a check-in can land earlier). */
  cursorKnown: boolean;
  /** A saved entry's id -> the render key it already had as an unsaved one, so its row stays put. */
  aliases: Record<string, string>;
}

export const emptyFeed = (): FeedState => ({
  entries: [],
  nextBefore: null,
  cursorKnown: false,
  aliases: {},
});

/** The row's key: stable from the moment a check-in is shown until it is saved. */
export function renderKey(entry: FamilyActivityEntry, aliases: Record<string, string>): string {
  return aliases[entry.activity_id] ?? entry.activity_id;
}

/** Whether an unsaved entry is the same check-in as a saved one (the poll beat the POST). */
function sameCheckIn(pending: FamilyActivityEntry, saved: FamilyActivityEntry): boolean {
  return (
    saved.kind === 'check_in' &&
    !isPending(saved) &&
    saved.actor_member_id === pending.actor_member_id &&
    saved.check_in_kind === pending.check_in_kind &&
    (saved.note ?? null) === (pending.note ?? null) &&
    Math.abs(new Date(saved.at).getTime() - new Date(pending.at).getTime()) < 120_000
  );
}

/**
 * Takes a freshly read first page into the feed.
 * - The first read takes the page and its cursor.
 * - A later read merges by `activity_id` and keeps the cursor.
 * - A gap: more than a page of entries arrived since the last read, so the page shares nothing with
 *   what is showing yet has older entries behind it. Merging would hide that gap behind a cursor
 *   that skips it, so the list restarts from this page and its cursor.
 * - An unsaved check-in that the page already holds as a saved entry is dropped, and the saved one
 *   keeps the unsaved one's render key.
 */
export function applyFirstPage(
  state: FeedState,
  page: { entries: readonly FamilyActivityEntry[]; next_before: string | null },
): FeedState {
  const saved = state.entries.filter((entry) => !isPending(entry));
  const pending = state.entries.filter(isPending);
  const known = new Set(saved.map((entry) => entry.activity_id));
  const gap =
    state.cursorKnown &&
    saved.length > 0 &&
    page.next_before !== null &&
    !page.entries.some((entry) => known.has(entry.activity_id));

  const aliases = gap ? {} : { ...state.aliases };
  const stillPending: FamilyActivityEntry[] = [];
  const claimed = new Set<string>();
  for (const waiting of pending) {
    // Only an entry the list does not hold yet can be this check-in's saved copy.
    const match = page.entries.find(
      (entry) =>
        !known.has(entry.activity_id) &&
        !claimed.has(entry.activity_id) &&
        sameCheckIn(waiting, entry),
    );
    if (match) {
      claimed.add(match.activity_id);
      aliases[match.activity_id] = aliases[waiting.activity_id] ?? waiting.activity_id;
    } else {
      stillPending.push(waiting);
    }
  }

  const base = gap ? [] : saved;
  return {
    entries: mergeActivity([...base, ...stillPending], page.entries),
    nextBefore: !state.cursorKnown || gap ? page.next_before : state.nextBefore,
    cursorKnown: true,
    aliases,
  };
}

/** Adds the older page that "Show more" read. */
export function applyOlderPage(
  state: FeedState,
  page: { entries: readonly FamilyActivityEntry[]; next_before: string | null },
): FeedState {
  return {
    ...state,
    entries: mergeActivity(state.entries, page.entries),
    nextBefore: page.next_before,
    cursorKnown: true,
  };
}

/** Shows a check-in at once, before the API has answered. */
export function addOptimistic(state: FeedState, temp: FamilyActivityEntry): FeedState {
  return { ...state, entries: mergeActivity(state.entries, [temp]) };
}

/** The API saved it: the saved entry takes the place (and render key) of the unsaved one. */
export function settleCheckIn(
  state: FeedState,
  tempId: string,
  saved: FamilyActivityEntry,
): FeedState {
  // Keep the row's key, unless another entry already wears it (then its own id is the safe key).
  const heldByOther = Object.entries(state.aliases).some(
    ([id, key]) => id !== saved.activity_id && key === tempId,
  );
  const key = state.aliases[saved.activity_id] ?? (heldByOther ? saved.activity_id : tempId);
  return {
    ...state,
    entries: mergeActivity(
      state.entries.filter((entry) => entry.activity_id !== tempId),
      [saved],
    ),
    aliases: { ...state.aliases, [saved.activity_id]: key },
  };
}

/** The API refused it: take the unsaved entry back out. */
export function rollbackCheckIn(state: FeedState, tempId: string): FeedState {
  return { ...state, entries: state.entries.filter((entry) => entry.activity_id !== tempId) };
}

/** A read or write that began for one group and person must not land in another's feed. */
export function isStale(startedFor: string | null, now: string | null): boolean {
  return startedFor !== now;
}
