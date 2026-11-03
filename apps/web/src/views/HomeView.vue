<script setup lang="ts">
import type { DailyMetric, PersonState, WearableStatus } from '@silverloop/api-client';
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import ErrorAlert from '@/components/ErrorAlert.vue';
import ActivityFeed from '@/components/home/ActivityFeed.vue';
import CatchUpCard from '@/components/home/CatchUpCard.vue';
import CheckInCard from '@/components/home/CheckInCard.vue';
import DayTimeline from '@/components/home/DayTimeline.vue';
import FortnightPanel from '@/components/home/FortnightPanel.vue';
import HomeHero from '@/components/home/HomeHero.vue';
import NeedsHelperList from '@/components/home/NeedsHelperList.vue';
import TaskPanel from '@/components/home/TaskPanel.vue';
import WeatherCard from '@/components/home/WeatherCard.vue';
import WeekAhead from '@/components/home/WeekAhead.vue';
import Icon from '@/components/ui/Icon.vue';
import { useAction } from '@/composables/useAction';
import { useFamily } from '@/composables/useFamily';
import { useFamilyActivity } from '@/composables/useFamilyActivity';
import { currentGroup, loadMe } from '@/composables/useMe';
import { useNow } from '@/composables/useNow';
import { useTasks } from '@/composables/useTasks';
import { showToast } from '@/composables/useToast';
import { addDays } from '@/lib/calendar';
import { needingHelp, upcomingWithin } from '@/lib/coverage';
import type { Appointment, FamilyMember } from '@/lib/family';
import { homeSeniorOf } from '@/lib/family-group';
import { sampleNotice } from '@/lib/home';
import { DEMO_PERSON_ID } from '@/lib/labels';
import { isSampleSource } from '@/lib/reading-days';
import { oneOffTasksByDay, repeatingCountByDay } from '@/lib/tasks';
import { greetingFor, visitWhen } from '@/lib/today';
import { getPersonMetrics, getPersonState, getWearable } from '@/services/careApi';

/**
 * Family Home answers one question: "Is she okay today, and is there anything I need to do?"
 * Three zones, in that order: the hero (her day in one plain sentence), "Needs you" (visits that
 * need someone, the check-in, today's tasks) and "Recently" (the family feed). Everything else
 * about the week (the day by the hour, two weeks of steps, the weather, the week ahead) is one
 * click away under "See more about this week".
 */
const { error, run } = useAction();
const family = useFamily();
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
    {
      actionLabel: 'Undo',
      action: async () => {
        family.stepBack(appointment.id);
        // Back on the list: focus returns to that visit's "I'll go".
        await nextTick();
        document
          .querySelector<HTMLElement>(`.needs-go[data-go="${CSS.escape(appointment.id)}"]`)
          ?.focus();
      },
    },
  );
}

// Tasks from the Tasks panel, so the week ahead shows them beside the appointments. As on the
// calendar, only one-off tasks are listed; the daily and weekly ones are a count per day.
const tasks = useTasks();
const allWeekTasks = computed(() =>
  tasks.tasksByDay(Array.from({ length: 7 }, (_, offset) => addDays(today, offset))),
);
const weekTasks = computed(() => oneOffTasksByDay(allWeekTasks.value));
const weekRepeating = computed(() => repeatingCountByDay(allWeekTasks.value));

// The screen's one "Sample data" notice, in the hero: sample steps (the hero and the chart) and
// seeded family updates. The cards no longer carry a badge each.
const feed = useFamilyActivity({ subscribe: false });
const sampleNote = computed(() =>
  sampleNotice(elder.value, {
    steps:
      (person.value !== null && isSampleSource(person.value.signal.quality.source)) ||
      (history.value ?? []).some((day) => isSampleSource(day.source)),
    feed:
      currentGroup.value !== null &&
      feed.entries.value.some((entry) => entry.origin === 'demo_seed'),
  }),
);

