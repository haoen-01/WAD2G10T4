<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { useDisplay } from '@/composables/useDisplay';
import { clamp01, countUp, holdThenMove, sectionProgress, shotNumber } from '@/lib/landing-scroll';

/**
 * The scrolling story at the top of `/login`, before "who is signing in":
 * 1. The headline among four of the app's screens. Scrolling blurs it away while a green card
 *    rises and grows to fill the screen; on it a phone counts up Mdm Lim's steps, "CARE+" slides
 *    in and small notes float up.
 * 2. The app tour: six screens in a row that glide past one at a time, each resting in the middle.
 * 3. Then the sign-in choices (the page itself, `LoginChooserView.vue`).
 *
 * How it works: each part is a tall section with a stage pinned inside it (`position: sticky`).
 * One `scroll` listener (at most once a frame, `requestAnimationFrame`) works out how far through
 * each section the reader is (`lib/landing-scroll.ts`) and writes it to CSS variables (`--p`,
 * `--g`); the CSS turns those into `transform`, `opacity` and `filter`. The screens are pictures
 * of the app in `public/landing/`.
 *
 * Stacked and still instead (the `.still` class, a normal page read top to bottom): with reduced
 * motion, and when the screen is too short for a pinned scene to fit (a phone turned sideways, or
 * a large zoom, whether the browser's or Care+'s own text size), so nothing is ever cut off.
 */
const SHOTS = [
  {
    src: '/landing/home.jpg',
    kicker: 'Home',
    title: 'See her day at a glance.',
    text: 'Steps against her usual day, what is coming up, and what the family has done.',
    alt: 'The family’s Home screen',
  },
  {
    src: '/landing/calendar.jpg',
    kicker: 'Calendar',
    title: 'Share who goes along.',
    text: 'Every visit shows who is going, and which ones still need someone.',
    alt: 'The Calendar screen',
  },
  {
    src: '/landing/family.jpg',
    kicker: 'Family',
    title: 'Know who is free, and when.',
    text: 'Each person paints their free hours, so the gaps show at once.',
    alt: 'The Family screen',
  },
  {
    src: '/landing/walk.jpg',
    kicker: 'Walk',
    title: 'Walks she chooses to share.',
    text: 'Her place on the map only when she turns it on, and a badge for every walk.',
    alt: 'The Walk screen',
  },
  {
    src: '/landing/watch.jpg',
    kicker: 'Watch',
    title: 'Her watch, in 3D.',
    text: 'Battery, steps and wear time from her simulated watch.',
    alt: 'The Watch screen',
  },
  {
    src: '/landing/senior.jpg',
    kicker: 'My day',
    title: 'Big, clear, and hers.',
    text: 'Mdm Lim’s own screen: her steps, her tasks and her calendar.',
    alt: 'The senior’s own My day screen',
  },
] as const;

const FROM_STEPS = 4980;
const TO_STEPS = 5720;
/** Below this height (in CSS pixels at Care+'s 100% text size) a pinned scene does not fit. */
const MIN_STAGE_HEIGHT = 600;

const root = ref<HTMLElement | null>(null);
const story = ref<HTMLElement | null>(null);
const tour = ref<HTMLElement | null>(null);
const stage = ref<HTMLElement | null>(null);
const track = ref<HTMLElement | null>(null);
const still = ref(false);
const steps = ref(TO_STEPS);
const shot = ref(1);
let frame = 0;

function paint() {
  frame = 0;
  const el = root.value;
  if (still.value || !el || !story.value || !tour.value || !stage.value || !track.value) return;
  const pinTop =
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sl-pinned-height')) ||
    0;
  const stageHeight = stage.value.offsetHeight;

  // Part 1: the headline, then the card.
  const storyBox = story.value.getBoundingClientRect();
  const p = sectionProgress(storyBox.top, storyBox.height, stageHeight, pinTop);
  el.style.setProperty('--p', p.toFixed(4));
  steps.value = countUp((p - 0.36) / 0.34, FROM_STEPS, TO_STEPS);

  // Part 2: the screens, each resting before the next.
  const cards = Array.from(track.value.children) as HTMLElement[];
  if (cards.length > 1) {
    const step = cards[1].offsetLeft - cards[0].offsetLeft;
    el.style.setProperty('--shift', `${step * (cards.length - 1)}px`);
    const tourBox = tour.value.getBoundingClientRect();
    const row = holdThenMove(
      sectionProgress(tourBox.top, tourBox.height, stageHeight, pinTop),
      cards.length,
    );
    el.style.setProperty('--g', row.toFixed(4));
    cards.forEach((card, index) => {
      const distance = clamp01(Math.abs(index - row * (cards.length - 1)));
      card.style.setProperty('--c', (1 - distance * 0.12).toFixed(3));
      card.style.setProperty('--o', (1 - distance * 0.55).toFixed(3));
    });
    shot.value = shotNumber(row, cards.length);
  }
}

