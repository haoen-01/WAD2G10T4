<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { SKY_COLOURS, type WeatherScene } from '@/lib/weather-scene';

/**
 * A moving sky behind the Home weather card, like a phone's weather app: the sun's glow, the moon
 * and stars at night, clouds drifting past, rain and drizzle falling (with drops on the glass),
 * lightning in a thunderstorm, haze and mist. It follows the forecast for the chosen area.
 *
 * It is decoration (hidden from screen readers: the card says the forecast in words). It leans a
 * little towards the pointer, and a tap on the card splashes. It stops when the card is off screen
 * or the tab is hidden, and stands still for anyone whose device asks for less motion. Plain CSS
 * and one canvas: no library.
 */
const props = defineProps<{ scene: WeatherScene }>();

const root = ref<HTMLElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const lean = ref({ x: 0, y: 0 });
const flashing = ref(false);
const width = ref(400);

const reduceMotion =
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const showSun = computed(
  () => props.scene.time === 'day' && ['clear', 'partly', 'haze'].includes(props.scene.sky),
);
const showMoon = computed(
  () => props.scene.time === 'night' && ['clear', 'partly'].includes(props.scene.sky),
);
const colours = computed(() => SKY_COLOURS[`${props.scene.sky}-${props.scene.time}`]);

/** The same clouds every time for the same sky: spread out, different sizes and speeds. */
const clouds = computed(() =>
  Array.from({ length: props.scene.clouds }, (_, i) => {
    const r = (n: number) => (((Math.sin((i + 1) * 12.9898 * n) * 43758.5453) % 1) + 1) % 1;
    const duration = (props.scene.windy ? 38 : 80) + r(1) * 50;
    return {
      top: `${-8 + r(2) * 48}%`,
      scale: 0.7 + r(3) * 0.8,
      duration: `${duration}s`,
      delay: `${-r(4) * duration}s`,
      opacity: 0.55 + r(5) * 0.4,
      x: r(6),
    };
  }),
);

const style = computed(() => ({
  '--sky-top': colours.value[0],
  '--sky-bottom': colours.value[1],
  '--sky-w': `${width.value}px`,
}));

const leanNear = computed(() => ({
  transform: `translate(${lean.value.x * 10}px, ${lean.value.y * 6}px)`,
}));
const leanFar = computed(() => ({
  transform: `translate(${lean.value.x * 18}px, ${lean.value.y * 5}px)`,
}));

// ---- Rain, drops on the glass and splashes, on one canvas ----

interface Drop {
  x: number;
  y: number;
  length: number;
  speed: number;
  alpha: number;
}
interface Bead {
  x: number;
  y: number;
  r: number;
  slide: number;
}
interface Ripple {
  x: number;
  y: number;
  age: number;
}

let drops: Drop[] = [];
let beads: Bead[] = [];
let ripples: Ripple[] = [];
let frame = 0;
let last = 0;
let visible = true;
let observer: IntersectionObserver | null = null;
let resizer: ResizeObserver | null = null;
let lightningTimer: number | null = null;

function size() {
  const element = canvas.value;
  const box = root.value?.getBoundingClientRect();
  if (!element || !box) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  element.width = Math.round(box.width * ratio);
  element.height = Math.round(box.height * ratio);
  element.getContext('2d')?.setTransform(ratio, 0, 0, ratio, 0, 0);
  width.value = box.width;
  seed(box.width, box.height);
}

function seed(w: number, h: number) {
  const rain = props.scene.rain;
  const perArea = rain === 0 ? 0 : rain === 1 ? 50 : rain === 2 ? 110 : 190;
  const count = Math.round((perArea * w * h) / (400 * 300));
  drops = Array.from({ length: count }, () => newDrop(w, Math.random() * h));
  beads =
    rain === 0
      ? []
      : Array.from({ length: rain === 1 ? 10 : 18 }, () => ({
          x: Math.random() * w,
          y: Math.random() * h,
          r: 1.5 + Math.random() * 3.5,
          slide: 0,
        }));
}

function newDrop(w: number, y = -20): Drop {
  const heavy = props.scene.rain === 3;
  const drizzle = props.scene.rain === 1;
  return {
    x: Math.random() * (w + 80) - 40,
    y,
    length: drizzle ? 6 + Math.random() * 6 : 12 + Math.random() * (heavy ? 20 : 12),
    speed: (drizzle ? 260 : heavy ? 720 : 520) * (0.75 + Math.random() * 0.5),
    alpha: (drizzle ? 0.35 : 0.45) * (0.5 + Math.random() * 0.5),
  };
}

