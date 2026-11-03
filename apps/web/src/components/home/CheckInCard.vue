<script setup lang="ts">
import type { CheckInKind } from '@silverloop/api-client';
import { computed, nextTick, ref } from 'vue';

import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import { useFamilyActivity } from '@/composables/useFamilyActivity';
import { showToast } from '@/composables/useToast';
import { classifyApiError } from '@/lib/api-errors';

/**
 * "I was in touch": a family member tells the rest of the group they called, visited or messaged.
 * It only records that for the family. Care+ contacts nobody and sends nothing.
 */
const props = defineProps<{ elder: string; actor: { id: string; name: string } | null }>();

const NOTE_MAX = 200;
const KINDS: { kind: CheckInKind; label: string; icon: 'phone' | 'walk' | 'chat'; past: string }[] =
  [
    { kind: 'called', label: 'Called', icon: 'phone', past: 'called' },
    { kind: 'visited', label: 'Visited', icon: 'walk', past: 'visited' },
    { kind: 'messaged', label: 'Messaged', icon: 'chat', past: 'messaged' },
  ];

const feed = useFamilyActivity({ subscribe: false });
const note = ref('');
// The note is optional, so it waits behind "Add a note": the three choices come first.
const noteOpen = ref(false);
async function openNote() {
  noteOpen.value = true;
  await nextTick();
  document.getElementById('checkin-note')?.focus();
}
const busy = ref(false);
const left = computed(() => NOTE_MAX - note.value.length);

async function send(kind: CheckInKind, past: string) {
  if (!props.actor || busy.value) return;
  const words = note.value.trim();
  busy.value = true;
  try {
    await feed.checkIn(kind, words, props.actor);
    note.value = '';
    noteOpen.value = false;
    showToast(`Shared with the family: you ${past} ${props.elder}.`);
  } catch (caught) {
    // The entry was taken back out of the feed; the note stays so nothing has to be retyped.
    showToast(`Could not share that. ${classifyApiError(caught).message}`);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BasePanel id="home-checkin" title="Tell the family you were in touch" heading-tag="h3">
    <p class="sl-note">
      Let the others know you got in touch with {{ elder }}. This is only shared with your family
      group.
    </p>

    <p class="form-label mb-2" aria-hidden="true">How were you in touch?</p>
    <div class="checkin-row" role="group" aria-label="How you were in touch">
      <button
        v-for="item in KINDS"
        :key="item.kind"
        type="button"
        class="btn btn-outline-primary checkin-btn"
        :disabled="busy || !actor"
        :aria-describedby="actor ? undefined : 'checkin-hint'"
        @click="send(item.kind, item.past)"
      >
        <Icon :name="item.icon" class="checkin-icon" />
        <span>{{ item.label }}</span>
      </button>
    </div>

    <button
      v-if="!noteOpen"
      type="button"
      class="btn btn-link px-0 mt-2"
      :aria-expanded="noteOpen"
      aria-controls="checkin-note-box"
      data-testid="checkin-add-note"
      @click="openNote"
    >
      <Icon name="note" class="me-1" />Add a note first (optional)
    </button>
    <div v-else id="checkin-note-box" class="mt-3">
      <label class="form-label" for="checkin-note">Add a note (optional)</label>
      <textarea
        id="checkin-note"
        v-model="note"
        class="form-control"
        rows="2"
        :maxlength="NOTE_MAX"
        aria-describedby="checkin-note-left"
        placeholder="For example: she sounded cheerful"
      ></textarea>
      <p id="checkin-note-left" class="form-text mt-1 mb-0">
        {{ left }} characters left. Then choose how you were in touch above.
      </p>
    </div>

    <p v-if="!actor" id="checkin-hint" class="form-text mt-2 mb-0">
      Sharing is off until Care+ knows who you are. Pick your name under “Viewing as” on the
      Calendar, or join the family group first.
    </p>
  </BasePanel>
</template>

<style scoped>
/* Three across when they fit; at a large zoom or a narrow phone they wrap instead of overflowing. */
.checkin-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(5.5rem, 1fr));
  gap: 0.5rem;
}

/* Tall tiles, not pills: a pill's round ends crowd "Messaged" at phone width. */
.checkin-btn {
  border-radius: var(--sl-radius-sm);
  padding-inline: 0.35rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  min-width: 0;
  min-height: 4.5rem;
  font-weight: 700;
  transition:
    background-color var(--sl-dur-base) ease,
    color var(--sl-dur-base) ease,
    transform var(--sl-dur-press) var(--sl-ease-out);
}

.checkin-icon {
  font-size: 1.5rem;
}
</style>
