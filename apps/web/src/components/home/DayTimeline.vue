<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import { useFamily } from '@/composables/useFamily';
import { useFamilyActivity } from '@/composables/useFamilyActivity';
import { useNow } from '@/composables/useNow';
import { useTasks } from '@/composables/useTasks';
import { showToast } from '@/composables/useToast';
import { addDays, todayIso } from '@/lib/calendar';
import { stillNeedsHelper } from '@/lib/coverage';
import {
  clockToMinutes,
  dayRecord,
  daySummary,
  dayWindow,
  focusAt,
  hasHappened,
  isUnderway,
  minutesToLabel,
  marksUnderLabel,
  momentInZone,
  nowLabelTransform,
  positionOf,
  sortMoments,
} from '@/lib/day-timeline';
import type { TimelineLane, TimelineMoment } from '@/lib/day-timeline';
import { feedLine } from '@/lib/family-feed';
import { PRODUCT_TIME_ZONE, formatIsoDay } from '@/lib/format-date';
import { minutesOf } from '@/lib/today';

/**
 * "Mdm Lim's day": the senior's day by the hour, live. Three lanes: appointments (as long as they
 * last, with the faces of who is going), tasks (at their times) and the family (who called,
 * visited or took an appointment, and when). Today a "Now" line moves along and everything before
 * it counts as passed. An earlier day shows what she did: the tasks ticked off and not, her
 * appointments and who went, and how the family kept in touch.
 *
 * Tap anything for its details. An appointment that still needs someone offers "I'll go"; a task
 * today can be ticked off. Everything stays live: tasks change at once (`useTasks`), the family
 * feed re-reads every 30 s (`useFamilyActivity`), and this re-reads the calendar every 30 s while
 * the page is visible, and when the tab comes back. Rules: `lib/day-timeline.ts`.
 */
const props = defineProps<{ personId: string; elder: string }>();

const family = useFamily();
const { appointments, state } = family;
const tasks = useTasks();
const activity = useFamilyActivity();
const now = useNow();

// ---- Which day ----
// "Today" comes from the live clock, not from when the page was opened, so a tab left open past
// midnight moves on to the new day by itself (within the clock's 30 s tick).
const today = computed(() => todayIso(now.value));
const offset = ref(0);
const day = computed(() => addDays(today.value, offset.value));
const isToday = computed(() => offset.value === 0);
const isPast = computed(() => offset.value < 0);
const dayLabel = computed(() =>
  offset.value === 0
    ? 'Today'
    : offset.value === -1
      ? 'Yesterday'
      : offset.value === 1
        ? 'Tomorrow'
        : formatIsoDay(day.value),
);

// ---- The day's moments ----
function memberOf(id: string) {
  const member = state.members.find((candidate) => candidate.id === id);
  return member ? { id: member.id, name: member.name, colour: member.colour } : null;
}

