<script setup lang="ts">
import { computed } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import type { WatchPointId } from '@/lib/watch';

/**
 * The simulated watch, drawn in 3D with CSS alone (no 3D library): `transform-style: preserve-3d`
 * with layered slices for the case's thickness, a strap of hinged segments that curls back the way
 * a real strap does, a crown, a back with its sensors, and a charger that docks on the back.
 *
 * It only draws. The page turns it (`yaw`, `pitch`) and picks what the screen shows (`face`).
 * Every figure on the screen comes from the props, so the watch shows the senior's real readings.
 */
const props = defineProps<{
  /** Degrees around the upright axis. */
  yaw: number;
  /** Degrees tipped back (negative) or forward. */
  pitch: number;
  /** What the screen shows: the day at a glance, or one point's own screen. */
  face: 'home' | WatchPointId;
  steps: number | null;
  usualSteps: number | null;
  /** Recent days of steps, oldest first, for the little chart on the screen. */
  stepBars: number[];
  activeMinutes: number | null;
  sleepLabel: string | null;
  wearLabel: string | null;
  battery: number | null;
  charging: boolean;
  connected: boolean;
  /** The time on the watch, e.g. "2:11". */
  time: string;
  /** Docks the charger on the back. */
  docked: boolean;
  /** Fades out the back of the band, so the back of the watch can be seen. */
  bandOpen?: boolean;
  /** The day the figures are from, under the step count. "Today" unless they are older. */
  dayLabel?: string;
}>();

// ---- Sizes, in px (the page scales the whole scene) ----
const W = 184;
const H = 220;
const DEPTH = 34;
/** How far the case's edge rounds off towards the glass and the back. */
const EDGE = 9;
const SLICES = 26;
const STRAP_W = 124;
/**
 * The band is one closed, slightly oval loop round the watch, as it sits in a product shot: up from
 * the top of the case, over and down the back, and round under the bottom. `LOOP_RY` is half its height,
 * `LOOP_RZ` half its depth.
 */
const LOOP_RY = 150;
const LOOP_RZ = 84;
/** The middle of the whole watch, front to back: halfway between the glass and the back of the band.
 * The watch turns round this point, not round the case. */
const CENTRE_Z = (DEPTH / 2 + 1 + (-3 - 2 * LOOP_RZ)) / 2;
const LOOP_STEP = 6;

/**
 * The case: thin slices through its depth. Towards the glass and the back each slice is a little
 * smaller, so the edge rounds off like a real case, and each is lit by how much it faces outwards
 * (brightest round the middle, where the polished edge catches the light).
 */
const slices = Array.from({ length: SLICES }, (_, i) => {
  const t = -1 + (2 * i) / (SLICES - 1);
  const round = Math.sqrt(Math.max(0, 1 - Math.min(0.94, t * t)));
  const inset = EDGE * (1 - round);
  return {
    z: (t * DEPTH) / 2,
    width: W - 2 * inset,
    height: H - 2 * inset,
    radius: 54 - inset,
    light: (0.72 + 0.4 * round).toFixed(3),
  };
});
const FACE_W = slices[slices.length - 1].width;
const FACE_H = slices[slices.length - 1].height;

/**
 * The band, in short segments round the oval. It starts and ends just inside the case's outline,
 * so it seems to come out from under it. Each segment sits on the oval, turned along it, and is
 * shaded by how far round it has gone (brightest facing you, darkest at the back). Holes run along
 * the lower half, as on a sport band.
 */
function band() {
  const start = (Math.asin((H / 2 - 20) / LOOP_RY) * 180) / Math.PI;
  const segments = [];
  for (let degrees = start; degrees < 360 - start; degrees += LOOP_STEP) {
    const mid = ((degrees + LOOP_STEP / 2) * Math.PI) / 180;
    const y = -LOOP_RY * Math.sin(mid);
    const z = -3 - LOOP_RZ * (1 - Math.cos(mid));
    // Along the oval: the direction it is heading at this point.
    const dy = -LOOP_RY * Math.cos(mid);
    const dz = -LOOP_RZ * Math.sin(mid);
    const turn = (Math.atan2(dz, dy) * 180) / Math.PI;
    const length = Math.hypot(dy, dz) * ((LOOP_STEP * Math.PI) / 180) * 1.3;
    const index = Math.round((degrees - start) / LOOP_STEP);
    segments.push({
      height: length,
      transform: `translate3d(0, ${y.toFixed(2)}px, ${z.toFixed(2)}px) rotateX(${turn.toFixed(2)}deg)`,
      light: (0.78 + 0.27 * Math.max(0, Math.cos(mid))).toFixed(3),
      holes: degrees > 190 && degrees < 290 && index % 2 === 0,
      end: false,
      // The half of the loop behind the watch, which would hide its back.
      behind: Math.cos(mid) < 0.25,
    });
  }
  return segments;
}
const straps = band();

