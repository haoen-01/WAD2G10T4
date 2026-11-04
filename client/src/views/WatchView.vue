<script setup lang="ts">
import type { DailyMetric } from '@silverloop/api-client';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';

import type { IconName } from '@/components/ui/Icon.vue';
import Icon from '@/components/ui/Icon.vue';
import Watch3D from '@/components/watch/Watch3D.vue';
import WatchDetail from '@/components/watch/WatchDetail.vue';
import { useNow } from '@/composables/useNow';
import { useReducedMotion } from '@/composables/useReducedMotion';
import { todayIso } from '@/lib/calendar';
import { readingPastDay } from '@/lib/home';
import {
  careTimeline,
  easeInOutCubic,
  easeOutCubic,
  hoursLabel,
  nearestTurn,
  watchPoints,
  watchFrame,
  wrapAngle,
  type WatchPoint,
} from '@/lib/watch';
import { syncedAgo } from '@/lib/wearable';
import { useActivityStore } from '@/stores/activity';

/**
 * The senior's simulated watch, in 3D. It spins in once, the points around it draw out, then it
 * keeps turning slowly. Drag it (or use the buttons under it) to turn it yourself. Open a point and
 * the watch turns to show that part of it while the details slide in beside it.
 *
 * Built with CSS 3D and Vue transitions only. With "reduce motion" on, nothing spins on its own and
 * every change is instant.
 */

const now = useNow();
const reduced = useReducedMotion();

// ---- The senior's data (all read-only, all existing routes) ----
// From the Pinia activity store Home shares (`stores/activity.ts`): opening the Watch page from Home
// reuses the reading Home has just made, so both show the same steps and the same percentage.
const activity = useActivityStore();
const { person, wearable, noSenior, latestDay: latest } = storeToRefs(activity);
const metrics = computed<DailyMetric[]>(() => activity.history ?? []);
// Reading until the first read is in.
const loading = computed(() => activity.loading || !activity.loaded);

function load(): Promise<void> {
  return activity.load();
}

const elder = computed(() => person.value?.display_name ?? 'your senior');
const synced = computed(() =>
  wearable.value?.last_synced_at
    ? syncedAgo(wearable.value.last_synced_at, now.value).replace(/^synced /, '')
    : null,
);
/** The latest reading's own day ("Thu, 20 Aug") when it is not today, so it never reads as today. */
const pastDay = computed(() =>
  person.value ? readingPastDay(person.value.current_day, todayIso(now.value)) : null,
);
const points = computed(() =>
  watchPoints({
    pastDay: pastDay.value,
    steps: person.value?.signal.current_steps ?? null,
    usualSteps: person.value?.baseline.median_steps ?? null,
    metrics: metrics.value,
    wearable: wearable.value,
    syncedAgo: synced.value,
    elder: elder.value,
  }),
);
// The points name icons as plain strings (lib/ stays free of components).
const iconOf = (name: string) => name as IconName;
const pointOf = (id: string) => points.value.find((point) => point.id === id) ?? null;
const care = computed(() => careTimeline(wearable.value));
const careOpen = ref(false);
const battery = computed(() => wearable.value?.battery_percent ?? null);
const clock = computed(() =>
  new Intl.DateTimeFormat('en-SG', { hour: 'numeric', minute: '2-digit', hour12: true })
    .format(now.value)
    .replace(/\s?[ap]m$/i, ''),
);

// ---- Turning the watch ----
const REST_YAW = -40;
const REST_PITCH = 4;
const SPIN_DEGREES_PER_SECOND = 20;

const yaw = ref(REST_YAW);
const pitch = ref(REST_PITCH);
const autoSpin = ref(true);
/** `intro`: spinning in. `ready`: the points are out and the watch turns on its own. */
const phase = ref<'waiting' | 'intro' | 'ready'>('waiting');

interface Tween {
  fromYaw: number;
  toYaw: number;
  fromPitch: number;
  toPitch: number;
  start: number;
  duration: number;
  ease: (t: number) => number;
  done?: () => void;
  fromCamera?: Camera;
  toCamera?: Camera;
}
let tween: Tween | null = null;
let frameId = 0;
let lastFrame = 0;
let velocity = 0; // degrees per second, after a drag
let lastTouched = 0;

function tweenTo(
  toYaw: number,
  toPitch: number,
  duration: number,
  ease = easeInOutCubic,
  done?: () => void,
  toCamera?: Camera,
) {
  if (reduced.value || duration <= 0) {
    yaw.value = toYaw;
    pitch.value = toPitch;
    tween = null;
    if (toCamera) camera.value = toCamera;
    done?.();
    return;
  }
  tween = {
    fromYaw: yaw.value,
    toYaw,
    fromPitch: pitch.value,
    toPitch,
    start: performance.now(),
    duration,
    ease,
    done,
    fromCamera: toCamera ? { ...camera.value } : undefined,
    toCamera,
  };
}

