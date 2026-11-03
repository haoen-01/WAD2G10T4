<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';

import type { IconName } from '@/components/ui/Icon.vue';
import Icon from '@/components/ui/Icon.vue';
import type { WatchPoint } from '@/lib/watch';

/**
 * One point of the watch, opened: what it is, the figure, a chart of recent days and a few facts.
 * Its rows rise in one after another once the watch has turned; each opens to say a little more.
 * Back (and Escape, handled by the page) closes it.
 */
const props = defineProps<{ point: WatchPoint; elder: string }>();
const emit = defineEmits<{ close: [] }>();
// The points name icons as plain strings (lib/ stays free of components).
const iconOf = (name: string) => name as IconName;

const heading = ref<HTMLElement | null>(null);
onMounted(() => {
  // Move focus to the heading so a screen reader starts reading the details.
  void nextTick(() => heading.value?.focus({ preventScroll: true }));
});

const top = computed(() =>
  Math.max(props.point.guide ?? 0, ...props.point.bars.map((bar) => bar.value), 1),
);
const guideAt = computed(() =>
  props.point.guide === null ? null : `${(props.point.guide / top.value) * 100}%`,
);
// Which rows are open.
const opened = ref<string | null>(null);
const toggle = (label: string) => (opened.value = opened.value === label ? null : label);

const chartLabel = computed(() =>
  props.point.bars.map((bar) => `${bar.label} ${Math.round(bar.value * 10) / 10}`).join(', '),
);
</script>

<template>
  <section
    class="detail"
    role="region"
    :aria-labelledby="`watch-detail-${point.id}`"
    :data-testid="`watch-detail-${point.id}`"
  >
    <div class="detail-top" style="--i: 0">
      <button type="button" class="detail-back" @click="emit('close')">
        <Icon name="chevron-left" class="me-1" />Back
      </button>
    </div>

    <div class="detail-head" style="--i: 1">
      <span class="detail-icon"><Icon :name="iconOf(point.icon)" /></span>
      <div>
        <h2 :id="`watch-detail-${point.id}`" ref="heading" class="detail-title" tabindex="-1">
          {{ point.label }}
        </h2>
        <p class="detail-figure mb-0">{{ point.headline }}</p>
        <p v-if="point.note" class="detail-note mb-0">
          <span class="dot" aria-hidden="true"></span>{{ point.note }}
        </p>
      </div>
    </div>

    <figure v-if="point.bars.length" class="detail-chart" style="--i: 2">
      <div
        class="bars"
        role="img"
        :aria-label="`The last ${point.bars.length} days: ${chartLabel}`"
      >
        <span
          v-for="(bar, index) in point.bars"
          :key="index"
          class="bar"
          :class="{ latest: index === point.bars.length - 1 }"
          :style="{ height: `${(bar.value / top) * 100}%`, '--b': index }"
        ></span>
        <span v-if="guideAt" class="guide" :style="{ bottom: guideAt }">
          <span>{{ point.guide }} h</span>
        </span>
      </div>
      <figcaption class="chart-axis">
        <span>{{ point.bars[0].label }}</span>
        <span>Latest</span>
      </figcaption>
    </figure>

    <ul class="facts list-unstyled mb-0">
      <li v-for="(fact, index) in point.facts" :key="fact.label" :style="{ '--i': index + 3 }">
        <button
          type="button"
          class="fact"
          :aria-expanded="opened === fact.label"
          :disabled="!fact.more"
          @click="toggle(fact.label)"
        >
          <span class="fact-icon"><Icon :name="iconOf(fact.icon)" /></span>
          <span class="fact-text">
            <span class="fact-label">{{ fact.label }}</span>
            <strong class="fact-value">{{ fact.value }}</strong>
          </span>
          <Icon
            v-if="fact.more"
            name="chevron-right"
            class="fact-chevron"
            :class="{ open: opened === fact.label }"
          />
        </button>
        <Transition name="more">
          <p v-if="opened === fact.label && fact.more" class="fact-more mb-0">{{ fact.more }}</p>
        </Transition>
      </li>
    </ul>

    <p v-if="point.example" class="example mb-0" :style="{ '--i': point.facts.length + 3 }">
      Example device information for the simulated watch, not {{ elder }}’s data.
    </p>
  </section>
</template>

<style scoped>
/* Wide screens: the left half of the dark stage, beside the watch. */
.detail {
  position: absolute;
  top: 4rem;
  bottom: 0;
  left: 0;
  z-index: 4;
  width: min(42%, 520px);
  padding: 1rem clamp(1.5rem, 4vw, 4rem) 3rem;
  overflow-y: auto;
  color: #eef4f1;
}

.detail > *,
.facts li {
  animation: rise 0.7s cubic-bezier(0.22, 1, 0.36, 1) both;
  animation-delay: calc(0.55s + var(--i, 0) * 0.08s);
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
}