const moments = computed<TimelineMoment[]>(() => {
  const list: TimelineMoment[] = [];
  for (const appointment of appointments) {
    if (appointment.date !== day.value) continue;
    const start = clockToMinutes(appointment.start);
    if (start === null) continue;
    const people = family
      .helperIdsOf(appointment.id)
      .map(memberOf)
      .filter((person): person is NonNullable<typeof person> => person !== null);
    const open = stillNeedsHelper(state.assignments, appointment);
    const meId = family.currentMember.value?.id;
    const mine = people.some((person) => person.id === meId);
    // "You" for the viewer, so the line reads "You’re going" rather than your own name.
    const names = people.map((person) => (person.id === meId ? 'You' : person.name));
    const going =
      mine && people.length === 1
        ? `You${isPast.value ? ' went' : '’re going'}`
        : `${names.join(' and ')} ${isPast.value ? 'went' : 'going'}`;
    list.push({
      id: `appointment-${appointment.id}`,
      lane: 'appointment',
      start,
      end: clockToMinutes(appointment.end) ?? start + 60,
      title: appointment.title,
      detail: people.length
        ? `${going} with ${props.elder}`
        : open
          ? 'Still needs someone to go along'
          : 'No one needs to go along',
      icon: appointment.kind,
      kind: appointment.kind,
      open,
      people,
      mine,
      appointmentId: appointment.id,
      place: appointment.location,
    });
  }
  for (const task of tasks.tasksOn(props.personId, day.value)) {
    const start = clockToMinutes(task.time);
    if (start === null) continue;
    list.push({
      id: `task-${task.task_id}`,
      lane: 'task',
      start,
      title: task.title,
      detail: task.completed ? 'Done' : isPast.value ? 'Not ticked off' : 'To do',
      icon: task.kind === 'medicine' ? 'medicine' : 'task',
      done: task.completed,
      taskId: task.task_id,
    });
  }
  for (const entry of activity.entries.value) {
    const at = momentInZone(entry.at, PRODUCT_TIME_ZONE);
    if (!at || at.day !== day.value) continue;
    const line = feedLine(entry, { elder: props.elder });
    const person = memberOf(entry.actor_member_id);
    list.push({
      id: `family-${entry.activity_id}`,
      lane: 'family',
      start: at.minute,
      title: `${line.actor} ${line.rest}`,
      // Seeded demo entries say so, as they do in the family feed.
      detail: [line.note ? `“${line.note}”` : '', entry.origin === 'demo_seed' ? 'Sample' : '']
        .filter(Boolean)
        .join(' · '),
      icon: line.icon,
      people: person ? [person] : [],
    });
  }
  return sortMoments(list);
});

/**
 * The stretch of the day drawn on the timeline, in minutes after midnight. Today it always takes
 * in "now", so the Now line is on screen late at night and early in the morning too.
 */
const range = computed(() => {
  const drawn = dayWindow(moments.value);
  if (!isToday.value) return drawn;
  const minute = minutesOf(now.value);
  return {
    from: Math.min(drawn.from, Math.floor(minute / 60) * 60),
    to: Math.min(24 * 60, Math.max(drawn.to, Math.ceil((minute + 1) / 60) * 60)),
  };
});
const summary = computed(() => daySummary(moments.value));
const record = computed(() => dayRecord(moments.value));

// "Now" in minutes. A past day counts as wholly passed; a future one as not started.
const nowMinute = computed(() => minutesOf(now.value));
const passedUntil = computed(() => (isToday.value ? nowMinute.value : isPast.value ? 24 * 60 : -1));
const showNow = computed(
  () => isToday.value && nowMinute.value >= range.value.from && nowMinute.value <= range.value.to,
);
const nowAt = computed(() => `${positionOf(nowMinute.value, range.value) * 100}%`);
const nowLabelStyle = computed(() => ({
  transform: nowLabelTransform(positionOf(nowMinute.value, range.value)),
}));
const passedWidth = computed(() => (isToday.value ? nowAt.value : isPast.value ? '100%' : '0%'));

// ---- Hour marks along the top: every 2 hours (every 3 on a phone, via CSS) ----
const hours = computed(() => {
  const marks: { minute: number; label: string; at: string; minor: boolean }[] = [];
  for (let minute = range.value.from; minute <= range.value.to; minute += 60) {
    const hour = minute / 60;
    marks.push({
      minute,
      label:
        hour === 12
          ? '12 pm'
          : hour === 0 || hour === 24
            ? '12 am'
            : hour > 12
              ? `${hour - 12} pm`
              : `${hour} am`,
      at: `${positionOf(minute, range.value) * 100}%`,
      minor: hour % 2 === 1,
    });
  }
  return marks;
});