/** The crown: ridged discs side by side along the right edge. */
const crown = Array.from({ length: 10 }, (_, i) => W / 2 - 2 + i * 1.6);

const modelStyle = computed(() => ({
  // Read right to left: the watch leans on its stand (`pitch`, a slight slant), the stand turns
  // round its upright axis like a turntable (`yaw`), and we look down on it a little, matching
  // the halo beneath it.
  // The outer `translateZ` pair moves the turning point to the middle of the whole watch (case and
  // band), keeping it at the same distance from the viewer.
  transform: `translateZ(${CENTRE_Z}px) rotateX(10deg) rotateY(${props.yaw}deg) rotateZ(4deg) rotateX(${props.pitch}deg) translateZ(${-CENTRE_Z}px)`,
  // The glass's reflection slides as the watch turns.
  '--glare': `${50 + Math.sin((props.yaw * Math.PI) / 180) * 60}%`,
}));

// ---- The screen ----
const RING = 2 * Math.PI * 40;
const stepShare = computed(() =>
  props.steps === null || !props.usualSteps ? 0 : Math.min(1, props.steps / props.usualSteps),
);
const batteryShare = computed(() => (props.battery ?? 0) / 100);
const bars = computed(() => {
  const values = props.stepBars.slice(-14);
  const top = Math.max(1, ...values);
  return values.map((value) => Math.max(0.08, value / top));
});
const stepsText = computed(() =>
  props.steps === null ? '—' : new Intl.NumberFormat('en-SG').format(props.steps),
);
</script>

