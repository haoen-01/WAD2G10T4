<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import type { Appointment } from '@/lib/family';
import {
  WEEKDAYS_LONG,
  WEEKDAYS_SHORT,
  formatIsoDay,
  formatMonthYear,
  parseIsoDay,
} from '@/lib/format-date';
import { weekOf } from '@/lib/week';

/**
 * The phone's calendar: one week as seven day buttons, with a sideways swipe and Previous and Next
 * buttons to change week (the buttons do exactly what the swipe does). Choosing a day shows its
 * agenda below. The month grid (`Calendar.vue`) is the wide-screen version of the same thing.
 */
const props = defineProps<{
  selectedDay: string;
  today: string;
  appointmentsByDay: Record<string, Appointment[]>;
  /** How many of each day's appointments nobody has taken yet. */
  uncoveredByDay: Record<string, number>;
  /** Of those, how many have someone asked and waiting for an answer. */
  askedByDay?: Record<string, number>;
  holidaysByDay?: Record<string, string>;
  /** The day the open appointment form has chosen. */
  pickedDay?: string | null;
}>();
const emit = defineEmits<{
  'select-day': [iso: string];
  /** One week back (-1) or forward (1), keeping the same weekday. */
  'shift-week': [delta: -1 | 1];
  'go-today': [];
}>();

const days = computed(() => weekOf(props.selectedDay));
const title = computed(() => {
  const first = parseIsoDay(days.value[0]);
  const last = parseIsoDay(days.value[6]);
  if (!first || !last) return '';
  if (first.month === last.month) return formatMonthYear(first.year, first.month);
  // Across two months the names are shortened, so the title stays on one line.
  const short = (value: string) => value.split(' ')[0].slice(0, 3);
  const a = formatMonthYear(first.year, first.month);
  const b = formatMonthYear(last.year, last.month);
  return first.year === last.year
    ? `${short(a)} – ${short(b)} ${last.year}`
    : `${short(a)} ${first.year} – ${short(b)} ${last.year}`;
});

// The week slides the way it was turned.
const direction = ref<'forward' | 'back'>('forward');
watch(
  () => days.value[0],
  (next, previous) => {
    direction.value = next >= previous ? 'forward' : 'back';
  },
);

const askedOn = (iso: string) => props.askedByDay?.[iso] ?? 0;
/** Every appointment still needing a helper that day has someone asked: amber, not coral. */
const allAsked = (iso: string) =>
  (props.uncoveredByDay[iso] ?? 0) > 0 && askedOn(iso) >= (props.uncoveredByDay[iso] ?? 0);

function labelFor(iso: string): string {
  const appointments = props.appointmentsByDay[iso]?.length ?? 0;
  const open = props.uncoveredByDay[iso] ?? 0;
  const holiday = props.holidaysByDay?.[iso];
  const planned =
    appointments === 0
      ? 'nothing planned'
      : `${appointments} ${appointments === 1 ? 'appointment' : 'appointments'}`;
  return [
    formatIsoDay(iso, { style: 'long' }),
    iso === props.today ? ', today' : '',
    holiday ? `, public holiday: ${holiday}` : '',
    `: ${planned}`,
    open ? `, ${open} ${open === 1 ? 'needs' : 'need'} a helper` : '',
    open && askedOn(iso) ? `, ${askedOn(iso)} with someone asked and waiting` : '',
  ].join('');
}

// A sideways swipe turns the week; a mostly vertical one is a scroll and is left alone.
let touchStart: { x: number; y: number } | null = null;
function onTouchStart(event: TouchEvent) {
  const touch = event.changedTouches[0];
  touchStart = { x: touch.clientX, y: touch.clientY };
}
function onTouchEnd(event: TouchEvent) {
  if (!touchStart) return;
  const touch = event.changedTouches[0];
  const dx = touch.clientX - touchStart.x;
  const dy = touch.clientY - touchStart.y;
  touchStart = null;
  if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy) * 2) return;
  emit('shift-week', dx < 0 ? 1 : -1);
}
</script>

