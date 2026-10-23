<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import type { AppointmentRequest } from '@silverloop/api-client';

import AddAppointmentForm from '@/components/calendar/AddAppointmentForm.vue';
import AppointmentDetails from '@/components/calendar/AppointmentDetails.vue';
import Calendar from '@/components/calendar/Calendar.vue';
import CoverageSummary from '@/components/calendar/CoverageSummary.vue';
import DayAgenda from '@/components/calendar/DayAgenda.vue';
import DetailsSheet from '@/components/calendar/DetailsSheet.vue';
import KindFilter from '@/components/calendar/KindFilter.vue';
import PublicHolidays from '@/components/calendar/PublicHolidays.vue';
import UpcomingList from '@/components/calendar/UpcomingList.vue';
import ViewingAsPicker from '@/components/calendar/ViewingAsPicker.vue';
import { showToast } from '@/composables/useToast';
import { useFamily } from '@/composables/useFamily';
import { useTasks } from '@/composables/useTasks';
import { monthGrid, monthOf, shiftMonth } from '@/lib/calendar';
import { coverageOf, stillNeedsHelper, upcomingWithin } from '@/lib/coverage';
import { KIND_LABELS } from '@/lib/family';
import type { Appointment, AppointmentKind, FamilyMember } from '@/lib/family';
import { formatIsoDay, parseIsoDay } from '@/lib/format-date';
import { DEMO_PERSON_ID } from '@/lib/labels';
import { freeMembers, heatFor } from '@/lib/planner';
import type { TaskInput, TaskOccurrence } from '@/lib/tasks';

const route = useRoute();
const family = useFamily();
const { state, today, appointments, currentMember, elderName, loaded, groupId } = family;

// ---- Filters: the legend doubles as a set of switches ----
const ALL_KINDS = Object.keys(KIND_LABELS) as AppointmentKind[];
const shownKinds = reactive(new Set<AppointmentKind>(ALL_KINDS));
const onlyOpen = ref(route.query.help === '1');
const filtersOn = computed(() => onlyOpen.value || shownKinds.size < ALL_KINDS.length);

function toggleKind(kind: AppointmentKind) {
  if (shownKinds.has(kind)) shownKinds.delete(kind);
  else shownKinds.add(kind);
}
function clearFilters() {
  ALL_KINDS.forEach((kind) => shownKinds.add(kind));
  onlyOpen.value = false;
}

const visible = computed(() =>
  appointments.filter(
    (appointment) =>
      shownKinds.has(appointment.kind) &&
      (!onlyOpen.value || stillNeedsHelper(state.assignments, appointment)),
  ),
);

// ---- Where to start: a day or an appointment can be linked to from Home ----
// The appointments arrive from the API after the screen opens, so a linked one is found then.
const linkedAppointmentId =
  typeof route.query.appointment === 'string' ? route.query.appointment : null;
const linkedDay =
  typeof route.query.day === 'string' && parseIsoDay(route.query.day) ? route.query.day : null;
const startDay = linkedDay ?? today;

const month = ref(monthOf(startDay));
const selectedDay = ref(startDay);
const selectedId = ref<string | null>(linkedAppointmentId);
const side = ref<HTMLElement | null>(null);
const detailsRow = ref<HTMLElement | null>(null);
// Filled in by <PublicHolidays> once Nager.Date answers; the grid marks these days.
const holidays = ref<Record<string, string>>({});

const byDay = computed(() => {
  const days: Record<string, Appointment[]> = {};
  for (const appointment of visible.value) (days[appointment.date] ??= []).push(appointment);
  return days;
});
const uncoveredByDay = computed(() => {
  const days: Record<string, number> = {};
  for (const appointment of visible.value) {
    if (stillNeedsHelper(state.assignments, appointment)) {
      days[appointment.date] = (days[appointment.date] ?? 0) + 1;
    }
  }
  return days;
});

const dayList = computed(() => byDay.value[selectedDay.value] ?? []);

// ---- Tasks from the Tasks panel (kept in this browser), shown beside the appointments ----
// They need nobody to go along, so "Only those still needing someone" hides them.
const tasks = useTasks();
const taskPerson = computed(() => family.personId.value ?? DEMO_PERSON_ID);
const tasksByDay = computed<Record<string, TaskOccurrence[]>>(() =>
  onlyOpen.value
    ? {}
    : tasks.tasksByDay(
        taskPerson.value,
        monthGrid(month.value)
          .flat()
          .map((cell) => cell.iso),
      ),
);
const dayTasks = computed(() =>
  onlyOpen.value ? [] : tasks.tasksOn(taskPerson.value, selectedDay.value),
);
function toggleTask(task: TaskOccurrence) {
  tasks.setCompleted(taskPerson.value, task.task_id, task.date, !task.completed);
}
function saveTask(taskId: string, input: TaskInput) {
  tasks.update(taskPerson.value, taskId, input);
  showToast('Saved.');
}
function deleteTask(taskId: string) {
  tasks.remove(taskPerson.value, taskId);
  showToast('Deleted.');
}
// The next few appointments, leaving out the chosen day: those are already listed above.
const comingUp = computed(() =>
  visible.value
    .filter((appointment) => appointment.date >= today && appointment.date !== selectedDay.value)
    .slice(0, 5),
);
const selected = computed(
  () => appointments.find((appointment) => appointment.id === selectedId.value) ?? null,
);
const statuses = computed(() =>
  Object.fromEntries(
    state.members.map((member) => [
      member.id,
      selected.value ? family.statusOf(member.id, selected.value) : 'unknown',
    ]),
  ),
);

