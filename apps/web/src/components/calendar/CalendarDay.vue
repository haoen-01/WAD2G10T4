<script setup lang="ts">
import { computed } from 'vue';

import type { CalendarCell } from '@/lib/calendar';
import { KIND_LABELS, type Appointment, type FamilyMember } from '@/lib/family';
import { formatClockTime, formatIsoDay } from '@/lib/format-date';
import type { TaskOccurrence } from '@/lib/tasks';

const props = defineProps<{
  cell: CalendarCell;
  isToday: boolean;
  isSelected: boolean;
  /** The one day in the grid that Tab reaches; the arrow keys reach the rest. */
  tabbable: boolean;
  appointments: Appointment[];
  /** How many of them still need a helper. */
  uncovered: number;
  /** The public holiday on this day, if any. */
  holiday?: string | null;
  /** The day's tasks from the Tasks panel, shown after the appointments. */
  tasks?: TaskOccurrence[];
  /** Before today: shown faded. */
  past?: boolean;
  /**
   * While choosing a day for an appointment (or dragging one): who in the family is free then.
   * The cell is shaded by how many, so the best day stands out. `null` the rest of the time.
   */
  heat?: FamilyMember[] | null;
  heatTotal?: number;
  /** The day the open appointment form has chosen. */
  picked?: boolean;
  /** The day a dragged appointment would land on. */
  dropTarget?: boolean;
  /** Appointments that can be dragged to another day (one-off ones, for group members). */
  movableIds?: ReadonlySet<string>;
}>();
defineEmits<{ select: [] }>();

// Appointments first, then tasks: what the cell shows as dots on a phone and chips on a wider screen.
// `label`, `when` and `detail` fill the card that pops out when a chip is pointed at.
const items = computed(() => [
  ...props.appointments.map((appointment) => ({
    key: appointment.id,
    title: appointment.title,
    kind: appointment.kind,
    label: KIND_LABELS[appointment.kind],
    when: `${formatClockTime(appointment.start)} – ${formatClockTime(appointment.end)}`,
    detail: appointment.location ?? '',
    done: false,
    movable: props.movableIds?.has(appointment.id) ?? false,
  })),
  ...(props.tasks ?? []).map((task) => ({
    key: `task-${task.task_id}`,
    title: task.title,
    kind: 'task',
    label: task.kind === 'medicine' ? 'Medicine' : 'Task',
    when: formatClockTime(task.time),
    detail: task.notes,
    done: task.completed,
    movable: false,
  })),
]);

const showHeat = computed(() => !!props.heat && !props.past);
const heatRatio = computed(() =>
  props.heat && props.heatTotal ? props.heat.length / props.heatTotal : 0,
);

// Read out in full, because what the cell shows (a number and some colour) is not enough on its own.
const label = computed(() => {
  const count = props.appointments.length;
  const planned =
    count === 0
      ? props.tasks?.length
        ? 'no appointments'
        : 'nothing planned'
      : `${count} ${count === 1 ? 'appointment' : 'appointments'}`;
  const open =
    props.uncovered > 0
      ? `, ${props.uncovered} ${props.uncovered === 1 ? 'needs' : 'need'} a helper`
      : '';
  const taskCount = props.tasks?.length ?? 0;
  const tasks = taskCount ? `, ${taskCount} ${taskCount === 1 ? 'task' : 'tasks'}` : '';
  const day = formatIsoDay(props.cell.iso, { style: 'long' });
  const holiday = props.holiday ? `, public holiday: ${props.holiday}` : '';
  const free = showHeat.value ? `, ${props.heat?.length ?? 0} of the family free` : '';
  return `${day}${props.isToday ? ', today' : ''}${holiday}: ${planned}${open}${tasks}${free}`;
});
</script>