<template>
  <div class="scene" aria-hidden="true">
    <div class="model" :style="modelStyle">
      <!-- Straps first, so the case sits over where they join. -->
      <div
        v-for="segment in straps"
        :key="segment.transform"
        class="strap"
        :class="{ end: segment.end, behind: segment.behind && bandOpen }"
        :style="{
          width: `${STRAP_W}px`,
          height: `${segment.height}px`,
          marginLeft: `${-STRAP_W / 2}px`,
          marginTop: `${-segment.height / 2}px`,
          transform: segment.transform,
          filter: `brightness(${segment.light})`,
        }"
      >
        <span v-if="segment.holes" class="hole"></span>
      </div>

      <!-- The case: slices give it depth and a rounded edge. -->
      <div
        v-for="(slice, index) in slices"
        :key="`s${index}`"
        class="slice"
        :style="{
          width: `${slice.width}px`,
          height: `${slice.height}px`,
          marginLeft: `${-slice.width / 2}px`,
          marginTop: `${-slice.height / 2}px`,
          borderRadius: `${slice.radius}px`,
          transform: `translateZ(${slice.z}px)`,
          filter: `brightness(${slice.light})`,
        }"
      ></div>

      <!-- Crown and side button, on the right. -->
      <div
        v-for="(x, index) in crown"
        :key="`k${index}`"
        class="crown"
        :style="{ transform: `translate3d(${x}px, -38px, 0) rotateY(90deg)` }"
      ></div>
      <div
        class="side-button"
        :style="{ transform: `translate3d(${W / 2 + 1}px, 30px, 0) rotateY(90deg)` }"
      ></div>

      <!-- The back: the sensor dome and its two lights. -->
      <div
        class="back"
        :style="{
          width: `${FACE_W}px`,
          height: `${FACE_H}px`,
          marginLeft: `${-FACE_W / 2}px`,
          marginTop: `${-FACE_H / 2}px`,
          transform: `translateZ(${-DEPTH / 2 - 1}px) rotateY(180deg)`,
        }"
      >
        <div class="dome">
          <span class="led led-a" :class="{ on: face === 'wear' }"></span>
          <span class="led led-b" :class="{ on: face === 'wear' }"></span>
        </div>
      </div>

      <!-- The charger, docked on the back when the battery is opened. -->
      <div
        v-for="index in 5"
        :key="`p${index}`"
        class="puck"
        :class="{ docked, top: index === 5 }"
        :style="{ '--z': `${-DEPTH / 2 - 4 - index * 2.4}px` }"
      ></div>

      <!-- The face: black glass with the screen in it. -->
      <div
        class="front"
        :style="{
          width: `${FACE_W}px`,
          height: `${FACE_H}px`,
          marginLeft: `${-FACE_W / 2}px`,
          marginTop: `${-FACE_H / 2}px`,
          transform: `translateZ(${DEPTH / 2 + 1}px)`,
        }"
      >
        <div class="screen">
          <Transition name="screen" mode="out-in">
            <div :key="face" class="screen-content" :class="`screen-${face}`">
              <template v-if="face === 'home' || face === 'steps'">
                <span class="time">{{ time }}</span>
                <svg class="ring" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="40" class="ring-track" />
                  <circle
                    cx="50"
                    cy="50"
                    r="40"
                    class="ring-fill"
                    :stroke-dasharray="RING"
                    :stroke-dashoffset="RING * (1 - stepShare)"
                  />
                </svg>
                <Icon name="walk" class="ring-icon" />
                <span class="small">{{ dayLabel ?? 'Today' }}</span>
                <strong class="big">{{ stepsText }}</strong>
                <span class="small">steps</span>
                <span class="bars">
                  <span
                    v-for="(bar, index) in bars"
                    :key="index"
                    :style="{ height: `${bar * 100}%` }"
                  ></span>
                </span>
              </template>
              <template v-else-if="face === 'active'">
                <span class="time">{{ time }}</span>
                <span class="pulse-ring"><Icon name="activity" /></span>
                <strong class="big">{{ activeMinutes ?? '—' }}</strong>
                <span class="small">active minutes</span>
              </template>
              <template v-else-if="face === 'sleep'">
                <span class="moon"></span>
                <strong class="word">Sleep</strong>
                <span class="small">{{ sleepLabel ?? 'Not recorded' }}</span>
              </template>
              <template v-else-if="face === 'wear'">
                <span class="time big-time">{{ time }}</span>
                <span class="small">Worn {{ wearLabel ?? '—' }}</span>
              </template>
              <template v-else-if="face === 'battery'">
                <svg class="ring ring-battery" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="40" class="ring-track" />
                  <circle
                    cx="50"
                    cy="50"
                    r="40"
                    class="ring-fill"
                    :stroke-dasharray="RING"
                    :stroke-dashoffset="RING * (1 - batteryShare)"
                  />
                </svg>
                <Icon name="battery" class="ring-icon" />
                <strong class="big">{{ battery ?? '—' }}%</strong>
                <span class="small">{{ charging ? 'Charging' : 'Battery' }}</span>
              </template>
              <template v-else-if="face === 'connection'">
                <span class="waves" :class="{ off: !connected }"
                  ><span></span><span></span><span></span
                ></span>
                <strong class="word">{{ connected ? 'Connected' : 'Offline' }}</strong>
                <span class="small">Simulated watch</span>
              </template>
              <template v-else-if="face === 'water'">
                <Icon name="water" class="water-icon" />
                <strong class="word">50 m</strong>
                <span class="small">Water lock</span>
              </template>
            </div>
          </Transition>
          <!-- Water: droplets bead on the glass. -->
          <Transition name="drops">
            <span v-if="face === 'water'" class="drops">
              <span v-for="index in 9" :key="index" :class="`drop drop-${index}`"></span>
            </span>
          </Transition>
        </div>
        <div class="glare"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scene {
  position: relative;
  width: 260px;
  height: 460px;
  perspective: 1100px;
  perspective-origin: 50% 45%;
}

.model {
  position: absolute;
  top: 50%;
  left: 50%;
  transform-style: preserve-3d;
}

.model > * {
  position: absolute;
  top: 0;
  left: 0;
}

/* ---- Strap: matte sage silicone ---- */
.strap {
  /* Soft rounded edges across the width, like moulded silicone. */
  background: linear-gradient(
    90deg,
    #5f8570 0%,
    #93b8a0 7%,
    #b4d1bd 22%,
    #c3dcca 50%,
    #b0cdb9 78%,
    #8db29a 93%,
    #5c8169 100%
  );
  backface-visibility: visible;
}

.strap {
  transition: opacity 0.6s ease;
}

/* Opened on the back of the watch: the band behind it fades away. */
.strap.behind {
  opacity: 0;
}

.strap.end {
  border-radius: 40% 40% 40% 40% / 60% 60% 60% 60%;
}

.hole {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #4f6d5a;
  box-shadow: inset 0 1px 2px rgb(0 0 0 / 45%);
  transform: translate(-50%, -50%);
}