function schedule() {
  if (!frame) frame = requestAnimationFrame(paint);
}

const { zoom } = useDisplay();
const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)') ?? null;

/** Pinned and moving, or stacked and still. Checked again whenever any of its reasons changes. */
function decide() {
  const tooShort = (window.innerHeight * 100) / zoom.value < MIN_STAGE_HEIGHT;
  still.value = (reducedMotion?.matches ?? false) || tooShort;
  if (still.value) {
    steps.value = TO_STEPS;
    shot.value = 1;
  }
  schedule();
}

watch(zoom, decide);

onMounted(() => {
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', decide, { passive: true });
  reducedMotion?.addEventListener('change', decide);
  decide();
});

onBeforeUnmount(() => {
  window.removeEventListener('scroll', schedule);
  window.removeEventListener('resize', decide);
  reducedMotion?.removeEventListener('change', decide);
  if (frame) cancelAnimationFrame(frame);
});
</script>

<template>
  <div ref="root" class="landing" :class="{ still }">
    <section ref="story" class="story" aria-labelledby="landing-title">
      <div ref="stage" class="stage">
        <figure class="float f1" aria-hidden="true"><img src="/landing/home.jpg" alt="" /></figure>
        <figure class="float f2" aria-hidden="true">
          <img src="/landing/calendar.jpg" alt="" />
        </figure>
        <figure class="float f3" aria-hidden="true">
          <img src="/landing/senior.jpg" alt="" />
        </figure>
        <figure class="float f4" aria-hidden="true">
          <img src="/landing/family.jpg" alt="" />
        </figure>

        <div class="hero">
          <span class="hero-chip"
            ><span class="hero-dot"></span>For families, and the seniors they love</span
          >
          <h1 id="landing-title" class="hero-title">
            Stay close to her day,<br /><span class="hero-dim">not just her steps.</span>
          </h1>
          <p class="hero-lede">
            Care+ helps a family share the care of an older parent, gently and with her say-so.
          </p>
          <a class="btn btn-primary btn-lg sl-cta" href="#sign-in">
            Get started <Icon name="arrow-down" class="ms-1" />
          </a>
        </div>
        <div class="scroll-hint" aria-hidden="true">
          Scroll
          <Icon name="chevron-down" />
        </div>

        <div class="card-grow">
          <div class="card-in">
            <div class="copy">
              <h2 class="copy-title">Care, shared.<br />Never watched.</h2>
              <p class="mb-0">
                <strong>Care+</strong> shows the family how Mdm Lim’s day is going, who is going
                along to each visit, and cheers every walk she takes. She chooses what is shared.
              </p>
            </div>

            <div class="phone" aria-hidden="true">
              <div class="phone-notch"></div>
              <div class="phone-screen">
                <div class="phone-top">
                  <span>Tuesday, 3 November</span><span class="phone-me">L</span>
                </div>
                <div class="phone-hello">Good evening,<br />Mdm Lim</div>
                <div class="phone-ring">
                  <svg viewBox="0 0 170 170">
                    <circle cx="85" cy="85" r="70" class="ring-track" />
                    <circle
                      cx="85"
                      cy="85"
                      r="70"
                      class="ring-fill"
                      transform="rotate(-90 85 85)"
                    />
                    <text x="85" y="88" class="ring-num">{{ steps.toLocaleString('en-SG') }}</text>
                    <text x="85" y="110" class="ring-unit">steps today</text>
                  </svg>
                </div>
                <div class="phone-row">
                  <span class="phone-day">2</span>
                  <span
                    >Doctor’s appointment<br /><span class="phone-soft">Mon, 10:00 am</span></span
                  >
                </div>
                <div class="phone-row">
                  <span class="phone-tick"></span>
                  <span>Blood pressure tablet<br /><span class="phone-soft">8:00 pm</span></span>
                </div>
              </div>
            </div>

            <div class="word" aria-hidden="true">CARE+</div>

            <div class="chip chip-a" aria-hidden="true">
              <Icon name="star" class="chip-star" />
              <span
                ><strong>Park Loop</strong><br /><span class="phone-soft">Badge earned</span></span
              >
            </div>
            <div class="chip chip-b" aria-hidden="true">
              <span class="chip-avatar">S</span>
              <span
                ><strong>Sarah is going along</strong><br /><span class="phone-soft"
                  >Doctor’s visit, Mon</span
                ></span
              >
            </div>
            <div class="chip chip-c" aria-hidden="true">
              <span class="hero-dot"></span>Watch synced 4 min ago
            </div>
          </div>
        </div>
      </div>
    </section>

    <section ref="tour" class="tour" aria-labelledby="landing-tour">
      <div class="stage tour-stage">
        <div class="tour-head">
          <h2 id="landing-tour" class="tour-title">
            One app,<br /><span class="hero-dim">every part of her care.</span>
          </h2>
          <div v-if="!still" class="tour-count">
            <span>{{ shot }} / {{ SHOTS.length }}</span>
            <span class="tour-bar" aria-hidden="true"><span></span></span>
          </div>
        </div>
        <ul ref="track" class="track">
          <li v-for="item in SHOTS" :key="item.src" class="shot">
            <figure class="m-0">
              <img class="shot-img" :src="item.src" :alt="item.alt" loading="lazy" />
              <figcaption>
                <span class="shot-kicker">{{ item.kicker }}</span>
                <span
                  ><strong class="shot-title">{{ item.title }}</strong
                  >{{ ' ' }}<span class="shot-text">{{ item.text }}</span></span
                >
              </figcaption>
            </figure>
          </li>
        </ul>
        <p class="tour-note">Sample screens, with Care+’s made-up demo family.</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.landing {
  /* Scroll progress, set by the script: --p through part 1, --g along the tour's row. */
  --p: 0;
  --g: 0;
  --stage-h: calc(100dvh - var(--sl-pinned-height, 0px));
  /* Each effect's own 0-to-1, cut from --p: the headline fades, the card grows, then its
     contents arrive in turn, and the ring fills. */
  --pb: clamp(0, calc(var(--p) - 0.06), 1);
  --h: clamp(0, calc(1 - (var(--p) - 0.06) / 0.2), 1);
  --q: clamp(0, calc((var(--p) - 0.08) / 0.3), 1);
  --r: clamp(0, calc((var(--p) - 0.28) / 0.18), 1);
  --w: clamp(0, calc((var(--p) - 0.36) / 0.2), 1);
  --s: clamp(0, calc((var(--p) - 0.48) / 0.14), 1);
  --f: clamp(0, calc((var(--p) - 0.36) / 0.34), 1);

  position: relative;
  width: 100vw;
  /* No space below: the sign-in section starts right where the story ends. */
  margin: -1.5rem 0 0 calc(50% - 50vw);
  background:
    radial-gradient(50% 40% at 15% 10%, rgb(11 104 79 / 70%), transparent),
    radial-gradient(40% 30% at 60% 0%, rgb(111 220 174 / 18%), transparent),
    radial-gradient(50% 40% at 90% 60%, rgb(11 104 79 / 55%), transparent), #04110d;
  color: #ffffff;
}