.detail-back {
  display: inline-flex;
  align-items: center;
  border: 0;
  background: transparent;
  color: #d5e2dc;
  font-weight: 600;
}

.detail-back {
  padding: 0.25rem 0.5rem 0.25rem 0;
}

.detail-back:hover,
.detail-back:focus-visible {
  background: rgb(255 255 255 / 10%);
  color: #fff;
}

.detail-back {
  border-radius: 999px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  margin: 1.4rem 0 1.25rem;
}

.detail-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 3.2rem;
  height: 3.2rem;
  border-radius: 50%;
  background: #f4f8f6;
  color: #17251f;
  font-size: 1.4rem;
}

.detail-title {
  margin: 0;
  /* Light on the dark stage (the page's own heading colour is dark in light mode). */
  color: #fff;
  font-size: clamp(1.6rem, 3vw, 2.1rem);
  font-weight: 800;
  letter-spacing: -0.02em;
  outline: none;
}

.detail-figure {
  font-size: 1.15rem;
  font-weight: 600;
}

.detail-note {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  margin-top: 0.3rem;
  color: #8fe0b0;
  font-size: 0.92rem;
}

.detail-note .dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: currentcolor;
}

/* A bar for each day, growing in one after another. */
.detail-chart {
  margin: 0 0 1.25rem;
}

.bars {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  height: 84px;
  padding-bottom: 1px;
  border-bottom: 1px solid rgb(255 255 255 / 15%);
}

.bar {
  flex: 0 0 5px;
  min-height: 3px;
  border-radius: 3px;
  background: linear-gradient(to top, rgb(77 214 140 / 45%), rgb(77 214 140 / 85%));
  transform-origin: bottom;
  animation: grow 0.8s cubic-bezier(0.22, 1, 0.36, 1) both;
  animation-delay: calc(0.75s + var(--b) * 0.035s);
}

.bar.latest {
  background: #6ff0a8;
  box-shadow: 0 0 14px rgb(111 240 168 / 45%);
}

@keyframes grow {
  from {
    transform: scaleY(0);
  }
}

.guide {
  position: absolute;
  right: 0;
  left: 0;
  z-index: 1;
  border-top: 1.5px dashed rgb(255 255 255 / 80%);
}

.guide span {
  position: absolute;
  top: -1.2rem;
  right: 0;
  color: #cfdcd6;
  font-size: 0.75rem;
}

.chart-axis {
  display: flex;
  justify-content: space-between;
  margin-top: 0.35rem;
  color: #a9bdb4;
  font-size: 0.75rem;
}

.facts {
  display: grid;
}

.facts li {
  border-top: 1px solid rgb(255 255 255 / 10%);
}

/* Each row opens to say a little more; the chevron turns to show it is open. */
.fact {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  width: 100%;
  padding: 0.8rem 0.25rem;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  transition: background 0.2s ease;
}

.fact:hover:not(:disabled),
.fact:focus-visible {
  border-radius: 12px;
  background: rgb(255 255 255 / 6%);
}

.fact:disabled {
  opacity: 1;
}

.fact-text {
  flex: 1;
  min-width: 0;
}

.fact-chevron {
  flex: none;
  color: #cfdcd6;
  transition: transform 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}

.fact-chevron.open {
  transform: rotate(90deg);
}

.fact-more {
  padding: 0 0.25rem 0.9rem 3.35rem;
  color: #c3d3cc;
  font-size: 0.88rem;
}

.more-enter-active,
.more-leave-active {
  transition:
    opacity 0.3s ease,
    transform 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}

.more-enter-from,
.more-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.fact-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 2.2rem;
  height: 2.2rem;
  border: 1px solid rgb(255 255 255 / 25%);
  border-radius: 50%;
  font-size: 1rem;
}

.fact-label {
  display: block;
  color: #b8c9c1;
  font-size: 0.82rem;
}

.fact-value {
  display: block;
  font-size: 0.98rem;
  font-weight: 600;
}

.example {
  margin-top: 0.75rem;
  color: #b8c9c1;
  font-size: 0.8rem;
}

/* Phones and small tablets: the details sit under the watch. */
@media (max-width: 991.98px) {
  .detail {
    position: relative;
    width: auto;
    order: 4;
    top: auto;
    margin-top: 360px;
    padding: 1.25rem 1.25rem 2rem;
    background: color-mix(in srgb, var(--bs-dark) 92%, transparent);
    border-radius: 28px 28px 0 0;
    overflow: visible;
  }

  .detail-head {
    margin-top: 0.5rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .detail > *,
  .facts li,
  .bar {
    animation: none;
  }
}

.detail {
  overflow-wrap: anywhere;
}
.detail-back {
  min-height: 44px;
}
.detail-back:focus-visible,
.fact:focus-visible {
  outline: 3px solid var(--bs-white);
  outline-offset: 3px;
}
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation: none !important;
    transition: none !important;
  }
}
</style>
