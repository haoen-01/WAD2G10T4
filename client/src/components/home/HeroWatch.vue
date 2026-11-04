<script setup lang="ts">
import type { DailyMetric, PersonState, WearableStatus } from '@silverloop/api-client';
import { computed, onBeforeUnmount, ref } from 'vue';
import { RouterLink } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import Watch3D from '@/components/watch/Watch3D.vue';
import { useReducedMotion } from '@/composables/useReducedMotion';
import { hoursLabel, nearestTurn } from '@/lib/watch';

/**
 * The senior's (simulated) watch in Home's hero: the same `Watch3D` the Watch page draws, showing
 * the latest readings, with the day they are from on its screen.
 *
 * - The picture is a link: a tap (a press that hardly moves), or Enter once it has focus, opens
 *   the Watch page.
 * - Dragging it sideways turns it; the two buttons beside the hint turn it too, so turning never
 *   needs a drag.
 * - At rest it stands still: frames run only while it is being turned, coasts after a flick, or
 *   eases back to face you. With reduced motion there is no coasting, no easing back and no eased
 *   button turn: it moves only as far as the finger or the button moves it.
 */
const props = defineProps<{
  person: PersonState | null;
  history: DailyMetric[] | null;
  wearable: WearableStatus | null;
  now: Date;
  /** The day the readings are from, shown on the watch's screen ("Today" or "Tue, 18 Aug"). */
  dayLabel: string;
  elder: string;
}>();

const reduced = useReducedMotion();

const latest = computed(() => props.history?.[props.history.length - 1] ?? null);
const clock = computed(() =>
  new Intl.DateTimeFormat('en-SG', { hour: 'numeric', minute: '2-digit', hour12: true })
    .format(props.now)
    .replace(/\s?[ap]m$/i, ''),
);

// ---- Turning ----
const REST_YAW = -32;
const REST_PITCH = 4;
/** How far one press of a turn button turns it, in degrees. */
const BUTTON_TURN = 45;
/** How long it waits, untouched, before it comes back round to face you. */
const SETTLE_MS = 1800;
const TAP_MAX_TRAVEL = 6;
const TAP_MAX_MS = 400;

const yaw = ref(REST_YAW);
const dragging = ref(false);
let offset = 0; // how far it has been turned from rest
let target: number | null = null; // where a button press is turning it to
let velocity = 0;
let lastX = 0;
let lastMove = 0;
let lastTouched = 0;
// Where and when the press began: a press that hardly moves is a tap, which follows the link.
let downX = 0;
let downAt = 0;
let travel = 0;
let wasDrag = false;
let frameId = 0;
let lastFrame = 0;

