<script setup lang="ts">
import type { DailyMetric, PersonState, WearableStatus } from '@silverloop/api-client';
import { computed, onMounted, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

import ErrorAlert from '@/components/ErrorAlert.vue';
import FortnightPanel from '@/components/home/FortnightPanel.vue';
import HomeHero from '@/components/home/HomeHero.vue';
import NeedsHelperList from '@/components/home/NeedsHelperList.vue';
import TaskPanel from '@/components/home/TaskPanel.vue';
import WeatherCard from '@/components/home/WeatherCard.vue';
import WeekAhead from '@/components/home/WeekAhead.vue';
import Icon from '@/components/ui/Icon.vue';
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue';
import { useAction } from '@/composables/useAction';
import { useFamily } from '@/composables/useFamily';
import { currentGroup, loadMe } from '@/composables/useMe';
import { useNow } from '@/composables/useNow';
import { useTasks } from '@/composables/useTasks';
import { showToast } from '@/composables/useToast';
import { addDays } from '@/lib/calendar';
import { needingHelp, upcomingWithin } from '@/lib/coverage';
import type { Appointment, FamilyMember } from '@/lib/family';
import { DEMO_PERSON_ID } from '@/lib/labels';
import { greetingFor, visitWhen } from '@/lib/today';
import { getPersonMetrics, getPersonState, getWearable } from '@/services/careApi';

const { error, run } = useAction();
const family = useFamily();
const now = useNow();

// The senior's watch (simulated until a real device): shown in the hero so the family can remind
// them to charge it. Extra detail: if it cannot be read, the rest of Home still shows.
const wearable = ref<WearableStatus | null>(null);
const wearableFailed = ref(false);
async function loadWearable() {
  wearableFailed.value = false;
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
const personId = ref(DEMO_PERSON_ID);

async function load() {
  await run(async () => {
    await loadMe().catch(() => null);
    personId.value = currentGroup.value?.person_id ?? DEMO_PERSON_ID;
    person.value = await getPersonState(personId.value);
  });
  void loadWearable();
  loading.value = false;
  if (person.value) void loadHistory();
}

async function loadHistory() {
  historyFailed.value = false;
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
  tasks.tasksByDay(
    personId.value,
    Array.from({ length: 7 }, (_, offset) => addDays(today, offset)),
  ),
);
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

    <ErrorAlert v-if="error" :message="error" class="mb-4" @retry="load" />

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
          @volunteer="goWith"
        />
      </div>
      <div class="col-12 col-lg-5 d-flex flex-column gap-4">
        <WeatherCard />
        <TaskPanel
          id="home-tasks"
          :key="personId"
          class="flex-grow-1"
          :person-id="personId"
          :can-manage="true"
        />
      </div>

      <div class="col-12">
        <section id="home-week" aria-labelledby="week-heading">
          <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
            <h2 id="week-heading" class="h4 d-flex align-items-center gap-2 mb-0">
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
