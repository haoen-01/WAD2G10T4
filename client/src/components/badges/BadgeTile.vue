<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import BadgeCoin from '@/components/badges/BadgeCoin.vue';
import Icon from '@/components/ui/Icon.vue';
import type { ShelfBadge } from '@/composables/useBadges';
import { useCoinSpin } from '@/composables/useCoinSpin';
import { earnedWords } from '@/lib/badges';

/**
 * One badge on the shelf, with no box around it. Claimed: in colour; on hover the medal itself
 * lifts out and turns slowly to show the dates on its back, and a drag across it spins it by hand
 * (on a phone too). It settles face up when let go or left. Earned but not claimed: grey with a
 * gold rim and a Claim button. Not earned yet: grey, with how close she is. A tap or click opens
 * it up close; the drag has that same view's "Turn over" button as its equivalent.
 */
const props = defineProps<{
  badge: ShelfBadge;
  /** The senior claims her own badges; the family only looks. */
  canClaim: boolean;
  celebrating: boolean;
  /** Whose badge, for the engraving on the back. */
  owner: string;
  /** Up close in the viewer right now: the medal here makes way for it. */
  away: boolean;
}>();
const emit = defineEmits<{ open: [from: HTMLElement]; claim: [] }>();

const coin = ref<HTMLElement | null>(null);
const spin = useCoinSpin();
const won = computed(() => props.badge.state === 'claimed');
const hovered = ref(false);
const focused = ref(false);
/** A drag just ended: the click it would otherwise make is not a tap. */
let dragged = false;

function update() {
  if (won.value && (hovered.value || focused.value)) spin.auto();
  else spin.front();
}
function enter(event: PointerEvent) {
  if (event.pointerType !== 'mouse') return;
  hovered.value = true;
  update();
}
function leave() {
  hovered.value = false;
  update();
}
function focus(event: FocusEvent) {
  focused.value = (event.target as HTMLElement).matches(':focus-visible');
  update();
}
function blur() {
  focused.value = false;
  update();
}
watch(() => props.badge.state, update);
watch(
  () => props.away,
  (away) => {
    if (away) spin.reset();
  },
);

function down(event: PointerEvent) {
  if (won.value) spin.down(event);
}
function move(event: PointerEvent) {
  if (won.value) spin.move(event);
}
function up(event: PointerEvent) {
  if (spin.up(event)) dragged = true;
}
function open() {
  if (dragged) {
    dragged = false;
    return;
  }
  if (coin.value) emit('open', coin.value);
}

const percent = computed(() =>
  Math.round((100 * props.badge.progress.value) / Math.max(1, props.badge.progress.target)),
);

const status = computed(() => {
  if (props.badge.state === 'claimed') return `Earned ${earnedWords(props.badge)}`;
  if (props.badge.state === 'ready')
    return props.canClaim ? 'Ready to claim' : 'Earned, not claimed yet';
  return props.badge.progress.words;
});
</script>

<template>
  <li
    class="badge-tile"
    :class="[
      `is-${badge.state}`,
      { 'is-celebrating': celebrating, 'is-away': away, 'is-dragging': spin.dragging.value },
    ]"
    :data-testid="`badge-${badge.id}`"
    :data-state="badge.state"
  >
    <button
      type="button"
      class="tile-open"
      :aria-label="`${badge.name}. ${status}. Show it up close`"
      @click="open"
      @pointerenter="enter"
      @pointerleave="leave"
      @focus="focus"
      @blur="blur"
    >
      <span
        class="tile-stage"
        aria-hidden="true"
        @pointerdown="down"
        @pointermove="move"
        @pointerup="up"
        @pointercancel="up"
      >
        <span v-if="badge.state !== 'locked'" class="tile-halo"></span>
        <span v-if="celebrating" class="tile-burst">
          <span v-for="n in 10" :key="n" class="tile-spark" :style="{ '--i': n }"></span>
        </span>
        <span ref="coin" class="tile-coin">
          <BadgeCoin
            :badge="badge"
            :angle="spin.angle.value"
            :celebrate="celebrating"
            :owner="owner"
          />
        </span>
      </span>
      <span class="tile-name">{{ badge.name }}</span>
      <span class="tile-status">
        <Icon v-if="badge.state === 'locked'" name="lock" class="tile-lock" />{{ status }}
      </span>
      <span v-if="badge.state === 'locked'" class="tile-bar" aria-hidden="true">
        <span :style="{ width: `${percent}%` }"></span>
      </span>
    </button>
    <button
      v-if="badge.state === 'ready' && canClaim"
      type="button"
      class="btn tile-claim"
      :data-testid="`claim-${badge.id}`"
      @click="emit('claim')"
    >
      <Icon name="sparkle" /> Claim
    </button>
  </li>
</template>

