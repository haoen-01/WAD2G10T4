<script setup lang="ts">
import { computed, ref } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { useWalk } from '@/composables/useWalk';
import { HOUR_MS, MINUTE_MS } from '@/lib/stillness';

/**
 * Controls for the simulated watch, so the walk and the check-in can be shown in a few minutes:
 * start, pause, speed, keep her in one place, skip ahead, lose the signal, or play a recorded walk
 * from a GPX file. Clearly labelled as a simulation; a real watch would not have these.
 */
const walk = useWalk();
const SPEEDS = [1, 5, 20];
const gpxProblem = ref<string | null>(null);

const sim = computed(() => walk.demoState.value);

async function chooseGpx(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  gpxProblem.value = walk.playRecording(await file.text(), file.name);
}
</script>

<template>
  <section class="sl-panel demo-controls" aria-labelledby="demo-walk-heading">
    <h2 id="demo-walk-heading" class="h6 d-flex align-items-center gap-2 mb-1">
      <Icon name="watch" /> Simulated walk
    </h2>
    <p class="sl-note mb-3">
      There is no real watch yet, so this plays a made-up walk around Bishan–Ang Mo Kio Park, in
      this browser only.
    </p>

    <div class="d-flex flex-wrap gap-2 mb-3">
      <button
        v-if="!walk.demoActive.value"
        type="button"
        class="btn btn-primary"
        data-testid="demo-start"
        @click="walk.startDemo()"
      >
        <Icon name="play" /> Start the demo walk
      </button>
      <template v-else>
        <button
          type="button"
          class="btn btn-outline-primary"
          data-testid="demo-pause"
          @click="walk.setPlaying(!walk.playing.value)"
        >
          <Icon :name="walk.playing.value ? 'pause' : 'play'" />
          {{ walk.playing.value ? 'Pause' : 'Carry on' }}
        </button>
        <button
          type="button"
          class="btn btn-outline-secondary"
          data-testid="demo-reset"
          @click="walk.resetDemo()"
        >
          <Icon name="refresh" /> Reset
        </button>
      </template>
    </div>

    <template v-if="walk.demoActive.value && sim">
      <div class="mb-3" role="group" aria-labelledby="demo-speed-label">
        <p id="demo-speed-label" class="form-label mb-1">Speed</p>
        <div class="demo-speed">
          <button
            v-for="speed in SPEEDS"
            :key="speed"
            type="button"
            class="btn btn-sm btn-outline-primary"
            :aria-pressed="walk.speed.value === speed"
            :data-testid="`demo-speed-${speed}`"
            @click="walk.setSpeed(speed)"
          >
            {{ speed }}×
          </button>
        </div>
      </div>

      <div class="d-grid gap-2">
        <button
          type="button"
          class="btn btn-outline-secondary text-start"
          :aria-pressed="sim.stayStill"
          data-testid="demo-stay"
          @click="walk.setStayStill(!sim.stayStill)"
        >
          <Icon name="pin" /> Stay still here
        </button>
        <div class="d-flex gap-2">
          <button
            type="button"
            class="btn btn-outline-secondary flex-grow-1"
            data-testid="demo-skip-15"
            @click="walk.skipAhead(15 * MINUTE_MS)"
          >
            <Icon name="timer" /> Skip 15 min
          </button>
          <button
            type="button"
            class="btn btn-outline-secondary flex-grow-1"
            data-testid="demo-skip"
            @click="walk.skipAhead(HOUR_MS)"
          >
            <Icon name="timer" /> Skip 1 hour
          </button>
        </div>
        <button
          type="button"
          class="btn btn-outline-secondary text-start"
          :aria-pressed="sim.signalLost"
          data-testid="demo-signal"
          @click="walk.setSignalLost(!sim.signalLost)"
        >
          <Icon name="watch" /> Lose the signal
        </button>
      </div>
    </template>

    <div class="mt-3">
      <label for="demo-gpx" class="form-label mb-1">Or play a recorded walk (GPX file)</label>
      <input
        id="demo-gpx"
        class="form-control"
        type="file"
        accept=".gpx,application/gpx+xml"
        data-testid="demo-gpx"
        @change="chooseGpx"
      />
      <p class="sl-note mt-1 mb-0">
        From Strava, Garmin or another watch. It is read in this browser, not uploaded. The Streets
        and Quiet looks fetch map pictures of its area from OpenFreeMap.
      </p>
      <p v-if="gpxProblem" class="text-danger mt-1 mb-0" role="alert">{{ gpxProblem }}</p>
    </div>
  </section>
</template>

<style scoped>
.demo-controls {
  border-style: dashed;
}

.demo-controls .btn {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  min-height: 2.75rem;
}

.demo-speed {
  display: inline-flex;
  gap: 0.35rem;
}

.demo-speed .btn {
  min-width: 3.25rem;
  justify-content: center;
}

.demo-speed .btn[aria-pressed='true'] {
  background: var(--sl-jade);
  border-color: var(--sl-jade);
  color: var(--sl-jade-on);
}
</style>
