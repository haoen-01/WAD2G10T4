<script setup lang="ts">
import type { MyDay } from '@silverloop/api-client';
import { computed, ref, useId } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { useReadAloud } from '@/composables/useReadAloud';
import { stepLabel } from '@/lib/agent';
import { myDaySource, readButtonLabel } from '@/lib/my-day';
import { getMyDay, getMyDaySpeech, getMyDayVoice } from '@/services/careApi';

/**
 * "Read my day": one big button that asks the API for a short run-through of today and reads it
 * aloud with the browser's own speech, in one warm voice, a sentence at a time (nothing is recorded
 * or sent anywhere for that; see `useReadAloud`). While it reads, the big button stops it and a
 * second button pauses and resumes. The words stay on screen too, for anyone who would rather
 * read, or whose browser cannot speak.
 */
const props = defineProps<{ personId: string }>();

// The natural Kokoro voice on the Care+ server when it is there; the browser's own voice if not.
const speech = useReadAloud({
  status: () => getMyDayVoice(props.personId),
  audio: (sentence) => getMyDaySpeech(props.personId, sentence),
});
const { canSpeak } = speech;
const day = ref<MyDay | null>(null);
const loading = ref(false);
const failed = ref(false);
const reading = computed(() => speech.state.value !== 'idle');
const paused = computed(() => speech.state.value === 'paused');

async function readMyDay() {
  if (reading.value) return speech.stop();
  // Straight from the press, before the day is fetched: lets the voice start when it arrives.
  speech.prime();
  loading.value = true;
  failed.value = false;
  try {
    // Asked fresh each time: a reminder ticked a minute ago should not be read out as still to do.
    day.value = await getMyDay(props.personId);
    void speech.speak(day.value.script);
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

const voiceId = useId();
function pickVoiceFrom(event: Event) {
  speech.setVoiceChoice((event.target as HTMLSelectElement).value || null);
}

function togglePause() {
  if (paused.value) speech.resume();
  else speech.pause();
}
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
    <button
      v-if="reading"
      type="button"
      class="btn btn-outline-primary btn-lg read-btn ms-2"
      :aria-pressed="paused"
      data-testid="read-my-day-pause"
      @click="togglePause"
    >
      <Icon :name="paused ? 'play' : 'pause'" class="me-2" />{{ paused ? 'Resume' : 'Pause' }}
    </button>
    <div v-if="canSpeak && speech.voiceText.value" class="small text-body-secondary mt-2">
      <p class="mb-0" :title="speech.voiceName.value ?? undefined" data-testid="my-day-voice">
        Voice: {{ speech.voiceText.value }}
      </p>
      <p
        v-if="speech.engine.value === 'browser' && speech.hint.value"
        class="mb-0"
        data-testid="my-day-voice-hint"
      >
        {{ speech.hint.value }}
      </p>
      <details
        v-if="speech.engine.value === 'browser' && speech.voices.value.length > 1"
        class="mt-1"
      >
        <summary>Choose a voice</summary>
        <label :for="`${voiceId}-voice`" class="visually-hidden">Voice</label>
        <select
          :id="`${voiceId}-voice`"
          class="form-select form-select-sm mt-1 voice-select"
          :value="speech.chosenName.value ?? ''"
          data-testid="my-day-voice-choice"
          @change="pickVoiceFrom"
        >
          <option value="">Best available (automatic)</option>
          <option v-for="item in speech.voices.value" :key="item.name" :value="item.name">
            {{ item.label }}
          </option>
        </select>
      </details>
    </div>
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
.voice-select {
  max-width: 24rem;
}
.script {
  max-width: 40rem;
  font-size: 1.25rem;
  line-height: 1.55;
}
</style>
