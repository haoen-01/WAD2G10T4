<script setup lang="ts">
import type { CatchUp } from '@silverloop/api-client';
import { onMounted, ref, watch } from 'vue';

import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import {
  catchUpHeading,
  catchUpSource,
  lastVisitKey,
  parseLastVisit,
  stepLabel,
} from '@/lib/catch-up';
import { viewerKey } from '@/composables/useMe';
import { getCatchUp } from '@/services/careApi';

/**
 * "Since you last visited": what changed in the family group since this person last opened Home for
 * it on this browser (on a first visit, "Where things stand"). The heading follows the `since` the
 * API answered for, so it always agrees with the summary under it. Extra detail: while it is being put together a
 * quiet placeholder holds its place; if it cannot be read, the card stays hidden and the rest of
 * Home is unaffected.
 */
const props = defineProps<{ groupId: string }>();

const catchUp = ref<CatchUp | null>(null);
const loading = ref(true);

function readSince(groupId: string): string | null {
  try {
    return parseLastVisit(
      window.localStorage.getItem(lastVisitKey(viewerKey(), groupId)),
      new Date(),
    );
  } catch {
    return null; // Storage blocked: every visit reads as the first.
  }
}

function markVisited(groupId: string): void {
  try {
    window.localStorage.setItem(lastVisitKey(viewerKey(), groupId), new Date().toISOString());
  } catch {
    // Storage blocked: nothing to remember.
  }
}

async function load(groupId: string): Promise<void> {
  catchUp.value = null;
  loading.value = true;
  const since = readSince(groupId);
  try {
    const result = await getCatchUp(groupId, since);
    // Another group was picked while this one was read: its catch-up is not for this card.
    if (groupId !== props.groupId) return;
    catchUp.value = result;
    markVisited(groupId);
  } catch {
    if (groupId === props.groupId) catchUp.value = null;
  } finally {
    if (groupId === props.groupId) loading.value = false;
  }
}

onMounted(() => void load(props.groupId));
watch(
  () => props.groupId,
  (next) => void load(next),
);
</script>

<template>
  <div v-if="loading" class="sl-panel catch-up-wait" aria-hidden="true">
    <span class="wait-line wait-heading"></span>
    <span class="wait-line"></span>
    <span class="wait-line wait-short"></span>
  </div>
  <BasePanel
    v-else-if="catchUp"
    class="catch-up"
    heading-class="h5 d-flex align-items-center gap-2 mb-2"
    data-testid="catch-up"
    :data-mode="catchUp.mode"
  >
    <template #title>
      <span class="sl-icon-chip" aria-hidden="true"><Icon name="sparkle" /></span
      >{{ catchUpHeading(catchUp.since) }}
    </template>
    <p class="summary mb-2">{{ catchUp.summary }}</p>
    <ul v-if="catchUp.highlights.length" class="highlights mb-2">
      <li v-for="line in catchUp.highlights" :key="line">
        <Icon name="arrow-right" class="highlight-mark" />{{ line }}
      </li>
    </ul>
    <p class="sl-note mb-0">{{ catchUpSource(catchUp) }}</p>
    <details v-if="catchUp.steps.length" class="steps small mt-1" data-testid="catch-up-steps">
      <summary>How Care+ wrote this</summary>
      <ol class="mb-0 mt-1 ps-3">
        <li v-for="(step, index) in catchUp.steps" :key="index">
          {{ stepLabel(step.tool_name) }}<span v-if="!step.ok"> (not accepted, tried again)</span>
        </li>
      </ol>
    </details>
  </BasePanel>
</template>

<style scoped>
.summary {
  max-width: 48rem;
  font-size: 1.1rem;
  line-height: 1.5;
}

.highlights {
  display: grid;
  gap: 0.35rem;
  max-width: 48rem;
  padding: 0;
  list-style: none;
}

.highlights li {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}

.highlight-mark {
  flex: none;
  width: 1rem;
  height: 1rem;
  color: var(--sl-jade-deep);
  transform: translateY(0.15rem);
}

/* "How Care+ wrote this": a quiet fold with a target big enough to tap. */
.steps {
  color: var(--sl-ink-soft);
}

.steps summary {
  display: inline-flex;
  align-items: center;
  min-height: 2.75rem;
  cursor: pointer;
}

.steps summary:focus-visible {
  border-radius: var(--sl-radius-sm);
  outline: 3px solid var(--sl-focus);
  outline-offset: 2px;
}

/* While the catch-up is put together: three soft bars hold its place. */
.wait-line {
  display: block;
  width: min(34rem, 95%);
  height: 1rem;
  margin-bottom: 0.75rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-line);
  opacity: 0.6;
}

.wait-heading {
  width: min(14rem, 60%);
  height: 1.4rem;
}

.wait-short {
  width: min(20rem, 60%);
  margin-bottom: 0;
}
</style>
