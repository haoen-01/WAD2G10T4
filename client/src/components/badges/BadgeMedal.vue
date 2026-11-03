<script setup lang="ts">
import { computed, useId } from 'vue';

import {
  backTextScale,
  GOLD,
  GOLD_LIP,
  inset,
  LAYERS,
  motifParts,
  SHAPES,
  TONES,
  type Part,
} from '@/lib/badge-art';
import type { BadgeLook } from '@/lib/badges';

/**
 * One face of a walking badge, as an enamel pin: a polished gold rim, coloured enamel with the
 * picture inlaid in gold wire, and a gloss. `ghost` draws a badge not yet won: grey and engraved,
 * with a gold rim when it is ready to claim. The back is brushed gold with the dates engraved.
 * Decorative: the badge's name and dates are always given in text beside it as well.
 */
const props = withDefaults(
  defineProps<{
    look: BadgeLook;
    face?: 'front' | 'back';
    variant?: 'colour' | 'ghost';
    /** Ghost only: keep the gold rim (earned, waiting to be claimed). */
    goldRim?: boolean;
    /** Back only: the engraved lines, top to bottom. */
    lines?: { text: string; size?: number; soft?: boolean }[];
  }>(),
  { face: 'front', variant: 'colour', goldRim: false, lines: () => [] },
);

