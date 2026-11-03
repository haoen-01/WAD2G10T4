<script setup lang="ts">
import { ref } from 'vue';

import { usePointerGlow } from '@/composables/usePointerGlow';

/**
 * The living background behind every page: soft glows of Care+ colour that drift slowly, a glow
 * that trails the mouse, a darker edge (vignette) and a fine film grain. CSS draws all of it:
 * - each glow is a `radial-gradient` that fades to nothing, so no blur filter is needed;
 * - `@keyframes` drift them over 26 to 34 seconds, there and back twice (about two minutes),
 *   then they rest, so nothing on the page moves for ever on its own;
 * - two layers lean a few pixels towards the mouse (`--sl-lean-x/y`) and the trailing glow sits
 *   at the mouse (`--sl-mx/my`), both set by `usePointerGlow`; a long `transition` makes them lag;
 * - the grain is an SVG `feTurbulence` noise filter at low opacity (no blend mode: blending a
 *   full-screen layer every frame is slow).
 * The colours are tokens in `theme.css` (`--sl-bg-*`), so light and dark mode each have their own.
 * It sits behind everything (`z-index: -1`), ignores the mouse (`pointer-events: none`) and is
 * hidden from screen readers. With reduced motion nothing drifts, leans or follows.
 */
const layer = ref<HTMLElement | null>(null);
usePointerGlow(layer);
</script>

<template>
  <div ref="layer" class="living" aria-hidden="true">
    <div class="lean lean-back">
      <div class="glow glow-main"></div>
      <div class="glow glow-deep"></div>
    </div>
    <div class="lean lean-front">
      <div class="glow glow-bright"></div>
      <div class="glow glow-warm"></div>
    </div>
    <div class="follow"></div>
    <div class="vignette"></div>
    <svg class="grain" xmlns="http://www.w3.org/2000/svg">
      <filter id="living-grain">
        <feTurbulence
          type="fractalNoise"
          baseFrequency="0.85"
          numOctaves="2"
          stitchTiles="stitch"
        />
      </filter>
      <rect width="100%" height="100%" filter="url(#living-grain)" />
    </svg>
  </div>
</template>

<style scoped>
.living {
  position: fixed;
  z-index: -1;
  inset: 0;
  overflow: hidden;
  isolation: isolate;
  background: var(--sl-mist);
  pointer-events: none;
}

.lean {
  position: absolute;
  inset: 0;
  transition: transform 1.4s var(--sl-ease);
}

.lean-back {
  transform: translate(calc(var(--sl-lean-x, 0) * -40px), calc(var(--sl-lean-y, 0) * -26px));
}

.lean-front {
  transform: translate(calc(var(--sl-lean-x, 0) * 28px), calc(var(--sl-lean-y, 0) * 18px));
}

.glow {
  position: absolute;
  border-radius: 50%;
  will-change: transform;
}

.glow-main {
  top: 6vh;
  left: -22vw;
  width: 72vw;
  height: 92vh;
  background: radial-gradient(closest-side, var(--sl-bg-main), transparent);
  animation: drift-a 32s ease-in-out 4 alternate;
}

.glow-deep {
  top: 28vh;
  right: -24vw;
  width: 64vw;
  height: 96vh;
  background: radial-gradient(closest-side, var(--sl-bg-deep), transparent);
  animation: drift-b 34s ease-in-out 4 alternate;
}

.glow-bright {
  top: -24vh;
  left: 28vw;
  width: 50vw;
  height: 74vh;
  background: radial-gradient(closest-side, var(--sl-bg-bright), transparent);
  animation: drift-c 26s ease-in-out 4 alternate;
}

.glow-warm {
  right: 4vw;
  bottom: -18vh;
  width: 38vw;
  height: 60vh;
  background: radial-gradient(closest-side, var(--sl-bg-warm), transparent);
  animation: drift-a 30s ease-in-out 4 alternate-reverse;
}

/* The glow that trails the mouse: placed at the mouse, then pulled back by half its size. */
.follow {
  position: absolute;
  top: 0;
  left: 0;
  width: 36rem;
  height: 36rem;
  margin: -18rem 0 0 -18rem;
  border-radius: 50%;
  background: radial-gradient(closest-side, var(--sl-bg-follow), transparent);
  opacity: var(--sl-follow, 0);
  transform: translate(var(--sl-mx, 50vw), var(--sl-my, 30vh));
  transition:
    transform 1.1s var(--sl-ease),
    opacity 0.7s ease;
}

.vignette {
  position: absolute;
  inset: 0;
  background: radial-gradient(120% 70% at 50% 20%, transparent 35%, var(--sl-bg-vignette) 100%);
}

.grain {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: var(--sl-bg-grain);
}

@keyframes drift-a {
  50% {
    transform: translate(12%, 6%) scale(1.12);
  }
  100% {
    transform: translate(-8%, 10%) scale(0.94);
  }
}

@keyframes drift-b {
  to {
    transform: translate(-16%, 8%) rotate(24deg) scale(1.1);
  }
}

@keyframes drift-c {
  to {
    transform: translate(16%, 10%) scale(1.18);
  }
}

@media (prefers-reduced-motion: reduce) {
  .glow {
    animation: none;
  }

  .lean {
    transform: none;
  }

  .follow {
    display: none;
  }
}

/* Printing: no background. */
@media print {
  .living {
    display: none;
  }
}
</style>