function frame(time: number) {
  const dt = lastFrame ? Math.min(0.05, (time - lastFrame) / 1000) : 0;
  lastFrame = time;
  if (tween) {
    const progress = Math.min(1, (time - tween.start) / tween.duration);
    const eased = tween.ease(progress);
    yaw.value = tween.fromYaw + (tween.toYaw - tween.fromYaw) * eased;
    pitch.value = tween.fromPitch + (tween.toPitch - tween.fromPitch) * eased;
    if (tween.fromCamera && tween.toCamera) {
      camera.value = {
        x: tween.fromCamera.x + (tween.toCamera.x - tween.fromCamera.x) * eased,
        y: tween.fromCamera.y + (tween.toCamera.y - tween.fromCamera.y) * eased,
        scale: tween.fromCamera.scale + (tween.toCamera.scale - tween.fromCamera.scale) * eased,
      };
    }
    if (progress >= 1) {
      const done = tween.done;
      tween = null;
      done?.();
    }
  } else if (!reduced.value && !dragging.value && !selected.value) {
    if (Math.abs(velocity) > 2) {
      // Let go mid-drag: the watch keeps turning and slows, like something with weight.
      yaw.value += velocity * dt;
      velocity *= Math.pow(0.05, dt);
    } else if (spinning.value && time - lastTouched > 1500) {
      yaw.value += SPIN_DEGREES_PER_SECOND * dt;
    }
    pitch.value += (REST_PITCH - pitch.value) * Math.min(1, dt * 2.5);
  }
  frameId = requestAnimationFrame(frame);
}

const spinning = computed(() => autoSpin.value && !reduced.value && phase.value === 'ready');

function toggleSpin() {
  autoSpin.value = !autoSpin.value;
  if (!autoSpin.value) {
    tween = null;
    velocity = 0;
    phase.value = 'ready';
  }
}

function startIntro() {
  if (reduced.value) {
    phase.value = 'ready';
    return;
  }
  phase.value = 'intro';
  // One full turn that settles facing you, then the points draw out.
  yaw.value = REST_YAW - 360;
  tweenTo(REST_YAW, REST_PITCH, 2200, easeOutCubic, () => {
    phase.value = 'ready';
  });
}

// ---- Drag to turn (the buttons below do the same) ----
const dragging = ref(false);
let lastX = 0;
let lastMove = 0;

function onPointerDown(event: PointerEvent) {
  if (selected.value || event.button !== 0) return;
  phase.value = 'ready';
  dragging.value = true;
  tween = null;
  velocity = 0;
  lastX = event.clientX;
  lastMove = performance.now();
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return;
  const nowMs = performance.now();
  const dx = event.clientX - lastX;
  const step = dx * 0.5;
  yaw.value += step;
  const dt = Math.max(1, nowMs - lastMove) / 1000;
  velocity = velocity * 0.6 + (step / dt) * 0.4;
  lastX = event.clientX;
  lastMove = nowMs;
}

function onPointerUp() {
  if (!dragging.value) return;
  dragging.value = false;
  if (performance.now() - lastMove > 80) velocity = 0; // held still before letting go
  velocity = reduced.value ? 0 : Math.max(-720, Math.min(720, velocity));
  lastTouched = performance.now();
}

function turnBy(degrees: number) {
  phase.value = 'ready';
  velocity = 0;
  lastTouched = performance.now();
  tweenTo(yaw.value + degrees, REST_PITCH, 700);
}

function resetTurn() {
  phase.value = 'ready';
  velocity = 0;
  lastTouched = performance.now();
  tweenTo(nearestTurn(yaw.value, REST_YAW), REST_PITCH, 900);
}

function onStageKey(event: KeyboardEvent) {
  const turns: Record<string, number> = { ArrowLeft: -30, ArrowRight: 30 };
  if (event.key in turns) {
    event.preventDefault();
    turnBy(turns[event.key]);
  } else if (event.key === 'Home') {
    event.preventDefault();
    resetTurn();
  }
}

const turnedDegrees = computed(() => Math.round((wrapAngle(yaw.value) + 360) % 360));

// ---- Opening a point ----
const selectedId = ref<string | null>(null);
const selected = computed<WatchPoint | null>(() =>
  selectedId.value ? pointOf(selectedId.value) : null,
);
// A single watch stays mounted when its dialog moves into the browser's top layer.
// Its camera and orientation share one animation clock, including the return journey.
interface Camera {
  x: number;
  y: number;
  scale: number;
}
const camera = ref<Camera>({ x: 0, y: 0, scale: 1 });
const fullscreen = ref(false);
const closing = ref(false);
const sceneHome = ref<HTMLElement | null>(null);
const stage = ref<HTMLElement | null>(null);
const homeHeight = ref<number | null>(null);
let returnFocus: HTMLElement | null = null;
let returnPose = { yaw: REST_YAW, pitch: REST_PITCH };
let previousOverflow = '';
let previousScroll = { x: 0, y: 0 };
let alive = true;
let opening = false;
const cameraStyle = computed(() =>
  fullscreen.value
    ? {
        transform: `translate3d(${camera.value.x - window.innerWidth / 2}px, ${camera.value.y - window.innerHeight / 2}px, 0) scale(${camera.value.scale})`,
      }
    : undefined,
);

function overviewCamera(): Camera {
  const rect = sceneHome.value!.getBoundingClientRect();
  const small = window.innerWidth < 992;
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + (small ? 200 : 255),
    scale: small ? 0.74 : 1.12,
  };
}

function frameSelected(duration = 1200) {
  const point = selected.value;
  if (!point) return;
  tweenTo(
    nearestTurn(yaw.value, point.pose.yaw),
    point.pose.pitch,
    duration,
    easeInOutCubic,
    undefined,
    watchFrame(point.id, window.innerWidth, window.innerHeight),
  );
}

