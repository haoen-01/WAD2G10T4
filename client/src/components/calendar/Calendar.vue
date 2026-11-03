<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';

import CalendarDay from '@/components/calendar/CalendarDay.vue';
import Icon from '@/components/ui/Icon.vue';
import { addDays, monthGrid, shiftMonth, toIsoDay } from '@/lib/calendar';
import type { MonthRef } from '@/lib/calendar';
import type { Appointment, FamilyMember } from '@/lib/family';
import type { TaskOccurrence } from '@/lib/tasks';
import { WEEKDAYS_LONG, WEEKDAYS_SHORT, formatMonthYear, parseIsoDay } from '@/lib/format-date';

/**
 * One month as a grid of days. A mouse or finger picks a day; on a phone a sideways swipe turns the
 * month. A keyboard moves like any date grid: arrows by day and week, Home and End to the ends of
 * the week, Page Up and Page Down by month. Only one day is in the tab order at a time.
 */
const props = defineProps<{
  month: MonthRef;
  today: string;
  selectedDay: string;
  appointmentsByDay: Record<string, Appointment[]>;
  /** How many of each day's appointments nobody has taken yet. */
  uncoveredByDay: Record<string, number>;
  /** Of those, how many have someone asked and waiting for an answer. */
  askedByDay?: Record<string, number>;
  /** Public holiday names by date (from `PublicHolidays.vue`); empty until they have loaded. */
  holidaysByDay?: Record<string, string>;
  /** Tasks from the Tasks panel by date. */
  tasksByDay?: Record<string, TaskOccurrence[]>;
  /** While choosing a day or dragging: who in the family is free, by date (`null` otherwise). */
  heatByDay?: Record<string, FamilyMember[]> | null;
  heatTotal?: number;
  /** The day the open appointment form has chosen. */
  pickedDay?: string | null;
  /** Appointments that can be dragged to another day. */
  movableIds?: ReadonlySet<string>;
}>();
const emit = defineEmits<{
  previous: [];
  next: [];
  'go-today': [];
  'select-day': [iso: string];
  /** A keyboard move, which may cross into another month. */
  'move-day': [iso: string];
  /** An appointment picked up, or put down (`null`), so the calendar can show who is free. */
  'drag-appointment': [id: string | null];
  /** An appointment dropped on another day. */
  'drop-appointment': [id: string, iso: string];
}>();

// ---- Dragging an appointment to another day (mouse or finger) ----
// A press on a movable chip becomes a drag once it has moved a little; a short press is still a
// click that opens the day. While dragging, a copy of the chip follows the pointer, the day under
// it is outlined, and letting go there moves the appointment.
const dragging = ref<{ id: string; title: string; x: number; y: number } | null>(null);
const dropDay = ref<string | null>(null);
let press: { id: string; title: string; x: number; y: number } | null = null;
let justDragged = false;

function dayUnder(x: number, y: number): string | null {
  return document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-iso]')?.dataset.iso ?? null;
}

function onPointerDown(event: PointerEvent) {
  const chip = (event.target as HTMLElement).closest<HTMLElement>('[data-appt]');
  if (!chip || event.button > 0) return;
  press = {
    id: chip.dataset.appt ?? '',
    title: chip.textContent?.trim() ?? '',
    x: event.clientX,
    y: event.clientY,
  };
  window.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp, { once: true });
  window.addEventListener('pointercancel', cancelDrag, { once: true });
}

function onPointerMove(event: PointerEvent) {
  if (!press) return;
  if (!dragging.value) {
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) < 6) return;
    dragging.value = { ...press, x: event.clientX, y: event.clientY };
    emit('drag-appointment', press.id);
  }
  dragging.value = { ...dragging.value, x: event.clientX, y: event.clientY };
  dropDay.value = dayUnder(event.clientX, event.clientY);
}

function onPointerUp(event: PointerEvent) {
  const drag = dragging.value;
  const target = drag ? dayUnder(event.clientX, event.clientY) : null;
  cancelDrag();
  if (!drag) return;
  // The click that follows letting go must not also open the day.
  justDragged = true;
  setTimeout(() => (justDragged = false), 0);
  if (target) emit('drop-appointment', drag.id, target);
}

