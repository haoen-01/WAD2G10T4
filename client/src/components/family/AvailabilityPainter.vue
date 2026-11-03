<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { addDays } from '@/lib/calendar';
import type { AvailabilityEntry, FamilyMember } from '@/lib/family';
import { WEEKDAYS_LONG, WEEKDAYS_SHORT, parseIsoDay } from '@/lib/format-date';
import { PAINT_SLOTS, slotStatuses } from '@/lib/planner';
import type { SlotStatus } from '@/lib/planner';

/**
 * "When can you help?" as a week you paint on: press on an hour and drag across the others to mark
 * them free (or busy), drag over them again to clear. A finger works the same as a mouse. Each
 * cell is also a button, so a keyboard can tick hours one at a time. Letting go saves the days
 * that changed (the parent turns them into availability windows).
 *
 * Each hour also shows how many others in the family are free then, so a good time stands out.
 */
const props = defineProps<{
  today: string;
  memberId: string;
  members: FamilyMember[];
  availability: AvailabilityEntry[];
}>();
const emit = defineEmits<{ paint: [day: string, slots: SlotStatus[]] }>();

const mode = ref<'available' | 'unavailable'>('available');
const week = ref(0);
const days = computed(() =>
  Array.from({ length: 7 }, (_, offset) => {
    const iso = addDays(props.today, week.value * 7 + offset);
    const parts = parseIsoDay(iso);
    return {
      iso,
      short: iso === props.today ? 'Today' : parts ? WEEKDAYS_SHORT[parts.weekday] : '',
      long: parts ? `${WEEKDAYS_LONG[parts.weekday]} ${parts.day}` : iso,
      day: parts?.day ?? '',
    };
  }),
);

// Changes not yet saved, by day. What is saved shows wherever there is no draft.
const draft = reactive<Record<string, SlotStatus[]>>({});
const slotsOf = (day: string) =>
  draft[day] ?? slotStatuses(props.availability, props.memberId, day);

const others = computed(() => props.members.filter((member) => member.id !== props.memberId));
function othersFree(day: string, slot: number): FamilyMember[] {
  return others.value.filter(
    (member) => slotStatuses(props.availability, member.id, day)[slot] === 'available',
  );
}

const WORDS: Record<string, string> = { available: 'free', unavailable: 'busy' };
function cellLabel(day: { long: string; iso: string }, slot: number) {
  const mine = slotsOf(day.iso)[slot];
  const free = othersFree(day.iso, slot).length;
  return `${day.long}, ${PAINT_SLOTS[slot].label}: ${mine ? WORDS[mine] : 'not set'}${
    free ? `, ${free} others free` : ''
  }`;
}

// ---- Painting ----
let painting: SlotStatus | undefined;
const touched = new Set<string>();

function paint(day: string, slot: number) {
  if (painting === undefined) return;
  const slots = [...slotsOf(day)];
  if (slots[slot] === painting) return;
  slots[slot] = painting;
  draft[day] = slots;
  touched.add(day);
}

function cellAt(event: PointerEvent) {
  const cell = document
    .elementFromPoint(event.clientX, event.clientY)
    ?.closest<HTMLElement>('[data-slot]');
  return cell ? { day: cell.dataset.day ?? '', slot: Number(cell.dataset.slot) } : null;
}

function start(event: PointerEvent) {
  const cell = cellAt(event);
  if (!cell || event.button > 0) return;
  event.preventDefault();
  // Pressing on an hour already marked this way clears instead: the drag then erases.
  painting = slotsOf(cell.day)[cell.slot] === mode.value ? null : mode.value;
  paint(cell.day, cell.slot);
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', finish, { once: true });
  window.addEventListener('pointercancel', finish, { once: true });
}

function move(event: PointerEvent) {
  const cell = cellAt(event);
  if (cell) paint(cell.day, cell.slot);
}

function finish() {
  painting = undefined;
  window.removeEventListener('pointermove', move);
  for (const day of touched) {
    emit('paint', day, draft[day]);
    delete draft[day];
  }
  touched.clear();
}