async function open(point: WatchPoint, event?: Event) {
  if (closing.value || opening) return;
  phase.value = 'ready';
  velocity = 0;
  dragging.value = false;
  if (fullscreen.value) {
    selectedId.value = point.id;
    frameSelected();
    return;
  }
  const dialog = card.value;
  if (!dialog || !stage.value) return;
  opening = true;
  returnFocus =
    (event?.currentTarget as HTMLElement | undefined) ?? (document.activeElement as HTMLElement);
  returnPose = { yaw: yaw.value, pitch: pitch.value };
  previousScroll = { x: window.scrollX, y: window.scrollY };
  homeHeight.value = dialog.getBoundingClientRect().height;
  camera.value = overviewCamera();
  tween = null;
  previousOverflow = document.documentElement.style.overflow;
  document.documentElement.style.overflow = 'hidden';
  fullscreen.value = true;
  selectedId.value = point.id;
  // An already-open non-modal dialog must close before showModal can promote it.
  dialog.close();
  await nextTick();
  if (!alive) return;
  dialog.showModal();
  opening = false;
  frameSelected();
}

function finishClose() {
  const dialog = card.value;
  dialog?.close();
  fullscreen.value = false;
  selectedId.value = null;
  closing.value = false;
  document.documentElement.style.overflow = previousOverflow;
  // Restore the non-modal overview; the dialog/model itself is never replaced.
  dialog?.show();
  lastTouched = performance.now();
  void nextTick(() => {
    if (!alive) return;
    homeHeight.value = null;
    window.scrollTo(previousScroll.x, previousScroll.y);
    returnFocus?.focus({ preventScroll: true });
    measure();
  });
}

function close() {
  if (!fullscreen.value || closing.value || opening) return;
  closing.value = true;
  tweenTo(
    nearestTurn(yaw.value, returnPose.yaw),
    returnPose.pitch,
    1000,
    easeInOutCubic,
    finishClose,
    overviewCamera(),
  );
}

function onWindowKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && selectedId.value) {
    event.preventDefault();
    close();
  }
}

function onViewportResize() {
  if (!fullscreen.value) return;
  if (closing.value) {
    tweenTo(
      nearestTurn(yaw.value, returnPose.yaw),
      returnPose.pitch,
      300,
      easeInOutCubic,
      finishClose,
      overviewCamera(),
    );
  } else frameSelected(350);
}

watch(reduced, (value) => {
  if (!value) return;
  velocity = 0;
  phase.value = 'ready';
  const pending = tween;
  tween = null;
  if (pending) {
    yaw.value = pending.toYaw;
    pitch.value = pending.toPitch;
    if (pending.toCamera) camera.value = pending.toCamera;
    pending.done?.();
  }
});

// The points sit around the watch: four on the left, three on the right (on wide screens).
const placed = computed(() => {
  const left = points.value.filter((point) => point.side === 'left');
  const right = points.value.filter((point) => point.side === 'right');
  const spread = (list: WatchPoint[], from: number, to: number) =>
    list.map((point, index) => ({
      point,
      top: list.length === 1 ? (from + to) / 2 : from + ((to - from) * index) / (list.length - 1),
    }));
  return [...spread(left, 12, 72), ...spread(right, 20, 64)].map((entry, order) => ({
    ...entry,
    order,
  }));
});

// ---- Leader lines, measured in pixels so they meet each dot exactly ----
const card = ref<HTMLDialogElement | null>(null);
const cardSize = ref({ width: 0, height: 0 });
const leaders = ref<{ id: string; d: string; order: number; endX: number; endY: number }[]>([]);
const dots = new Map<string, HTMLElement>();
function setDot(id: string, element: unknown) {
  if (element instanceof HTMLElement) dots.set(id, element);
  else dots.delete(id);
}

/** Where an element sits inside the card, ignoring transforms (the points slide in). */
function offsetIn(element: HTMLElement, container: HTMLElement) {
  let x = element.offsetWidth / 2;
  let y = element.offsetHeight / 2;
  let node: HTMLElement | null = element;
  while (node && node !== container) {
    x += node.offsetLeft;
    y += node.offsetTop;
    node = node.offsetParent as HTMLElement | null;
  }
  return { x, y };
}

function measure() {
  const container = card.value;
  if (!container) return;
  const width = container.clientWidth;
  const height = container.clientHeight;
  cardSize.value = { width, height };
  // Phones lay the points out in a grid with no lines.
  if (width < 992) {
    leaders.value = [];
    return;
  }
  const centreX = width / 2;
  const centreY = (height - 90) / 2;
  const bySide = { left: 0, right: 0 };
  const counts = {
    left: placed.value.filter((entry) => entry.point.side === 'left').length,
    right: placed.value.filter((entry) => entry.point.side === 'right').length,
  };
  leaders.value = placed.value.flatMap((entry) => {
    const dot = dots.get(entry.point.id);
    if (!dot) return [];
    const side = entry.point.side;
    const index = bySide[side]++;
    const share = counts[side] > 1 ? index / (counts[side] - 1) : 0.5;
    const from = offsetIn(dot, container);
    const sign = side === 'left' ? -1 : 1;
    // Each line ends on the watch's edge, spread down its height.
    const end = { x: centreX + sign * 112, y: centreY - 96 + share * 192 };
    // A soft curve: out level from the point, then easing into the watch.
    const pull = Math.abs(end.x - from.x) * 0.55;
    return [
      {
        id: entry.point.id,
        order: entry.order,
        d: `M ${from.x} ${from.y} C ${from.x - sign * pull} ${from.y}, ${end.x + sign * pull * 0.5} ${end.y}, ${end.x} ${end.y}`,
        endX: end.x,
        endY: end.y,
      },
    ];
  });
}

let resizeObserver: ResizeObserver | null = null;

onMounted(async () => {
  window.addEventListener('keydown', onWindowKey);
  window.addEventListener('resize', onViewportResize);
  frameId = requestAnimationFrame(frame);
  await load();
  if (!alive) return;
  await nextTick();
  if (!alive) return;
  if (card.value) {
    resizeObserver = new ResizeObserver(() => measure());
    resizeObserver.observe(card.value);
  }
  measure();
  if (!fullscreen.value && phase.value === 'waiting') startIntro();
});