// The month ahead at a glance: how many visits already have someone going.
const coverage = computed(() =>
  coverageOf(upcomingWithin(appointments, today, 30), state.assignments),
);

function helpersOf(appointment: Appointment): FamilyMember[] {
  return family
    .helperIdsOf(appointment.id)
    .map((id) => state.members.find((member) => member.id === id))
    .filter((member): member is FamilyMember => member !== undefined);
}

// ---- Choosing things ----
const narrow = ref(false);
let media: MediaQueryList | null = null;
const onMedia = () => {
  narrow.value = media?.matches ?? false;
};

// Where focus was before the details opened, so closing them puts it back.
let opener: HTMLElement | null = null;

function pickDay(iso: string) {
  selectedDay.value = iso;
  selectedId.value = null;
  // Below xl the list sits under the calendar, out of sight: bring it into view.
  // The chosen day's list sits under the calendar: bring it into view if it is off screen.
  void nextTick(() => side.value?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
}

function moveDay(iso: string) {
  selectedDay.value = iso;
  selectedId.value = null;
  const target = monthOf(iso);
  if (target.year !== month.value.year || target.month !== month.value.month) month.value = target;
}

function pickAppointment(appointment: Appointment) {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  selectedId.value = appointment.id;
  selectedDay.value = appointment.date;
  month.value = monthOf(appointment.date);
  // Wide screens show the details under the calendar: bring them into view.
  if (!narrow.value) {
    void nextTick(() => detailsRow.value?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
  }
}

function closeDetails() {
  selectedId.value = null;
  const back = opener;
  opener = null;
  void nextTick(() => {
    if (back && document.contains(back)) back.focus();
  });
}

function goToday() {
  selectedDay.value = today;
  selectedId.value = null;
  month.value = monthOf(today);
}

// "Viewing as" is a `v-model`: choosing someone switches the app to them and says so.
const viewerId = computed({
  get: () => state.currentMemberId,
  set: (id: string | null) => {
    if (!id) return;
    family.setCurrentMember(id);
    const name = family.currentMember.value?.name;
    if (name) showToast(`Now viewing as ${name}.`);
  },
});

function stepBack(appointment: Appointment) {
  family.stepBack(appointment.id);
  showToast(`You stepped back from ${appointment.title}.`, {
    actionLabel: 'Undo',
    action: () => family.volunteer(appointment.id),
  });
}

// ---- Keep the screen in step with the filters ----
// Turning a filter on used to leave open details (which hide the lists on a wide screen) and a
// chosen day with nothing left on it, so the matching visits were out of sight. Close details the
// filters now hide, and when the chosen day is empty move to the first upcoming day that matches.
function followFilters() {
  const current = selected.value;
  if (current && !visible.value.some((appointment) => appointment.id === current.id)) {
    selectedId.value = null;
  }
  if (!filtersOn.value || selectedId.value || dayList.value.length) return;
  const next = visible.value.find((appointment) => appointment.date >= today);
  if (next) moveDay(next.date);
}
watch([onlyOpen, () => shownKinds.size], followFilters);

// Once the calendar has loaded: open a linked appointment on its day, or apply `?help=1`.
watch(
  loaded,
  (isLoaded) => {
    if (!isLoaded) return;
    const linked = linkedAppointmentId
      ? appointments.find((appointment) => appointment.id === linkedAppointmentId)
      : undefined;
    if (linked) {
      selectedDay.value = linked.date;
      month.value = monthOf(linked.date);
    } else if (linkedAppointmentId) {
      selectedId.value = null;
    }
    if (onlyOpen.value && !linked && !linkedDay) followFilters();
  },
  { immediate: true },
);

// ---- Adding, editing, moving and removing appointments ----
const canChange = computed(() => !!groupId.value && !!currentMember.value);
/** The open form: a new appointment, one being edited, or nothing. */
const formFor = ref<Appointment | 'new' | null>(null);
const formOpen = computed(() => formFor.value !== null);
const savingNew = ref(false);
/** The form's day and times, shared with the calendar: tapping a day picks it. */
const draft = reactive({ date: today, start: '10:00', end: '11:00' });

function openAdd(day?: string) {
  const chosen = day ?? selectedDay.value;
  Object.assign(draft, { date: chosen >= today ? chosen : today, start: '10:00', end: '11:00' });
  selectedId.value = null;
  formFor.value = 'new';
}
function openEdit(appointment: Appointment) {
  Object.assign(draft, { date: appointment.date, start: appointment.start, end: appointment.end });
  selectedId.value = null;
  formFor.value = appointment;
}
async function saveForm(request: AppointmentRequest) {
  const editing = formFor.value;
  savingNew.value = true;
  if (editing && editing !== 'new') await family.updateAppointment(editing, request);
  else await family.addAppointment(request);
  savingNew.value = false;
  formFor.value = null;
  moveDay(request.date);
  showToast(editing && editing !== 'new' ? 'Saved.' : `Added ${request.title}.`);
}
async function removeAppointment(appointment: Appointment) {
  if (!appointment.seriesId) return;
  const every = appointment.repeat && appointment.repeat !== 'none' ? ' (every repeat)' : '';
  if (!window.confirm(`Delete ${appointment.title}${every}?`)) return;
  closeDetails();
  await family.removeAppointment(appointment.seriesId);
  showToast(`Deleted ${appointment.title}.`);
}

/** One-off appointments can be moved or edited (a repeating one's last day is not known here). */
const isOneOff = (appointment: Appointment) =>
  !!appointment.seriesId && (!appointment.repeat || appointment.repeat === 'none');
const movableIds = computed(
  () => new Set(canChange.value ? appointments.filter(isOneOff).map((a) => a.id) : []),
);

// Dragging an appointment chip onto another day moves it there.
const dragged = ref<Appointment | null>(null);
function onDrag(id: string | null) {
  dragged.value = id ? (appointments.find((a) => a.id === id) ?? null) : null;
}
function onDrop(id: string, iso: string) {
  const appointment = appointments.find((a) => a.id === id);
  if (!appointment || iso === appointment.date) return;
  if (iso < today) {
    showToast('Pick today or a later day.');
    return;
  }
  const from = appointment.date;
  void family.moveAppointment(appointment, iso);
  showToast(`Moved to ${formatIsoDay(iso)}.`, {
    actionLabel: 'Undo',
    action: () => {
      const moved = appointments.find((a) => a.seriesId === appointment.seriesId);
      if (moved) void family.moveAppointment(moved, from);
    },
  });
}

// ---- Who is free: shading the calendar while choosing a day or dragging ----
const gridDays = computed(() =>
  monthGrid(month.value)
    .flat()
    .map((cell) => cell.iso),
);
const heatTimes = computed(() =>
  dragged.value
    ? { start: dragged.value.start, end: dragged.value.end }
    : formOpen.value
      ? { start: draft.start, end: draft.end }
      : null,
);
const heatByDay = computed(() =>
  heatTimes.value
    ? heatFor(
        state.availability,
        state.members,
        gridDays.value,
        heatTimes.value.start,
        heatTimes.value.end,
      )
    : null,
);
const freeForDraft = computed(() =>
  freeMembers(state.availability, state.members, draft.date, draft.start, draft.end),
);

// While the form is open, tapping a day on the calendar picks it for the form.
function onSelectDay(iso: string) {
  if (formOpen.value && iso >= today) draft.date = iso;
  else pickDay(iso);
}

// ---- On a phone the details rise as a sheet over the calendar ----
const sheetOpen = computed(() => narrow.value && selected.value !== null);
watch(sheetOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : '';
});

function onKey(event: KeyboardEvent) {
  if (event.key !== 'Escape') return;
  if (selected.value) closeDetails();
  else if (formFor.value) formFor.value = null;
}

onMounted(() => {
  // Below xl the details open as a sheet (the lists sit under a full-width calendar there).
  media = window.matchMedia('(max-width: 1199.98px)');
  onMedia();
  media.addEventListener('change', onMedia);
  window.addEventListener('keydown', onKey);
});
onBeforeUnmount(() => {
  media?.removeEventListener('change', onMedia);
  window.removeEventListener('keydown', onKey);
  document.body.style.overflow = '';
});
</script>

<template>
  <div class="calendar-page">
    <header class="page-head">
      <div>
        <h1 class="mb-0">Calendar</h1>
        <p class="text-body-secondary mb-0">{{ elderName }}</p>
      </div>
      <!-- Top right: who is looking, then "+ Add". -->
      <div class="head-tools">
        <ViewingAsPicker
          v-if="family.canViewAs && state.members.length"
          v-model="viewerId"
          :members="state.members"
        />
        <button
          v-if="canChange"
          type="button"
          class="btn btn-primary"
          data-testid="add-appointment"
          :disabled="formOpen"
          @click="openAdd()"
        >
          + Add
        </button>
        <RouterLink v-else-if="!groupId && loaded" class="btn btn-outline-primary" to="/family">
          Join the family group
        </RouterLink>
      </div>
    </header>

    <div class="toolbar">
      <CoverageSummary :coverage="coverage" />
      <KindFilter
        :shown="shownKinds"
        :only-open="onlyOpen"
        :filters-on="filtersOn"
        @toggle="toggleKind"
        @toggle-open="onlyOpen = !onlyOpen"
        @clear="clearFilters"
      />
    </div>

    <p v-if="formOpen" class="hint" role="status">
      Greener days = more family free. Tap one to pick it.
    </p>
    <p v-else-if="movableIds.size" class="sl-note mb-2 d-none d-md-block">
      Tip: drag an appointment to another day to move it.
    </p>

    <p v-if="family.error.value" class="alert alert-danger" role="alert">
      {{ family.error.value }}
    </p>

    <!-- Bootstrap grid, one thing per row: the calendar, then the chosen day ("Today"), then
         "Coming up". While adding or editing, the form sits beside the calendar from xl, so a day
         can be tapped to pick it. An appointment's details open under the calendar from xl, and as
         a sheet over the page below that. -->
    <div class="row g-4">
      <div class="col-12" :class="{ 'col-xl-7': formFor }">
        <Calendar
          :month="month"
          :today="today"
          :selected-day="selectedDay"
          :appointments-by-day="byDay"
          :uncovered-by-day="uncoveredByDay"
          :holidays-by-day="holidays"
          :tasks-by-day="tasksByDay"
          :heat-by-day="heatByDay"
          :heat-total="state.members.length"
          :picked-day="formOpen ? draft.date : null"
          :movable-ids="movableIds"
          @previous="month = shiftMonth(month, -1)"
          @next="month = shiftMonth(month, 1)"
          @go-today="goToday"
          @select-day="onSelectDay"
          @move-day="moveDay"
          @drag-appointment="onDrag"
          @drop-appointment="onDrop"
        />
        <PublicHolidays
          class="mt-3"
          :year="month.year"
          :month="month.month"
          @loaded="holidays = $event"
        />
      </div>

      <div v-if="formFor" class="col-12 col-xl-5">
        <AddAppointmentForm
          :key="formFor === 'new' ? 'new' : formFor.id"
          v-model:date="draft.date"
          v-model:start="draft.start"
          v-model:end="draft.end"
          class="mb-4"
          :today="today"
          :busy="savingNew"
          :appointment="formFor === 'new' ? null : formFor"
          :free="freeForDraft"
          :family-size="state.members.length"
          @save="saveForm"
          @cancel="formFor = null"
        />
      </div>

      <div v-if="selected" ref="detailsRow" class="col-12">
        <DetailsSheet :open="selected !== null" :narrow="narrow" @close="closeDetails">
          <AppointmentDetails
            v-if="selected"
            :appointment="selected"
            :members="state.members"
            :helper-ids="family.helperIdsOf(selected.id)"
            :statuses="statuses"
            :current-member="currentMember"
            :elder-name="elderName"
            :today="today"
            @back="closeDetails"
            @volunteer="family.volunteer(selected.id)"
            @step-back="selected && stepBack(selected)"
            @respond="(status) => selected && family.respond(selected.id, status)"
            @remove="selected && removeAppointment(selected)"
            @edit="selected && openEdit(selected)"
          />
        </DetailsSheet>
      </div>

      <div ref="side" class="col-12">
        <DayAgenda
          :day="selectedDay"
          :appointments="dayList"
          :holiday="holidays[selectedDay] ?? null"
          :filters-on="filtersOn"
          :helpers-of="helpersOf"
          :tasks="dayTasks"
          :today="today"
          @select="pickAppointment"
          @toggle-task="toggleTask"
          @save-task="saveTask"
          @delete-task="deleteTask"
          :can-add="canChange"
          @add="openAdd"
        />
      </div>

      <div class="col-12">
        <UpcomingList
          :appointments="comingUp"
          :today="today"
          :filters-on="filtersOn"
          :helpers-of="helpersOf"
          @select="pickAppointment"
          @clear-filters="clearFilters"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Title on the left; who is looking and "+ Add" together on the right. */
.page-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

/* "Calendar", then who is looking, on one line (wrapping under it on a narrow phone). */
.head-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem 1rem;
  margin-left: auto;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem 1.5rem;
  margin-bottom: 1rem;
  padding: 0.6rem 0.9rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius);
  background: var(--sl-surface);
}

.hint {
  display: inline-block;
  margin-bottom: 0.75rem;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-size: 0.9rem;
  font-weight: 600;
}
</style>
