<script setup lang="ts">
import type { CatchUp } from '@silverloop/api-client';
import { onMounted, ref, watch } from 'vue';

import BasePanel from '@/components/ui/BasePanel.vue';
import {
  catchUpHeading,
  catchUpSource,
  lastVisitKey,
  parseLastVisit,
  stepLabel,
} from '@/lib/catch-up';
import { getCatchUp } from '@/services/careApi';

/**
 * "Since you last visited": the catch-up agent's summary of what changed in the group since this
 * browser last opened Home for it. Extra detail: if it cannot be read, the card stays hidden and
 * the rest of Home is unaffected.
 */
const props = defineProps<{ groupId: string }>();

const catchUp = ref<CatchUp | null>(null);
const since = ref<string | null>(null);

function readSince(groupId: string): string | null {
  try {
    return parseLastVisit(window.localStorage.getItem(lastVisitKey(groupId)), new Date());
  } catch {
    return null; // Storage blocked: every visit reads as the first.
  }
}

function markVisited(groupId: string): void {
  try {
    window.localStorage.setItem(lastVisitKey(groupId), new Date().toISOString());
  } catch {
    // Storage blocked: nothing to remember.
  }
}

async function load(groupId: string): Promise<void> {
  catchUp.value = null;
  since.value = readSince(groupId);
  try {
    catchUp.value = await getCatchUp(groupId, since.value);
    markVisited(groupId);
  } catch {
    catchUp.value = null;
  }
}

onMounted(() => void load(props.groupId));
watch(
  () => props.groupId,
  (next) => void load(next),
);
</script>

<template>
  <BasePanel
    v-if="catchUp"
    :title="catchUpHeading(since)"
    heading-tag="h3"
    data-testid="catch-up"
    :data-mode="catchUp.mode"
  >
    <p class="mb-2">{{ catchUp.summary }}</p>
    <ul v-if="catchUp.highlights.length" class="mb-2 ps-3">
      <li v-for="line in catchUp.highlights" :key="line">{{ line }}</li>
    </ul>
    <p class="small text-body-secondary mb-0">{{ catchUpSource(catchUp) }}</p>
    <details v-if="catchUp.steps.length" class="small mt-2" data-testid="catch-up-steps">
      <summary>How Care+ wrote this</summary>
      <ol class="mb-0 mt-1 ps-3">
        <li v-for="(step, index) in catchUp.steps" :key="index">
          {{ stepLabel(step.tool_name) }}<span v-if="!step.ok"> (not accepted, tried again)</span>
        </li>
      </ol>
    </details>
  </BasePanel>
</template>