onBeforeUnmount(() => {
  alive = false;
  tween = null;
  if (fullscreen.value) {
    card.value?.close();
    document.documentElement.style.overflow = previousOverflow;
  }
  window.removeEventListener('resize', onViewportResize);
  cancelAnimationFrame(frameId);
  window.removeEventListener('keydown', onWindowKey);
  resizeObserver?.disconnect();
});

const RING = 2 * Math.PI * 22;
</script>

<template>
  <div class="watch-page">
    <header class="watch-head">
      <div>
        <h1 class="watch-title">Watch</h1>
        <p class="watch-sub mb-0">
          {{ elder }}’s day, at a glance. <span class="sim-label">Simulated watch</span>
        </p>
      </div>
      <!-- The watch battery, shown as a ring (the Battery point has the details). -->
      <div
        v-if="!noSenior"
        class="battery-chip"
        role="img"
        :aria-label="`Watch battery ${battery ?? 'not known'}${battery === null ? '' : '%'}`"
        data-testid="watch-battery"
      >
        <svg viewBox="0 0 50 50" class="battery-ring" aria-hidden="true">
          <circle cx="25" cy="25" r="22" class="track" />
          <circle
            cx="25"
            cy="25"
            r="22"
            class="fill"
            :stroke-dasharray="RING"
            :stroke-dashoffset="RING * (1 - (battery ?? 0) / 100)"
          />
        </svg>
        <span class="battery-figure" aria-hidden="true">{{ battery ?? '—' }}<small>%</small></span>
      </div>
    </header>

    <p v-if="noSenior" class="sl-note" data-testid="watch-no-senior">
      No senior is linked to this family group yet, so there is no watch to show.
    </p>

    <div v-else ref="sceneHome" :style="homeHeight ? { height: `${homeHeight}px` } : undefined">
      <dialog
        open
        ref="card"
        class="stage-card"
        :class="{
          'is-entered': phase !== 'waiting',
          'is-ready': phase === 'ready',
          'is-zoomed': fullscreen,
          'is-closing': closing,
          'is-dragging': dragging,
        }"
        :role="fullscreen ? 'dialog' : 'region'"
        :aria-modal="fullscreen || undefined"
        :aria-label="fullscreen ? `${selected?.label} — Simulated watch` : 'The watch in 3D'"
        @cancel.prevent="close"
        data-testid="watch-stage"
      >
        <div class="zoom-backdrop" aria-hidden="true"></div>
        <template v-if="fullscreen">
          <span class="zoom-label">Simulated watch</span>
        </template>

        <!-- Opened: the battery stays in view, top right, as in the overview. -->
        <div
          v-if="selected && selected.id !== 'battery'"
          class="zoom-battery"
          role="img"
          :aria-label="`Watch battery ${battery ?? 'not known'}${battery === null ? '' : '%'}`"
        >
          <svg viewBox="0 0 50 50" class="battery-ring" aria-hidden="true">
            <circle cx="25" cy="25" r="22" class="track" />
            <circle
              cx="25"
              cy="25"
              r="22"
              class="fill"
              :stroke-dasharray="RING"
              :stroke-dashoffset="RING * (1 - (battery ?? 0) / 100)"
            />
          </svg>
          <span class="battery-figure" aria-hidden="true"
            >{{ battery ?? '—' }}<small>%</small></span
          >
        </div>

        <!-- Leader lines from each point to the watch. -->
        <svg
          class="leaders"
          :viewBox="`0 0 ${cardSize.width || 1} ${cardSize.height || 1}`"
          aria-hidden="true"
        >
          <g v-for="line in leaders" :key="line.id">
            <path
              :d="line.d"
              pathLength="1"
              :style="{ transitionDelay: `${line.order * 90 + 150}ms` }"
            />
            <circle
              :cx="line.endX"
              :cy="line.endY"
              r="3.5"
              class="leader-end"
              :style="{ transitionDelay: `${line.order * 90 + 800}ms` }"
            />
          </g>
        </svg>

        <ul class="callouts list-unstyled mb-0" :inert="fullscreen">
          <li
            v-for="entry in placed"
            :key="entry.point.id"
            class="callout-item"
            :class="`side-${entry.point.side}`"
            :style="{ '--top': `${entry.top}%`, transitionDelay: `${entry.order * 90}ms` }"
          >
            <button
              type="button"
              class="callout"
              :data-testid="`watch-point-${entry.point.id}`"
              :aria-label="`${entry.point.label}: ${entry.point.value}. Show details`"
              @click="open(entry.point, $event)"
            >
              <span class="callout-icon"><Icon :name="iconOf(entry.point.icon)" /></span>
              <span class="callout-text">
                <strong>{{ entry.point.label }}</strong>
                <span>{{ entry.point.value }}</span>
                <small v-if="entry.point.example" class="example-caption">Example spec</small>
              </span>
              <span
                :ref="(element) => setDot(entry.point.id, element)"
                class="callout-dot"
                aria-hidden="true"
              ></span>
            </button>
          </li>
        </ul>

        <div
          ref="stage"
          class="stage"
          :inert="fullscreen"
          :tabindex="fullscreen ? -1 : 0"
          role="slider"
          aria-label="Turn the watch"
          aria-valuemin="0"
          aria-valuemax="359"
          :aria-valuenow="turnedDegrees"
          :aria-valuetext="`Turned ${turnedDegrees} degrees`"
          aria-describedby="watch-turn-hint"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
          @keydown="onStageKey"
        >
          <div class="stage-zoom" :style="cameraStyle">
            <div class="stage-enter">
              <Watch3D
                :yaw="yaw"
                :pitch="pitch"
                :face="selected ? selected.id : 'home'"
                :steps="person?.signal.current_steps ?? null"
                :usual-steps="person?.baseline.median_steps ?? null"
                :day-label="pastDay ?? 'Today'"
                :step-bars="metrics.map((metric) => metric.steps)"
                :active-minutes="latest?.active_minutes ?? null"
                :sleep-label="
                  typeof latest?.sleep_hours === 'number' ? hoursLabel(latest.sleep_hours) : null
                "
                :wear-label="latest ? hoursLabel(latest.wear_hours) : null"
                :battery="battery"
                :charging="wearable?.charging ?? false"
                :connected="wearable?.connected ?? false"
                :time="clock"
                :docked="selected?.id === 'battery' && (wearable?.charging ?? false)"
                :band-open="selected?.view === 'back'"
              />
            </div>
          </div>
          <!-- A glowing halo under the watch: it fades in once the watch has spun in. -->
          <div class="orbit" aria-hidden="true">
            <svg viewBox="0 0 320 70" class="orbit-ring">
              <ellipse cx="160" cy="35" rx="150" ry="26" class="halo" />
            </svg>
            <span class="orbit-shadow"></span>
          </div>
        </div>

        <div class="controls" :inert="fullscreen">
          <div class="control-row">
            <button type="button" class="control" aria-label="Turn left" @click="turnBy(-45)">
              <Icon name="chevron-left" />
            </button>
            <button
              type="button"
              class="control control-main"
              :aria-label="autoSpin ? 'Stop turning' : 'Keep turning'"
              :aria-pressed="!autoSpin"
              :disabled="reduced"
              data-testid="watch-spin"
              @click="toggleSpin"
            >
              <Icon :name="autoSpin && !reduced ? 'pause' : 'play'" />
            </button>
            <button type="button" class="control" aria-label="Turn right" @click="turnBy(45)">
              <Icon name="chevron-right" />
            </button>
          </div>
          <button type="button" class="reset-control" @click="resetTurn">Reset view</button>
          <p id="watch-turn-hint" class="hint mb-0">
            <Icon name="hand" class="me-1" />Drag to rotate, or use the arrows
          </p>
        </div>

        <Transition name="detail">
          <WatchDetail
            v-if="selected && !closing"
            :key="selected.id"
            :point="selected"
            :elder="elder"
            @close="close"
          />
        </Transition>

        <p v-if="loading" class="loading-note" role="status">Reading the watch…</p>
      </dialog>
    </div>

    <!-- Looking after the watch: general tips; "Today" is the watch's real status. -->
    <section v-if="!noSenior" class="care-card" aria-labelledby="care-heading">
      <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
        <h2 id="care-heading" class="care-title mb-0">
          <Icon name="clock" class="me-2" />Maintenance timeline
        </h2>
        <span class="sl-note">Example care schedule</span>
        <span class="care-badge" :class="{ warn: care[0].what !== 'All good' }">
          <span class="dot" aria-hidden="true"></span
          >{{ care[0].what === 'All good' ? 'On track' : care[0].what }}
        </span>
        <button
          type="button"
          class="care-more ms-auto"
          :aria-expanded="careOpen"
          aria-controls="care-details"
          @click="careOpen = !careOpen"
        >
          {{ careOpen ? 'Hide details' : 'View details' }}
          <Icon name="chevron-right" class="ms-1 care-chevron" :class="{ open: careOpen }" />
        </button>
      </div>
      <ol class="care-line list-unstyled mb-0">
        <li
          v-for="(step, index) in care"
          :key="step.when"
          :class="{ now: step.now }"
          :style="{ '--i': index }"
        >
          <span class="care-dot" aria-hidden="true"></span>
          <strong>{{ step.when }}</strong>
          <span>{{ step.what }}</span>
        </li>
      </ol>
      <Transition name="care-open">
        <p v-if="careOpen" id="care-details" class="care-details mb-0">
          “Today” is how the watch is right now. The rest are general care tips for a watch like
          this one: wipe the sensors on the back with a soft, damp cloth every few months, check the
          battery still lasts the day, and give the strap and buttons a once-over each year.
        </p>
      </Transition>
    </section>

    <p class="mt-4 mb-0 sl-note d-flex align-items-center gap-2">
      <Icon name="shield-check" class="flex-shrink-0" />
      Simulated watch. Activity figures come from {{ elder }}’s available daily data. Device
      specifications and future maintenance tips are examples, labelled separately.
    </p>
  </div>