@media (min-width: 768px) {
  .landing {
    margin-top: -3rem;
  }
}

/* `100vw` includes the scroll bar, so the band is a few pixels wider than the page. Only on the
   page that shows it, the layout cuts that off instead of scrolling sideways. `clip`, unlike
   `hidden`, keeps `position: sticky` working inside. */
:global(.shell:has(.landing)) {
  overflow-x: clip;
}

/* A phone with the bottom tab bar: the stage stops above it. */
@media (max-width: 767.98px) {
  :root:has(.mainnav--tabs) .landing {
    --stage-h: calc(100dvh - var(--sl-pinned-height, 0px) - var(--sl-tabbar-height));
  }
}

.stage {
  position: sticky;
  top: var(--sl-pinned-height, 0px);
  height: var(--stage-h);
  overflow: hidden;
}

/* ---- Part 1 ---- */
.story {
  position: relative;
  height: calc(var(--stage-h) * 3.4);
}

.float {
  position: absolute;
  width: clamp(10.5rem, 21vw, 20rem);
  aspect-ratio: 16 / 10;
  margin: 0;
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 16%);
  border-radius: 1rem;
  box-shadow: 0 24px 60px rgb(0 0 0 / 50%);
  opacity: calc(0.62 * var(--h));
  transform: translate(calc(var(--pb) * var(--dx)), calc(var(--pb) * var(--dy))) rotate(var(--rot))
    scale(calc(1 + var(--pb) * 0.25));
}

