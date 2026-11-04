<script setup lang="ts">
import type { DailyMetric, PersonState, WearableStatus } from '@silverloop/api-client';
import { computed, onBeforeUnmount, ref } from 'vue';
import { useRouter } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import Watch3D from '@/components/watch/Watch3D.vue';
import { useReducedMotion } from '@/composables/useReducedMotion';
import { hoursLabel, nearestTurn, wrapAngle } from '@/lib/watch';

/**
 * Her watch, live, as the picture in Home's hero: the same `Watch3D` the watch page draws, showing
 * her real readings, under the day they are from. Drag it (or use the arrow keys) to turn it; let
 * go and it coasts, then eases back to face you. At rest it stands still. A tap (a press that
 * hardly moves) or Enter opens the full Watch page, as does Watch in the menu.
 */
const props = defineProps<{
  person: PersonState | null;
  history: DailyMetric[] | null;
  wearable: WearableStatus | null;
  now: Date;
  /** The day the readings are from, shown on the watch's screen ("Today" or "Tue, 18 Aug"). */
  dayLabel: string;
}>();

const reduced = useReducedMotion();
const router = useRouter();

const latest = computed(() => props.history?.[props.history.length - 1] ?? null);
const clock = computed(() =>
  new Intl.DateTimeFormat('en-SG', { hour: 'numeric', minute: '2-digit', hour12: true })
    .format(props.now)
    .replace(/\s?[ap]m$/i, ''),
);

// ---- Turning ----
// At rest it stands still: the frame loop runs only while it is being turned, coasts after a
// flick, or eases back to face you, and then stops, so Home does no work while it is just read.
const REST_YAW = -32;
const REST_PITCH = 4;

const yaw = ref(REST_YAW);
const pitch = ref(REST_PITCH);
const dragging = ref(false);
let offset = 0; // how far the person has turned it from rest
let velocity = 0;
let lastX = 0;
let lastMove = 0;
let lastTouched = 0;
// Where and when the press began: a press that hardly moves is a tap, which opens the Watch page.
let downX = 0;
let downAt = 0;
let travel = 0;
const TAP_MAX_TRAVEL = 6;
const TAP_MAX_MS = 400;
let frameId = 0;
let lastFrame = 0;

function frame(time: number) {
  const dt = lastFrame ? Math.min(0.05, (time - lastFrame) / 1000) : 0;
  lastFrame = time;
  let moving = dragging.value;
  if (!dragging.value) {
    if (Math.abs(velocity) > 2) {
      // Let go mid-drag: it keeps turning and slows, like something with weight.
      offset += velocity * dt;
      velocity *= Math.pow(0.04, dt);
      moving = true;
    } else if (time - lastTouched > 1800) {
      // Then it comes back round to face you, the short way.
      const home = nearestTurn(offset, 0);
      offset += (home - offset) * Math.min(1, dt * 2);
      if (Math.abs(home - offset) < 0.1) offset = 0;
      else moving = true;
    } else {
      moving = true; // waiting to ease back
    }
  }
  yaw.value = REST_YAW + offset;
  if (moving) frameId = requestAnimationFrame(frame);
  else {
    frameId = 0;
    lastFrame = 0;
  }
}

function wake() {
  if (!frameId) frameId = requestAnimationFrame(frame);
}

onBeforeUnmount(() => cancelAnimationFrame(frameId));

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return;
  dragging.value = true;
  velocity = 0;
  downX = event.clientX;
  downAt = performance.now();
  travel = 0;
  lastX = event.clientX;
  lastMove = performance.now();
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  wake();
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return;
  const now = performance.now();
  travel = Math.max(travel, Math.abs(event.clientX - downX));
  const step = (event.clientX - lastX) * 0.5;
  offset += step;
  const dt = Math.max(1, now - lastMove) / 1000;
  velocity = velocity * 0.6 + (step / dt) * 0.4;
  lastX = event.clientX;
  lastMove = now;
}

function openWatch() {
  void router.push({ name: 'watch' });
}