/* ---- Case: brushed aluminium ---- */
.slice {
  background: linear-gradient(
    100deg,
    #6d7673 0%,
    #b9c1be 14%,
    #f3f5f4 34%,
    #d3d9d6 52%,
    #a7b0ad 72%,
    #e4e8e6 86%,
    #78817e 100%
  );
}

.crown {
  width: 34px;
  height: 34px;
  margin: -17px 0 0 -17px;
  border-radius: 50%;
  background: repeating-conic-gradient(#c3cbc8 0 6deg, #8a9390 6deg 12deg);
  box-shadow: inset 0 0 0 2px rgb(255 255 255 / 25%);
}

.side-button {
  width: 10px;
  height: 52px;
  margin: -26px 0 0 -5px;
  border-radius: 6px;
  background: linear-gradient(90deg, #8b9491, #e5e9e7, #8b9491);
}

/* ---- Back: ceramic with the sensor dome ---- */
.back {
  display: grid;
  place-items: center;
  border-radius: 47px;
  background: radial-gradient(circle at 40% 30%, #dfe6e3, #aab6b1 70%, #8e9a95);
}

.dome {
  position: relative;
  width: 118px;
  height: 118px;
  border-radius: 50%;
  background: radial-gradient(circle at 45% 35%, #3a4340, #121614 72%);
  box-shadow:
    0 0 0 6px #9aa6a1,
    inset 0 2px 10px rgb(255 255 255 / 12%);
}

.led {
  position: absolute;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #1f3b2c;
  transition:
    background 0.6s ease,
    box-shadow 0.6s ease;
}

.led-a {
  top: 38px;
  left: 30px;
}

.led-b {
  right: 30px;
  bottom: 38px;
}

.led.on {
  background: #7dffb0;
  box-shadow:
    0 0 10px 3px rgb(80 255 150 / 80%),
    0 0 30px 10px rgb(60 220 130 / 45%);
  animation: led 1.6s ease-in-out infinite;
}

@keyframes led {
  50% {
    opacity: 0.55;
  }
}

/* ---- Charger: a white puck that eases onto the back ---- */
.puck {
  width: 104px;
  height: 104px;
  margin: -52px 0 0 -52px;
  border-radius: 50%;
  background: #e9eceb;
  opacity: 0;
  transform: translateZ(calc(var(--z) - 70px));
  transition:
    transform 0.9s cubic-bezier(0.22, 1, 0.36, 1),
    opacity 0.5s ease;
}

.puck.top {
  background: radial-gradient(circle at 40% 35%, #ffffff, #d6dbd9 75%);
}

.puck.docked {
  opacity: 1;
  transform: translateZ(var(--z));
}

/* ---- Face: black glass ---- */
.front {
  padding: 10px;
  border-radius: 47px;
  /* The glass meets the case with a thin bright edge, then a black border round the screen. */
  background: radial-gradient(120% 90% at 30% 10%, #1a201e, #030504 60%);
  box-shadow:
    0 0 0 1.5px rgb(255 255 255 / 55%),
    inset 0 0 0 1px rgb(255 255 255 / 18%),
    inset 0 2px 14px rgb(255 255 255 / 8%);
}

.screen {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  border-radius: 37px;
  background: radial-gradient(circle at 50% 0%, #0e1512, #000 70%);
}

.glare {
  position: absolute;
  inset: 0;
  border-radius: 47px;
  /* Curved glass: a soft highlight at the top left, and a sheen that slides as it turns. */
  background:
    radial-gradient(70% 45% at 22% 8%, rgb(255 255 255 / 16%), transparent 70%),
    linear-gradient(
      115deg,
      transparent 30%,
      rgb(255 255 255 / 13%) 46%,
      rgb(255 255 255 / 3%) 54%,
      transparent 64%
    );
  background-position:
    0 0,
    var(--glare) 0;
  background-size:
    100% 100%,
    260% 100%;
  pointer-events: none;
}

.screen-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 14px 10px 12px;
  color: #f2f6f4;
  font-family: var(--sl-font-display, inherit);
  text-align: center;
}

.time {
  position: absolute;
  top: 12px;
  right: 22px;
  color: #c8d2ce;
  font-size: 11px;
  font-weight: 600;
}

.big-time {
  position: static;
  margin-bottom: 4px;
  color: #fff;
  font-size: 40px;
  letter-spacing: -0.02em;
}

.ring {
  width: 64px;
  height: 64px;
  margin-bottom: -46px;
  transform: rotate(-90deg);
}

.ring-track {
  fill: none;
  stroke: rgb(77 214 140 / 20%);
  stroke-width: 7;
}

.ring-fill {
  fill: none;
  stroke: #4dd68c;
  stroke-linecap: round;
  stroke-width: 7;
  transition: stroke-dashoffset 1.2s cubic-bezier(0.22, 1, 0.36, 1);
}

.ring-icon {
  margin-bottom: 26px;
  color: #4dd68c;
  font-size: 20px;
}

.small {
  color: #a9b5b0;
  font-size: 10px;
}

.big {
  font-size: 30px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.02em;
}

.word {
  font-size: 22px;
  font-weight: 700;
}

.bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 18px;
  margin-top: 8px;
}

.bars span {
  width: 3px;
  border-radius: 2px;
  background: #4dd68c;
}

.pulse-ring {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  margin-bottom: 8px;
  border: 6px solid #ff9f43;
  border-radius: 50%;
  color: #ff9f43;
  font-size: 20px;
  animation: breathe 2.4s ease-in-out infinite;
}

@keyframes breathe {
  50% {
    box-shadow: 0 0 22px rgb(255 159 67 / 55%);
  }
}

.moon {
  width: 56px;
  height: 56px;
  margin-bottom: 10px;
  border-radius: 50%;
  box-shadow:
    -14px 8px 0 0 #9d8cff,
    -14px 8px 26px 6px rgb(130 110 255 / 55%);
  transform: translateX(10px);
}

.ring-battery .ring-fill {
  stroke: #9be15d;
}

.waves {
  position: relative;
  display: block;
  width: 60px;
  height: 60px;
  margin-bottom: 8px;
}

.waves span {
  position: absolute;
  inset: 0;
  border: 2px solid #4dd68c;
  border-radius: 50%;
  opacity: 0;
  animation: wave 2.4s ease-out infinite;
}

.waves span:nth-child(2) {
  animation-delay: 0.8s;
}

.waves span:nth-child(3) {
  animation-delay: 1.6s;
}

.waves.off span {
  border-color: #6c7773;
  animation: none;
  opacity: 0.5;
}

@keyframes wave {
  0% {
    opacity: 0.9;
    transform: scale(0.2);
  }

  100% {
    opacity: 0;
    transform: scale(1);
  }
}

.water-icon {
  margin-bottom: 6px;
  color: #6fd3ff;
  font-size: 38px;
}

.drops {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.drop {
  position: absolute;
  border-radius: 50%;
  background: radial-gradient(
    circle at 35% 30%,
    rgb(255 255 255 / 85%),
    rgb(255 255 255 / 15%) 40%,
    rgb(255 255 255 / 4%) 70%
  );
  box-shadow: 0 1px 2px rgb(0 0 0 / 40%);
}

.drop-1 {
  top: 14%;
  left: 18%;
  width: 12px;
  height: 12px;
}
.drop-2 {
  top: 26%;
  left: 72%;
  width: 8px;
  height: 9px;
}
.drop-3 {
  top: 62%;
  left: 14%;
  width: 9px;
  height: 9px;
}
.drop-4 {
  top: 76%;
  left: 64%;
  width: 14px;
  height: 13px;
}
.drop-5 {
  top: 44%;
  left: 84%;
  width: 6px;
  height: 6px;
}
.drop-6 {
  top: 8%;
  left: 48%;
  width: 6px;
  height: 7px;
}
.drop-7 {
  top: 86%;
  left: 30%;
  width: 7px;
  height: 7px;
}
.drop-8 {
  top: 52%;
  left: 6%;
  width: 5px;
  height: 5px;
}
.drop-9 {
  top: 36%;
  left: 34%;
  width: 5px;
  height: 5px;
}

/* The screen changes with a soft blur, like a real watch face. */
.screen-enter-active,
.screen-leave-active {
  transition:
    opacity 0.35s ease,
    filter 0.35s ease,
    transform 0.35s ease;
}

.screen-enter-from,
.screen-leave-to {
  opacity: 0;
  filter: blur(6px);
  transform: scale(0.94);
}

.drops-enter-active,
.drops-leave-active {
  transition: opacity 0.8s ease;
}

.drops-enter-from,
.drops-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation: none !important;
    transition: none !important;
  }

  .led.on,
  .pulse-ring,
  .waves span {
    animation: none;
  }

  .waves span {
    opacity: 0.6;
  }

  .puck,
  .ring-fill {
    transition: none;
  }
}
</style>