.float img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: top;
}

.f1 {
  --rot: -6deg;
  --dx: -26vw;
  --dy: -18vh;
  top: 12%;
  left: 3%;
}

.f2 {
  --rot: 5deg;
  --dx: 26vw;
  --dy: -20vh;
  top: 9%;
  right: 3%;
}

.f3 {
  --rot: 5deg;
  --dx: -28vw;
  --dy: 16vh;
  top: 60%;
  left: 5%;
}

.f4 {
  --rot: -4deg;
  --dx: 28vw;
  --dy: 18vh;
  top: 62%;
  right: 4%;
}

.hero {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1.1rem;
  padding: 0 1.5rem;
  text-align: center;
  opacity: var(--h);
  filter: blur(calc(var(--pb) * 30px));
  transform: translateY(calc(var(--pb) * -80px)) scale(calc(1 - var(--pb) * 0.2));
}

.hero-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 1rem;
  border: 1px solid rgb(255 255 255 / 12%);
  border-radius: 999px;
  background: rgb(9 26 21 / 70%);
  color: #d9ebe4;
  font-size: 0.875rem;
}

.hero-dot {
  flex: none;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: #6fdcae;
  box-shadow: 0 0 10px #6fdcae;
}

.hero-title {
  margin: 0;
  color: #ffffff;
  font-size: clamp(2.75rem, 7.4vw, 6.5rem);
  line-height: 0.98;
  letter-spacing: -0.035em;
  text-shadow: 0 6px 40px rgb(4 17 13 / 90%);
}

.hero-dim {
  color: rgb(255 255 255 / 62%);
}

.hero-lede {
  max-width: 36ch;
  margin: 0;
  color: #d9ebe4;
  font-size: 1.25rem;
  text-shadow: 0 4px 24px rgb(4 17 13 / 90%);
}

.scroll-hint {
  position: absolute;
  z-index: 6;
  bottom: 1.2rem;
  left: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  color: #b5cbc3;
  font-size: 0.85rem;
  opacity: clamp(0, calc(1 - var(--p) * 10), 1);
  transform: translateX(-50%);
}

.scroll-hint .sl-icon {
  animation: landing-bob 1.6s ease-in-out infinite;
}

@keyframes landing-bob {
  50% {
    transform: translateY(6px);
  }
}

.card-grow {
  position: absolute;
  z-index: 5;
  inset: 0;
  overflow: hidden;
  border-radius: calc((1 - var(--q)) * 44px);
  background: linear-gradient(160deg, #0b684f 0%, #073d30 55%, #052a21 100%);
  box-shadow: 0 30px 80px rgb(0 0 0 / 45%);
  transform: translateY(calc((1 - var(--q)) * var(--stage-h) * 0.66))
    scale(calc(0.56 + var(--q) * 0.44));
}

.card-in {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: var(--r);
}

.copy {
  position: absolute;
  top: 50%;
  left: clamp(1.5rem, 6vw, 6rem);
  max-width: 21rem;
  color: #d9ebe4;
  transform: translate(calc((1 - var(--r)) * -40px), -50%);
}

.copy strong {
  color: #ffffff;
}

.copy-title {
  margin: 0 0 0.75rem;
  color: #ffffff;
  font-family: 'Bricolage Grotesque', var(--bs-body-font-family);
  font-size: 2.1rem;
  font-weight: 800;
  line-height: 1.05;
}

.phone {
  position: relative;
  z-index: 2;
  height: min(38rem, calc(var(--stage-h) - 6rem));
  aspect-ratio: 300 / 610;
  overflow: hidden;
  border: 10px solid #1c2e28;
  border-radius: 48px;
  background: #06140f;
  box-shadow:
    0 40px 90px rgb(0 0 0 / 55%),
    inset 0 0 0 2px #31453f;
  transform: translateY(calc((1 - var(--r)) * 80px)) rotate(calc((1 - var(--r)) * -6deg));
}

.phone-notch {
  position: absolute;
  top: 10px;
  left: 50%;
  width: 90px;
  height: 24px;
  margin-left: -45px;
  border-radius: 999px;
  background: #000000;
}

.phone-screen {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  padding: 3rem 1.1rem 1.1rem;
  font-size: 0.8rem;
}

.phone-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #b5cbc3;
}