<template>
  <td class="cal-cell" :class="{ outside: !cell.inMonth }">
    <button
      type="button"
      class="cal-day"
      :class="{
        today: isToday,
        selected: isSelected,
        busy: items.length > 0,
        holiday: !!holiday,
        past,
        heat: showHeat,
        picked,
        target: dropTarget,
      }"
      :style="showHeat ? { '--heat': heatRatio } : undefined"
      :data-iso="cell.iso"
      :tabindex="tabbable ? 0 : -1"
      :aria-label="label"
      :aria-pressed="isSelected"
      @click="$emit('select')"
    >
      <span class="cal-top" aria-hidden="true">
        <span class="cal-num">{{ cell.day }}</span>
        <span v-if="uncovered" class="cal-open" title="Needs a helper"></span>
      </span>
      <span v-if="holiday" class="cal-holiday" :title="holiday" aria-hidden="true">
        {{ holiday }}
      </span>
      <!-- Narrow screens: one dot per item (a task's is square). Wider screens: the titles. -->
      <span v-if="items.length" class="cal-dots" aria-hidden="true">
        <span
          v-for="item in items.slice(0, 4)"
          :key="item.key"
          class="cal-dot"
          :class="`kind-${item.kind}`"
        ></span>
      </span>
      <span v-if="showHeat && heat?.length" class="cal-heat" aria-hidden="true">
        {{ heat?.length ?? 0 }} free
      </span>
      <!-- Each chip, and a card with all of it that pops out while the mouse is on the chip. The
           day's own name already says what is planned, so these are hidden from screen readers. -->
      <span
        v-for="item in items.slice(0, 2)"
        :key="`chip-${item.key}`"
        class="cal-item"
        aria-hidden="true"
      >
        <span
          class="cal-chip"
          :class="[`kind-${item.kind}`, { done: item.done, movable: item.movable }]"
          :data-appt="item.movable ? item.key : undefined"
        >
          <template v-if="item.kind === 'task'">{{ item.done ? '✓' : '☐' }} </template
          >{{ item.title }}
        </span>
        <span class="cal-pop" :class="`kind-${item.kind}`" data-testid="cal-pop">
          <span class="cal-pop-meta">
            <span class="cal-pop-dot"></span>{{ item.label
            }}<template v-if="item.when"> · {{ item.when }}</template>
          </span>
          <span class="cal-pop-title" :class="{ done: item.done }">{{ item.title }}</span>
          <span v-if="item.detail" class="cal-pop-detail">{{ item.detail }}</span>
          <span v-if="item.done" class="cal-pop-detail">Done</span>
          <span v-if="item.movable" class="cal-pop-hint">Drag to another day to move it</span>
        </span>
      </span>
      <span v-if="items.length > 2" class="cal-item" aria-hidden="true">
        <span class="cal-more">+{{ items.length - 2 }} more</span>
        <span class="cal-pop cal-pop-list" data-testid="cal-pop">
          <span v-for="item in items.slice(2)" :key="`more-${item.key}`" class="cal-pop-row">
            <span class="cal-pop-dot" :class="`kind-${item.kind}`"></span>
            <span class="cal-pop-when">{{ item.when }}</span>
            <span :class="{ done: item.done }">{{ item.title }}</span>
          </span>
        </span>
      </span>
    </button>
  </td>
</template>

<style scoped>
.cal-cell {
  padding: 2px;
  vertical-align: top;
}

.cal-day {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.25rem;
  width: 100%;
  min-height: 3.6rem;
  padding: 0.3rem;
  border: 1px solid var(--sl-line);
  border-radius: 0.65rem;
  background: var(--sl-surface);
  color: var(--sl-ink);
  text-align: left;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease,
    transform 0.12s var(--sl-ease);
}

.cal-day:hover {
  border-color: var(--sl-jade);
}

.cal-day:active {
  transform: scale(0.97);
}

/* ---- Pointing at a day: it lifts, takes a soft green tint and a shadow, and its number lights up.
   Mouse and trackpad only: on a touch screen a tap just selects the day. ---- */
@media (hover: hover) {
  .cal-day {
    transition:
      background-color 0.18s ease,
      border-color 0.18s ease,
      box-shadow 0.18s ease,
      transform 0.18s var(--sl-ease);
  }

  .cal-day:hover {
    background: color-mix(in srgb, var(--sl-jade) 6%, var(--sl-surface));
    box-shadow:
      0 8px 20px rgb(16 42 38 / 14%),
      0 0 0 1px var(--sl-jade);
    transform: translateY(-3px);
  }

  .cal-day.past:hover,
  .outside .cal-day:hover {
    background: color-mix(in srgb, var(--sl-jade) 5%, var(--sl-mist));
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--sl-jade) 50%, transparent);
  }

  .cal-day.selected:hover {
    box-shadow:
      inset 0 0 0 2px var(--sl-ink),
      0 8px 20px rgb(16 42 38 / 14%);
  }

  .cal-day:not(.today):hover .cal-num {
    background: var(--sl-jade-soft);
    color: var(--sl-jade-deep);
  }

  .cal-num {
    transition:
      background-color 0.18s ease,
      color 0.18s ease;
  }

  /* The day being pointed at sits above its neighbours, so its pop-out cards can overlap them. */
  .cal-cell:hover {
    position: relative;
    z-index: 4;
  }
}

