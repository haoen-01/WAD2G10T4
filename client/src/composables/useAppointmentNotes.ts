import type { AppointmentNote } from '@silverloop/api-client';
import { computed, onScopeDispose, ref, watch } from 'vue';

import { classifyApiError } from '@/lib/api-errors';
import {
  NOTES_FULL_MESSAGE,
  cleanNote,
  isCurrent,
  isDayFull,
  removeOutcome,
} from '@/lib/appointment-notes';
import * as api from '@/services/careApi';

export { NOTE_MAX_LENGTH } from '@/lib/appointment-notes';

interface Target {
  groupId: string | null;
  /** The stored appointment (`seriesId`), not one day of it. */
  appointmentId: string | null | undefined;
  /** The day, `YYYY-MM-DD`. */
  date: string;
}

/**
 * The family notes on one day of an appointment. One instance per open sheet or panel (not a
 * singleton): it starts over whenever the group, appointment or day it is given changes, and a
 * reply that arrives after that is dropped, so a slow answer for yesterday's appointment never
 * lands under today's.
 */
export function useAppointmentNotes(target: () => Target) {
  const notes = ref<AppointmentNote[]>([]);
  const loading = ref(false);
  const loadError = ref<string | null>(null);
  const adding = ref(false);
  const addError = ref<string | null>(null);
  const removing = ref<ReadonlySet<string>>(new Set());
  const removeError = ref<string | null>(null);

  const key = computed(() => {
    const { groupId, appointmentId, date } = target();
    return groupId && appointmentId ? `${groupId}|${appointmentId}|${date}` : null;
  });
  // Bumped on every change of `key` and on unmount: an older request checks it before it writes.
  let generation = 0;

  async function load() {
    const current = target();
    const mine = ++generation;
    notes.value = [];
    loadError.value = null;
    addError.value = null;
    removeError.value = null;
    removing.value = new Set();
    adding.value = false;
    if (!key.value || !current.groupId || !current.appointmentId) {
      loading.value = false;
      return;
    }
    loading.value = true;
    try {
      const found = await api.getAppointmentNotes(
        current.groupId,
        current.appointmentId,
        current.date,
      );
      if (isCurrent(mine, generation)) notes.value = found;
    } catch (caught) {
      if (isCurrent(mine, generation)) loadError.value = classifyApiError(caught).message;
    } finally {
      if (isCurrent(mine, generation)) loading.value = false;
    }
  }

  async function add(text: string): Promise<boolean> {
    const current = target();
    const clean = cleanNote(text);
    if (!key.value || !current.groupId || !current.appointmentId || adding.value) return false;
    if (clean === null) return false;
    const mine = generation;
    adding.value = true;
    addError.value = null;
    try {
      const created = await api.addAppointmentNote(current.groupId, current.appointmentId, {
        date: current.date,
        text: clean,
      });
      if (!isCurrent(mine, generation)) return false;
      notes.value = [...notes.value, created];
      return true;
    } catch (caught) {
      if (isCurrent(mine, generation)) {
        addError.value = isDayFull(caught) ? NOTES_FULL_MESSAGE : classifyApiError(caught).message;
      }
      return false;
    } finally {
      if (isCurrent(mine, generation)) adding.value = false;
    }
  }

  async function remove(note: AppointmentNote): Promise<void> {
    const current = target();
    if (!key.value || !current.groupId || removing.value.has(note.note_id)) return;
    const mine = generation;
    removing.value = new Set(removing.value).add(note.note_id);
    removeError.value = null;
    try {
      await api.deleteAppointmentNote(current.groupId, note.note_id);
      if (isCurrent(mine, generation))
        notes.value = notes.value.filter((n) => n.note_id !== note.note_id);
    } catch (caught) {
      if (isCurrent(mine, generation)) {
        // Already deleted elsewhere: it is gone either way, so drop it rather than stick an error.
        if (removeOutcome(caught) === 'gone') {
          notes.value = notes.value.filter((n) => n.note_id !== note.note_id);
        } else {
          removeError.value = classifyApiError(caught).message;
        }
      }
    } finally {
      if (isCurrent(mine, generation)) {
        const next = new Set(removing.value);
        next.delete(note.note_id);
        removing.value = next;
      }
    }
  }

  watch(key, () => void load(), { immediate: true });
  onScopeDispose(() => {
    generation += 1;
  });

  return { notes, loading, loadError, adding, addError, removing, removeError, load, add, remove };
}