</template>

<style scoped>
.watch-page {
  --stage-h: 600px;
  --ease-premium: cubic-bezier(0.65, 0, 0.35, 1);
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
}

.watch-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.watch-title {
  margin: 0;
  font-size: clamp(2.4rem, 6vw, 3.4rem);
  font-weight: 800;
  letter-spacing: -0.03em;
}

.watch-sub {
  color: var(--sl-ink-soft);
}

.sim-label {
  display: inline-flex;
  white-space: nowrap;
  margin-left: 0.35rem;
  padding: 0.1rem 0.55rem;
  border-radius: 999px;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-size: 0.78rem;
  font-weight: 700;
}

/* The battery, top right: just the ring with the percentage in it. */
.battery-chip {
  position: relative;
  display: inline-grid;
  place-items: center;
  color: var(--sl-ink);
}

.battery-ring {
  width: 3.4rem;
  height: 3.4rem;
  transform: rotate(-90deg);
}

.battery-ring .track,
.battery-ring .fill {
  fill: none;
  stroke-width: 5;
}

.battery-ring .track {
  stroke: var(--sl-line);
}

.battery-ring .fill {
  stroke: var(--bs-success);
  stroke-linecap: round;
  transition: stroke-dashoffset 1.4s var(--ease-out);
}

.battery-figure {
  position: absolute;
  inset: 0;
  /* Number and % side by side, centred in the ring. */
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  text-align: center;
}