:root[data-bs-theme='dark'] .cal-day:hover {
  box-shadow:
    0 8px 20px rgb(0 0 0 / 45%),
    0 0 0 1px var(--sl-jade);
}

@media (prefers-reduced-motion: reduce) {
  .cal-day,
  .cal-day:hover,
  .cal-day:active {
    transform: none;
  }
}

/* Days already gone: quieter, so this week and next stand out. */
.cal-day.past {
  border-color: transparent;
  background: var(--sl-mist);
  color: var(--sl-ink-soft);
}

.cal-day.past .cal-chip {
  opacity: 0.6;
}

/* The spill-over days of the neighbouring months: still pressable, but plainly not this month. */
.outside .cal-day {
  border-color: transparent;
  background: transparent;
  color: color-mix(in srgb, var(--sl-ink-soft) 70%, transparent);
}

.cal-day.selected {
  border-color: var(--sl-ink);
  box-shadow: inset 0 0 0 2px var(--sl-ink);
}

/* Choosing a day: greener the more of the family is free. */
.cal-day.heat {
  border-color: color-mix(in srgb, var(--sl-jade) calc(30% + var(--heat) * 70%), var(--sl-line));
  background: color-mix(in srgb, var(--sl-jade) calc(var(--heat) * 32%), var(--sl-surface));
}

.cal-day.picked,
.cal-day.target {
  border-color: var(--sl-jade-deep);
  box-shadow: inset 0 0 0 3px var(--sl-jade-deep);
}

.cal-heat {
  align-self: flex-start;
  padding: 0 0.35rem;
  border-radius: 999px;
  background: var(--sl-surface);
  color: var(--sl-jade-deep);
  font-size: 0.7rem;
  font-weight: 800;
  white-space: nowrap;
}

.cal-chip.movable {
  cursor: grab;
  /* A finger drags the appointment instead of scrolling the page. */
  touch-action: none;
}

.cal-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cal-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.75rem;
  height: 1.75rem;
  border-radius: 999px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.today .cal-num {
  background: var(--sl-jade);
  color: #fff;
}

/* A coral ring with a gap: an open loop, something still to arrange. */
.cal-open {
  width: 0.7rem;
  height: 0.7rem;
  border: 2.5px solid var(--sl-coral);
  border-top-color: transparent;
  border-radius: 50%;
  transform: rotate(45deg);
}

.cal-dots {
  display: flex;
  flex-wrap: wrap;
  gap: 0.2rem;
}

.cal-dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 50%;
  background: var(--kind);
}

.cal-dot.kind-task {
  border-radius: 0.1rem;
}

.cal-chip.kind-task {
  border-left-style: dashed;
}

.cal-chip.done {
  color: var(--sl-ink-soft);
  text-decoration: line-through;
}