function draw(now: number) {
  const element = canvas.value;
  const context = element?.getContext('2d');
  const box = root.value?.getBoundingClientRect();
  if (!element || !context || !box) return;
  const dt = last ? Math.min(0.05, (now - last) / 1000) : 0;
  last = now;
  const w = box.width;
  const h = box.height;
  context.clearRect(0, 0, w, h);

  // Falling rain: slanted lines, slanting more in the wind.
  const slant = props.scene.windy ? 0.35 : 0.12;
  context.lineCap = 'round';
  context.lineWidth = props.scene.rain === 3 ? 1.4 : 1;
  for (const drop of drops) {
    drop.y += drop.speed * dt;
    drop.x += drop.speed * dt * slant;
    if (drop.y - drop.length > h) {
      if (Math.random() < 0.25) ripples.push({ x: drop.x, y: h - 4 - Math.random() * 30, age: 0 });
      Object.assign(drop, newDrop(w));
    }
    context.strokeStyle = `rgba(255,255,255,${drop.alpha})`;
    context.beginPath();
    context.moveTo(drop.x, drop.y);
    context.lineTo(drop.x - drop.length * slant, drop.y - drop.length);
    context.stroke();
  }

  // Drops on the glass: still, now and then one slides down and a new one lands.
  for (const bead of beads) {
    if (bead.slide === 0 && Math.random() < dt * 0.08) bead.slide = 20 + Math.random() * 40;
    if (bead.slide > 0) {
      bead.y += bead.slide * dt;
      if (bead.y > h + 10)
        Object.assign(bead, { x: Math.random() * w, y: Math.random() * h * 0.6, slide: 0 });
    }
    const glow = context.createRadialGradient(
      bead.x - bead.r * 0.35,
      bead.y - bead.r * 0.35,
      0,
      bead.x,
      bead.y,
      bead.r,
    );
    glow.addColorStop(0, 'rgba(255,255,255,0.55)');
    glow.addColorStop(0.6, 'rgba(255,255,255,0.12)');
    glow.addColorStop(1, 'rgba(255,255,255,0.28)');
    context.fillStyle = glow;
    context.beginPath();
    context.arc(bead.x, bead.y, bead.r, 0, Math.PI * 2);
    context.fill();
  }

  // Splashes and taps: rings that widen and fade.
  ripples = ripples.filter((ripple) => ripple.age < 0.6);
  for (const ripple of ripples) {
    ripple.age += dt;
    const t = ripple.age / 0.6;
    context.strokeStyle = `rgba(255,255,255,${0.5 * (1 - t)})`;
    context.lineWidth = 1;
    context.beginPath();
    context.ellipse(ripple.x, ripple.y, 3 + t * 14, 1 + t * 4, 0, 0, Math.PI * 2);
    context.stroke();
  }

  const busy = drops.length > 0 || beads.length > 0 || ripples.length > 0;
  frame = busy && visible && !reduceMotion ? requestAnimationFrame(draw) : 0;
}

function start() {
  if (frame || !visible) return;
  last = 0;
  frame = requestAnimationFrame(draw);
}

function stop() {
  if (frame) cancelAnimationFrame(frame);
  frame = 0;
}

// ---- Lightning: a double flash now and then (never more than two in a second) ----

function scheduleLightning() {
  if (lightningTimer !== null) window.clearTimeout(lightningTimer);
  lightningTimer = null;
  if (!props.scene.lightning || reduceMotion) return;
  lightningTimer = window.setTimeout(
    () => {
      if (visible) {
        flashing.value = true;
        window.setTimeout(() => (flashing.value = false), 90);
        window.setTimeout(() => (flashing.value = true), 240);
        window.setTimeout(() => (flashing.value = false), 320);
      }
      scheduleLightning();
    },
    5000 + Math.random() * 6000,
  );
}

// ---- Leaning towards the pointer, and splashing where the card is tapped ----

let card: HTMLElement | null = null;

function onMove(event: PointerEvent) {
  const box = root.value?.getBoundingClientRect();
  if (!box || reduceMotion) return;
  lean.value = {
    x: ((event.clientX - box.left) / box.width - 0.5) * 2,
    y: ((event.clientY - box.top) / box.height - 0.5) * 2,
  };
}

function onLeave() {
  lean.value = { x: 0, y: 0 };
}

function onTap(event: PointerEvent) {
  const box = root.value?.getBoundingClientRect();
  if (!box || reduceMotion) return;
  for (let i = 0; i < 3; i += 1) {
    ripples.push({ x: event.clientX - box.left, y: event.clientY - box.top, age: -i * 0.12 });
  }
  start();
}

