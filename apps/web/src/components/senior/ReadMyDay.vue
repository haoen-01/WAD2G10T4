<script setup lang="ts">
import type { MyDay } from '@silverloop/api-client';
import { onBeforeUnmount, ref } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { stepLabel } from '@/lib/agent';
import { myDaySource, readButtonLabel } from '@/lib/my-day';
import { getMyDay } from '@/services/careApi';

/**
 * "Read my day": one big button that asks the API for a short run-through of today and reads it
 * aloud with the browser's own speech (nothing is recorded or sent anywhere for that). The words
 * stay on screen too, for anyone who would rather read, or whose browser cannot speak.
 */
const props = defineProps<{ personId: string }>();

const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window;
const day = ref<MyDay | null>(null);
const loading = ref(false);
const failed = ref(false);
const reading = ref(false);

function stopReading() {
  if (canSpeak) window.speechSynthesis.cancel();
  reading.value = false;
}

function speak(script: string) {
  if (!canSpeak) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(script);
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

async function readMyDay() {
  if (reading.value) return stopReading();
  loading.value = true;
  failed.value = false;
  try {
    // Asked fresh each time: a reminder ticked a minute ago should not be read out as still to do.
    day.value = await getMyDay(props.personId);
    speak(day.value.script);
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

onBeforeUnmount(stopReading);
</script>

<template>
  <section
    class="sl-panel read-my-day"
    aria-labelledby="read-my-day-heading"
    data-testid="read-my-day"
  >
    <h2 id="read-my-day-heading" class="h4">Your day, read to you</h2>
    <button
      type="button"
      class="btn btn-primary btn-lg read-btn"
      :aria-pressed="canSpeak ? reading : undefined"
      :disabled="loading"
      @click="readMyDay"
    >
      <Icon :name="reading ? 'stop' : 'speaker'" class="me-2" />{{
        loading ? 'Getting your day…' : readButtonLabel(canSpeak, reading)
      }}
    </button>
    <p v-if="failed" class="mt-3 mb-0" role="status">
      Your day could not be fetched just now. Your calendar and reminders below are still up to
      date.
    </p>
    <div v-if="day" class="mt-3" role="status" :data-mode="day.mode" data-testid="my-day-script">
      <p class="script mb-2">{{ day.script }}</p>
      <p class="small text-body-secondary mb-0">{{ myDaySource(day) }}</p>
      <details v-if="day.steps.length" class="small mt-2">
        <summary>How Care+ wrote this</summary>
        <ol class="mb-0 mt-1 ps-3">
          <li v-for="(step, index) in day.steps" :key="index">
            {{ stepLabel(step.tool_name) }}<span v-if="!step.ok"> (not accepted, tried again)</span>
          </li>
        </ol>
      </details>
    </div>
  </section>
</template>

<style scoped>
.read-btn {
  display: inline-flex;
  align-items: center;
  min-height: 4rem;
  font-size: 1.25rem;
  font-weight: 700;
}
.script {
  max-width: 40rem;
  font-size: 1.25rem;
  line-height: 1.55;
}
</style>