.battery-figure small {
  font-size: 0.6em;
}

/* ---- The stage ---- */
.stage-card {
  position: relative;
  min-height: var(--stage-h);
  overflow: hidden;
  border-radius: 28px;
  /* The watch sits on the page itself, in a soft pool of light. */
  background: radial-gradient(
    ellipse 42% 50% at 50% 46%,
    color-mix(in srgb, var(--sl-surface) 85%, transparent),
    transparent 75%
  );
  isolation: isolate;
}

.zoom-backdrop {
  position: absolute;
  inset: 0;
  z-index: 0;
  background:
    radial-gradient(ellipse 55% 70% at 72% 50%, #3d5a4b, transparent 70%),
    linear-gradient(120deg, #13201b, #1f3329 55%, #2c4538);
  opacity: 0;
  transition: opacity 0.9s var(--ease-premium);
}

.is-zoomed .zoom-backdrop {
  opacity: 1;
}

.stage {
  position: absolute;
  top: 0;
  left: 50%;
  z-index: 2;
  display: grid;
  place-items: center;
  width: 340px;
  height: calc(var(--stage-h) - 90px);
  margin-left: -170px;
  cursor: var(--sl-cur-spin);
  touch-action: pan-y;
  user-select: none;
  outline: none;
}

.stage:focus-visible {
  border-radius: 24px;
  box-shadow: 0 0 0 3px var(--bs-focus-ring-color, rgb(13 110 253 / 25%));
}

.is-dragging .stage {
  cursor: var(--sl-cur-grabbing);
}

.stage-zoom {
  position: relative;
  z-index: 1;
  transform-style: preserve-3d;
}

/* Opened: the watch glides to the right and comes closer. */
.is-zoomed .stage-zoom {
  will-change: transform;
}

.is-zoomed .stage {
  cursor: default;
}

/* Arriving: from small and soft to full size, while it spins. */
.stage-enter {
  opacity: 0;
  scale: 1.12;
  filter: blur(8px);
  transform: scale(0.82) translateY(24px);
  transition:
    opacity 1s ease,
    filter 1.2s ease,
    transform 1.6s var(--ease-out);
}

.is-entered .stage-enter {
  opacity: 1;
  filter: none;
  transform: none;
}

/*
 * A glowing halo under the watch, in the brand jade (so it suits light and dark mode). It fades in
 * once the watch has spun in, then glows gently; it glows a little brighter while you turn it.
 */
.orbit {
  --halo: color-mix(in srgb, var(--sl-jade) 75%, white);
  position: absolute;
  z-index: 0;
  bottom: 4px;
  left: 50%;
  width: 320px;
  height: 70px;
  margin-left: -160px;
  pointer-events: none;
  transition: opacity 0.8s ease;
}

.orbit-ring {
  position: absolute;
  inset: 0;
  overflow: visible;
}

.halo {
  fill: none;
  stroke: var(--halo);
  stroke-width: 2;
  opacity: 0;
  filter: drop-shadow(0 0 3px var(--halo)) drop-shadow(0 0 9px var(--halo));
  transition: filter 0.4s ease;
}

.orbit-shadow {
  position: absolute;
  top: 22px;
  left: 50%;
  width: 200px;
  height: 26px;
  margin-left: -100px;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgb(0 0 0 / 22%), transparent);
}

.is-ready .halo {
  animation:
    halo-in 1.2s ease-out both,
    halo-glow 4.5s ease-in-out 1.2s infinite;
}

@keyframes halo-in {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

@keyframes halo-glow {
  50% {
    opacity: 0.6;
  }
}

.is-dragging .halo {
  filter: drop-shadow(0 0 4px var(--halo)) drop-shadow(0 0 16px var(--halo));
}

.is-zoomed .orbit {
  opacity: 0;
}

/* ---- Points around the watch ---- */
.leaders {
  position: absolute;
  inset: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.leaders path {
  fill: none;
  stroke: var(--sl-ink-soft);
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  stroke-opacity: 0.45;
  stroke-width: 1.2;
  transition: stroke-dashoffset 0.9s var(--ease-out);
}

.is-ready .leaders path {
  stroke-dashoffset: 0;
}

.callout-item {
  position: absolute;
  top: var(--top);
  z-index: 3;
  width: min(220px, 20%);
  opacity: 0;
  visibility: hidden;
  filter: blur(4px);
  transition:
    opacity 0.6s ease,
    filter 0.6s ease,
    transform 0.8s var(--ease-out);
}

.side-left {
  left: max(2%, calc(50% - 470px));
  transform: translateX(-18px);
}

.side-right {
  right: max(2%, calc(50% - 470px));
  transform: translateX(18px);
}

.is-ready .callout-item {
  opacity: 1;
  visibility: visible;
  filter: none;
  transform: none;
}

.callout {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.7rem;
  width: 100%;
  padding: 0.55rem 0.7rem;
  border: 1px solid transparent;
  border-radius: 16px;
  background: transparent;
  color: var(--sl-ink);
  text-align: left;
  transition:
    background 0.25s ease,
    border-color 0.25s ease,
    transform 0.3s var(--ease-out),
    box-shadow 0.3s ease;
}

.side-right .callout {
  flex-direction: row-reverse;
  text-align: right;
}

.callout:hover,
.callout:focus-visible {
  border-color: var(--sl-line);
  background: var(--sl-surface);
  box-shadow: 0 10px 28px rgb(0 0 0 / 10%);
  transform: translateY(-2px);
}

.callout-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 2.2rem;
  height: 2.2rem;
  color: var(--sl-jade-deep);
  font-size: 1.55rem;
}

.callout-text {
  display: grid;
  min-width: 0;
  line-height: 1.25;
}

.callout-text strong {
  font-size: 0.95rem;
}

.callout-text span {
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
}

.example-caption {
  color: var(--sl-ink-soft);
  font-size: 0.72rem;
}

.callout-dot {
  position: absolute;
  top: 50%;
  width: 9px;
  height: 9px;
  margin-top: -4.5px;
  border: 2px solid var(--sl-surface);
  border-radius: 50%;
  background: var(--sl-jade-deep);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--sl-jade) 25%, transparent);
}

