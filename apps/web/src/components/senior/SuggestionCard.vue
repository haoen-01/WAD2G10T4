<script setup>
import { onBeforeUnmount, ref } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { SENIOR_REPLIES } from '@/lib/labels';

const props = defineProps({
  suggestion: { type: Object, required: true },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits({ reply: (outcome, thanks) => Boolean(outcome && thanks) });
const replies = SENIOR_REPLIES;
const icons = { accepted: 'check-circle', deferred: 'clock', declined: 'x' };
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
function reply(outcome, thanks) {
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
/* The suggestion reads as a message from the centre: generous type, nothing else competing. */
.suggestion {
  position: relative;
  padding: 1.5rem;
  border: 2px solid var(--sl-jade);
  border-radius: var(--sl-radius);
  background: var(--sl-surface);
}

@media (min-width: 768px) {
  .suggestion {
    padding: 2rem 2.25rem;
  }
}

.suggestion-from {
  display: inline-flex;
  align-items: center;
  margin-bottom: 0.75rem;
  padding: 0.25rem 0.85rem;
  border-radius: 999px;
  background: var(--sl-sun-soft);
  font-size: 1rem;
  font-weight: 700;
}

.suggestion-title {
  font-size: clamp(1.7rem, 4vw, 2.3rem);
  font-weight: 800;
}

.suggestion-message {
  max-width: 40rem;
  font-size: 1.3rem;
  line-height: 1.5;
}

.read-btn {
  --bs-btn-padding-x: 0.9rem;
  margin-left: -0.9rem;
}

.replies {
  display: grid;
  gap: 0.75rem;
}

@media (min-width: 768px) {
  .replies {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.reply {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 4rem;
}
</style>