function onVisibility() {
  visible = document.visibilityState === 'visible';
  if (visible) start();
  else stop();
}

onMounted(() => {
  size();
  card = root.value?.parentElement ?? null;
  card?.addEventListener('pointermove', onMove);
  card?.addEventListener('pointerleave', onLeave);
  card?.addEventListener('pointerdown', onTap);
  document.addEventListener('visibilitychange', onVisibility);
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    resizer = new ResizeObserver(size);
    resizer.observe(root.value);
  }
  if (typeof IntersectionObserver !== 'undefined' && root.value) {
    observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting && document.visibilityState === 'visible';
      if (visible) start();
      else stop();
    });
    observer.observe(root.value);
  }
  // Less motion: draw the rain once, standing still.
  if (reduceMotion) requestAnimationFrame(draw);
  else start();
  scheduleLightning();
});

onBeforeUnmount(() => {
  stop();
  if (lightningTimer !== null) window.clearTimeout(lightningTimer);
  card?.removeEventListener('pointermove', onMove);
  card?.removeEventListener('pointerleave', onLeave);
  card?.removeEventListener('pointerdown', onTap);
  document.removeEventListener('visibilitychange', onVisibility);
  observer?.disconnect();
  resizer?.disconnect();
});

watch(
  () => props.scene,
  () => {
    size();
    stop();
    if (reduceMotion) requestAnimationFrame(draw);
    else start();
    scheduleLightning();
  },
);
</script>

<template>
  <div
    ref="root"
    class="sky"
    :class="[`sky-${scene.sky}`, `is-${scene.time}`, { 'is-windy': scene.windy }]"
    :style="style"
    aria-hidden="true"
  >
    <div class="sky-lights" :style="leanNear">
      <div v-if="showSun" class="sky-sun"></div>
      <template v-if="showMoon">
        <div class="sky-stars"></div>
        <div class="sky-moon"></div>
      </template>
    </div>

    <div class="sky-clouds" :style="leanFar">
      <span
        v-for="(cloud, index) in clouds"
        :key="index"
        class="sky-cloud"
        :style="{
          top: cloud.top,
          '--scale': cloud.scale,
          '--opacity': cloud.opacity,
          '--x': cloud.x,
          animationDuration: cloud.duration,
          animationDelay: cloud.delay,
        }"
      ></span>
    </div>

    <div v-if="scene.sky === 'fog' || scene.sky === 'haze'" class="sky-mist">
      <span></span>
      <span></span>
    </div>

    <canvas ref="canvas" class="sky-canvas"></canvas>
    <div v-if="scene.lightning" class="sky-flash" :class="{ 'is-on': flashing }"></div>
    <!-- Darkens the lower part a little, so the words stay easy to read over clouds. -->
    <div class="sky-scrim"></div>
  </div>
</template>

<style scoped>
.sky {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  border-radius: inherit;
  background: linear-gradient(180deg, var(--sky-top), var(--sky-bottom));
  pointer-events: none;
  transition: background 0.6s ease;
}

.sky-lights,
.sky-clouds {
  position: absolute;
  inset: 0;
  transition: transform 0.8s cubic-bezier(0.2, 0.8, 0.2, 1);
}

/* ---- Sun: a bright core with a soft glow that breathes ---- */
/* Mostly off the top corner, so its glow lights the sky without sitting behind the words. */
.sky-sun {
  position: absolute;
  top: -5rem;
  right: -4rem;
  width: 11rem;
  height: 11rem;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgb(255 252 235 / 95%) 0 14%,
    rgb(255 236 170 / 55%) 24%,
    rgb(255 225 140 / 18%) 46%,
    transparent 70%
  );
  animation: sun-breathe 7s ease-in-out infinite;
}

.sky-haze .sky-sun {
  opacity: 0.55;
  filter: blur(4px);
}

.sky-partly .sky-sun {
  opacity: 0.85;
}

/* ---- Night: the moon and a sprinkle of stars that twinkle ---- */
/* Between the heading and the Refresh button. */
.sky-moon {
  position: absolute;
  top: 1.1rem;
  right: 9.5rem;
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  background: #f4f1e4;
  box-shadow:
    inset -0.55rem -0.2rem 0 0 #d9d4bf,
    0 0 1.5rem 0.4rem rgb(244 241 228 / 25%);
}