.side-left .callout-dot {
  right: -22px;
}

.side-right .callout-dot {
  left: -22px;
}

/* Opened: the points and controls step aside. */
.is-zoomed .callout-item,
.is-zoomed .leaders,
.is-zoomed .controls {
  opacity: 0;
  pointer-events: none;
  transition-delay: 0ms !important;
}

.is-zoomed .leaders path {
  transition-delay: 0ms !important;
}

/* ---- Controls under the watch ---- */
.controls {
  position: absolute;
  bottom: 6px;
  left: 50%;
  z-index: 3;
  display: grid;
  justify-items: center;
  gap: 0.4rem;
  transform: translateX(-50%);
  transition: opacity 0.5s ease;
}

.control-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.control {
  display: grid;
  place-items: center;
  width: 2.5rem;
  height: 2.5rem;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--sl-ink);
  transition:
    background 0.2s ease,
    transform 0.2s var(--ease-out);
}

.control:hover,
.control:focus-visible {
  background: var(--sl-jade-soft);
}

.control:active {
  transform: scale(0.92);
}

.control-main {
  width: 3rem;
  height: 3rem;
  border: 1px solid var(--sl-line);
  background: var(--sl-surface);
  box-shadow: 0 6px 18px rgb(0 0 0 / 10%);
}

.hint {
  display: inline-flex;
  align-items: center;
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
}

.loading-note {
  position: absolute;
  top: 1rem;
  left: 50%;
  z-index: 4;
  color: var(--sl-ink-soft);
  transform: translateX(-50%);
}

/* ---- The details panel arriving ---- */
.detail-enter-active {
  transition:
    opacity 0.7s ease 0.35s,
    transform 0.9s var(--ease-out) 0.35s;
}

.detail-leave-active {
  transition:
    opacity 0.35s ease,
    transform 0.45s ease;
}

.detail-enter-from {
  opacity: 0;
  transform: translateX(-32px);
}

.detail-leave-to {
  opacity: 0;
  transform: translateX(-16px);
}

/* ---- Watch care ---- */
.care-card {
  margin-top: 1.5rem;
  padding: 1.25rem 1.5rem 1.5rem;
  border: 1px solid var(--sl-line);
  border-radius: 24px;
  background: var(--sl-surface);
}

.care-title {
  display: flex;
  align-items: center;
  font-size: 1.2rem;
  font-weight: 800;
}

.care-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.15rem 0.65rem;
  border-radius: 999px;
  background: var(--bs-success-bg-subtle);
  color: var(--bs-success-text-emphasis);
  font-size: 0.8rem;
  font-weight: 700;
}

.care-badge.warn {
  background: var(--bs-warning-bg-subtle);
  color: var(--bs-warning-text-emphasis);
}

.care-badge .dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: currentcolor;
}

.care-line {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
}

/* The line joining the steps, drawn in from the left. */
.care-line::before {
  position: absolute;
  top: 9px;
  right: 12.5%;
  left: 12.5%;
  height: 2px;
  background: var(--sl-line);
  content: '';
  transform-origin: left;
  animation: draw 1.2s var(--ease-out) 0.4s both;
}

.care-line li {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 0.1rem;
  font-size: 0.9rem;
  text-align: center;
  animation: rise 0.7s var(--ease-out) both;
  animation-delay: calc(0.5s + var(--i) * 0.12s);
}

.care-line li span {
  color: var(--sl-ink-soft);
}

.care-dot {
  width: 20px;
  height: 20px;
  margin-bottom: 0.35rem;
  border: 3px solid var(--sl-surface);
  border-radius: 50%;
  background: var(--sl-line);
  box-shadow: 0 0 0 1px var(--sl-line);
}

.now .care-dot {
  background: var(--sl-jade-deep);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--sl-jade) 30%, transparent);
}

@keyframes draw {
  from {
    transform: scaleX(0);
  }
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
}

/* The end of each line, on the watch: a small dot that appears once the line arrives. */
.leader-end {
  fill: var(--sl-jade-deep);
  opacity: 0;
  transition: opacity 0.4s ease;
}

.is-ready .leader-end {
  opacity: 1;
}

.is-zoomed .leader-end {
  opacity: 0;
  transition-delay: 0ms !important;
}

/* Opened: the battery, top right, light on the dark stage. */
.zoom-battery {
  position: absolute;
  top: 1.25rem;
  right: 1.5rem;
  z-index: 5;
  display: inline-grid;
  place-items: center;
  padding: 0.3rem;
  border-radius: 50%;
  background: rgb(12 22 18 / 55%);
  backdrop-filter: blur(10px);
  color: #eef4f1;
  animation: rise-in 0.7s var(--ease-out) 0.6s both;
}

