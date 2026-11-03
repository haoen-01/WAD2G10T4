<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';

import BadgeCelebration from '@/components/badges/BadgeCelebration.vue';
import BadgeCoin from '@/components/badges/BadgeCoin.vue';
import Icon from '@/components/ui/Icon.vue';
import type { ShelfBadge } from '@/composables/useBadges';
import { useCoinSpin } from '@/composables/useCoinSpin';
import { TONES } from '@/lib/badge-art';
import { badgeSentence, momentWords } from '@/lib/badges';

/**
 * A badge up close, the way a medal is shown off: it flies out of the shelf onto a dark stage,
 * turns once as it lands, and then it is hers to spin. Drag it (or flick it) and it turns and
 * settles face on; "Turn over" does the same for anyone who cannot drag. No card, no table: the
 * medal, its name and one line about it. Back (or Escape) sends it home to its place on the shelf.
 *
 * The first look at a badge after it is claimed is a celebration, filling the whole screen:
 * confetti in the badge's colours, gold light turning behind the medal, sparkles, two turns as it
 * lands and "Congratulations!". Once for her, once for her family; after that it is the calm view.
 */
const props = defineProps<{
  badge: ShelfBadge | null;
  canClaim: boolean;
  /** "You" on her own page, her name for the family. */
  who: string;
  /** Whose badge, for the engraving on the back. */
  owner: string;
  /** The medal on the shelf it flies out of and back to. */
  origin: HTMLElement | null;
  /** The first look at this badge since it was claimed: celebrate it. */
  firstLook: boolean;
}>();
const emit = defineEmits<{ close: []; claim: [id: string]; seen: [id: string] }>();

const dialog = ref<HTMLDialogElement | null>(null);
const flyer = ref<HTMLElement | null>(null);
const turnButton = ref<HTMLButtonElement | null>(null);
const spin = useCoinSpin();
/** Said inside the view (the page behind it is out of reach while it is open). */
const said = ref('');
const closing = ref(false);
/** Celebrating right now. */
const party = ref(false);

const won = computed(() => props.badge?.state === 'claimed');
const percent = computed(() =>
  props.badge
    ? Math.round((100 * props.badge.progress.value) / Math.max(1, props.badge.progress.target))
    : 0,
);
const showingBack = computed(() => {
  const turn = ((spin.angle.value % 360) + 360) % 360;
  return turn > 90 && turn < 270;
});
const sentence = computed(() => (props.badge ? badgeSentence(props.badge, props.who) : ''));
const self = computed(() => props.who === 'You');

/** Confetti in the badge's own enamel colours and gold, with a little party colour. */
const colours = computed(() => {
  const tone = props.badge ? TONES[props.badge.look.tone] : null;
  return [
    ...(tone ? [tone.hi, tone.mid, tone.a1, tone.a2] : []),
    '#f2d488',
    '#c4953a',
    '#fff6d2',
    '#ff7aa8',
    '#7cc7ff',
    '#8ee6b0',
  ];
});

/** The celebration: once per first look, marked as seen straight away. */
function celebrate(badge: ShelfBadge) {
  party.value = true;
  emit('seen', badge.id);
  said.value = self.value
    ? `Congratulations! You earned a new badge: ${badge.name}.`
    : `Congratulations to ${props.who}! A new badge: ${badge.name}.`;
  if (!reduced()) {
    try {
      navigator.vibrate?.([24, 70, 24]);
    } catch {
      // No vibration on this device.
    }
  }
}

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

/** How to move the stage's medal so it sits exactly over the shelf's one. */
function fromShelf(): Keyframe | null {
  const from = props.origin?.getBoundingClientRect();
  const to = flyer.value?.getBoundingClientRect();
  if (!from || !to || !to.width || !from.width) return null;
  const dx = from.left + from.width / 2 - (to.left + to.width / 2);
  const dy = from.top + from.height / 2 - (to.top + to.height / 2);
  return { transform: `translate(${dx}px, ${dy}px) scale(${from.width / to.width})` };
}

async function arrive() {
  await nextTick();
  if (reduced()) return;
  const start = fromShelf();
  const motion = start
    ? flyer.value?.animate([start, { transform: 'none' }], {
        duration: 620,
        easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
      })
    : null;
  if (won.value) {
    await motion?.finished.catch(() => undefined);
    spin.flourish(party.value ? 2 : 1);
  }
}

