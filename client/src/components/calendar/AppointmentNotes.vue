<script setup lang="ts">
import { computed, nextTick, ref } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import { NOTE_MAX_LENGTH, useAppointmentNotes } from '@/composables/useAppointmentNotes';
import type { FamilyMember } from '@/lib/family';
import type { AppointmentNote } from '@silverloop/api-client';
import { formatMomentTime } from '@/lib/format-date';

/**
 * The family's notes on one day of an appointment ("I'll bring the blue folder"), oldest first.
 * Anyone in the care group can add one and delete their own; the senior never sees them, and
 * nothing here contacts anyone. Not the appointment's own "Details" (what to bring), which the
 * person who booked it writes once.
 */
const props = defineProps<{
  groupId: string;
  /** The stored appointment (`seriesId`). */
  appointmentId: string;
  /** The day, `YYYY-MM-DD`. */
  date: string;
  members: FamilyMember[];
}>();

const { notes, loading, loadError, adding, addError, removing, removeError, load, add, remove } =
  useAppointmentNotes(() => ({
    groupId: props.groupId,
    appointmentId: props.appointmentId,
    date: props.date,
  }));

const draft = ref('');
const trimmed = computed(() => draft.value.trim());
const canAdd = computed(
  () => trimmed.value.length >= 1 && trimmed.value.length <= NOTE_MAX_LENGTH && !adding.value,
);
const colourOf = (memberId: string) => props.members.find((m) => m.id === memberId)?.colour ?? 0;

async function submit() {
  if (!canAdd.value) return;
  if (await add(draft.value)) {
    draft.value = '';
    await nextTick();
    document.getElementById('family-note-text')?.focus();
  }
}

// Delete asks first, in place: "Delete this note?" with Keep as the default.
const confirming = ref<string | null>(null);
async function askDelete(id: string) {
  confirming.value = id;
  await nextTick();
  document.getElementById(`note-keep-${id}`)?.focus();
}
async function keep(id: string) {
  confirming.value = null;
  await nextTick();
  document.getElementById(`note-delete-${id}`)?.focus();
}
async function confirmDelete(note: AppointmentNote) {
  confirming.value = null;
  await remove(note);
  await nextTick();
  // Gone: on to the box for the next note. Still there (it failed): back to its Delete, by the error.
  const gone = !notes.value.some((n) => n.note_id === note.note_id);
  document.getElementById(gone ? 'family-note-text' : `note-delete-${note.note_id}`)?.focus();
}

// The phone's keyboard must not hide the box being typed in.
function keepInView(event: FocusEvent) {
  (event.target as HTMLElement).scrollIntoView({ block: 'nearest' });
}

const snippet = (text: string) => (text.length > 40 ? `${text.slice(0, 40)}…` : text);
</script>

<template>
  <section class="notes" aria-labelledby="family-notes-heading" data-testid="family-notes">
    <h3 id="family-notes-heading" class="h5 mb-1">Family notes</h3>
    <p class="sl-note mb-3">
      For this day only. Only your family group can read them; the person you care for does not see
      them.
    </p>

    <p v-if="loading" class="sl-note mb-0" role="status">Loading notes…</p>
    <div
      v-else-if="loadError"
      class="alert alert-danger d-flex flex-wrap align-items-center gap-2"
      role="alert"
    >
      <span class="me-auto">{{ loadError }}</span>
      <button type="button" class="btn btn-sm btn-outline-danger" @click="load()">Try again</button>
    </div>
    <template v-else>
      <p v-if="notes.length === 0" class="empty">No notes for this day yet.</p>
      <!-- Plain blocks, not a list: the people's rows above are the page's only list items. -->
      <div v-else class="note-list">
        <div v-for="note in notes" :key="note.note_id" class="note" data-testid="family-note">
          <MemberAvatar :name="note.author_name" :colour="colourOf(note.member_id)" size="sm" />
          <div class="note-body">
            <p class="note-meta">
              <strong>{{ note.is_mine ? 'You' : note.author_name }}</strong>
              <span>{{ formatMomentTime(note.created_at) }}</span>
            </p>
            <p class="note-text">{{ note.text }}</p>
          </div>
          <div v-if="note.is_mine" class="note-actions">
            <template v-if="confirming === note.note_id">
              <span class="note-ask" role="group" :aria-label="`Delete this note?`">
                <span>Delete this note?</span>
                <button
                  type="button"
                  class="btn btn-link text-danger fw-semibold"
                  aria-label="Yes, delete this note"
                  :disabled="removing.has(note.note_id)"
                  @click="confirmDelete(note)"
                >
                  Delete
                </button>
                <button
                  :id="`note-keep-${note.note_id}`"
                  type="button"
                  class="btn btn-link"
                  @click="keep(note.note_id)"
                >
                  Keep
                </button>
              </span>
            </template>
            <button
              v-else
              :id="`note-delete-${note.note_id}`"
              type="button"
              class="btn btn-link text-body-secondary"
              :aria-label="`Delete your note: ${snippet(note.text)}`"
              :disabled="removing.has(note.note_id)"
              @click="askDelete(note.note_id)"
            >
              Delete
            </button>
          </div>
        </div>
      </div>
      <p v-if="removeError" class="text-danger mt-2 mb-0" role="alert">{{ removeError }}</p>

      <form class="mt-3" @submit.prevent="submit">
        <label for="family-note-text" class="form-label fw-semibold">Add a note</label>
        <textarea
          id="family-note-text"
          v-model="draft"
          class="form-control"
          rows="2"
          :maxlength="NOTE_MAX_LENGTH"
          :readonly="adding"
          :aria-busy="adding"
          aria-describedby="family-note-count"
          @focus="keepInView"
        ></textarea>
        <div class="d-flex align-items-center justify-content-between gap-2 mt-2">
          <span id="family-note-count" class="sl-note tabular"
            >{{ draft.length }} / {{ NOTE_MAX_LENGTH }}</span
          >
          <button type="submit" class="btn btn-primary" :disabled="!canAdd">
            {{ adding ? 'Adding…' : 'Add note' }}
          </button>
        </div>
        <p v-if="addError" class="text-danger mt-2 mb-0" role="alert">{{ addError }}</p>
      </form>
    </template>
  </section>
</template>

<style scoped>
.empty {
  margin: 0;
  padding: 0.85rem 1rem;
  border: 2px dashed var(--sl-line);
  border-radius: var(--sl-radius-sm);
  color: var(--sl-ink-soft);
}

.note-list {
  display: grid;
  gap: 0.6rem;
}

.note {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 0.6rem;
  align-items: start;
  padding: 0.65rem 0.75rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
}

.note-body {
  min-width: 0;
}

.note-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.1rem 0.6rem;
  margin: 0;
  font-size: 0.9rem;
}

.note-meta span {
  color: var(--sl-ink-soft);
}

.note-text {
  margin: 0.15rem 0 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.note-actions {
  grid-column: 2;
  justify-self: end;
  margin-top: -0.4rem;
}

.note-actions .btn {
  min-width: 2.75rem;
  min-height: 2.75rem;
  padding-block: 0;
}

.note-ask {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  font-size: 0.9rem;
}

#family-note-text {
  scroll-margin-bottom: 6rem;
}
</style>
