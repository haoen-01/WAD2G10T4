<script setup lang="ts">
import type { DailyMetric, PersonState, WearableStatus } from '@silverloop/api-client';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

import ErrorAlert from '@/components/ErrorAlert.vue';
import ActivityFeed from '@/components/home/ActivityFeed.vue';
import CheckInCard from '@/components/home/CheckInCard.vue';
import DayTimeline from '@/components/home/DayTimeline.vue';
import FortnightPanel from '@/components/home/FortnightPanel.vue';
import HomeHero from '@/components/home/HomeHero.vue';
import MorningSummary from '@/components/home/MorningSummary.vue';
import NeedsHelperList from '@/components/home/NeedsHelperList.vue';
import TaskPanel from '@/components/home/TaskPanel.vue';
import WeatherCard from '@/components/home/WeatherCard.vue';
import WeekAhead from '@/components/home/WeekAhead.vue';
import Icon from '@/components/ui/Icon.vue';
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue';
import { useAction } from '@/composables/useAction';
import { useAsks } from '@/composables/useAsks';
import { useFamily } from '@/composables/useFamily';
import { currentGroup, loadMe } from '@/composables/useMe';
import { useNow } from '@/composables/useNow';
import { useTasks } from '@/composables/useTasks';
import { showToast } from '@/composables/useToast';
import { addDays } from '@/lib/calendar';
import { needingHelp, stillNeedsHelper, upcomingWithin } from '@/lib/coverage';
import type { Appointment, FamilyMember } from '@/lib/family';
import { homeSeniorOf } from '@/lib/family-group';
import { formatIsoDay } from '@/lib/format-date';
import { DEMO_PERSON_ID } from '@/lib/labels';
import {
  buildSummary,
  MORNING_KEY,
  MORNING_OFF,
  shouldShowSummary,
  shownToday,
} from '@/lib/morning-summary';
import { isSampleSource } from '@/lib/reading-days';
import { greetingFor, visitWhen } from '@/lib/today';
import { getPersonMetrics, getPersonState, getWearable } from '@/services/careApi';

const { error, run } = useAction();
const family = useFamily();
// Who has been asked to go along (the amber "Asked Emily · waiting" tags), read fresh on opening.
useAsks();
const now = useNow();

// The senior's watch (simulated until a real device): shown in the hero so the family can remind
// them to charge it. Extra detail: if it cannot be read, the rest of Home still shows.
const wearable = ref<WearableStatus | null>(null);
const wearableFailed = ref(false);
async function loadWearable() {
  wearableFailed.value = false;
  if (!personId.value) {
    wearable.value = null;
    return;
  }
  try {
    wearable.value = await getWearable(personId.value);
  } catch {
    wearableFailed.value = true;
  }
}
const person = ref<PersonState | null>(null);
const loading = ref(true);

// The fortnight of readings is extra detail: if it fails, the overview still shows.
const history = ref<DailyMetric[] | null>(null);
const historyFailed = ref(false);

// The senior this family member cares for (the one picked in the navbar, if more than one).
// Null while that group has no senior linked: then nothing about any senior is read.
const personId = ref<string | null>(DEMO_PERSON_ID);

async function load() {
  await run(async () => {
    await loadMe().catch(() => null);
    personId.value = homeSeniorOf(currentGroup.value, DEMO_PERSON_ID);
    person.value = personId.value ? await getPersonState(personId.value) : null;
  });
  if (!person.value) history.value = null;
  void loadWearable();
  loading.value = false;
  if (person.value) void loadHistory();
  openSummaryOnceToday();
}

async function loadHistory() {
  historyFailed.value = false;
  if (!personId.value) return;
  try {
    history.value = await getPersonMetrics(personId.value, 14);
  } catch {
    historyFailed.value = true;
  }
}

onMounted(load);
watch(
  () => currentGroup.value?.group_id,
  (next, previous) => {
    if (previous !== undefined && next !== previous) void load();
  },
);

const greeting = computed(() => greetingFor(now.value.getHours()));
const viewer = computed(() => family.currentMember.value?.name ?? null);
const elder = computed(() => person.value?.display_name ?? family.elderName.value);
const usual = computed(() => person.value?.baseline.median_steps ?? 0);

// The family calendar (see lib/family.ts).
const { today, appointments, state } = family;
function helpersOf(appointmentId: string): FamilyMember[] {
  return family
    .helperIdsOf(appointmentId)
    .map((id) => state.members.find((member) => member.id === id))
    .filter((member): member is FamilyMember => member !== undefined);
}
const unhelped = computed(() =>
  needingHelp(upcomingWithin(appointments, today, 13), state.assignments),
);