async function close() {
  if (closing.value) return;
  closing.value = true;
  spin.reset();
  const back = reduced() ? null : fromShelf();
  if (back && flyer.value) {
    await flyer.value
      .animate([{ transform: 'none' }, back], {
        duration: 420,
        easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
      })
      .finished.catch(() => undefined);
  }
  closing.value = false;
  emit('close');
}

/** Claimed here: say so in the view, turn once in celebration, keep focus on a button still there. */
async function claim() {
  const badge = props.badge;
  if (!badge) return;
  emit('claim', badge.id);
  await nextTick();
  if (props.badge?.id !== badge.id || props.badge.state !== 'claimed') return;
  celebrate(props.badge);
  spin.flourish(2);
  turnButton.value?.focus();
}

function up(event: PointerEvent) {
  spin.up(event);
}

watch(
  () => props.badge?.id ?? null,
  (id) => {
    if (id) {
      said.value = '';
      party.value = false;
      spin.reset();
      if (!dialog.value?.open) dialog.value?.showModal();
      if (props.firstLook && props.badge?.state === 'claimed') celebrate(props.badge);
      void arrive();
    } else {
      party.value = false;
      if (dialog.value?.open) dialog.value.close();
    }
  },
  { flush: 'post' },
);

onBeforeUnmount(() => {
  dialog.value?.close();
});
</script>

<template>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="badge-viewer"
      :class="{ 'is-closing': closing, 'is-party': party }"
      aria-labelledby="badge-viewer-title"
      data-testid="badge-viewer"
      @cancel.prevent="close"
    >
      <template v-if="badge">
        <div class="viewer-bar">
          <button type="button" class="viewer-back" data-testid="badge-viewer-back" @click="close">
            <Icon name="chevron-left" /> Badges
          </button>
        </div>

        <BadgeCelebration v-if="party" :colours="colours" :origin="flyer" />

        <div class="viewer-body">
          <header v-if="party" class="viewer-cheer" data-testid="badge-cheer">
            <p class="viewer-cheer-kicker">
              {{ self ? 'You earned a new badge' : `${who} earned a new badge` }}
            </p>
            <p class="viewer-cheer-title" aria-hidden="true">Congratulations!</p>
          </header>
          <div
            class="viewer-stage"
            :class="{ 'can-drag': won, 'is-dragging': spin.dragging.value }"
            @pointerdown="won && spin.down($event)"
            @pointermove="spin.move"
            @pointerup="up"
            @pointercancel="up"
          >
            <div v-if="party" class="viewer-rays" aria-hidden="true"></div>
            <div v-if="party" class="viewer-sparkles" aria-hidden="true">
              <span v-for="n in 10" :key="n" :style="{ '--n': n }"></span>
            </div>
            <div ref="flyer" class="viewer-medal">
              <BadgeCoin
                :badge="badge"
                :angle="won ? spin.angle.value : 0"
                :thickness="16"
                :owner="owner"
              />
            </div>
          </div>

          <div class="viewer-words">
            <h2 id="badge-viewer-title" class="viewer-name">{{ badge.name }}</h2>
            <p class="viewer-line" data-testid="badge-viewer-line">{{ sentence }}</p>
            <p
              v-if="badge.claimedAt !== null"
              class="viewer-claimed"
              data-testid="badge-claimed-on"
            >
              Claimed {{ momentWords(badge.claimedAt) }}
            </p>

            <template v-if="!badge.earned">
              <p class="viewer-progress-words">{{ badge.progress.words }}</p>
              <div
                class="viewer-progress"
                role="progressbar"
                :aria-valuenow="percent"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-label="`${badge.name}: ${percent}% of the way`"
              >
                <span :style="{ width: `${percent}%` }"></span>
              </div>
            </template>

            <p v-if="badge.state === 'ready' && !canClaim" class="viewer-claimed">
              Waiting for {{ who }} to claim it on her own page.
            </p>

            <!-- For screen readers: the heading above the medal says it for everyone else. -->
            <p class="visually-hidden" role="status" data-testid="badge-viewer-said">{{ said }}</p>

            <button
              v-if="badge.state === 'ready' && canClaim"
              type="button"
              class="viewer-claim"
              data-testid="viewer-claim"
              @click="claim"
            >
              <Icon name="sparkle" /> Claim this badge
            </button>
            <button
              v-if="won"
              ref="turnButton"
              type="button"
              class="viewer-turn"
              data-testid="badge-turn"
              @click="spin.turn"
            >
              <Icon name="refresh" /> {{ showingBack ? 'Show the front' : 'Turn over' }}
            </button>
            <p v-if="won" class="viewer-hint" aria-hidden="true">Drag the medal to spin it</p>
          </div>
        </div>
      </template>
    </dialog>
  </Teleport>