// "See more about this week": the day by the hour, two weeks of steps, the weather and the week
// ahead, one click away. Remembered in this browser; a link to one of its parts opens it.
const MORE_KEY = 'careplus.home.more.v1';
const MORE_PARTS = ['#home-more', '#home-timeline', '#home-chart', '#home-weather', '#home-week'];
const route = useRoute();
function savedMore(): boolean {
  try {
    return localStorage.getItem(MORE_KEY) === 'open';
  } catch {
    return false;
  }
}
const moreOpen = ref(savedMore() || MORE_PARTS.includes(route.hash));
function toggleMore() {
  moreOpen.value = !moreOpen.value;
  try {
    localStorage.setItem(MORE_KEY, moreOpen.value ? 'open' : 'closed');
  } catch {
    // Storage can be blocked; the section still opens and closes.
  }
}
watch(
  () => route.hash,
  async (hash) => {
    if (!MORE_PARTS.includes(hash)) return;
    moreOpen.value = true;
    await nextTick();
    document.querySelector(hash)?.scrollIntoView();
  },
);
</script>

<template>
  <div class="home">
    <!-- 1. Is she okay today? Her day in one sentence, warm and personal. -->
    <HomeHero
      :person="person"
      :loading="loading"
      :wearable="wearable"
      :wearable-failed="wearableFailed"
      :now="now"
      :greeting="greeting"
      :viewer="viewer"
      :elder="elder"
      :no-senior="!loading && personId === null"
      :sample-note="sampleNote"
    />

    <ErrorAlert v-if="error" :message="error" class="mb-4" @retry="load" />

    <!-- 2. Is there anything I need to do? Visits that need someone, the check-in, today's tasks.
         Wide screens: visits and the check-in on the left, tasks on the right. Phones: one column,
         in that order. -->
    <section id="home-needs-you" class="home-zone home-band" aria-labelledby="needs-you-heading">
      <h2 id="needs-you-heading" class="sl-section-title needs-you-title">
        <span v-if="unhelped.length" class="needs-you-dot" aria-hidden="true"></span>Needs you
      </h2>
      <div v-if="loading" class="row g-4" aria-hidden="true">
        <div v-for="n in 2" :key="n" class="col-12" :class="n === 1 ? 'col-lg-7' : 'col-lg-5'">
          <div class="sl-panel">
            <span class="sl-skeleton sk-heading"></span>
            <span class="sl-skeleton sk-row"></span>
            <span class="sl-skeleton sk-row"></span>
          </div>
        </div>
      </div>
      <div v-else class="row g-4">
        <div class="col-12 col-lg-7 d-flex flex-column gap-4">
          <NeedsHelperList
            id="home-needs"
            :appointments="unhelped"
            :elder="elder"
            :can-volunteer="canVolunteer"
            :helper="family.currentMember.value"
            @volunteer="goWith"
          />
          <CheckInCard v-if="currentGroup" :elder="elder" :actor="checkInActor" />
        </div>
        <div class="col-12 col-lg-5">
          <TaskPanel id="home-tasks" :can-manage="true" />
        </div>
      </div>
    </section>

    <!-- 3. Recently: what the family has done. -->
    <div v-if="!loading && currentGroup" class="home-zone d-flex flex-column gap-4">
      <CatchUpCard :group-id="currentGroup.group_id" />
      <ActivityFeed :elder="elder" :members="state.members" />
    </div>

    <!-- 4. More about this week, one click away. -->
    <section v-if="!loading" id="home-more" class="home-zone" aria-labelledby="more-heading">
      <h2 id="more-heading" class="visually-hidden">More about this week</h2>
      <button
        type="button"
        class="more-toggle"
        :aria-expanded="moreOpen"
        :aria-controls="moreOpen ? 'home-more-panel' : undefined"
        data-testid="home-more-toggle"
        @click="toggleMore"
      >
        <span class="more-words">
          <span class="more-title">{{
            moreOpen ? 'Less about this week' : 'See more about this week'
          }}</span>
          <span class="more-hint"
            >Her day by the hour, her last two weeks, the weather and the week ahead</span
          >
        </span>
        <Icon name="chevron-right" class="more-chevron" :class="{ open: moreOpen }" />
      </button>

      <div v-if="moreOpen" id="home-more-panel" class="more-panel">
        <!-- The senior's day by the hour, live: appointments, tasks and the family. -->
        <DayTimeline id="home-timeline" :elder="elder" />

        <div class="row g-4">
          <div class="col-12 col-lg-7">
            <FortnightPanel
              id="home-chart"
              class="h-100"
              :history="history"
              :failed="historyFailed"
              :has-person="person !== null"
              :usual="usual"
              @retry="loadHistory"
            />
          </div>
          <div class="col-12 col-lg-5">
            <WeatherCard id="home-weather" class="h-100" />
          </div>
        </div>

        <section id="home-week" aria-labelledby="week-heading">
          <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
            <h3 id="week-heading" class="sl-section-title d-flex align-items-center gap-2 mb-0">
              <Icon name="calendar" />The week ahead
            </h3>
            <RouterLink class="btn btn-outline-primary" to="/calendar">
              <Icon name="calendar" class="me-1" />Calendar
            </RouterLink>
          </div>

          <WeekAhead
            :today="today"
            :appointments="appointments"
            :helpers-of="helpersOf"
            :tasks-by-day="weekTasks"
            :repeating-by-day="weekRepeating"
          />
        </section>
      </div>
    </section>

    <p class="mt-5 mb-0 sl-note d-flex align-items-center gap-2">
      <Icon name="shield-check" class="flex-shrink-0" />
      Care+ does not diagnose, predict illness, detect falls, or contact anyone without consent.
    </p>
  </div>
