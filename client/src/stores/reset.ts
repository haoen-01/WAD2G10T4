import { getActivePinia } from 'pinia';

import { useActivityStore } from '@/stores/activity';
import { useCalendarStore } from '@/stores/calendar';
import { useSessionStore } from '@/stores/session';

/**
 * Forgets everything the shared stores hold about whoever was signed in (who they are, the senior's
 * activity, the family calendar), so nothing of theirs is shown to the next person. Called on
 * signing out and when the session expires. Does nothing before Pinia is active.
 */
export function clearViewerStores(): void {
  if (!getActivePinia()) return;
  useSessionStore().clear();
  useActivityStore().reset();
  useCalendarStore().reset();
}