.zoom-battery .track {
  stroke: rgb(255 255 255 / 20%);
}

.zoom-battery .fill {
  stroke: #e9f2ee;
}

@keyframes rise-in {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
}

.care-more {
  display: inline-flex;
  align-items: center;
  padding: 0.3rem 0.9rem;
  border: 1px solid var(--sl-jade-deep);
  border-radius: 999px;
  background: transparent;
  color: var(--sl-jade-deep);
  font-size: 0.85rem;
  font-weight: 700;
  transition: background 0.2s ease;
}

.care-more:hover,
.care-more:focus-visible {
  background: var(--sl-jade-soft);
}

.care-chevron {
  transition: transform 0.3s var(--ease-out);
}

.care-chevron.open {
  transform: rotate(90deg);
}

.care-details {
  margin-top: 1.25rem;
  padding-top: 1rem;
  border-top: 1px solid var(--sl-line);
  color: var(--sl-ink-soft);
  font-size: 0.92rem;
}

.care-open-enter-active,
.care-open-leave-active {
  transition:
    opacity 0.35s ease,
    transform 0.35s var(--ease-out);
}

.care-open-enter-from,
.care-open-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

/* ---- Phones and small tablets: watch on top, points in a grid below ---- */
@media (max-width: 991.98px) {
  .watch-page {
    --stage-h: 440px;
  }

  .stage-card {
    min-height: 0;
    padding-bottom: 1rem;
    display: flex;
    flex-direction: column;
  }

  .stage {
    position: relative;
    top: auto;
    left: auto;
    order: 1;
    width: 100%;
    height: 400px;
    margin: 0;
  }

  .stage-enter {
    scale: 0.74;
  }

  .leaders {
    display: none;
  }

  .controls {
    position: relative;
    bottom: auto;
    left: auto;
    order: 2;
    margin-bottom: 1rem;
    transform: none;
  }

  .callouts {
    position: relative;
    z-index: 3;
    order: 3;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.5rem;
    padding: 0 1rem;
  }

  .callout-item {
    position: static;
    width: auto;
  }

  .side-right .callout {
    flex-direction: row;
    text-align: left;
  }

  .callout {
    border-color: var(--sl-line);
    background: var(--sl-surface);
  }

  .callout-dot {
    display: none;
  }

  /* Opened: the watch stays on top, a little closer; the details replace the points. */
  .is-zoomed .stage-zoom {
    will-change: transform;
  }

  .is-zoomed .callouts,
  .is-zoomed .controls {
    display: none;
  }

  /* The page's own battery ring is just above, so the copy inside the stage is not needed. */
  .zoom-battery {
    display: none;
  }

  .care-line {
    grid-template-columns: repeat(2, 1fr);
    row-gap: 1rem;
  }

  .care-line::before {
    display: none;
  }
}

@media (max-width: 575.98px) {
  .callouts {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  /* The halo is simply lit, without the gentle glow. */
  .is-ready .halo {
    animation: none;
    opacity: 1;
  }

  .stage-zoom,
  .stage-enter,
  .callout-item,
  .leaders path,
  .zoom-backdrop,
  .detail-enter-active,
  .detail-leave-active {
    transition: none !important;
  }

  .stage-enter,
  .callout-item {
    filter: none;
  }

  .care-line::before,
  .care-line li {
    animation: none;
  }
}

/* A non-modal dialog is the overview; showModal promotes the same scene to the top layer. */
.stage-card {
  width: 100%;
  max-width: none;
  max-height: none;
  margin: 0;
  padding: 0;
  border: 0;
  color: var(--sl-ink);
}
.stage-card::backdrop {
  background: transparent;
}
.stage-card.is-zoomed {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100dvh;
  min-height: 0;
  max-height: none;
  border-radius: 0;
  overflow-x: hidden;
  overflow-y: auto;
  background: transparent;
}
.is-zoomed .zoom-backdrop {
  position: fixed;
  background:
    radial-gradient(
      ellipse at 74% 44%,
      color-mix(in srgb, var(--sl-jade) 38%, var(--bs-dark)),
      transparent 75%
    ),
    var(--bs-dark);
}
.is-closing .zoom-backdrop {
  opacity: 0;
}
.is-zoomed .stage {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100dvh;
  margin: 0;
  pointer-events: none;
}
.is-zoomed .stage-enter {
  scale: 1;
}
.is-zoomed .callouts,
.is-zoomed .controls,
.is-zoomed .leaders {
  visibility: hidden;
}
.is-zoomed .zoom-battery {
  right: 1.5rem;
  top: 1rem;
}
.zoom-label {
  position: fixed;
  left: 2rem;
  top: 1.1rem;
  z-index: 6;
  color: var(--bs-white);
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.is-closing .zoom-label,
.is-closing .zoom-battery {
  visibility: hidden;
}
.reset-control {
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--sl-jade-deep);
  font-size: 0.8rem;
  text-decoration: underline;
  padding: 0.3rem 0.75rem;
}
@media (max-width: 991.98px) {
  .stage-card:not(.is-zoomed) {
    padding-bottom: 1rem;
  }
  .is-zoomed .zoom-battery {
    display: inline-flex;
    top: 0.8rem;
    right: 1rem;
    padding: 0.25rem;
    gap: 0;
  }
  .zoom-label {
    left: 1rem;
    top: 1.8rem;
    font-size: 0.68rem;
  }
}
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation: none !important;
    transition: none !important;
  }
}
</style>
