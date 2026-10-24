<script setup lang="ts">
import type { CheckInKind } from '@silverloop/api-client';
import { computed, ref } from 'vue';

import PressScale from '@/components/motion/PressScale.vue';
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
const busy = ref(false);
const left = computed(() => NOTE_MAX - note.value.length);

async function send(kind: CheckInKind, past: string) {
  if (!props.actor || busy.value) return;
  const words = note.value.trim();
  busy.value = true;
  try {
    await feed.checkIn(kind, words, props.actor);
    note.value = '';
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
  <BasePanel id="home-checkin" title="Tell the family you were in touch">
    <p class="sl-note">
      Let the others know you got in touch with {{ elder }}. This is only shared with your family
      group.
    </p>

    <div class="row g-2 mb-3" role="group" aria-label="How you were in touch">
      <div v-for="item in KINDS" :key="item.kind" class="col-4">
        <PressScale>
          <button
            type="button"
            class="btn btn-outline-primary checkin-btn w-100"
            :disabled="busy || !actor"
            @click="send(item.kind, item.past)"
          >
            <Icon :name="item.icon" class="checkin-icon" />
            <span>{{ item.label }}</span>
          </button>
        </PressScale>
      </div>
    </div>

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
    <p id="checkin-note-left" class="form-text mb-0">{{ left }} characters left</p>
  </BasePanel>
</template>

<style scoped>
.checkin-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  min-height: 4.5rem;
  font-weight: 700;
}

.checkin-icon {
  font-size: 1.5rem;
}
</style>