// ---- An hour mark the Now label sits on is hidden whole, so no letter of it peeks out ----
// Measured, because the widths depend on the zoom and the font.
const track = ref<HTMLElement | null>(null);
const nowLabel = ref<HTMLElement | null>(null);
const coveredHours = ref<ReadonlySet<number>>(new Set());
function measureCoveredHours() {
  const label = nowLabel.value?.getBoundingClientRect();
  const elements = track.value?.querySelectorAll<HTMLElement>('.timeline-hour') ?? [];
  const marks = [...elements].map((element, index) => {
    const box = element.getBoundingClientRect();
    return { key: hours.value[index]?.minute ?? -1, left: box.left, right: box.right };
  });
  coveredHours.value = new Set(label ? marksUnderLabel(label, marks) : []);
}
watch([hours, nowMinute, showNow], measureCoveredHours, { flush: 'post' });
let resizeWatcher: ResizeObserver | undefined;
watch(
  nowLabel,
  (label, previous) => {
    if (previous) resizeWatcher?.unobserve(previous);
    if (label) resizeWatcher?.observe(label);
  },
  { flush: 'post' },
);

const LANES: { lane: TimelineLane; label: string }[] = [
  { lane: 'appointment', label: 'Appointments' },
  { lane: 'task', label: 'Tasks' },
  { lane: 'family', label: 'Family updates' },
];
const inLane = (lane: TimelineLane) => moments.value.filter((moment) => moment.lane === lane);

/** Late in the day there is no room after the bar, so the name goes before it instead. */
function titleBefore(moment: TimelineMoment): boolean {
  return positionOf(moment.end ?? moment.start, range.value) > 0.8;
}

function markerStyle(moment: TimelineMoment) {
  const left = positionOf(moment.start, range.value) * 100;
  if (moment.end === undefined) return { left: `${left}%` };
  const right = positionOf(moment.end, range.value) * 100;
  return { left: `${left}%`, width: `${Math.max(right - left, 1.5)}%` };
}

function markerLabel(moment: TimelineMoment): string {
  const when =
    moment.end !== undefined
      ? `${minutesToLabel(moment.start)} to ${minutesToLabel(moment.end)}`
      : minutesToLabel(moment.start);
  return `${when}, ${moment.title}${moment.detail ? `, ${moment.detail}` : ''}. Show details.`;
}

// ---- Details: the tapped moment, else (today) what is on now or next ----
const selectedId = ref<string | null>(null);
watch(day, () => (selectedId.value = null));
const focused = computed(() => {
  const chosen = moments.value.find((moment) => moment.id === selectedId.value);
  if (chosen) return chosen;
  return isToday.value ? focusAt(moments.value, nowMinute.value) : null;
});
const focusWord = computed(() => {
  const moment = focused.value;
  if (!moment || selectedId.value || !isToday.value) return '';
  if (isUnderway(moment, nowMinute.value)) return 'Now';
  return moment.start > nowMinute.value ? 'Next' : 'Latest';
});

function select(moment: TimelineMoment) {
  selectedId.value = selectedId.value === moment.id ? null : moment.id;
}

// ---- Acting from the details ----
const canVolunteer = computed(() => family.currentMember.value !== null && !isPast.value);
function goWith(moment: TimelineMoment) {
  const appointmentId = moment.appointmentId;
  if (!appointmentId) return;
  family.volunteer(appointmentId);
  showToast(`You’re going to ${moment.title}.`, {
    actionLabel: 'Undo',
    action: () => family.stepBack(appointmentId),
  });
}
// "Can't go" stays on the card for as long as you are going, so changing your mind days later
// does not depend on catching the toast. Stepping back tells the family, as on the calendar.
function stepBack(moment: TimelineMoment) {
  const appointmentId = moment.appointmentId;
  if (!appointmentId) return;
  family.stepBack(appointmentId);
  showToast(`You’ve stepped back from ${moment.title}.`, {
    actionLabel: 'Undo',
    action: () => family.volunteer(appointmentId),
  });
}
function toggleTask(moment: TimelineMoment) {
  if (!moment.taskId) return;
  tasks.setCompleted(props.personId, moment.taskId, day.value, !moment.done);
}