function frame(time: number) {
  const dt = lastFrame ? Math.min(0.05, (time - lastFrame) / 1000) : 0;
  lastFrame = time;
  let moving = dragging.value;
  if (!dragging.value) {
    if (target !== null) {
      // A button press: ease round to where it asked.
      offset += (target - offset) * Math.min(1, dt * 8);
      if (Math.abs(target - offset) < 0.2) {
        offset = target;
        target = null;
        lastTouched = performance.now();
      }
      moving = true;
    } else if (Math.abs(velocity) > 2) {
      // Let go mid-drag: it keeps turning and slows, like something with weight.
      offset += velocity * dt;
      velocity *= Math.pow(0.04, dt);
      moving = true;
    } else if (time - lastTouched > SETTLE_MS) {
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
  // Reduced motion: no frames of its own; the watch is moved straight to where it is asked.
  if (reduced.value) {
    yaw.value = REST_YAW + offset;
    return;
  }
  if (!frameId) frameId = requestAnimationFrame(frame);
}

onBeforeUnmount(() => cancelAnimationFrame(frameId));

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return;
  dragging.value = true;
  wasDrag = false;
  velocity = 0;
  target = null;
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
  if (reduced.value) yaw.value = REST_YAW + offset;
}

function onPointerUp(event: PointerEvent) {
  if (!dragging.value) return;
  dragging.value = false;
  // Anything but a quick press that hardly moved was a turn, so the click after it is not a tap.
  wasDrag =
    event.type !== 'pointerup' ||
    travel >= TAP_MAX_TRAVEL ||
    performance.now() - downAt >= TAP_MAX_MS;
  if (performance.now() - lastMove > 80) velocity = 0; // held still before letting go
  velocity = reduced.value || !wasDrag ? 0 : Math.max(-600, Math.min(600, velocity));
  lastTouched = performance.now();
}

/** The link's click: a tap or Enter opens the Watch page; the click that ends a drag does not. */
function onClick(event: MouseEvent, navigate: (event?: MouseEvent) => unknown) {
  if (wasDrag) {
    event.preventDefault();
    wasDrag = false;
    return;
  }
  void navigate(event);
}

/** The turn buttons: the same turn a drag gives, a step at a time. */
function turn(direction: -1 | 1) {
  velocity = 0;
  lastTouched = performance.now();
  if (reduced.value) {
    offset += direction * BUTTON_TURN;
    yaw.value = REST_YAW + offset;
    return;
  }
  target = (target ?? offset) + direction * BUTTON_TURN;
  wake();
}
</script>

<template>
  <figure class="hero-watch mb-0" data-testid="hero-watch">
    <RouterLink v-slot="{ href, navigate }" :to="{ name: 'watch' }" custom>
      <a
        :href="href"
        class="watch-stage"
        :class="{ dragging }"
        draggable="false"
        :aria-label="`Open ${elder}’s watch page`"
        data-testid="hero-watch-open"
        :data-turn="Math.round(yaw - REST_YAW)"
        @click="onClick($event, navigate)"
        @dragstart.prevent
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <span class="watch-disc" aria-hidden="true"></span>
        <span class="watch-scale">
          <Watch3D
            :yaw="yaw"
            :pitch="REST_PITCH"
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
        </span>
      </a>
    </RouterLink>
    <figcaption class="watch-caption">
      <button
        type="button"
        class="btn btn-outline-secondary turn-btn"
        aria-label="Turn the watch left"
        title="Turn left"
        data-testid="hero-watch-left"
        @click="turn(-1)"
      >
        <Icon name="chevron-left" />
      </button>
      <span class="watch-hint"
        >Drag or use the arrows to turn it. Tap it to open the Watch page.</span
      >
      <button
        type="button"
        class="btn btn-outline-secondary turn-btn"
        aria-label="Turn the watch right"
        title="Turn right"
        data-testid="hero-watch-right"
        @click="turn(1)"
      >
        <Icon name="chevron-right" />
      </button>
    </figcaption>
  </figure>
</template>

<style scoped>
.hero-watch {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
}

.watch-stage {
  position: relative;
  display: grid;
  place-items: center;
  width: min(100%, 17rem);
  height: 21rem;
  /* The turned watch never widens the page: what spills past the stage's sides is clipped. */
  overflow-x: clip;
  border-radius: var(--sl-radius);
  cursor: var(--sl-cur-grab, grab);
  touch-action: pan-y;
  user-select: none;
  -webkit-user-drag: none;
}

.watch-stage.dragging {
  cursor: var(--sl-cur-grabbing, grabbing);
}

.watch-stage:focus-visible {
  outline: 3px solid var(--sl-focus);
  outline-offset: 2px;
}

/* A soft pool of light behind the watch. Decoration only. */
.watch-disc {
  position: absolute;
  inset: 50% auto auto 50%;
  width: 16rem;
  height: 16rem;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    var(--sl-jade-soft) 0%,
    var(--sl-jade-soft) 55%,
    transparent 72%
  );
  transform: translate(-50%, -50%);
}

/* `zoom` shrinks the scene's layout box too (a transform would not), so it never widens a phone
   page at 150% zoom. */
.watch-scale {
  position: relative;
  display: block;
  zoom: 0.68;
  pointer-events: none;
}

.watch-caption {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  max-width: 20rem;
  margin-top: 0.25rem;
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  text-align: center;
}

.watch-hint {
  min-width: 0;
}

.turn-btn {
  display: inline-grid;
  flex: none;
  place-items: center;
  width: 2.75rem;
  height: 2.75rem;
  padding: 0;
  border-radius: 50%;
}

.turn-btn :deep(.sl-icon) {
  width: 1.25rem;
  height: 1.25rem;
}

@media (max-width: 575.98px) {
  .watch-stage {
    height: 18rem;
  }

  .watch-disc {
    width: 14rem;
    height: 14rem;
  }

  .watch-scale {
    zoom: 0.58;
  }
}
</style>
