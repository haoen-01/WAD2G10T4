<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';

import { burst, opacityOf, seeded, shower, stepPieces, type Piece } from '@/lib/confetti';

/**
 * Confetti across the whole screen, for the first look at a new badge: thrown up from both bottom
 * corners, bursting out of the medal, then a light fall from the top, in the badge's own colours
 * and gold. About five seconds, then it is gone. It never takes a tap or a drag (the medal can
 * still be spun through it), and nothing is drawn for someone who asked for less motion.
 */
const props = defineProps<{
  colours: readonly string[];
  /** The medal, for the burst out of its centre. */
  origin: HTMLElement | null;
}>();

const canvas = ref<HTMLCanvasElement | null>(null);
let pieces: Piece[] = [];
let frame = 0;
let last = 0;
let elapsed = 0;
let width = 0;
let height = 0;
const rand = seeded(Date.now() & 0xffff);

/** What is thrown when: seconds after it starts. */
const PLAN: { at: number; done: boolean; run: () => Piece[] }[] = [
  {
    at: 0.3,
    done: false,
    run: () => [
      ...burst(90, -10, height + 10, -62, 28, height * 1.55, props.colours, rand),
      ...burst(90, width + 10, height + 10, -118, 28, height * 1.55, props.colours, rand),
    ],
  },
  {
    at: 0.62,
    done: false,
    run: () => {
      const box = props.origin?.getBoundingClientRect();
      const x = box ? box.left + box.width / 2 : width / 2;
      const y = box ? box.top + box.height / 2 : height / 2;
      return burst(80, x, y, -90, 360, Math.min(width, height) * 1.1, props.colours, rand);
    },
  },
  ...Array.from({ length: 14 }, (_, i) => ({
    at: 0.9 + i * 0.12,
    done: false,
    run: () => shower(6, width, props.colours, rand),
  })),
];

function fit() {
  const el = canvas.value;
  if (!el) return;
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  width = window.innerWidth;
  height = window.innerHeight;
  el.width = Math.round(width * ratio);
  el.height = Math.round(height * ratio);
  el.getContext('2d')?.setTransform(ratio, 0, 0, ratio, 0, 0);
}

function draw(ctx: CanvasRenderingContext2D) {
  ctx.clearRect(0, 0, width, height);
  for (const p of pieces) {
    ctx.save();
    ctx.globalAlpha = opacityOf(p);
    ctx.translate(p.x, p.y);
    ctx.rotate(p.spin);
    // A turning piece of paper shows its edge, then its face: squash it as it flutters.
    ctx.scale(1, 0.25 + 0.75 * Math.abs(Math.cos(p.sway * 1.7)));
    ctx.fillStyle = p.colour;
    if (p.shape === 'dot') {
      ctx.beginPath();
      ctx.arc(0, 0, p.w / 2, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
    }
    ctx.restore();
  }
}

function tick(time: number) {
  const dt = last ? Math.min(0.05, (time - last) / 1000) : 0;
  last = time;
  elapsed += dt;
  for (const step of PLAN) {
    if (!step.done && elapsed >= step.at) {
      step.done = true;
      pieces = pieces.concat(step.run());
    }
  }
  pieces = stepPieces(pieces, dt, height);
  const ctx = canvas.value?.getContext('2d');
  if (ctx) draw(ctx);
  const more = PLAN.some((step) => !step.done) || pieces.length > 0;
  frame = more ? requestAnimationFrame(tick) : 0;
}

onMounted(() => {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
  fit();
  window.addEventListener('resize', fit);
  frame = requestAnimationFrame(tick);
});

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame);
  window.removeEventListener('resize', fit);
});
</script>

<template>
  <canvas ref="canvas" class="badge-confetti" aria-hidden="true" data-testid="badge-confetti" />
</template>

<style scoped>
.badge-confetti {
  position: fixed;
  inset: 0;
  z-index: 3;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>