// ---- Live: re-read the calendar every 30 s while visible, and when the tab comes back ----
const lastSynced = ref<Date | null>(null);
const syncedLabel = computed(() =>
  lastSynced.value ? minutesToLabel(minutesOf(lastSynced.value)) : '',
);
let timer: ReturnType<typeof setInterval> | undefined;
async function sync(onlyIfVisible = true) {
  if (onlyIfVisible && document.visibilityState !== 'visible') return;
  await family.refresh();
  lastSynced.value = new Date();
}
function onVisible() {
  if (document.visibilityState === 'visible') void sync();
}
onMounted(() => {
  // The first read always runs; the 30 s re-reads pause while the tab is hidden.
  void sync(false);
  timer = setInterval(() => void sync(), 30_000);
  document.addEventListener('visibilitychange', onVisible);
  window.addEventListener('focus', onVisible);
  measureCoveredHours();
  void document.fonts?.ready.then(measureCoveredHours);
  // The track changes width with the window and with the app's zoom.
  resizeWatcher = new ResizeObserver(measureCoveredHours);
  if (track.value) resizeWatcher.observe(track.value);
  // The label grows with the zoom even where the track keeps its width.
  if (nowLabel.value) resizeWatcher.observe(nowLabel.value);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  document.removeEventListener('visibilitychange', onVisible);
  window.removeEventListener('focus', onVisible);
  resizeWatcher?.disconnect();
});

const iconOf = (moment: TimelineMoment) => moment.icon as IconName;
</script>