.phone-me,
.chip-avatar {
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-weight: 700;
}

.phone-me {
  width: 26px;
  height: 26px;
  background: #0b684f;
  font-size: 0.7rem;
}

.phone-hello {
  font-family: 'Bricolage Grotesque', var(--bs-body-font-family);
  font-size: 1.35rem;
  font-weight: 800;
  line-height: 1.1;
}

.phone-ring svg {
  display: block;
  width: min(170px, 100%);
  margin: 0 auto;
}

.ring-track,
.ring-fill {
  fill: none;
  stroke-width: 12;
}

.ring-track {
  stroke: rgb(255 255 255 / 10%);
}

.ring-fill {
  stroke: #6fdcae;
  stroke-linecap: round;
  stroke-dasharray: 439.8;
  stroke-dashoffset: calc(439.8 * (1 - var(--f) * 0.996));
}

.ring-num {
  fill: #ffffff;
  font-family: 'Bricolage Grotesque', sans-serif;
  font-size: 34px;
  font-weight: 800;
  text-anchor: middle;
}

.ring-unit {
  fill: #b5cbc3;
  font-size: 12px;
  text-anchor: middle;
}

.phone-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.75rem;
  border-radius: 14px;
  background: rgb(255 255 255 / 6%);
}

.phone-day {
  display: grid;
  flex: none;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: rgb(140 180 255 / 18%);
  color: #c3d7ff;
  font-weight: 700;
}

.phone-tick {
  flex: none;
  width: 26px;
  height: 26px;
  border: 2px solid #f4c95d;
  border-radius: 50%;
}

.phone-soft {
  color: #b5cbc3;
}

.word {
  position: absolute;
  z-index: 3;
  top: 50%;
  right: clamp(-2.5rem, 2vw, 4rem);
  color: #f2f7f4;
  font-family: 'Bricolage Grotesque', var(--bs-body-font-family);
  font-size: clamp(5.5rem, 15vw, 15rem);
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 0.8;
  opacity: var(--w);
  text-shadow: 0 20px 60px rgb(0 0 0 / 40%);
  transform: translate(calc((1 - var(--w)) * 60vw), -50%);
}

.chip {
  position: absolute;
  z-index: 4;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.9rem;
  border: 1px solid rgb(255 255 255 / 14%);
  border-radius: 18px;
  background: rgb(14 32 27 / 88%);
  box-shadow: 0 14px 34px rgb(0 0 0 / 40%);
  font-size: 0.8rem;
  line-height: 1.25;
  opacity: var(--s);
}

.chip-star {
  width: 1.6rem;
  height: 1.6rem;
  color: #f4c95d;
}

.chip-avatar {
  width: 30px;
  height: 30px;
  background: #8a3f7c;
}

.chip-a {
  top: calc(50% - 15rem);
  left: calc(50% - 15.5rem);
  transform: translateY(calc((1 - var(--s)) * 30px));
}

.chip-b {
  top: calc(50% + 11rem);
  left: calc(50% + 4.5rem);
  transform: translateY(calc((1 - var(--s)) * 40px));
}

.chip-c {
  top: calc(50% + 6.5rem);
  left: calc(50% - 17.5rem);
  transform: translateY(calc((1 - var(--s)) * 50px));
}

/* ---- Part 2 ---- */
.tour {
  position: relative;
  height: calc(var(--stage-h) * 5.2);
  background: linear-gradient(180deg, #052a21 0%, #04110d calc(var(--stage-h) * 0.9));
}

.tour-stage {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 1.4rem;
}

.tour-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.75rem 1.5rem;
  padding: 0 clamp(1.5rem, 6vw, 6rem);
}

.tour-title {
  margin: 0;
  color: #ffffff;
  font-family: 'Bricolage Grotesque', var(--bs-body-font-family);
  font-size: clamp(2rem, 4.2vw, 3.6rem);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1;
}

.tour-count {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  color: #cfe3db;
  font-size: 0.95rem;
  font-variant-numeric: tabular-nums;
}