<template>
  <section class="sl-panel week" aria-labelledby="week-heading" data-testid="week-strip">
    <div class="week-head">
      <h2 id="week-heading" class="week-title mb-0">{{ title }}</h2>
      <!-- Today first, then the two arrows as a pair that never splits: on a narrow phone at a large
           text size the pair wraps under Today together. -->
      <div class="week-nav">
        <button type="button" class="btn btn-outline-primary" @click="emit('go-today')">
          Today
        </button>
        <span class="week-arrows">
          <button
            type="button"
            class="btn btn-outline-primary"
            aria-label="Previous week"
            @click="emit('shift-week', -1)"
          >
            <Icon name="chevron-left" />
          </button>
          <button
            type="button"
            class="btn btn-outline-primary"
            aria-label="Next week"
            @click="emit('shift-week', 1)"
          >
            <Icon name="chevron-right" />
          </button>
        </span>
      </div>
    </div>

    <div class="week-swipe" @touchstart.passive="onTouchStart" @touchend="onTouchEnd">
      <Transition :name="`slide-${direction}`" mode="out-in">
        <div :key="days[0]" class="week-days" role="group" aria-label="Days of this week">
          <button
            v-for="iso in days"
            :key="iso"
            type="button"
            class="week-day"
            :class="{
              today: iso === today,
              selected: iso === selectedDay,
              picked: iso === pickedDay,
              past: iso < today,
              holiday: !!holidaysByDay?.[iso],
            }"
            :data-week-iso="iso"
            :aria-label="labelFor(iso)"
            :aria-pressed="iso === selectedDay"
            @click="emit('select-day', iso)"
          >
            <span class="week-name" aria-hidden="true">{{
              WEEKDAYS_SHORT[parseIsoDay(iso)?.weekday ?? 0]
            }}</span>
            <span class="visually-hidden">{{ WEEKDAYS_LONG[parseIsoDay(iso)?.weekday ?? 0] }}</span>
            <span class="week-num" aria-hidden="true">{{ parseIsoDay(iso)?.day }}</span>
            <span class="week-dots" aria-hidden="true">
              <span
                v-for="appointment in (appointmentsByDay[iso] ?? []).slice(0, 3)"
                :key="appointment.id"
                class="week-dot"
                :class="`kind-${appointment.kind}`"
              ></span>
              <span
                v-if="uncoveredByDay[iso]"
                class="week-open"
                :class="{ asked: allAsked(iso) }"
                :title="
                  allAsked(iso) ? 'Needs a helper · someone asked, waiting' : 'Needs a helper'
                "
              ></span>
            </span>
          </button>
        </div>
      </Transition>
    </div>
    <p class="sl-note mt-2 mb-0">Swipe sideways, or use the arrows, to change week.</p>
  </section>
</template>

<style scoped>
.week {
  padding: 0.85rem;
}

.week-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.week-title {
  flex: 0 0 auto;
  font-size: 1.05rem;
  font-weight: 700;
  white-space: nowrap;
}

/* The arrows and Today stay full size; on a narrow phone at a large text size the arrows wrap under
   Today, together, rather than push the page sideways. Lined up on the left, clear of Kaki at the
   right-hand edge. */
.week-nav {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-start;
  gap: 0.35rem;
  max-width: 100%;
}

.week-arrows {
  display: flex;
  gap: 0.35rem;
}

.week-nav .btn {
  min-width: 2.75rem;
  min-height: 2.75rem;
}

.week-swipe {
  overflow: hidden;
  touch-action: pan-y;
}

.week-days {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 0.2rem;
}

.week-day {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.15rem;
  min-height: 4.25rem;
  padding: 0.4rem 0.1rem;
  border: 1px solid transparent;
  border-radius: var(--sl-radius-sm);
  background: transparent;
  color: var(--sl-ink);
}

.week-day.past {
  color: var(--sl-ink-soft);
}

.week-day.holiday {
  background: var(--sl-sun-soft);
}

.week-day.today .week-num {
  box-shadow: inset 0 0 0 2px var(--sl-jade);
}

.week-day.picked {
  border-color: var(--sl-jade);
}

.week-day.selected {
  background: var(--sl-jade);
  color: #fff;
}

.week-day.selected .week-num {
  box-shadow: none;
}

.week-name {
  font-size: 0.75rem;
  font-weight: 700;
}

.week-num {
  display: grid;
  place-items: center;
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  font-size: 1.05rem;
  font-weight: 800;
}

.week-dots {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.2rem;
  min-height: 0.5rem;
}

.week-dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: var(--kind);
  box-shadow: 0 0 0 1.5px var(--sl-surface);
}

/* "Needs a helper": a ring, so it differs from the filled kind dots without relying on colour. */
.week-open {
  width: 0.45rem;
  height: 0.45rem;
  border: 2px solid var(--sl-coral-deep);
  border-radius: 50%;
  background: var(--sl-surface);
}

/* Someone asked and waiting: an amber ring, half filled, so it differs in shape as well. */
.week-open.asked {
  border-color: var(--sl-sun-deep);
  background: linear-gradient(var(--sl-surface) 50%, var(--sl-sun) 50%);
}

.slide-forward-enter-active,
.slide-forward-leave-active,
.slide-back-enter-active,
.slide-back-leave-active {
  transition:
    opacity 0.14s ease,
    transform 0.18s var(--sl-ease);
}

.slide-forward-enter-from,
.slide-back-leave-to {
  opacity: 0;
  transform: translateX(24px);
}

.slide-forward-leave-to,
.slide-back-enter-from {
  opacity: 0;
  transform: translateX(-24px);
}
</style>