</template>

<style scoped>
.badge-viewer {
  position: fixed;
  inset: 0;
  width: 100vw;
  max-width: none;
  height: 100dvh;
  max-height: none;
  margin: 0;
  padding: 0;
  border: 0;
  overflow-x: hidden;
  overflow-y: auto;
  color: #fff;
  background: radial-gradient(circle at 50% 38%, rgb(255 214 120 / 16%), transparent 48%), #000;
}
.badge-viewer[open] {
  display: flex;
  flex-direction: column;
  animation: viewer-in 0.36s ease both;
}
.badge-viewer.is-closing {
  animation: viewer-out 0.42s ease both;
}
.badge-viewer::backdrop {
  /* The view's own black fades in and out over the page, so the medal is seen leaving it. */
  background: transparent;
}
@keyframes viewer-in {
  from {
    background-color: rgb(0 0 0 / 0%);
  }
}
@keyframes viewer-out {
  to {
    background-color: rgb(0 0 0 / 0%);
    background-image: none;
  }
}
.viewer-bar {
  display: flex;
  padding: max(0.75rem, env(safe-area-inset-top)) 1rem 0;
}
.viewer-back {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  min-height: 48px;
  padding: 0 0.5rem;
  border: 0;
  background: none;
  color: #f2d488;
  font-size: 1.1rem;
  font-weight: 700;
}
.viewer-back:focus-visible,
.viewer-turn:focus-visible,
.viewer-claim:focus-visible {
  outline: 3px solid #f2d488;
  outline-offset: 3px;
  border-radius: 999px;
}
.viewer-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1.5rem;
  padding: 1rem 1.25rem max(2rem, env(safe-area-inset-bottom));
}
.viewer-stage {
  display: grid;
  place-items: center;
  width: 100%;
  touch-action: pan-y;
  user-select: none;
}
.viewer-stage.can-drag {
  cursor: var(--sl-cur-spin);
}
.viewer-stage.is-dragging {
  cursor: var(--sl-cur-grabbing);
}
.viewer-stage {
  position: relative;
}
.viewer-medal {
  position: relative;
  z-index: 1;
  width: min(72vw, 48dvh, 22rem);
  aspect-ratio: 1;
  will-change: transform;
}
.viewer-medal :deep(.coin-front) {
  filter: drop-shadow(0 18px 30px rgb(0 0 0 / 55%));
}
.viewer-words {
  max-width: 28rem;
  text-align: center;
}
.is-closing .viewer-words,
.is-closing .viewer-bar {
  opacity: 0;
  transition: opacity 0.2s ease;
}
.viewer-words > * {
  animation: viewer-words-in 0.4s ease 0.25s both;
}
@keyframes viewer-words-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
}
.viewer-name {
  margin: 0 0 0.35rem;
  font-size: clamp(1.4rem, 4.5vw, 1.9rem);
  font-weight: 800;
  color: #fff;
}
.viewer-line {
  margin: 0 0 0.25rem;
  color: rgb(255 255 255 / 78%);
  font-size: 1.05rem;
  line-height: 1.45;
}
.viewer-claimed,
.viewer-progress-words {
  margin: 0 0 0.25rem;
  color: rgb(255 255 255 / 62%);
  font-size: 0.95rem;
}
.viewer-progress-words {
  margin-top: 0.75rem;
  color: rgb(255 255 255 / 85%);
  font-weight: 700;
}
.viewer-progress {
  width: min(16rem, 80%);
  height: 0.45rem;
  margin: 0.5rem auto 0;
  border-radius: 1rem;
  background: rgb(255 255 255 / 16%);
  overflow: hidden;
}
.viewer-progress span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #b0802a, #f2d488);
}
.viewer-said {
  margin: 0.5rem 0 0;
  color: #f2d488;
  font-weight: 800;
}
.viewer-said:empty {
  margin: 0;
}
.viewer-claim,
.viewer-turn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 48px;
  margin-top: 1rem;
  padding: 0 1.4rem;
  border: 0;
  border-radius: 999px;
  font-weight: 800;
}
.viewer-claim {
  background: linear-gradient(135deg, #f8e3a0, #c4953a 55%, #8a6418);
  color: #2e1f03;
  box-shadow: 0 6px 18px rgb(196 149 58 / 35%);
}
.viewer-turn {
  background: none;
  color: #f2d488;
}
.viewer-hint {
  margin: 0;
  color: rgb(255 255 255 / 45%);
  font-size: 0.85rem;
}

/* ---- The first-look celebration ---- */
.badge-viewer.is-party {
  background:
    radial-gradient(circle at 50% 46%, rgb(255 210 110 / 30%), transparent 55%),
    radial-gradient(circle at 15% 100%, rgb(255 140 90 / 16%), transparent 40%),
    radial-gradient(circle at 85% 100%, rgb(120 160 255 / 16%), transparent 40%), #000;
}
.viewer-cheer {
  text-align: center;
  animation: cheer-in 0.7s cubic-bezier(0.34, 1.4, 0.64, 1) 0.35s both;
}
.viewer-cheer-kicker {
  margin: 0 0 0.15rem;
  color: rgb(255 255 255 / 80%);
  font-size: 0.85rem;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.viewer-cheer-title {
  margin: 0;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: clamp(2rem, 8vw, 3.2rem);
  font-weight: 800;
  line-height: 1.1;
  background: linear-gradient(
    100deg,
    #b0802a 0%,
    #fff3c4 30%,
    #e6c56d 50%,
    #fff6d8 65%,
    #b0802a 100%
  );
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 2px 10px rgb(242 196 90 / 35%));
  animation: cheer-shine 3.2s linear 0.9s infinite;
}
@keyframes cheer-in {
  from {
    opacity: 0;
    transform: translateY(-14px) scale(0.85);
  }
}
@keyframes cheer-shine {
  to {
    background-position: -220% 0;
  }
}
/* Gold light turning slowly behind the medal. */
.viewer-rays {
  position: absolute;
  top: 50%;
  left: 50%;
  width: min(150vw, 92dvh, 46rem);
  aspect-ratio: 1;
  border-radius: 50%;
  background: repeating-conic-gradient(
    from 0deg,
    rgb(255 220 140 / 26%) 0deg 7deg,
    rgb(255 220 140 / 0%) 7deg 22.5deg
  );
  -webkit-mask-image: radial-gradient(circle, #000 18%, transparent 68%);
  mask-image: radial-gradient(circle, #000 18%, transparent 68%);
  transform: translate(-50%, -50%);
  animation:
    rays-in 1s ease 0.3s both,
    rays-turn 26s linear infinite;
  pointer-events: none;
}
@keyframes rays-in {
  from {
    opacity: 0;
  }
}
@keyframes rays-turn {
  to {
    transform: translate(-50%, -50%) rotate(360deg);
  }
}
/* Four-pointed sparkles twinkling around the medal. */
.viewer-sparkles {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.viewer-sparkles span {
  --angle: calc(var(--n) * 36deg + 8deg);
  --reach: calc(min(72vw, 48dvh, 22rem) * (0.52 + 0.06 * (var(--n) - 5) * (var(--n) - 5) / 25));
  position: absolute;
  top: 50%;
  left: 50%;
  width: calc(0.7rem + (var(--n) * 2px));
  aspect-ratio: 1;
  background: radial-gradient(circle, #fff 0 18%, #ffe39a 30%, transparent 62%);
  clip-path: polygon(50% 0, 60% 40%, 100% 50%, 60% 60%, 50% 100%, 40% 60%, 0 50%, 40% 40%);
  transform: rotate(var(--angle)) translateY(calc(var(--reach) * -1))
    rotate(calc(var(--angle) * -1));
  animation: twinkle 1.6s ease-in-out calc(var(--n) * 0.17s + 0.5s) infinite both;
}
@keyframes twinkle {
  0%,
  100% {
    opacity: 0;
    scale: 0.3;
  }
  50% {
    opacity: 1;
    scale: 1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .viewer-rays {
    animation: none;
  }
  .viewer-sparkles span {
    animation: none;
    opacity: 0.85;
  }
}
</style>