<template>
  <section class="sl-panel timeline" aria-labelledby="timeline-heading" data-testid="day-timeline">
    <div class="timeline-head">
      <div>
        <h2 id="timeline-heading" class="sl-section-title d-flex align-items-center gap-2 mb-1">
          <Icon name="clock" />{{ elder }}’s day
          <span v-if="isToday" class="timeline-live" title="Updates on its own">
            <span class="timeline-live-dot" aria-hidden="true"></span>Live
          </span>
        </h2>
        <p class="timeline-chips mb-0" aria-live="polite">
          <span class="timeline-chip"
            ><Icon name="calendar" />{{ summary.appointments }}
            {{ summary.appointments === 1 ? 'appointment' : 'appointments' }}</span
          >
          <span class="timeline-chip">
            <Icon name="checklist" />{{ summary.tasksDone }}/{{ summary.tasks }} tasks done
          </span>
          <span class="timeline-chip"
            ><Icon name="users" />{{ summary.family }} family
            {{ summary.family === 1 ? 'update' : 'updates' }}</span
          >
        </p>
      </div>
      <div class="timeline-days" role="group" aria-label="Day">
        <button
          type="button"
          class="btn btn-sm btn-quiet"
          aria-label="Day before"
          :disabled="offset <= -6"
          @click="offset--"
        >
          <Icon name="chevron-left" />
        </button>
        <span class="timeline-day" aria-live="polite">
          <strong>{{ dayLabel }}</strong>
          <span v-if="dayLabel !== formatIsoDay(day)" class="sl-note">{{ formatIsoDay(day) }}</span>
        </span>
        <button
          type="button"
          class="btn btn-sm btn-quiet"
          aria-label="Day after"
          :disabled="offset >= 6"
          @click="offset++"
        >
          <Icon name="chevron-right" />
        </button>
        <button
          v-if="!isToday"
          type="button"
          class="btn btn-sm btn-link"
          data-testid="timeline-today"
          @click="offset = 0"
        >
          Today
        </button>
      </div>
    </div>

    <div class="timeline-body">
      <div class="timeline-labels" aria-hidden="true">
        <span class="timeline-hours-spacer"></span>
        <span v-for="lane in LANES" :key="lane.lane" class="timeline-lane-label">{{
          lane.label
        }}</span>
      </div>

      <div ref="track" class="timeline-track">
        <div class="timeline-hours" aria-hidden="true">
          <span
            v-for="mark in hours"
            :key="mark.minute"
            class="timeline-hour"
            :class="{ minor: mark.minor }"
            :style="{
              left: mark.at,
              visibility: coveredHours.has(mark.minute) ? 'hidden' : undefined,
            }"
            >{{ mark.label }}</span
          >
        </div>

        <div class="timeline-passed" :style="{ width: passedWidth }" aria-hidden="true"></div>

        <div
          v-for="lane in LANES"
          :key="lane.lane"
          class="timeline-lane"
          role="list"
          :aria-label="lane.label"
        >
          <span
            v-for="mark in hours"
            :key="mark.minute"
            class="timeline-grid"
            :style="{ left: mark.at }"
          ></span>
          <button
            v-for="moment in inLane(lane.lane)"
            :key="moment.id"
            type="button"
            role="listitem"
            class="marker"
            :class="[
              `marker-${moment.lane}`,
              moment.kind ? `kind-${moment.kind}` : '',
              {
                passed: hasHappened(moment, passedUntil),
                underway: isToday && isUnderway(moment, nowMinute),
                focused: focused?.id === moment.id,
                done: moment.done,
                open: moment.open,
              },
            ]"
            :style="markerStyle(moment)"
            :aria-label="markerLabel(moment)"
            :aria-pressed="selectedId === moment.id"
            :title="`${minutesToLabel(moment.start)} · ${moment.title}`"
            @click="select(moment)"
          >
            <!-- Family: the face of who shared it. Appointments: their icon, then who is going. -->
            <MemberAvatar
              v-if="moment.lane === 'family' && moment.people?.length"
              :name="moment.people[0].name"
              :colour="moment.people[0].colour"
              size="sm"
            />
            <Icon v-else :name="iconOf(moment)" />
            <span v-if="moment.lane === 'appointment'" class="marker-people">
              <MemberAvatar
                v-for="person in moment.people"
                :key="person.id"
                :name="person.name"
                :colour="person.colour"
                size="sm"
              />
              <span v-if="moment.open" class="marker-need" title="Needs someone to go along"
                >!</span
              >
            </span>
            <span
              v-if="moment.lane === 'appointment'"
              class="marker-title"
              :class="{ before: titleBefore(moment) }"
              >{{ moment.title }}</span
            >
          </button>
        </div>

        <div v-if="showNow" class="timeline-now" :style="{ left: nowAt }" aria-hidden="true">
          <span ref="nowLabel" class="timeline-now-label" :style="nowLabelStyle"
            >Now · {{ minutesToLabel(nowMinute) }}</span
          >
        </div>
      </div>
    </div>

    <!-- The tapped moment (or, today, what is on now or next), with what you can do about it. -->
    <div v-if="focused" class="timeline-details" aria-live="polite" data-testid="timeline-details">
      <span class="timeline-details-icon" :class="focused.kind ? `kind-${focused.kind}` : ''">
        <Icon :name="iconOf(focused)" />
      </span>
      <span class="timeline-details-text">
        <span class="timeline-details-when">
          <span v-if="focusWord" class="timeline-focus-word">{{ focusWord }}</span>
          {{ minutesToLabel(focused.start)
          }}<template v-if="focused.end !== undefined">
            – {{ minutesToLabel(focused.end) }}</template
          >
        </span>
        <strong class="d-block">{{ focused.title }}</strong>
        <span v-if="focused.place" class="timeline-details-sub d-block">
          <Icon name="pin" class="me-1" />{{ focused.place }}
        </span>
        <span v-if="focused.detail" class="timeline-details-sub d-block">{{ focused.detail }}</span>
      </span>
      <span class="timeline-actions">
        <template v-if="focused.lane === 'appointment' && canVolunteer">
          <!-- You are going: say so, with a lasting way to step back. -->
          <template v-if="focused.mine">
            <span class="timeline-going" data-testid="timeline-going">
              <Icon name="user-check" class="me-1" />You’re going
            </span>
            <button
              type="button"
              class="btn btn-outline-secondary btn-sm"
              data-testid="timeline-cant-go"
              @click="stepBack(focused)"
            >
              <Icon name="user-x" class="me-1" />Can’t go
            </button>
          </template>
          <button
            v-else-if="focused.open"
            type="button"
            class="btn btn-primary btn-sm"
            data-testid="timeline-go"
            @click="goWith(focused)"
          >
            <Icon name="user-plus" class="me-1" />I’ll go
          </button>
          <!-- Already covered (or nobody needs to go): no one else is needed, but you can still join. -->
          <template v-else>
            <span v-if="focused.people?.length" class="timeline-covered">No one else needed</span>
            <button
              type="button"
              class="btn btn-outline-primary btn-sm"
              data-testid="timeline-go-too"
              @click="goWith(focused)"
            >
              <Icon name="user-plus" class="me-1" />{{
                focused.people?.length ? 'I’ll go too' : 'I’ll go'
              }}
            </button>
          </template>
        </template>
        <button
          v-if="focused.lane === 'task' && !isPast && offset === 0"
          type="button"
          class="btn btn-sm"
          :class="focused.done ? 'btn-outline-secondary' : 'btn-outline-primary'"
          data-testid="timeline-tick"
          @click="toggleTask(focused)"
        >
          <Icon :name="focused.done ? 'x' : 'check'" class="me-1" />{{
            focused.done ? 'Not done' : 'Mark done'
          }}
        </button>
      </span>
    </div>

    <!-- An earlier day: what she did, as a short record. -->
    <div v-if="isPast" class="timeline-record" data-testid="timeline-record">
      <h3 class="h6 mb-2">What {{ elder }} did</h3>
      <p
        v-if="!record.done.length && !record.missed.length && !record.appointments.length"
        class="text-body-secondary mb-0"
      >
        No tasks or appointments that day.
      </p>
      <ul v-else class="record-list">
        <li v-for="item in record.done" :key="item.id" class="record-item record-done">
          <Icon name="check-circle" /><span
            ><strong>{{ item.title }}</strong> · {{ minutesToLabel(item.start) }}</span
          >
        </li>
        <li v-for="item in record.appointments" :key="item.id" class="record-item">
          <Icon name="calendar" /><span
            ><strong>{{ item.title }}</strong> · {{ minutesToLabel(item.start) }} ·
            {{ item.detail }}</span
          >
        </li>
        <li v-for="item in record.missed" :key="item.id" class="record-item record-missed">
          <Icon name="x" /><span
            ><strong>{{ item.title }}</strong> · not ticked off</span
          >
        </li>
      </ul>

      <template v-if="record.family.length">
        <h3 class="h6 mt-3 mb-2">Family in touch</h3>
        <ul class="record-list">
          <li v-for="item in record.family" :key="item.id" class="record-item">
            <MemberAvatar
              v-if="item.people?.length"
              :name="item.people[0].name"
              :colour="item.people[0].colour"
              size="sm"
            /><span>{{ item.title }} · {{ minutesToLabel(item.start) }}</span>
          </li>
        </ul>
      </template>
    </div>

    <p v-else-if="!moments.length" class="text-body-secondary mt-3 mb-0">
      Nothing planned for this day.
    </p>

    <p class="sl-note mt-2 mb-0">
      <template v-if="isToday && syncedLabel"> Updated {{ syncedLabel }}.</template>
    </p>
  </section>