<style scoped>
.badge-tile {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}
.tile-open {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  width: 100%;
  padding: 0.75rem 0.5rem 0.85rem;
  border: 0;
  background: transparent;
  color: var(--sl-ink);
  text-align: center;
  -webkit-tap-highlight-color: transparent;
}
.tile-open:focus {
  outline: none;
}
/* Keyboard focus rings the medal itself, not a box around the tile. */
.tile-open:focus-visible .tile-coin::after {
  content: '';
  position: absolute;
  inset: -8%;
  border-radius: 50%;
  outline: 3px solid var(--sl-focus);
  outline-offset: 2px;
}
.tile-stage {
  position: relative;
  display: block;
  width: min(100%, 9.5rem);
  aspect-ratio: 1;
}
.is-claimed .tile-stage {
  /* A sideways drag spins the medal; up and down still scrolls the page. */
  touch-action: pan-y;
  cursor: var(--sl-cur-spin);
}
.is-dragging .tile-stage {
  cursor: var(--sl-cur-grabbing);
}
.is-away .tile-coin,
.is-away .tile-halo {
  visibility: hidden;
}
.tile-coin {
  position: absolute;
  inset: 6%;
  z-index: 1;
  transition:
    transform 0.45s var(--sl-ease-spring),
    filter 0.45s var(--sl-ease);
}
.tile-name {
  font-weight: 800;
  line-height: 1.2;
  overflow-wrap: anywhere;
}
.tile-status {
  color: var(--sl-ink-soft);
  font-size: 0.85em;
  line-height: 1.3;
}
.tile-lock {
  width: 0.95em;
  height: 0.95em;
  margin-right: 0.25rem;
  vertical-align: -0.12em;
}
.tile-bar {
  display: block;
  width: 70%;
  height: 0.4rem;
  border-radius: 1rem;
  background: var(--sl-line);
  overflow: hidden;
}
.tile-bar > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #b0802a, #f2d488);
}
.is-locked .tile-name {
  color: var(--sl-ink-soft);
}

/* A soft gold light behind a badge that is won (or waiting to be claimed). */
.tile-halo {
  position: absolute;
  inset: 4%;
  border-radius: 50%;
  background: radial-gradient(circle, rgb(255 214 120 / 55%) 0%, rgb(255 214 120 / 0%) 68%);
  opacity: 0;
  transition: opacity 0.45s var(--sl-ease);
}
.is-ready .tile-halo {
  opacity: 0.7;
  animation: tile-pulse 2.6s ease-in-out infinite;
}
@keyframes tile-pulse {
  50% {
    opacity: 0.25;
    transform: scale(0.92);
  }
}

/* Claimed badges: hover, focus or a drag lifts the medal out (nothing else changes). */
@media (hover: hover) {
  .is-claimed .tile-open:hover .tile-coin {
    transform: translateY(-12px) scale(1.28);
    z-index: 3;
  }
  .is-claimed .tile-open:hover .tile-halo {
    opacity: 1;
  }
  .is-claimed .tile-open:hover :deep(.badge-sheen) {
    animation: tile-sheen 2.4s ease-in-out infinite;
  }
  .is-ready .tile-open:hover .tile-coin,
  .is-locked .tile-open:hover .tile-coin {
    transform: translateY(-4px) rotate(-3deg);
  }
}
.is-dragging .tile-coin,
.is-claimed .tile-open:focus-visible .tile-coin {
  transform: translateY(-10px) scale(1.2);
  z-index: 3;
}
.is-dragging .tile-halo,
.is-claimed .tile-open:focus-visible .tile-halo {
  opacity: 1;
}
@keyframes tile-sheen {
  0% {
    transform: translateX(0) rotate(22deg);
    opacity: 0;
  }
  20% {
    opacity: 1;
  }
  60%,
  100% {
    transform: translateX(300px) rotate(22deg);
    opacity: 0;
  }
}

.tile-claim {
  min-height: 48px;
  padding-inline: 1.4rem;
  border: 0;
  border-radius: 999px;
  background: linear-gradient(135deg, #f8e3a0, #c4953a 55%, #8a6418);
  color: #2e1f03;
  font-weight: 800;
  box-shadow:
    0 4px 12px rgb(138 100 24 / 35%),
    inset 0 1px 0 rgb(255 255 255 / 60%);
}
.tile-claim:hover {
  filter: brightness(1.06);
}
.tile-claim:focus-visible {
  outline: 3px solid var(--sl-focus);
  outline-offset: 2px;
}

/* Just claimed: two quick turns, a burst of gold light and a few sparks. */
.is-celebrating .tile-coin {
  z-index: 3;
  animation: tile-pop 1.6s var(--sl-ease) both;
}
.is-celebrating :deep(.coin-body) {
  animation: tile-claim-turn 1.6s cubic-bezier(0.2, 0.7, 0.2, 1) both;
}
.is-celebrating .tile-halo {
  opacity: 1;
  animation: tile-flare 1.6s var(--sl-ease) both;
}
@keyframes tile-pop {
  0% {
    transform: scale(1);
  }
  35% {
    transform: translateY(-12px) scale(1.25);
  }
  100% {
    transform: scale(1);
  }
}
@keyframes tile-claim-turn {
  from {
    transform: rotateY(0deg);
  }
  to {
    transform: rotateY(720deg);
  }
}
@keyframes tile-flare {
  0% {
    transform: scale(0.4);
    opacity: 0;
  }
  30% {
    transform: scale(1.35);
    opacity: 1;
  }
  100% {
    transform: scale(1);
    opacity: 0.6;
  }
}
.tile-burst {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
}
.tile-spark {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0.5rem;
  height: 0.5rem;
  margin: -0.25rem;
  border-radius: 50%;
  background: radial-gradient(circle, #fff7d6, #f2c14e 60%, transparent 70%);
  transform: rotate(calc(var(--i) * 36deg)) translateY(0);
  animation: tile-spark 1.1s var(--sl-ease) 0.15s both;
}
@keyframes tile-spark {
  0% {
    transform: rotate(calc(var(--i) * 36deg)) translateY(0) scale(0.4);
    opacity: 0;
  }
  25% {
    opacity: 1;
  }
  100% {
    transform: rotate(calc(var(--i) * 36deg)) translateY(-5.2rem) scale(1);
    opacity: 0;
  }
}
</style>