const uid = `bm${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
const url = (name: string) => `url(#${uid}-${name})`;

const tone = computed(() => TONES[props.look.tone]);
const outline = computed(() => SHAPES[props.look.shape]);
const ghost = computed(() => props.variant === 'ghost');
const parts = computed(() => (props.face === 'front' ? motifParts(props.look) : []));

const rimFill = computed(() => (ghost.value && !props.goldRim ? url('ghostRim') : url('gold')));
const lipFill = computed(() =>
  ghost.value && !props.goldRim ? 'var(--badge-ghost-lip)' : url('lip'),
);
const fieldFill = computed(() => {
  if (props.face === 'back') return url('brushed');
  return ghost.value ? 'var(--badge-ghost-face)' : url('enamel');
});

function colour(key: Part['fill'] | NonNullable<Part['line']>): string {
  if (key === 'none') return 'none';
  if (key === 'gold') return url('gold');
  return tone.value[key];
}

/** The SVG attributes for one part of the picture, in colour or engraved. */
function paint(part: Part): Record<string, string | number> {
  const base = { ...part.attrs };
  if (ghost.value) {
    const width = part.line ? Math.min(part.lineWidth ?? 2, 2.5) : 2;
    return {
      ...base,
      fill: part.line || part.fill === 'none' ? 'none' : 'var(--badge-ghost-face)',
      stroke: 'var(--badge-ghost-line)',
      'stroke-width': part.tag === 'text' ? 1.3 : width,
      'stroke-linejoin': 'round',
      'stroke-linecap': 'round',
    };
  }
  if (part.line) {
    return {
      ...base,
      fill: 'none',
      stroke: colour(part.line),
      'stroke-width': part.lineWidth ?? 3,
      'stroke-linecap': 'round',
    };
  }
  if (part.tag === 'text' && part.fill === 'gold') {
    return {
      ...base,
      fill: url('gold'),
      stroke: '#3a2606',
      'stroke-width': 2.4,
      'paint-order': 'stroke',
      'stroke-linejoin': 'round',
    };
  }
  return {
    ...base,
    fill: colour(part.fill),
    ...(part.wire ? { stroke: url('gold'), 'stroke-width': 2.6, 'stroke-linejoin': 'round' } : {}),
  };
}

/** The back's engraving, centred. */
const engraving = computed(() => {
  const scale = backTextScale(props.look.shape);
  const sized = props.lines.map((line) => ({ ...line, size: (line.size ?? 13) * scale }));
  const height = sized.reduce((sum, line) => sum + line.size * 1.38, 0);
  let y = 100 - height / 2;
  return sized.map((line) => {
    y += line.size * 1.38;
    return { ...line, y: y - line.size * 0.38 };
  });
});
</script>

<template>
  <svg
    class="badge-medal"
    :class="[`is-${variant}`, `is-${face}`]"
    viewBox="0 0 200 200"
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      <linearGradient :id="`${uid}-gold`" x1="0" y1="0" x2="1" y2="1">
        <stop v-for="[at, c] in GOLD" :key="at" :offset="at" :stop-color="c" />
      </linearGradient>
      <linearGradient :id="`${uid}-lip`" x1="1" y1="1" x2="0" y2="0">
        <stop v-for="[at, c] in GOLD_LIP" :key="at" :offset="at" :stop-color="c" />
      </linearGradient>
      <linearGradient :id="`${uid}-ghostRim`" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" style="stop-color: var(--badge-ghost-rim-hi)" />
        <stop offset="1" style="stop-color: var(--badge-ghost-rim-lo)" />
      </linearGradient>
      <radialGradient :id="`${uid}-enamel`" cx="0.32" cy="0.26" r="0.95">
        <stop offset="0" :stop-color="tone.hi" />
        <stop offset="0.55" :stop-color="tone.mid" />
        <stop offset="1" :stop-color="tone.lo" />
      </radialGradient>
      <radialGradient :id="`${uid}-brushed`" cx="0.38" cy="0.3" r="0.9">
        <stop offset="0" stop-color="#fff6d2" />
        <stop offset="0.5" stop-color="#e6c56d" />
        <stop offset="1" stop-color="#a87a28" />
      </radialGradient>
      <linearGradient :id="`${uid}-gloss`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#fff" stop-opacity="0.6" />
        <stop offset="1" stop-color="#fff" stop-opacity="0" />
      </linearGradient>
      <radialGradient :id="`${uid}-shade`" cx="0.5" cy="0.15" r="0.95">
        <stop offset="0.6" stop-color="#000" stop-opacity="0" />
        <stop offset="1" stop-color="#000" stop-opacity="0.35" />
      </radialGradient>
      <linearGradient :id="`${uid}-sheen`" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#fff" stop-opacity="0" />
        <stop offset="0.5" stop-color="#fff" stop-opacity="0.75" />
        <stop offset="1" stop-color="#fff" stop-opacity="0" />
      </linearGradient>
      <clipPath :id="`${uid}-field`">
        <path :d="outline" :transform="inset(LAYERS.field)" />
      </clipPath>
    </defs>

    <!-- The rim: polished gold (or pewter for one not yet won), its inner lip, then the enamel. -->
    <path :d="outline" :fill="rimFill" />
    <path
      :d="outline"
      fill="none"
      stroke="#fff"
      stroke-opacity="0.45"
      stroke-width="1.2"
      :transform="inset(0.985)"
    />
    <path :d="outline" :fill="lipFill" :transform="inset(LAYERS.lip)" />
    <path :d="outline" :fill="fieldFill" :transform="inset(LAYERS.field)" />

    <g :clip-path="`url(#${uid}-field)`">
      <template v-if="face === 'front'">
        <component :is="part.tag" v-for="(part, i) in parts" :key="i" v-bind="paint(part)">
          <template v-if="part.tag === 'text'">{{ part.text }}</template>
        </component>
      </template>
      <template v-else>
        <circle
          v-for="r in 22"
          :key="r"
          cx="100"
          cy="100"
          :r="r * 4.2"
          fill="none"
          stroke="#fff"
          stroke-opacity="0.16"
          stroke-width="0.8"
        />
      </template>

      <template v-if="!ghost">
        <!-- Light on the glaze: a soft top highlight, a little shade at the foot, and the sheen. -->
        <ellipse
          cx="78"
          cy="38"
          rx="96"
          ry="52"
          :fill="url('gloss')"
          transform="rotate(-18 78 38)"
        />
        <rect x="0" y="0" width="200" height="200" :fill="url('shade')" />
        <rect class="badge-sheen" x="-70" y="-30" width="46" height="260" :fill="url('sheen')" />
      </template>
    </g>

    <!-- The gold wire edge between rim and enamel. -->
    <path
      :d="outline"
      fill="none"
      :stroke="ghost && !goldRim ? 'var(--badge-ghost-line)' : url('gold')"
      stroke-width="2.4"
      :transform="inset(LAYERS.field)"
    />

    <g v-if="face === 'back'" class="badge-engraving" text-anchor="middle">
      <template v-for="(line, i) in engraving" :key="i">
        <text
          x="100"
          :y="line.y + 0.9"
          :font-size="line.size"
          fill="#fff"
          fill-opacity="0.6"
          :font-weight="line.soft ? 600 : 800"
        >
          {{ line.text }}
        </text>
        <text
          x="100"
          :y="line.y"
          :font-size="line.size"
          :fill="line.soft ? '#6b4b12' : '#3f2a05'"
          :font-weight="line.soft ? 600 : 800"
        >
          {{ line.text }}
        </text>
      </template>
    </g>
  </svg>
</template>

<style scoped>
.badge-medal {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
  font-family: Georgia, 'Times New Roman', serif;
  font-weight: 800;
  --badge-ghost-face: #eceef2;
  --badge-ghost-lip: #d5d8df;
  --badge-ghost-line: #a9aebb;
  --badge-ghost-rim-hi: #e4e6eb;
  --badge-ghost-rim-lo: #b4b8c3;
}
:root[data-bs-theme='dark'] .badge-medal {
  --badge-ghost-face: #23262d;
  --badge-ghost-lip: #30343c;
  --badge-ghost-line: #5d6371;
  --badge-ghost-rim-hi: #4a4f5a;
  --badge-ghost-rim-lo: #2a2d34;
}
.badge-engraving {
  font-family: Georgia, 'Times New Roman', serif;
  letter-spacing: 0.02em;
}
.badge-sheen {
  transform: translateX(0) rotate(22deg);
  transform-box: view-box;
  opacity: 0;
}
</style>
