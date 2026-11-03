import type { MyDay } from '@silverloop/api-client';

import { writtenBy } from './agent';

/**
 * "Read my day" on the senior's screen (see `components/senior/ReadMyDay.vue`). Pure, so
 * `node --test` can check it.
 */

/** Who wrote the run-through, in words the senior reads under it. */
export function myDaySource(day: Pick<MyDay, 'mode' | 'source'>): string {
  switch (writtenBy(day)) {
    case 'live':
      return 'Written by the Care+ assistant from your calendar, then checked.';
    case 'recorded':
      return 'From a recorded assistant run, not a live one, then checked.';
    default:
      return 'Put together by Care+ from your calendar.';
  }
}

/** The main button's words: it speaks when the browser can, and only shows the words when not. */
export function readButtonLabel(canSpeak: boolean, reading: boolean): string {
  if (reading) return 'Stop reading';
  return canSpeak ? 'Read my day' : 'Show my day';
}