function cancelDrag() {
  window.removeEventListener('pointermove', onPointerMove);
  if (dragging.value) emit('drag-appointment', null);
  press = null;
  dragging.value = null;
  dropDay.value = null;
}

function onClickCapture(event: MouseEvent) {
  if (!justDragged) return;
  event.stopPropagation();
  event.preventDefault();
}

onBeforeUnmount(cancelDrag);

const weeks = computed(() => monthGrid(props.month));
const title = computed(() => formatMonthYear(props.month.year, props.month.month));

// The month slides the way it was turned.
const direction = ref<'forward' | 'back'>('forward');
watch(
  () => props.month,
  (next, previous) => {
    direction.value =
      next.year * 12 + next.month >= previous.year * 12 + previous.month ? 'forward' : 'back';
  },
);

// The one day reachable with Tab: the chosen day if it is showing, else the 1st of the month.
const tabbable = computed(() => {
  const cells = weeks.value.flat();
  if (cells.some((cell) => cell.iso === props.selectedDay)) return props.selectedDay;
  return cells.find((cell) => cell.inMonth)?.iso ?? cells[0]?.iso;
});

const grid = ref<HTMLElement | null>(null);
let pendingFocus: string | null = null;

function focusPending() {
  if (!pendingFocus) return;
  const button = grid.value?.querySelector<HTMLButtonElement>(`[data-iso="${pendingFocus}"]`);
  if (button) {
    button.focus();
    pendingFocus = null;
  }
}

function sameDayInMonth(iso: string, delta: number): string {
  const parts = parseIsoDay(iso);
  if (!parts) return iso;
  const target = shiftMonth({ year: parts.year, month: parts.month }, delta);
  const length = new Date(Date.UTC(target.year, target.month, 0)).getUTCDate();
  return toIsoDay(target.year, target.month, Math.min(parts.day, length));
}

function onKey(event: KeyboardEvent) {
  const from =
    (event.target as HTMLElement).closest<HTMLElement>('[data-iso]')?.dataset.iso ??
    props.selectedDay;
  const weekday = parseIsoDay(from)?.weekday ?? 0;
  const moves: Record<string, () => string> = {
    ArrowLeft: () => addDays(from, -1),
    ArrowRight: () => addDays(from, 1),
    ArrowUp: () => addDays(from, -7),
    ArrowDown: () => addDays(from, 7),
    Home: () => addDays(from, -weekday),
    End: () => addDays(from, 6 - weekday),
    PageUp: () => sameDayInMonth(from, -1),
    PageDown: () => sameDayInMonth(from, 1),
  };
  const move = moves[event.key];
  if (!move) return;
  event.preventDefault();
  pendingFocus = move();
  emit('move-day', pendingFocus);
  // Same month: the button is already there. Another month: focus once it has slid in.
  void nextTick(focusPending);
}

// A sideways swipe turns the month; anything mostly vertical is a scroll and is left alone.
let touchStart: { x: number; y: number } | null = null;
function onTouchStart(event: TouchEvent) {
  // A finger on a movable appointment drags it; it does not turn the month.
  if ((event.target as HTMLElement).closest('[data-appt]')) {
    touchStart = null;
    return;
  }
  const touch = event.changedTouches[0];
  touchStart = { x: touch.clientX, y: touch.clientY };
}
function onTouchEnd(event: TouchEvent) {
  if (!touchStart) return;
  const touch = event.changedTouches[0];
  const dx = touch.clientX - touchStart.x;
  const dy = touch.clientY - touchStart.y;
  touchStart = null;
  if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 2) return;
  if (dx < 0) emit('next');
  else emit('previous');
}
</script>

