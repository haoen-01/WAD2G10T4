<script setup lang="ts">
import type { CatchUp } from '@silverloop/api-client';
import { onMounted, ref, watch } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { useAssistant } from '@/composables/useAssistant';
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
 * browser last opened Home for it, set as Home's editorial statement: the summary itself in large
 * serif, its highlights as a short list, and who wrote it, said plainly. While the agent writes,
 * the statement's place is held; if it cannot be read, the section stays hidden and the rest of
 * Home is unaffected. The result is handed up (`loaded`) so the hero can read it aloud.
 */
const props = defineProps<{ groupId: string }>();
const emit = defineEmits<{ loaded: [catchUp: CatchUp | null] }>();

const catchUp = ref<CatchUp | null>(null);
const since = ref<string | null>(null);
const loading = ref(true);
const assistant = useAssistant();

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
  loading.value = true;
  since.value = readSince(groupId);
  try {
    catchUp.value = await getCatchUp(groupId, since.value);
    markVisited(groupId);
  } catch {
    catchUp.value = null;
  } finally {
    loading.value = false;
    emit('loaded', catchUp.value);
  }
}

onMounted(() => void load(props.groupId));
watch(
  () => props.groupId,
  (next) => void load(next),
);
</script>

<template>
  <div v-if="loading" class="statement" aria-hidden="true">
    <span class="sl-skeleton sk-heading"></span>
    <span class="sl-skeleton sk-line"></span>
    <span class="sl-skeleton sk-line"></span>
    <span class="sl-skeleton sk-line sk-line--short"></span>
  </div>
  <section
    v-else-if="catchUp"
    class="statement"
    aria-labelledby="catch-up-heading"
    data-testid="catch-up"
    :data-mode="catchUp.mode"
  >
    <h2 id="catch-up-heading" class="statement-heading ed-serif">
      {{ catchUpHeading(since) }}
    </h2>
    <p class="statement-summary ed-serif">{{ catchUp.summary }}</p>
    <ul v-if="catchUp.highlights.length" class="statement-highlights">
      <li v-for="line in catchUp.highlights" :key="line">
        <Icon name="arrow-right" class="highlight-mark" />{{ line }}
      </li>
    </ul>
    <div class="statement-foot">
      <p class="statement-source mb-0">{{ catchUpSource(catchUp) }}</p>
      <button type="button" class="ask-kaki" @click="assistant.setOpen(true)">
        Ask Kaki about it<Icon name="chevron-right" />
      </button>
    </div>
    <details v-if="catchUp.steps.length" class="statement-steps" data-testid="catch-up-steps">
      <summary>How Care+ wrote this</summary>
      <ol class="mb-0 mt-2 ps-3">
        <li v-for="(step, index) in catchUp.steps" :key="index">
          {{ stepLabel(step.tool_name) }}<span v-if="!step.ok"> (not accepted, tried again)</span>
        </li>
      </ol>
    </details>
  </section>
</template>

<style scoped>
.statement {
  min-width: 0;
  color: var(--ed-ink);
}

.statement-heading {
  margin: 0 0 1.25rem;
  color: var(--ed-ink);
  font-size: clamp(2rem, 4vw, 3rem);
  line-height: 1;
}

/* The agent's own words, set as the page's statement. */
.statement-summary {
  max-width: 30ch;
  margin-bottom: 1.75rem;
  font-size: clamp(1.6rem, 2.9vw, 2.35rem);
  line-height: 1.18;
  letter-spacing: -0.015em;
  text-wrap: pretty;
}

.statement-highlights {
  display: grid;
  max-width: 34rem;
  margin: 0 0 1.75rem;
  padding: 0;
  list-style: none;
}

.statement-highlights li {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.75rem 0;
  border-top: 1px solid var(--ed-line);
  font-size: 1.05rem;
}

.statement-highlights li:last-child {
  border-bottom: 1px solid var(--ed-line);
}

.highlight-mark {
  flex: none;
  width: 1rem;
  height: 1rem;
  color: var(--ed-cross);
  transform: translateY(0.15rem);
}

.statement-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1.5rem;
}

.statement-source {
  color: var(--ed-ink-soft);
  font-size: 0.95rem;
}

.ask-kaki {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  min-height: 2.75rem;
  padding: 0;
  border: 0;
  background: none;
  color: var(--ed-ink);
  font-weight: 700;
  text-decoration: underline;
  text-underline-offset: 0.25em;
}

.ask-kaki:focus-visible {
  border-radius: 6px;
  outline: 3px solid var(--ed-ink);
  outline-offset: 3px;
}

.ask-kaki .sl-icon {
  width: 1rem;
  height: 1rem;
}

.statement-steps {
  margin-top: 0.75rem;
  color: var(--ed-ink-soft);
  font-size: 0.9rem;
}

.statement-steps summary {
  min-height: 2.75rem;
  padding-top: 0.6rem;
  cursor: pointer;
}

.sk-heading {
  display: block;
  width: min(18rem, 70%);
  height: 2.5rem;
  margin-bottom: 1.5rem;
}

.sk-line {
  display: block;
  width: min(34rem, 95%);
  height: 1.8rem;
  margin-bottom: 0.75rem;
}

.sk-line--short {
  width: min(20rem, 60%);
}
</style>
