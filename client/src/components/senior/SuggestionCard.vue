<script setup lang="ts">
import type { Intervention, OutcomeKind } from '@silverloop/api-client';
import { onBeforeUnmount, ref } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import { SENIOR_REPLIES } from '@/lib/labels';

const props = withDefaults(defineProps<{ suggestion: Intervention; busy?: boolean }>(), {
  busy: false,
});
const emit = defineEmits<{ reply: [outcome: OutcomeKind, thanks: string] }>();
const replies = SENIOR_REPLIES;
const icons: Partial<Record<OutcomeKind, IconName>> = {
  accepted: 'check-circle',
  deferred: 'clock',
  declined: 'x',
};
const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window;
const reading = ref(false);

function stopReading() {
  if (canSpeak) window.speechSynthesis.cancel();
  reading.value = false;
}
function readAloud() {
  if (!canSpeak) return;
  if (reading.value) return stopReading();
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(
    `${props.suggestion.title}. ${props.suggestion.message}`,
  );
  utterance.rate = 0.9;
  utterance.onend = () => {
    reading.value = false;
  };
  utterance.onerror = () => {
    reading.value = false;
  };
  reading.value = true;
  window.speechSynthesis.speak(utterance);
}
function reply(outcome: OutcomeKind, thanks: string) {
  stopReading();
  emit('reply', outcome, thanks);
}
onBeforeUnmount(stopReading);
</script>

<template>
  <section class="suggestion" aria-labelledby="suggestion-heading">
    <p class="suggestion-from"><Icon name="sparkle" class="me-2" />A suggestion for you</p>
    <h2 id="suggestion-heading" class="suggestion-title">{{ suggestion.title }}</h2>
    <p class="suggestion-message">{{ suggestion.message }}</p>

    <button
      v-if="canSpeak"
      type="button"
      class="btn btn-quiet read-btn mb-4"
      :aria-pressed="reading"
      @click="readAloud"
    >
      <Icon :name="reading ? 'stop' : 'speaker'" class="me-2" />
      {{ reading ? 'Stop reading' : 'Read this to me' }}
    </button>

    <div class="replies">
      <button
        v-for="(option, index) in replies"
        :key="option.outcome"
        type="button"
        class="btn btn-lg reply"
        :class="index === 0 ? 'btn-primary' : 'btn-outline-primary'"
        :disabled="busy"
        @click="reply(option.outcome, option.thanks)"
      >
        <Icon :name="icons[option.outcome] ?? 'check'" class="me-2" />{{ option.label }}
      </button>
    </div>
  </section>
</template>

<style scoped>
/* The suggestion reads as a message from the centre: one big calm card, nothing else competing. */
.suggestion {
  position: relative;
  padding: 1.25rem 1rem;
  border: 2px solid var(--sl-jade);
  border-radius: var(--sl-radius);
  background: color-mix(in srgb, var(--sl-jade) 6%, var(--sl-surface));
  box-shadow: var(--sl-elev-2);
}

@media (min-width: 576px) {
  .suggestion {
    padding: 1.5rem 1.25rem;
  }
}

@media (min-width: 768px) {
  .suggestion {
    padding: 2.25rem 2.5rem;
  }
}

.suggestion-from {
  display: inline-flex;
  align-items: center;
  margin-bottom: 1rem;
  padding: 0.3rem 0.9rem;
  border-radius: 1rem;
  line-height: 1.25;
  background: var(--sl-sun-soft);
  color: var(--sl-ink);
  font-size: 1rem;
  font-weight: 700;
}

.suggestion-title {
  margin-bottom: 0.75rem;
  font-size: clamp(1.55rem, 4vw, 2.4rem);
  font-weight: 800;
  overflow-wrap: anywhere;
}

.suggestion-message {
  max-width: 40rem;
  margin-bottom: 1.25rem;
  font-size: 1.3rem;
  line-height: 1.55;
}

.read-btn {
  --bs-btn-padding-x: 0.9rem;
  min-height: 3.5rem;
  margin-left: -0.9rem;
  font-size: 1.1rem;
}

/* Yes is the one big primary; the two quieter answers sit under it, side by side when there is room. */
.replies {
  display: grid;
  gap: 0.85rem;
  max-width: 40rem;
}

@media (min-width: 576px) {
  .replies {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .reply:first-child {
    grid-column: 1 / -1;
  }
}

.reply {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 4rem;
  font-size: 1.25rem;
  font-weight: 700;
}

.reply:first-child {
  min-height: 4.5rem;
  font-size: 1.4rem;
}

.reply.btn-outline-primary {
  background: var(--sl-surface);
}
</style>