<template>
  <section class="sl-panel cal" aria-labelledby="calendar-heading">
    <div class="cal-head">
      <h2 id="calendar-heading" class="h3 mb-0" aria-live="polite">{{ title }}</h2>
      <div class="cal-nav">
        <button
          type="button"
          class="btn btn-outline-primary"
          aria-label="Previous month"
          @click="$emit('previous')"
        >
          <Icon name="chevron-left" /><span class="d-none d-sm-inline ms-1">Previous</span>
        </button>
        <button type="button" class="btn btn-outline-primary" @click="$emit('go-today')">
          Today
        </button>
        <button
          type="button"
          class="btn btn-outline-primary"
          aria-label="Next month"
          @click="$emit('next')"
        >
          <span class="d-none d-sm-inline me-1">Next</span><Icon name="chevron-right" />
        </button>
      </div>
    </div>

    <div
      ref="grid"
      class="cal-grid"
      :class="{ dragging: !!dragging }"
      @keydown="onKey"
      @touchstart.passive="onTouchStart"
      @touchend="onTouchEnd"
      @pointerdown="onPointerDown"
      @click.capture="onClickCapture"
    >
      <table class="cal-table">
        <caption class="visually-hidden">
          {{
            title
          }}. Choose a day to see what is planned. Arrow keys move between days.
        </caption>
        <thead>
          <tr>
            <th v-for="(name, index) in WEEKDAYS_SHORT" :key="name" scope="col">
              <span aria-hidden="true">{{ name }}</span>
              <span class="visually-hidden">{{ WEEKDAYS_LONG[index] }}</span>
            </th>
          </tr>
        </thead>
        <Transition :name="`slide-${direction}`" mode="out-in" @after-enter="focusPending">
          <tbody :key="`${month.year}-${month.month}`">
            <tr v-for="week in weeks" :key="week[0].iso">
              <CalendarDay
                v-for="cell in week"
                :key="cell.iso"
                :cell="cell"
                :is-today="cell.iso === today"
                :is-selected="cell.iso === selectedDay"
                :tabbable="cell.iso === tabbable"
                :appointments="appointmentsByDay[cell.iso] ?? []"
                :uncovered="uncoveredByDay[cell.iso] ?? 0"
                :asked="askedByDay?.[cell.iso] ?? 0"
                :holiday="holidaysByDay?.[cell.iso] ?? null"
                :tasks="tasksByDay?.[cell.iso] ?? []"
                :past="cell.iso < today"
                :heat="heatByDay ? (heatByDay[cell.iso] ?? []) : null"
                :heat-total="heatTotal ?? 0"
                :picked="cell.iso === pickedDay"
                :drop-target="cell.iso === dropDay"
                :movable-ids="movableIds"
                @select="$emit('select-day', cell.iso)"
              />
            </tr>
          </tbody>
        </Transition>
      </table>
    </div>
    <div
      v-if="dragging"
      class="drag-ghost"
      :style="{ left: `${dragging.x}px`, top: `${dragging.y}px` }"
      aria-hidden="true"
    >
      {{ dragging.title }}
    </div>
    <p class="sl-note mt-3 mb-0 d-md-none">Swipe sideways to change the month.</p>
  </section>
</template>

<style scoped>
.cal {
  padding: 1rem;
}

@media (min-width: 768px) {
  .cal {
    padding: 1.25rem;
  }
}

.cal-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.cal-nav {
  display: flex;
  gap: 0.4rem;
}

.cal-grid {
  overflow: hidden;
  touch-action: pan-y;
}

.cal-grid.dragging {
  cursor: grabbing;
  user-select: none;
}

.drag-ghost {
  position: fixed;
  z-index: 1070;
  max-width: 12rem;
  padding: 0.3rem 0.6rem;
  border-radius: 0.4rem;
  background: var(--sl-ink);
  color: var(--sl-on-ink);
  font-size: 0.8rem;
  font-weight: 700;
  pointer-events: none;
  box-shadow: var(--sl-float);
  transform: translate(-50%, -130%);
}

.cal-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: separate;
}

.cal-table th {
  padding-bottom: 0.35rem;
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  font-weight: 700;
  text-align: center;
}

.slide-forward-enter-active,
.slide-forward-leave-active,
.slide-back-enter-active,
.slide-back-leave-active {
  transition:
    opacity 0.16s ease,
    transform 0.2s var(--sl-ease);
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