.sky-stars {
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(1px 1px at 12% 18%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 28% 42%, #fff 50%, transparent 51%),
    radial-gradient(1.5px 1.5px at 44% 12%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 58% 30%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 70% 8%, #fff 50%, transparent 51%),
    radial-gradient(1.5px 1.5px at 18% 66%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 52% 58%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 86% 48%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 36% 80%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 92% 74%, #fff 50%, transparent 51%);
  opacity: 0.8;
  animation: twinkle 4s ease-in-out infinite alternate;
}

/* ---- Clouds: soft puffs drifting across, from left to right ---- */
/* Thin enough that white words over a cloud stay readable. */
.sky-cloud {
  --cloud: rgb(255 255 255 / 55%);

  position: absolute;
  left: 0;
  width: 10rem;
  height: 3rem;
  border-radius: 999px;
  background: var(--cloud);
  opacity: var(--opacity);
  filter: blur(1.5px);
  animation-name: drift;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
}

.sky-cloud::before,
.sky-cloud::after {
  position: absolute;
  bottom: 35%;
  border-radius: 50%;
  background: inherit;
  content: '';
}

.sky-cloud::before {
  left: 18%;
  width: 4.2rem;
  height: 4.2rem;
}

.sky-cloud::after {
  left: 46%;
  width: 3.2rem;
  height: 3.2rem;
}

.is-night .sky-cloud {
  --cloud: rgb(150 165 185 / 45%);
}

.sky-cloudy .sky-cloud,
.sky-fog .sky-cloud {
  --cloud: rgb(225 232 240 / 45%);
}

.sky-rain .sky-cloud {
  --cloud: rgb(160 172 186 / 55%);
}

.sky-storm .sky-cloud {
  --cloud: rgb(70 80 95 / 85%);
}

.is-night.sky-rain .sky-cloud,
.is-night.sky-storm .sky-cloud,
.is-night.sky-cloudy .sky-cloud {
  --cloud: rgb(70 82 98 / 70%);
}

/* ---- Haze and mist: pale bands sliding slowly ---- */
.sky-mist span {
  position: absolute;
  left: -50%;
  width: 200%;
  height: 45%;
  background: linear-gradient(
    90deg,
    transparent,
    rgb(255 255 255 / 16%) 30%,
    rgb(255 255 255 / 22%) 50%,
    rgb(255 255 255 / 12%) 70%,
    transparent
  );
  filter: blur(8px);
  animation: mist 26s ease-in-out infinite alternate;
}

.sky-mist span:first-child {
  top: 20%;
}

.sky-mist span:last-child {
  top: 58%;
  animation-duration: 34s;
  animation-direction: alternate-reverse;
}

.sky-haze .sky-mist span {
  background: linear-gradient(
    90deg,
    transparent,
    rgb(230 205 150 / 16%) 40%,
    rgb(230 205 150 / 10%) 70%,
    transparent
  );
}

.sky-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

/* ---- Lightning: the whole sky lights up for a moment ---- */
.sky-flash {
  position: absolute;
  inset: 0;
  background: radial-gradient(
    ellipse at 30% 0%,
    rgb(235 240 255 / 70%),
    rgb(200 210 255 / 25%) 60%
  );
  opacity: 0;
  transition: opacity 0.06s linear;
}

.sky-flash.is-on {
  opacity: 0.55;
}

.sky-scrim {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgb(0 0 0 / 0%) 25%, rgb(0 0 0 / 22%) 100%);
}

@keyframes drift {
  from {
    transform: translateX(-12rem) scale(var(--scale));
  }

  to {
    transform: translateX(calc(var(--sky-w) + 2rem)) scale(var(--scale));
  }
}

@keyframes sun-breathe {
  0%,
  100% {
    transform: scale(1);
    opacity: 0.95;
  }

  50% {
    transform: scale(1.06);
    opacity: 1;
  }
}

@keyframes twinkle {
  from {
    opacity: 0.55;
  }

  to {
    opacity: 0.95;
  }
}

@keyframes mist {
  from {
    transform: translateX(-8%);
  }

  to {
    transform: translateX(8%);
  }
}

/* Less motion: the sky stands still (the rain is drawn once, without falling). */
@media (prefers-reduced-motion: reduce) {
  .sky-sun,
  .sky-stars,
  .sky-cloud,
  .sky-mist span {
    animation: none;
  }

  .sky-cloud {
    transform: translateX(calc(var(--sky-w) * var(--x) - 5rem)) scale(var(--scale));
  }

  .sky-lights,
  .sky-clouds {
    transition: none;
  }
}
</style>
