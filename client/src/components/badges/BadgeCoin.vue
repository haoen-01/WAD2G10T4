<script setup lang="ts">
import { computed } from 'vue';

import BadgeMedal from '@/components/badges/BadgeMedal.vue';
import type { ShelfBadge } from '@/composables/useBadges';
import { SHAPES } from '@/lib/badge-art';
import { earnedWords, momentWords } from '@/lib/badges';

/**
 * A badge as a thick gold coin in 3D: the enamel front, a milled gold edge, and the back engraved
 * with who earned it, the day, and the moment it was claimed. The parent turns it with `angle`.
 */
const props = withDefaults(
  defineProps<{
    badge: ShelfBadge;
    /** Degrees about the upright axis, or null to leave it to CSS. */
    angle?: number | null;
    /** Edge thickness in px. */
    thickness?: number;
    /** Just claimed: the grey face melts into colour. */
    celebrate?: boolean;
    /** Whose badge it is, for the back: "Earned by Mdm Lim". */
    owner?: string;
  }>(),
  { angle: null, thickness: 8, celebrate: false, owner: '' },
);

const won = computed(() => props.badge.state === 'claimed');
const outline = computed(() => SHAPES[props.badge.look.shape]);

/** Split a long name over two lines at the space nearest the middle. */
function splitName(name: string): string[] {
  if (name.length <= 15) return [name];
  const middle = name.length / 2;
  let best = -1;
  for (let i = 0; i < name.length; i += 1) {
    if (name[i] === ' ' && (best < 0 || Math.abs(i - middle) < Math.abs(best - middle))) best = i;
  }
  return best < 0 ? [name] : [name.slice(0, best).replace(/,$/, ''), name.slice(best + 1)];
}

const backLines = computed(() => {
  const badge = props.badge;
  const lines: { text: string; size?: number; soft?: boolean }[] = splitName(badge.name).map(
    (text) => ({ text, size: 14 }),
  );
  lines.push({
    text: props.owner ? `EARNED BY ${props.owner.toUpperCase()}` : 'EARNED',
    size: 8.5,
    soft: true,
  });
  const earned = earnedWords(badge);
  const [day, time] =
    earned.includes(' am') || earned.includes(' pm')
      ? [earned.slice(0, earned.lastIndexOf(', ')), earned.slice(earned.lastIndexOf(', ') + 2)]
      : [earned, null];
  lines.push({ text: `ON ${day.toUpperCase()}`, size: 11 });
  if (time) lines.push({ text: `AT ${time.toUpperCase()}`, size: 11 });
  if (badge.claimedAt !== null) {
    const claimed = momentWords(badge.claimedAt);
    lines.push({ text: 'CLAIMED', size: 8.5, soft: true });
    lines.push({ text: claimed.slice(0, claimed.lastIndexOf(', ')), size: 10, soft: true });
    lines.push({ text: claimed.slice(claimed.lastIndexOf(', ') + 2), size: 10, soft: true });
  }
  return lines;
});

const edges = computed(() => {
  const count = Math.max(2, Math.round(props.thickness / 1.25));
  return Array.from({ length: count }, (_, i) => {
    const z = -props.thickness / 2 + (props.thickness * (i + 0.5)) / count;
    // Darker towards the middle of the edge, like milled gold in shadow.
    const light = Math.abs(i - (count - 1) / 2) / ((count - 1) / 2 || 1);
    return { z, fill: light > 0.7 ? '#b48a35' : light > 0.35 ? '#8d6720' : '#6d4d12' };
  });
});

const bodyStyle = computed(() =>
  props.angle === null ? undefined : { transform: `rotateY(${props.angle}deg)` },
);
</script>

<template>
  <div class="coin" :class="{ 'is-won': won, 'is-celebrating': celebrate }">
    <div class="coin-body" :style="bodyStyle">
      <div class="coin-face coin-front" :style="{ transform: `translateZ(${thickness / 2}px)` }">
        <BadgeMedal v-if="won" :look="badge.look" class="coin-colour" />
        <BadgeMedal
          v-if="!won || celebrate"
          :look="badge.look"
          variant="ghost"
          :gold-rim="badge.state !== 'locked'"
          class="coin-ghost"
        />
      </div>
      <template v-if="won">
        <svg
          v-for="(edge, i) in edges"
          :key="i"
          class="coin-edge"
          viewBox="0 0 200 200"
          aria-hidden="true"
          focusable="false"
          :style="{ transform: `translateZ(${edge.z}px)` }"
        >
          <path :d="outline" :fill="edge.fill" />
        </svg>
        <div
          class="coin-face coin-back"
          :style="{ transform: `rotateY(180deg) translateZ(${thickness / 2}px)` }"
        >
          <BadgeMedal :look="badge.look" face="back" :lines="backLines" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.coin {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  perspective: 900px;
}
.coin-body {
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
}
.coin-face,
.coin-edge {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  backface-visibility: hidden;
}
.coin-edge {
  backface-visibility: visible;
}
.coin-face :deep(.badge-medal) {
  position: absolute;
  inset: 0;
}
.coin-front {
  filter: drop-shadow(0 6px 10px rgb(16 42 38 / 22%));
}
.coin.is-won .coin-front {
  filter: drop-shadow(0 8px 14px rgb(70 45 5 / 30%));
}

/* Claimed just now: the grey face fades away to show the enamel underneath. */
.coin.is-celebrating .coin-ghost {
  animation: coin-melt 1.2s var(--sl-ease) 0.25s forwards;
}
@keyframes coin-melt {
  to {
    opacity: 0;
  }
}
</style>