</template>

<style scoped>
/* Phones: room at the end so nothing on Home has to rest under Kaki's floating button. */
@media (max-width: 767.98px) {
  .home {
    padding-bottom: 5.5rem;
  }
}

.home-zone + .home-zone {
  margin-top: var(--sl-zone-gap);
}

/* "Needs you" sits on its own pale-sky band, the full width of the window (the shadow paints the
   band past the container; the clip keeps it from making the page scroll sideways). */
.home-band {
  padding-block: 1.75rem 2rem;
  background: var(--sl-band);
  box-shadow: 0 0 0 100vmax var(--sl-band);
  clip-path: inset(0 -100vmax);
}

.home-band + .home-zone {
  margin-top: 2rem;
}

.needs-you-title {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.needs-you-dot {
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 50%;
  background: var(--sl-coral);
}

/* A whole-width row that opens the section below: words on the left, a chevron that turns. */
.more-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  width: 100%;
  min-height: 3.5rem;
  padding: 1rem 1.25rem;
  border: 0;
  border-radius: var(--sl-radius);
  background: var(--sl-surface);
  box-shadow: var(--sl-rest);
  color: var(--sl-ink);
  text-align: left;
}

@media (hover: hover) and (pointer: fine) {
  .more-toggle:hover .more-title {
    text-decoration: underline;
  }
}

.more-words {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.more-title {
  font-size: 1.2rem;
  font-weight: 700;
}

.more-hint {
  color: var(--sl-ink-soft);
  font-size: 0.95rem;
}

.more-chevron {
  width: 1.5rem;
  height: 1.5rem;
  color: var(--sl-link);
  transition: transform var(--sl-dur-base) var(--sl-ease);
}

.more-chevron.open {
  transform: rotate(90deg);
}

.more-panel {
  display: grid;
  gap: 1.5rem;
  margin-top: 1.5rem;
}

.sk-heading {
  width: 55%;
  height: 1.5rem;
  margin-bottom: 1.25rem;
}

.sk-row {
  height: 2.75rem;
  margin-top: 0.75rem;
}
</style>