// "I'll go" straight from Home: the same change as the calendar's "I'll help" (saved through the
// API by useFamily), with an undo. Only someone in the group can take a visit.
const checkInActor = computed(() => {
  const member = family.currentMember.value;
  return member ? { id: member.id, name: member.name } : null;
});
const canVolunteer = computed(() => family.currentMember.value !== null);
function goWith(appointment: Appointment) {
  family.volunteer(appointment.id);
  showToast(
    `You’re going to ${appointment.title}, ${visitWhen(appointment.date, appointment.start, appointment.end)}.`,
    { actionLabel: 'Undo', action: () => family.stepBack(appointment.id) },
  );
}

// Tasks from the Tasks panel, so the week ahead shows them beside the appointments.
const tasks = useTasks();
const weekTasks = computed(() =>
  tasks.tasksByDay(Array.from({ length: 7 }, (_, offset) => addDays(today, offset))),
);

/*
 * Phones: Today's tasks come before the family updates, the updates start folded, and the week
 * ahead is a link to the calendar instead of the whole week. Plain `matchMedia`, kept in step when
 * the screen turns or resizes.
 */
const phoneQuery = window.matchMedia('(max-width: 767.98px)');
const isPhone = ref(phoneQuery.matches);
function onPhoneChange() {
  isPhone.value = phoneQuery.matches;
}
onMounted(() => phoneQuery.addEventListener('change', onPhoneChange));
onBeforeUnmount(() => phoneQuery.removeEventListener('change', onPhoneChange));
const weekVisits = computed(() => upcomingWithin(appointments, today, 6).length);

/*
 * The morning summary (`lib/morning-summary.ts`): opens by itself on the first visit each day,
 * and from the "Today's summary" button at any time. "Show this each morning" is remembered in
 * this browser.
 */
function readSummaryKey(): string | null {
  try {
    return window.localStorage.getItem(MORNING_KEY);
  } catch {
    return null;
  }
}
function writeSummaryKey(value: string) {
  try {
    window.localStorage.setItem(MORNING_KEY, value);
  } catch {
    // Private browsing: it simply opens again next time.
  }
}
const summaryOpen = ref(false);
const eachMorning = ref(readSummaryKey() !== MORNING_OFF);
watch(eachMorning, (on) => {
  writeSummaryKey(on ? shownToday(null, personId.value ?? '', today) : MORNING_OFF);
});

const summary = computed(() => {
  const reading = person.value;
  if (!reading) return null;
  const battery = wearable.value;
  return buildSummary({
    elder: elder.value,
    today,
    readingDay: reading.current_day,
    steps: reading.signal.current_steps,
    usual: reading.baseline.median_steps,
    readable: reading.signal.quality.safe_to_interpret,
    attentionBand: reading.attention_band,
    lastDecision: reading.last_decision,
    consentActive: reading.consent_active,
    appointmentsToday: appointments
      .filter((appointment) => appointment.date === today)
      .map((appointment) => ({
        title: appointment.title,
        start: appointment.start,
        end: appointment.end,
        needsSomeone: stillNeedsHelper(state.assignments, appointment),
      })),
    tasksToday: tasks
      .tasksOn(today)
      .map((task) => ({ title: task.title, time: task.time, completed: task.completed })),
    unhelpedSoon: needingHelp(upcomingWithin(appointments, today, 2), state.assignments).map(
      (appointment) => ({ title: appointment.title, date: appointment.date }),
    ),
    battery:
      battery && typeof battery.battery_percent === 'number'
        ? { percent: battery.battery_percent, charging: battery.charging }
        : null,
  });
});
const summarySample = computed(() => isSampleSource(person.value?.signal.quality.source));

function openSummaryOnceToday() {
  const id = personId.value;
  if (!id || !person.value || !currentGroup.value) return;
  const stored = readSummaryKey();
  if (!shouldShowSummary(stored, id, today)) return;
  writeSummaryKey(shownToday(stored, id, today));
  summaryOpen.value = true;
}
</script>