function onPointerUp(event: PointerEvent) {
  if (!dragging.value) return;
  dragging.value = false;
  // A tap, not a turn: open the Watch page with its full readings.
  if (
    event.type === 'pointerup' &&
    travel < TAP_MAX_TRAVEL &&
    performance.now() - downAt < TAP_MAX_MS
  ) {
    velocity = 0;
    openWatch();
    return;
  }
  if (performance.now() - lastMove > 80) velocity = 0; // held still before letting go
  velocity = reduced.value ? 0 : Math.max(-600, Math.min(600, velocity));
  lastTouched = performance.now();
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    event.preventDefault();
    openWatch();
    return;
  }
  const turns: Record<string, number> = { ArrowLeft: -30, ArrowRight: 30 };
  if (!(event.key in turns)) return;
  event.preventDefault();
  velocity = 0;
  offset += turns[event.key];
  lastTouched = performance.now();
  wake();
}

const turned = computed(() => Math.round((wrapAngle(yaw.value - REST_YAW) + 360) % 360));
</script>

<template>
  <figure class="hero-watch mb-0" data-testid="hero-watch">
    <div
      class="watch-stage"
      :class="{ dragging }"
      tabindex="0"
      role="slider"
      aria-label="Turn the watch. Press Enter to open the Watch page."
      aria-valuemin="0"
      aria-valuemax="359"
      :aria-valuenow="turned"
      :aria-valuetext="`Turned ${turned} degrees`"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @keydown="onKey"
    >
      <span class="watch-disc" aria-hidden="true"></span>
      <div class="watch-scale">
        <Watch3D
          :yaw="yaw"
          :pitch="pitch"
          face="home"
          :steps="person?.signal.current_steps ?? null"
          :usual-steps="person?.baseline.median_steps ?? null"
          :step-bars="(history ?? []).map((day) => day.steps)"
          :active-minutes="latest?.active_minutes ?? null"
          :sleep-label="
            typeof latest?.sleep_hours === 'number' ? hoursLabel(latest.sleep_hours) : null
          "
          :wear-label="latest ? hoursLabel(latest.wear_hours) : null"
          :battery="wearable?.battery_percent ?? null"
          :charging="wearable?.charging ?? false"
          :connected="wearable?.connected ?? false"
          :time="clock"
          :docked="false"
          :day-label="dayLabel"
        />
      </div>
    </div>
    <figcaption class="watch-caption">
      <Icon name="hand" class="watch-hint-icon" />Drag to turn the watch, or tap to open it
    </figcaption>
  </figure>
</template>

<style scoped>
.hero-watch {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.watch-stage {
  position: relative;
  display: grid;
  place-items: center;
  width: min(100%, 22rem);
  height: 26rem;
  cursor: grab;
  touch-action: pan-y;
  user-select: none;
  outline: none;
}

.watch-stage.dragging {
  cursor: grabbing;
}

.watch-stage:focus-visible {
  border-radius: var(--ed-radius);
  box-shadow: 0 0 0 3px var(--ed-on-plum);
}

/* A flat, paler disc behind the watch: where the light falls. Decoration only. */
.watch-disc {
  position: absolute;
  inset: 50% auto auto 50%;
  width: 21rem;
  height: 21rem;
  border-radius: 50%;
  background: var(--ed-disc);
  transform: translate(-50%, -50%);
}

/* `zoom` shrinks the scene's layout box too (a transform would not), so it never widens a phone
   page at 150% zoom. */
.watch-scale {
  position: relative;
  zoom: 0.82;
}

.watch-caption {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  margin-top: -0.75rem;
  color: var(--ed-on-plum-soft);
  font-size: 0.95rem;
}

.watch-hint-icon {
  width: 1rem;
  height: 1rem;
  margin-right: 0.35rem;
}

@media (max-width: 767.98px) {
  .watch-stage {
    height: 20rem;
  }

  .watch-disc {
    width: 16rem;
    height: 16rem;
  }

  .watch-scale {
    zoom: 0.62;
  }
}
</style>