/** Keyboard (Enter or Space): one hour at a time. A pointer press is handled above instead. */
function onKeyClick(event: MouseEvent, day: string, slot: number) {
  if (event.detail !== 0) return;
  painting = slotsOf(day)[slot] === mode.value ? null : mode.value;
  paint(day, slot);
  finish();
}

onBeforeUnmount(finish);
</script>

<template>
  <div class="painter" :class="mode === 'available' ? 'paint-free' : 'paint-busy'">
    <div class="painter-bar">
      <div class="mode-toggle" role="group" aria-label="Paint as">
        <button
          type="button"
          class="mode-btn"
          :class="{ on: mode === 'available' }"
          :aria-pressed="mode === 'available'"
          @click="mode = 'available'"
        >
          <span class="key key-free" aria-hidden="true"></span>Free
        </button>
        <button
          type="button"
          class="mode-btn"
          :class="{ on: mode === 'unavailable' }"
          :aria-pressed="mode === 'unavailable'"
          @click="mode = 'unavailable'"
        >
          <span class="key key-busy" aria-hidden="true"></span>Busy
        </button>
      </div>
      <div class="week-nav d-flex align-items-center gap-1">
        <button
          type="button"
          class="btn btn-quiet nav-btn"
          aria-label="Previous week"
          :disabled="week === 0"
          @click="week--"
        >
          <Icon name="chevron-left" />
        </button>
        <span class="small fw-semibold week-label">{{
          week === 0 ? 'This week' : `In ${week} wk`
        }}</span>
        <button
          type="button"
          class="btn btn-quiet nav-btn"
          aria-label="Next week"
          :disabled="week >= 3"
          @click="week++"
        >
          <Icon name="chevron-right" />
        </button>
      </div>
    </div>

    <p class="sl-note mb-1">
      Choose Free or Busy, then drag across the hours. Drag again to clear.
    </p>
    <ul class="legend list-unstyled sl-note mb-2" aria-label="Key">
      <li><span class="key key-empty" aria-hidden="true"></span>Not set</li>
      <li><span class="others-key" aria-hidden="true">+1</span>others free then</li>
    </ul>

    <div class="grid" role="grid" aria-label="Your availability" @pointerdown="start">
      <div class="corner" aria-hidden="true"></div>
      <div v-for="day in days" :key="day.iso" class="head" :class="{ today: day.iso === today }">
        <span>{{ day.short }}</span
        ><strong>{{ day.day }}</strong>
      </div>
      <template v-for="(slot, index) in PAINT_SLOTS" :key="slot.start">
        <div class="hour" aria-hidden="true">{{ slot.label }}</div>
        <button
          v-for="day in days"
          :key="`${day.iso}-${slot.start}`"
          type="button"
          class="cell"
          :class="[slotsOf(day.iso)[index] ?? 'empty', { 'is-today': day.iso === today }]"
          :style="{ '--others': othersFree(day.iso, index).length / Math.max(others.length, 1) }"
          :data-day="day.iso"
          :data-slot="index"
          :aria-label="cellLabel(day, index)"
          :title="
            othersFree(day.iso, index).length
              ? `Also free: ${othersFree(day.iso, index)
                  .map((m) => m.name)
                  .join(', ')}`
              : undefined
          "
          @click="onKeyClick($event, day.iso, index)"
        >
          <span v-if="othersFree(day.iso, index).length" class="others" aria-hidden="true">
            +{{ othersFree(day.iso, index).length }}
          </span>
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.painter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

/* Free / Busy as one segmented control, tall enough for a thumb. */
.mode-toggle {
  display: inline-flex;
  padding: 0.2rem;
  border: 1px solid var(--sl-line);
  border-radius: 999px;
  background: var(--sl-mist);
}

.mode-btn {
  display: inline-flex;
  align-items: center;
  min-height: 2.75rem;
  padding: 0 1.1rem;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--sl-ink);
  font-weight: 700;
  transition:
    background-color var(--sl-dur-base) var(--sl-ease),
    color var(--sl-dur-base) var(--sl-ease);
}

