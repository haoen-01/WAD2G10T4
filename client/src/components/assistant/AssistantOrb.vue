<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { glance, onLookChange, pointer, type Mood } from '@/composables/useAssistant';
import { ease, nextBlinkMs, pupilOffset, type Point } from '@/lib/assistant-geometry';

/**
 * Kaki's face: a dark glass orb with a slowly swirling rainbow rim and two soft white eyes that
 * follow the pointer. The eyes are moved straight on their elements each frame (no re-render), and
 * the frames stop once they have settled. Mood changes the look: thinking glances up and the rim
 * hurries; responding gives a small happy hop; an error tilts the eyes in concern; listening
 * widens them. With reduced motion the eyes stay centred and nothing bounces or swirls.
 */
const props = withDefaults(defineProps<{ size?: number; mood?: Mood; lifted?: boolean }>(), {
  size: 64,
  mood: 'idle',
  lifted: false,
});

const face = ref<HTMLElement | null>(null);
const eyes = ref<HTMLElement[]>([]);
const blinking = ref(false);
let frame = 0;
let blinkTimer = 0;
let openTimer = 0;
let alive = true;
let current: Point = { x: 0, y: 0 };
let reduced = false;

/** Where the eyes are looking: a glance, else the pointer, else ahead (or up, when thinking). */
function target(): Point | null {
  const now = performance.now();
  if (glance.until > now) return { x: glance.x, y: glance.y };
  if (pointer.known) return { x: pointer.x, y: pointer.y };
  return null;
}

function tick() {
  frame = 0;
  const box = face.value?.getBoundingClientRect();
  if (!box) return;
  const centre = { x: box.left + box.width / 2, y: box.top + box.height / 2 };
  const maxR = props.size * 0.075;
  let aim: Point = { x: 0, y: 0 };
  if (props.mood === 'thinking') {
    // Up and to the side, a little restless.
    const t = performance.now() / 700;
    aim = { x: Math.sin(t) * maxR * 0.8, y: -maxR * 0.85 };
  } else {
    const looking = target();
    if (looking) aim = pupilOffset(centre, looking, maxR, props.size * 2.5);
  }
  current = ease(current, aim, 0.18);
  const shift = `${current.x.toFixed(2)}px ${current.y.toFixed(2)}px`;
  for (const eye of eyes.value) eye.style.translate = shift;
  const settled = Math.hypot(aim.x - current.x, aim.y - current.y) < 0.05;
  const glancing = glance.until > performance.now();
  if (!settled || glancing || props.mood === 'thinking') frame = requestAnimationFrame(tick);
}

function wake() {
  if (reduced || frame) return;
  frame = requestAnimationFrame(tick);
}

function scheduleBlink() {
  if (!alive) return;
  blinkTimer = window.setTimeout(() => {
    blinking.value = true;
    openTimer = window.setTimeout(() => {
      blinking.value = false;
      scheduleBlink();
    }, 150);
  }, nextBlinkMs(Math.random()));
}

let stopWatching: () => void = () => {};
onMounted(() => {
  reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  if (reduced) return;
  stopWatching = onLookChange(wake);
  scheduleBlink();
  wake();
});

watch(
  () => props.mood,
  () => wake(),
);

onBeforeUnmount(() => {
  stopWatching();
  if (frame) cancelAnimationFrame(frame);
  alive = false;
  window.clearTimeout(blinkTimer);
  window.clearTimeout(openTimer);
});
</script>

<template>
  <span
    ref="face"
    class="orb"
    :class="[`is-${mood}`, { 'is-lifted': lifted, 'is-blinking': blinking }]"
    :style="{ '--orb': `${size}px` }"
    aria-hidden="true"
  >
    <span class="orb-glow"></span>
    <span class="orb-rim"></span>
    <span class="orb-rim orb-rim-2"></span>
    <span class="orb-glass"></span>
    <span class="orb-eyes">
      <span v-for="n in 2" :key="n" ref="eyes" class="orb-eye"></span>
    </span>
    <span class="orb-shine"></span>
  </span>
</template>

<style scoped>
.orb {
  --orb: 64px;
  position: relative;
  display: inline-block;
  width: var(--orb);
  height: var(--orb);
  flex: none;
  animation: orb-breathe 4.8s ease-in-out infinite;
  transition: translate 0.35s var(--sl-ease-spring);
}
.orb.is-lifted {
  translate: 0 -3px;
}