.cal-chip,
.cal-more {
  display: none;
  font-size: 0.75rem;
  line-height: 1.25;
}

.cal-chip {
  padding: 0.15rem 0.3rem;
  border-left: 3px solid var(--kind);
  border-radius: 0.3rem;
  background: color-mix(in srgb, var(--kind) 11%, var(--sl-surface));
  font-weight: 600;
  overflow-wrap: anywhere;
  hyphens: auto;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.cal-more {
  color: var(--sl-ink-soft);
}

/* ---- A chip, and the card that pops out of it ---- */
.cal-item {
  position: relative;
  display: none;
}

.cal-item:hover .cal-chip {
  background: color-mix(in srgb, var(--kind) 22%, var(--sl-surface));
}

.cal-item:hover .cal-more {
  color: var(--sl-ink);
  text-decoration: underline;
}

.cal-pop {
  position: absolute;
  z-index: 20;
  bottom: calc(100% + 0.4rem);
  left: 0;
  display: grid;
  gap: 0.15rem;
  width: max-content;
  min-width: 100%;
  max-width: 17rem;
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--sl-line);
  border-left: 4px solid var(--kind, var(--sl-ink-soft));
  border-radius: 0.6rem;
  background: var(--sl-surface);
  color: var(--sl-ink);
  box-shadow: var(--sl-float);
  font-size: 0.85rem;
  line-height: 1.35;
  text-align: left;
  white-space: normal;
  overflow-wrap: break-word;
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transform: translateY(0.3rem) scale(0.97);
  transform-origin: bottom left;
  transition:
    opacity 0.15s ease,
    transform 0.15s var(--sl-ease),
    visibility 0.15s;
}

.cal-pop-meta {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  color: var(--sl-ink-soft);
  font-size: 0.75rem;
  font-weight: 700;
}

.cal-pop-dot {
  flex: none;
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: var(--kind);
}

.cal-pop-title {
  font-size: 0.95rem;
  font-weight: 800;
}

.cal-pop-title.done,
.cal-pop-row .done {
  color: var(--sl-ink-soft);
  text-decoration: line-through;
}

.cal-pop-detail {
  color: var(--sl-ink-soft);
}

.cal-pop-hint {
  margin-top: 0.15rem;
  color: var(--sl-jade-deep);
  font-size: 0.75rem;
  font-weight: 700;
}

.cal-pop-list {
  gap: 0.3rem;
  border-left-color: var(--sl-ink-soft);
}

.cal-pop-row {
  display: grid;
  grid-template-columns: auto auto 1fr;
  align-items: baseline;
  gap: 0.45rem;
}

.cal-pop-when {
  color: var(--sl-ink-soft);
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* The first week opens its cards downwards, and the last days of the week open to the left, so
   none is cut off at the edge of the calendar. */
tr:first-child .cal-pop {
  top: calc(100% + 0.4rem);
  bottom: auto;
  transform-origin: top left;
}

.cal-cell:nth-child(n + 5) .cal-pop {
  right: 0;
  left: auto;
  transform-origin: bottom right;
}

/* No cards while an appointment is being dragged. */
.dragging .cal-pop {
  display: none;
}

@media (hover: hover) {
  .cal-item:hover .cal-pop {
    opacity: 1;
    visibility: visible;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cal-pop {
    transform: none;
    transition: none;
  }
}

/* A public holiday: a sun-coloured top edge on every screen, and its name on wider ones. */
.cal-day.holiday {
  border-top: 3px solid var(--sl-sun);
}

.cal-holiday {
  display: none;
  font-size: 0.7rem;
  font-weight: 700;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

@media (min-width: 768px) {
  .cal-day {
    min-height: 6.5rem;
    padding: 0.4rem;
  }

  .cal-dots {
    display: none;
  }

  .cal-chip {
    display: -webkit-box;
  }

  .cal-more,
  .cal-holiday,
  .cal-item {
    display: block;
  }
}
</style>