.mode-btn.on {
  background: var(--sl-jade);
  color: var(--sl-jade-on);
}

.mode-btn.on .key {
  box-shadow: 0 0 0 1.5px var(--sl-jade-on);
}

.mode-btn:focus-visible,
.cell:focus-visible {
  outline: 3px solid var(--sl-sun-deep);
  outline-offset: 2px;
}

.nav-btn {
  min-width: 2.75rem;
  min-height: 2.75rem;
}

.week-label {
  min-width: 4.5rem;
  text-align: center;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1rem;
}

.key-empty {
  border: 1px solid var(--sl-line);
  background: var(--sl-surface);
}

.key {
  display: inline-block;
  width: 0.75rem;
  height: 0.75rem;
  margin-right: 0.4rem;
  border-radius: 0.2rem;
  vertical-align: -0.05rem;
}

.key-free {
  background: var(--sl-jade);
  box-shadow: 0 0 0 1px var(--sl-surface);
}

/* Busy is grey stripes, mixed from the theme so it suits light and dark. */
.key-busy {
  background: repeating-linear-gradient(
    45deg,
    color-mix(in srgb, var(--sl-ink-soft) 70%, var(--sl-surface)) 0 3px,
    var(--sl-line) 3px 6px
  );
}

.grid {
  display: grid;
  grid-template-columns: 3rem repeat(7, minmax(0, 1fr));
  gap: 3px;
  /* Painting with a finger must not scroll the page. */
  touch-action: none;
  user-select: none;
}

.corner {
  min-height: 1rem;
}

.head {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-bottom: 0.25rem;
  color: var(--sl-ink-soft);
  font-size: 0.75rem;
  line-height: 1.2;
}

.head strong {
  color: var(--sl-ink);
  font-size: 1rem;
}

/* Today: its date sits in a filled disc and its whole column gets a faint edge. */
.head.today {
  color: var(--sl-jade-deep);
  font-weight: 700;
}

.head.today strong {
  align-self: center;
  min-width: 1.75rem;
  border-radius: 999px;
  background: var(--sl-jade);
  color: var(--sl-jade-on);
  text-align: center;
}

.cell.is-today {
  border-color: color-mix(in srgb, var(--sl-jade) 45%, var(--sl-line));
}

.hour {
  align-self: center;
  color: var(--sl-ink-soft);
  font-size: 0.72rem;
  text-align: right;
  padding-right: 0.25rem;
}

.cell {
  position: relative;
  min-height: 2.5rem;
  padding: 0;
  border: 1px solid var(--sl-line);
  border-radius: 0.35rem;
  background: var(--sl-surface);
  cursor: var(--sl-cur-free);
  transition: background-color 0.08s ease;
}

/* The brush matches what painting will do: a green tip for Free, a grey striped one for Busy. */
.paint-busy .cell {
  cursor: var(--sl-cur-busy);
}

/* Not painted by you: a light green the more others are free then, so overlaps show. */
.cell.empty {
  background: color-mix(in srgb, var(--sl-jade) calc(var(--others, 0) * 22%), var(--sl-surface));
}

.cell:hover {
  border-color: var(--sl-jade);
}

.cell.available {
  border-color: var(--sl-jade);
  background: var(--sl-jade);
}

.cell.unavailable {
  border-color: var(--sl-ink-soft);
  background: repeating-linear-gradient(
    45deg,
    color-mix(in srgb, var(--sl-ink-soft) 45%, var(--sl-surface)) 0 4px,
    var(--bs-tertiary-bg) 4px 8px
  );
}

.others,
.others-key {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--sl-jade-deep);
}

.others {
  position: absolute;
  top: 1px;
  right: 3px;
}

.cell.available .others {
  color: #fff;
}

.others-key {
  margin-right: 0.35rem;
  padding: 0 0.25rem;
  border: 1px solid var(--sl-line);
  border-radius: 0.25rem;
}

@media (min-width: 768px) {
  .cell {
    min-height: 2.5rem;
  }
}
</style>