<template>
  <div class="home">
    <HomeHero
      :person="person"
      :loading="loading"
      :wearable="wearable"
      :wearable-failed="wearableFailed"
      :now="now"
      :greeting="greeting"
      :viewer="viewer"
      :elder="elder"
    />

    <div v-if="summary && currentGroup" class="mb-4">
      <button
        type="button"
        class="btn btn-outline-primary"
        data-testid="open-morning-summary"
        @click="summaryOpen = true"
      >
        <Icon name="sun" class="me-1" />Today’s summary
      </button>
    </div>
    <MorningSummary
      v-if="summary"
      v-model:each-morning="eachMorning"
      :open="summaryOpen"
      :summary="summary"
      :greeting="greeting"
      :viewer="viewer"
      :elder="elder"
      :date-words="formatIsoDay(today)"
      :sample="summarySample"
      @close="summaryOpen = false"
    />

    <ErrorAlert v-if="error" :message="error" class="mb-4" @retry="load" />

    <!-- The senior's day by the hour, live: appointments, tasks and the family. -->
    <DayTimeline v-if="!loading" id="home-timeline" class="mb-4" :elder="elder" />

    <!-- Phones: today's tasks go here, before the family updates (see the Teleport below). -->
    <div id="home-tasks-spot" :class="{ 'mb-4': isPhone && !loading }"></div>

    <!-- What the family has been doing, and a one-tap way to say you were in touch. Phones: the
         check-in first; wide screens: the feed on the left, the check-in beside it. -->
    <div v-if="!loading && currentGroup" class="row g-4 mb-4">
      <div class="col-12 col-lg-5 order-lg-last">
        <CheckInCard :elder="elder" :actor="checkInActor" />
      </div>
      <div class="col-12 col-lg-7">
        <ActivityFeed :elder="elder" :members="state.members" :collapsible="isPhone" />
      </div>
    </div>

    <LoadingSpinner v-if="loading" />

    <!-- Bootstrap grid, in pairs that line up top and bottom. Wide screens (lg): the chart beside
         the weather, then the visits that need a helper beside the tasks. Phones: one column. -->
    <div v-else class="row g-4">
      <!-- Two stacked columns whose last panels stretch, so both columns end at the same line. The
           two-week chart is the main picture, so its column is the wider one. -->
      <div class="col-12 col-lg-7 d-flex flex-column gap-4">
        <FortnightPanel
          :history="history"
          :failed="historyFailed"
          :has-person="person !== null"
          :usual="usual"
          @retry="loadHistory"
        />
        <NeedsHelperList
          id="home-needs"
          class="flex-grow-1"
          :appointments="unhelped"
          :elder="elder"
          :can-volunteer="canVolunteer"
          :members="state.members"
          :availability="state.availability"
          :current-member-id="state.currentMemberId"
          @volunteer="goWith"
        />
      </div>
      <div class="col-12 col-lg-5 d-flex flex-column gap-4">
        <WeatherCard />
        <!-- One Tasks panel. On a phone, Teleport moves this same panel up to #home-tasks-spot;
             on wider screens (disabled) it stays here. Moving it keeps it alive, so a half-typed
             task survives turning the phone sideways. `defer` waits until the spot exists. -->
        <Teleport defer to="#home-tasks-spot" :disabled="!isPhone">
          <TaskPanel id="home-tasks" class="flex-grow-1" :can-manage="true" />
        </Teleport>
      </div>

      <!-- Phones: the week is one link to the calendar. -->
      <div v-if="isPhone" class="col-12">
        <RouterLink class="week-link sl-panel" to="/calendar" data-testid="week-link">
          <span class="sl-icon-chip"><Icon name="calendar" /></span>
          <span class="week-link-text">
            <span class="week-link-title">The week ahead</span>
            <span class="sl-note"
              >{{ weekVisits }} {{ weekVisits === 1 ? 'visit' : 'visits' }} in the next 7 days ·
              open the calendar</span
            >
          </span>
          <Icon name="arrow-right" class="week-link-go" />
        </RouterLink>
      </div>

      <div v-else class="col-12">
        <section id="home-week" aria-labelledby="week-heading">
          <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
            <h2 id="week-heading" class="sl-section-title d-flex align-items-center gap-2 mb-0">
              <Icon name="calendar" />The week ahead
            </h2>
            <RouterLink class="btn btn-outline-primary" to="/calendar">
              <Icon name="calendar" class="me-1" />Calendar
            </RouterLink>
          </div>

          <WeekAhead
            :today="today"
            :appointments="appointments"
            :helpers-of="helpersOf"
            :tasks-by-day="weekTasks"
          />
        </section>
      </div>
    </div>

    <p class="mt-5 mb-0 sl-note d-flex align-items-center gap-2">
      <Icon name="shield-check" class="flex-shrink-0" />
      Care+ does not diagnose, predict illness, detect falls, or contact anyone without consent.
    </p>
  </div>
</template>

<style scoped>
/* Phones: the week ahead as one row that opens the calendar. */
.week-link {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  color: var(--sl-ink);
  text-decoration: none;
}

.week-link:hover {
  color: var(--sl-ink);
}

.week-link-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.week-link-title {
  font-size: 1.15rem;
  font-weight: 700;
}

.week-link-go {
  flex: none;
  margin-left: auto;
  color: var(--sl-jade);
  transition: transform var(--sl-dur-base) var(--sl-ease);
}

.week-link:hover .week-link-go {
  transform: translateX(4px);
}
</style>
