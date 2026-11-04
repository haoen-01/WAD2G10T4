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
 * aloud, a sentence at a time: in a natural Kokoro voice made on the Care+ server's own CPU when it
 * is there, else with the browser's own speech in its warmest voice (see `useReadAloud`). "Choose a
 * voice" lists both. While it reads, the big button stops it and a second button pauses and
 * resumes. The words stay on screen too, for anyone who would rather
 * read, or whose browser cannot speak.
 */
const props = defineProps<{ personId: string }>();

// The natural Kokoro voice on the Care+ server when it is there; the browser's own voice if not.
const speech = useReadAloud({
  status: () => getMyDayVoice(props.personId),
  audio: (sentence, voice) => getMyDaySpeech(props.personId, sentence, voice),
});
// Kokoro's voices and the browser's, in one list; grouped only when there are both.
const voiceCount = computed(() => speech.serverVoices.value.length + speech.voices.value.length);
// True once it is known that nothing can be read aloud here (no Kokoro, and no voice of the
// device's own): the card then says so up front, and the button shows the day instead.
const { noVoice } = speech;
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

/** What the short status line says (announced, so kept to a few words). */
const status = computed(() => {
  if (loading.value) return 'Getting your day.';
  if (paused.value) return 'Reading paused.';
  if (reading.value) return 'Reading your day.';
  if (day.value && noVoice.value) return 'Your day is shown below, to read.';
  return '';
});

const noVoiceId = useId();

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
    <!-- Full width, one above the other, on a phone; side by side from the small breakpoint up. -->
    <div class="d-grid d-sm-flex flex-sm-wrap gap-2">
      <button
        type="button"
        class="btn btn-primary btn-lg read-btn"
        :disabled="loading"
        :aria-describedby="noVoice ? noVoiceId : undefined"
        @click="readMyDay"
      >
        <Icon :name="reading ? 'stop' : noVoice ? 'eye' : 'speaker'" class="read-icon" />{{
          loading ? 'One moment…' : readButtonLabel(!noVoice, reading)
        }}
      </button>
      <button
        v-if="reading"
        type="button"
        class="btn btn-outline-primary btn-lg read-btn"
        data-testid="read-my-day-pause"
        @click="togglePause"
      >
        <Icon :name="paused ? 'play' : 'pause'" class="read-icon" />{{
          paused ? 'Resume' : 'Pause'
        }}
      </button>
    </div>
    <!-- A short line for screen readers as the reading starts, pauses or ends: never the whole
         script, which is on screen to read. -->
    <p class="visually-hidden" role="status" data-testid="my-day-status">{{ status }}</p>
    <!-- Nothing can be read aloud here: said once, before the press, in place of the voice line. -->
    <p v-if="noVoice" :id="noVoiceId" class="mt-2 mb-0" data-testid="my-day-no-voice">
      This device has no reading voice of its own, so your day is shown here to read instead.
    </p>
    <div v-else-if="speech.voiceText.value" class="text-body-secondary mt-2">
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
      <details v-if="voiceCount > 1" class="voice-pick mt-1">
        <summary>Choose a voice</summary>
        <label :for="`${voiceId}-voice`" class="visually-hidden">Voice</label>
        <select
          :id="`${voiceId}-voice`"
          class="form-select mt-1 voice-select"
          :value="speech.chosenName.value ?? ''"
          data-testid="my-day-voice-choice"
          @change="pickVoiceFrom"
        >
          <option value="">Best available (automatic)</option>
          <template v-if="speech.serverVoices.value.length">
            <optgroup label="Natural voices (Care+)">
              <option v-for="item in speech.serverVoices.value" :key="item.name" :value="item.name">
                {{ item.label }}
              </option>
            </optgroup>
            <optgroup v-if="speech.voices.value.length" label="This browser’s voices">
              <option v-for="item in speech.voices.value" :key="item.name" :value="item.name">
                {{ item.label }}
              </option>
            </optgroup>
          </template>
          <template v-else>
            <option v-for="item in speech.voices.value" :key="item.name" :value="item.name">
              {{ item.label }}
            </option>
          </template>
        </select>
      </details>
    </div>
    <p v-if="failed" class="mt-3 mb-0" role="status">
      Your day could not be fetched just now. Your calendar and reminders below are still up to
      date.
    </p>
    <div v-if="day" class="mt-3" :data-mode="day.mode" data-testid="my-day-script">
      <p class="script mb-2">{{ day.script }}</p>
      <p class="small text-body-secondary mb-0">{{ myDaySource(day) }}</p>
      <details v-if="day.steps.length" class="steps small mt-2">
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
  justify-content: center;
  min-height: 4rem;
  font-size: 1.25rem;
  font-weight: 700;
}

.read-icon {
  margin-inline-end: 0.5rem;
}

/* A phone: full width, with slimmer sides so the label stays on one line at the largest text size. */
@media (max-width: 575.98px) {
  .read-btn {
    padding-inline: 0.75rem;
  }
}

/* The card itself is measured (it is full width, so measuring never changes its size). */
.read-my-day {
  container: read-my-day / inline-size;
}

/* Too narrow for the icon and the words side by side (a small phone at the largest text size):
   the icon sits above the words, so the words stay whole on one line at their full size. */
@container read-my-day (max-width: 11.25rem) {
  .read-btn {
    flex-direction: column;
    gap: 0.15rem;
    padding-block: 0.5rem;
    white-space: nowrap;
  }

  .read-icon {
    margin-inline-end: 0;
  }
}
/* The senior screen's touch targets: at least 48 px for the folds and the voice list. */
.voice-pick summary,
.steps summary {
  display: inline-flex;
  align-items: center;
  min-height: 3rem;
  cursor: pointer;
}

.voice-select {
  max-width: 24rem;
  min-height: 3rem;
}
.script {
  max-width: 40rem;
  font-size: 1.25rem;
  line-height: 1.55;
}
</style>
