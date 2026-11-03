import type { CatchUp } from '@silverloop/api-client';

import { writtenBy } from './agent';

/**
 * "Since you last visited" (see `components/home/CatchUpCard.vue`). Pure, so `node --test` can
 * check it: when the member last looked at a group, and how to say who wrote the catch-up.
 */

const KEY_PREFIX = 'careplus.lastVisit.v1.';

/** The storage key for one group's last visit; each group is caught up on separately. */
export function lastVisitKey(groupId: string): string {
  return `${KEY_PREFIX}${groupId}`;
}

/** A stored last visit, or null when there is none or it is not a real moment in the past. */
export function parseLastVisit(raw: string | null, now: Date): string | null {
  if (!raw) return null;
  const at = new Date(raw);
  if (Number.isNaN(at.getTime()) || at.getTime() > now.getTime()) return null;
  return at.toISOString();
}

/** The card's heading: a first visit has nothing to be "since". */
export function catchUpHeading(since: string | null): string {
  return since ? 'Since you last visited' : 'Where things stand';
}

/** Who put the catch-up together, said plainly. Never claims a model wrote a fallback, and never
 *  calls a replayed recording live. */
export function catchUpSource(catchUp: Pick<CatchUp, 'mode' | 'source'>): string {
  switch (writtenBy(catchUp)) {
    case 'live':
      return 'Written by the Care+ assistant from your family’s updates, then checked before showing.';
    case 'recorded':
      return 'Replayed from a recorded assistant run (not a live model), then checked before showing.';
    default:
      return 'Put together by Care+ from your family’s updates.';
  }
}

export { stepLabel } from './agent';