</template>

<style scoped>
.timeline-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem 1rem;
  margin-bottom: 1rem;
}

.timeline-live {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.1rem 0.55rem;
  border-radius: 999px;
  background: var(--sl-coral-soft);
  color: var(--sl-coral-deep);
  font-size: 0.75rem;
  font-weight: 800;
}

.timeline-live-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--sl-coral);
  animation: live 1.6s ease-in-out infinite;
}

@keyframes live {
  50% {
    opacity: 0.3;
  }
}

@media (prefers-reduced-motion: reduce) {
  .timeline-live-dot {
    animation: none;
  }
}

.timeline-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.timeline-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  font-weight: 600;
}

.timeline-days {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.15rem;
}

.timeline-day {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 6rem;
  line-height: 1.15;
  text-align: center;
}

/* ---- The timeline ---- */
.timeline-body {
  display: grid;
  grid-template-columns: 6.25rem minmax(0, 1fr);
  gap: 0 0.5rem;
}

.timeline-labels,
.timeline-track {
  display: grid;
  grid-template-rows: 1.6rem repeat(3, 3rem);
  gap: 0.35rem;
}

.timeline-lane-label {
  align-self: center;
  color: var(--sl-ink-soft);
  font-size: 0.8rem;
  font-weight: 700;
}