.tour-bar {
  width: 10rem;
  height: 4px;
  overflow: hidden;
  border-radius: 999px;
  background: rgb(255 255 255 / 12%);
}

.tour-bar span {
  display: block;
  width: calc(var(--g) * 100%);
  height: 100%;
  border-radius: inherit;
  background: #6fdcae;
}

.track {
  --card: min(60vw, 54rem, calc((var(--stage-h) - 16rem) * 1.6));
  --gap: 2.5rem;
  display: flex;
  gap: var(--gap);
  margin: 0;
  padding: 0 calc(50vw - var(--card) / 2);
  list-style: none;
  transform: translateX(calc(var(--g) * var(--shift, 0px) * -1));
  will-change: transform;
}

.shot {
  flex: 0 0 var(--card);
  opacity: var(--o, 1);
  transform: scale(var(--c, 1));
  transition:
    transform 0.25s ease-out,
    opacity 0.25s ease-out;
}

.shot-img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
  object-position: top;
  border: 1px solid rgb(255 255 255 / 14%);
  border-radius: 1.4rem;
  box-shadow:
    0 30px 70px rgb(0 0 0 / 50%),
    0 0 0 6px rgb(255 255 255 / 3%);
}

.shot figcaption {
  display: flex;
  align-items: baseline;
  gap: 1rem;
  margin-top: 0.9rem;
  padding: 0 0.4rem;
}

.shot-kicker {
  flex: none;
  color: #9debc8;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.shot-title {
  font-size: 1.2rem;
}

.shot-text {
  color: #cfe3db;
}

.tour-note {
  margin: 0;
  padding: 0 clamp(1.5rem, 6vw, 6rem);
  color: #9fb8af;
  font-size: 0.85rem;
}

/* ---- Phones ---- */
@media (max-width: 767.98px) {
  .f2,
  .f4,
  .chip-c {
    display: none;
  }

  .float {
    width: 42vw;
  }

  .f1 {
    top: 6%;
    left: -6%;
  }

  .f3 {
    top: 72%;
    right: -6%;
    left: auto;
  }

  .copy {
    top: 1.25rem;
    right: 1.5rem;
    left: 1.5rem;
    max-width: none;
    font-size: 0.95rem;
    transform: translateX(calc((1 - var(--r)) * -40px));
  }

  .copy-title {
    font-size: 1.6rem;
  }

  .phone {
    height: min(26rem, calc(var(--stage-h) - 15rem));
    margin-top: 8rem;
  }

  .word {
    top: auto;
    right: auto;
    bottom: 1rem;
    left: 50%;
    font-size: 24vw;
    transform: translate(calc(-50% + (1 - var(--w)) * 60vw), 0);
  }

  .chip-a {
    top: auto;
    bottom: 9rem;
    left: 0.75rem;
  }

  .chip-b {
    top: auto;
    right: 0.75rem;
    bottom: 6rem;
    left: auto;
  }

  .track {
    --card: 84vw;
    --gap: 1.1rem;
  }

  .shot figcaption {
    flex-direction: column;
    gap: 0.2rem;
  }
}

/* ---- Reduced motion: the same parts, stacked and still ---- */
.still .story,
.still .tour {
  height: auto;
}

.still .stage {
  position: relative;
  top: auto;
  height: auto;
  overflow: visible;
}

.still .float,
.still .scroll-hint {
  display: none;
}

.still .hero {
  position: relative;
  padding: 6rem 1.5rem 3rem;
  opacity: 1;
  filter: none;
  transform: none;
}

.still .card-grow {
  position: relative;
  height: 46rem;
  margin: 0 1.5rem;
  border-radius: 2.5rem;
  transform: none;
}

.still .card-in,
.still .chip,
.still .word {
  opacity: 1;
}

.still .phone,
.still .chip {
  transform: none;
}

.still .copy,
.still .word {
  transform: translateY(-50%);
}

.still .ring-fill {
  stroke-dashoffset: 0;
}

.still .tour-stage {
  padding: 4rem 0;
}

.still .track {
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  padding-bottom: 1rem;
  transform: none;
}

.still .shot {
  opacity: 1;
  scroll-snap-align: center;
  transform: none;
}

@media (max-width: 767.98px) {
  .still .copy {
    transform: none;
  }

  .still .word {
    transform: translateX(-50%);
  }
}
</style>