/* A soft coloured light around it, and the swirling rainbow rim. */
.orb-glow {
  position: absolute;
  inset: -14%;
  border-radius: 50%;
  background: conic-gradient(
    from var(--orb-turn, 0deg),
    rgb(255 95 109 / 45%),
    rgb(255 195 113 / 40%),
    rgb(71 229 188 / 40%),
    rgb(79 172 254 / 45%),
    rgb(166 108 255 / 40%),
    rgb(255 95 109 / 45%)
  );
  filter: blur(calc(var(--orb) * 0.14));
  opacity: 0.55;
  animation: orb-swirl 9s linear infinite;
}
.orb-rim {
  position: absolute;
  inset: 0;
  border-radius: 47% 53% 51% 49% / 52% 47% 53% 48%;
  background: conic-gradient(
    from var(--orb-turn, 0deg),
    #ff5f6d,
    #ffc371,
    #47e5bc,
    #4facfe,
    #a66cff,
    #ff5f6d
  );
  -webkit-mask: radial-gradient(circle, transparent 58%, #000 62%, #000 70%, transparent 74%);
  mask: radial-gradient(circle, transparent 58%, #000 62%, #000 70%, transparent 74%);
  filter: blur(calc(var(--orb) * 0.025));
  animation:
    orb-swirl 6s linear infinite,
    orb-wobble 7s ease-in-out infinite;
}
.orb-rim-2 {
  inset: 4%;
  opacity: 0.6;
  filter: blur(calc(var(--orb) * 0.05));
  animation:
    orb-swirl 8s linear infinite reverse,
    orb-wobble 5s ease-in-out infinite reverse;
}
/* The dark glass sphere, lit from the top left. */
.orb-glass {
  position: absolute;
  inset: 12%;
  border-radius: 50%;
  background:
    radial-gradient(circle at 34% 28%, rgb(120 200 210 / 45%), transparent 42%),
    radial-gradient(circle at 70% 78%, rgb(80 220 160 / 22%), transparent 45%),
    radial-gradient(circle at 50% 50%, #17343b, #08161b 70%, #040a0d);
  box-shadow:
    inset 0 calc(var(--orb) * -0.06) calc(var(--orb) * 0.12) rgb(0 0 0 / 55%),
    inset 0 calc(var(--orb) * 0.04) calc(var(--orb) * 0.08) rgb(255 255 255 / 12%),
    0 calc(var(--orb) * 0.08) calc(var(--orb) * 0.2) rgb(4 12 16 / 35%);
}
.orb-shine {
  position: absolute;
  top: 18%;
  left: 24%;
  width: 26%;
  height: 14%;
  border-radius: 50%;
  background: rgb(255 255 255 / 28%);
  filter: blur(calc(var(--orb) * 0.02));
  transform: rotate(-24deg);
  pointer-events: none;
}

/* The eyes: two soft white pills. Each moves as a whole to look. */
.orb-eyes {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: calc(var(--orb) * 0.13);
  transition: transform 0.3s var(--sl-ease);
}
.orb-eye {
  width: calc(var(--orb) * 0.1);
  height: calc(var(--orb) * 0.22);
  border-radius: 999px;
  background: #fff;
  box-shadow: 0 0 calc(var(--orb) * 0.08) rgb(255 255 255 / 55%);
  transition:
    transform 0.12s ease,
    height 0.25s var(--sl-ease),
    rotate 0.3s var(--sl-ease);
}
.is-blinking .orb-eye {
  transform: scaleY(0.12);
}
.is-listening .orb-eye {
  height: calc(var(--orb) * 0.27);
}
.is-error .orb-eye:first-child {
  rotate: 14deg;
}
.is-error .orb-eye:last-child {
  rotate: -14deg;
}
.is-error .orb-eyes {
  transform: translateY(calc(var(--orb) * 0.03));
}
.is-thinking .orb-rim {
  animation-duration: 2.2s, 7s;
}
.is-responding,
.is-success {
  animation: orb-hop 0.7s var(--sl-ease-spring);
}
.is-listening .orb-glow {
  opacity: 0.9;
  animation:
    orb-swirl 3s linear infinite,
    orb-pulse 1.1s ease-in-out infinite;
}

@property --orb-turn {
  syntax: '<angle>';
  inherits: true;
  initial-value: 0deg;
}
@keyframes orb-swirl {
  to {
    --orb-turn: 360deg;
  }
}
@keyframes orb-wobble {
  0%,
  100% {
    border-radius: 47% 53% 51% 49% / 52% 47% 53% 48%;
  }
  50% {
    border-radius: 53% 47% 48% 52% / 47% 53% 48% 52%;
  }
}
@keyframes orb-breathe {
  0%,
  100% {
    scale: 1;
  }
  50% {
    scale: 1.035;
  }
}
@keyframes orb-hop {
  30% {
    translate: 0 -18%;
    scale: 1.06 0.96;
  }
  60% {
    translate: 0 0;
    scale: 0.97 1.03;
  }
}
@keyframes orb-pulse {
  50% {
    scale: 1.12;
  }
}
@media (prefers-reduced-motion: reduce) {
  .orb,
  .orb-glow,
  .orb-rim,
  .orb-rim-2 {
    animation: none;
  }
}
</style>