.timeline-track {
  position: relative;
}

.timeline-hours {
  position: relative;
}

.timeline-hour {
  position: absolute;
  top: 0.2rem;
  color: var(--sl-ink-soft);
  font-size: 0.72rem;
  font-weight: 600;
  white-space: nowrap;
  transform: translateX(-50%);
}

.timeline-hour.minor {
  visibility: hidden;
}

.timeline-hour:first-child {
  transform: none;
}

.timeline-hour:last-child {
  transform: translateX(-100%);
}

/* The part of the day already gone: a soft wash behind the lanes. */
.timeline-passed {
  position: absolute;
  top: 1.95rem;
  bottom: 0;
  left: 0;
  border-radius: 0.6rem 0 0 0.6rem;
  background: color-mix(in srgb, var(--sl-jade) 7%, transparent);
  pointer-events: none;
}

.timeline-lane {
  position: relative;
  border-radius: 0.6rem;
  background: var(--bs-tertiary-bg);
}

.timeline-grid {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: color-mix(in srgb, var(--sl-line) 70%, transparent);
}

/* ---- Moments ---- */
.marker {
  position: absolute;
  top: 50%;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.3rem;
  height: 2.1rem;
  min-width: 2.1rem;
  padding: 0;
  border: 2px solid var(--sl-sun);
  border-radius: 999px;
  background: var(--sl-sun-soft);
  color: var(--sl-ink);
  transform: translate(-50%, -50%);
  transition:
    background-color 0.25s ease,
    border-color 0.25s ease,
    box-shadow 0.25s ease;
}

.marker-task.done {
  border-color: var(--sl-jade);
  background: var(--sl-jade);
  color: #fff;
}

/* A task whose time has passed but is not ticked off: an amber edge, so it stands out. */
.marker-task.passed:not(.done) {
  border-style: dashed;
}

.marker-family {
  border-color: transparent;
  background: transparent;
}

/* Appointments are bars as long as the appointment, starting at their start time. */
.marker-appointment {
  justify-content: flex-start;
  padding: 0 0.35rem;
  border-color: var(--kind);
  border-radius: 0.55rem;
  background: color-mix(in srgb, var(--kind) 12%, var(--sl-surface));
  color: var(--kind);
  transform: translateY(-50%);
}

.marker-appointment.underway {
  background: color-mix(in srgb, var(--kind) 30%, var(--sl-surface));
}

.marker-appointment.passed:not(.underway) {
  opacity: 0.7;
}

.marker-people {
  display: inline-flex;
  align-items: center;
}

.marker-people > * + * {
  margin-left: -0.35rem;
}

.marker-need {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.1rem;
  height: 1.1rem;
  border-radius: 50%;
  background: var(--sl-coral);
  color: #fff;
  font-size: 0.75rem;
  font-weight: 900;
}

/* An appointment's name sits just after its bar, so a short one keeps its true length. */
.marker-title {
  position: absolute;
  left: calc(100% + 0.4rem);
  max-width: 11rem;
  overflow: hidden;
  color: var(--sl-ink);
  font-size: 0.78rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
}

.marker-title.before {
  right: calc(100% + 0.4rem);
  left: auto;
  text-align: right;
}

.marker.focused {
  z-index: 2;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--sl-jade) 35%, transparent);
}

/* ---- Now ---- */
.timeline-now {
  position: absolute;
  top: 1.45rem;
  bottom: -0.25rem;
  z-index: 3;
  width: 0;
  border-left: 2px solid var(--sl-coral);
  pointer-events: none;
}

.timeline-now-label {
  position: absolute;
  top: -1.4rem;
  left: 0;
  padding: 0.05rem 0.45rem;
  border-radius: 999px;
  background: var(--sl-coral);
  color: #fff;
  font-size: 0.72rem;
  font-weight: 800;
  white-space: nowrap;
}

/* ---- Details ---- */
.timeline-details {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  min-height: 4.5rem;
  margin-top: 1.4rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
}

.timeline-details-icon {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 50%;
  background: color-mix(in srgb, var(--kind, var(--sl-jade)) 14%, var(--sl-surface));
  color: var(--kind, var(--sl-jade));
  font-size: 1.3rem;
}

.timeline-details-text {
  flex: 1 1 12rem;
  min-width: 0;
  overflow-wrap: anywhere;
}

.timeline-details-when {
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  font-weight: 700;
}

.timeline-focus-word {
  margin-right: 0.3rem;
  padding: 0 0.45rem;
  border-radius: 999px;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}

.timeline-details-sub {
  color: var(--sl-ink-soft);
  font-size: 0.92rem;
}

.timeline-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  flex: none;
  gap: 0.4rem;
  margin-left: auto;
}

.timeline-going {
  display: inline-flex;
  align-items: center;
  padding: 0.3rem 0.7rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--bs-primary) 14%, transparent);
  color: var(--bs-primary);
  font-weight: 700;
  font-size: 0.875rem;
}
.timeline-covered {
  color: var(--bs-secondary-color);
  font-size: 0.875rem;
}

/* ---- An earlier day's record ---- */
.timeline-record {
  margin-top: 1.1rem;
  padding: 0.85rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--bs-tertiary-bg);
}

.record-list {
  display: grid;
  /* A column never wider than the list, however large the zoom makes 16rem. */
  grid-template-columns: repeat(auto-fill, minmax(min(16rem, 100%), 1fr));
  gap: 0.4rem 1rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.record-item {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  min-width: 0;
  font-size: 0.92rem;
  overflow-wrap: anywhere;
}

.record-item > .sl-icon {
  flex: none;
  margin-top: 0.2rem;
  color: var(--sl-ink-soft);
}

.record-done > .sl-icon {
  color: var(--sl-jade);
}

.record-missed {
  color: var(--sl-ink-soft);
}

/* Phones: smaller moments, hour marks every three hours, details stacked. */
@media (max-width: 575.98px) {
  .timeline-body {
    grid-template-columns: 4.4rem minmax(0, 1fr);
  }

  .timeline-lane-label {
    font-size: 0.7rem;
  }

  .marker {
    height: 1.75rem;
    min-width: 1.75rem;
    font-size: 0.85rem;
  }

  .marker-title,
  .marker-people {
    display: none;
  }

  .timeline-hour {
    visibility: hidden;
  }

  .timeline-hour:nth-child(3n + 1) {
    visibility: visible;
  }

  .timeline-hour:first-child,
  .timeline-hour:last-child {
    visibility: hidden;
  }

  .timeline-details {
    flex-wrap: wrap;
  }

  .timeline-actions {
    width: 100%;
    margin-left: 0;
  }

  .timeline-actions .btn {
    flex: 1;
  }
}
</style>
