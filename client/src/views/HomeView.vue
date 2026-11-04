<script setup lang="ts">
import type { CatchUp, DailyMetric, PersonState, WearableStatus } from '@silverloop/api-client';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import ErrorAlert from '@/components/ErrorAlert.vue';
import MemberAvatar from '@/components/family/MemberAvatar.vue';
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
import { useAsks } from '@/composables/useAsks';
import { useFamily } from '@/composables/useFamily';
import { useFamilyActivity } from '@/composables/useFamilyActivity';
import { currentGroup, loadMe } from '@/composables/useMe';
import { useNow } from '@/composables/useNow';
import { useReadAloud } from '@/composables/useReadAloud';
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
import {
  getMyDaySpeech,
  getMyDayVoice,
  getPersonMetrics,
  getPersonState,
  getWearable,
} from '@/services/careApi';

/**
 * Family Home answers one question: "Is she okay today, and is there anything I need to do?" It
 * reads like an editorial page rather than a dashboard, in a few large sections that alternate
 * plum and cream: the hero (her day as one serif headline, beside her watch, live in 3D), the
 * family's catch-up (the AI companion's own words, set as the page's statement), "What needs you"
 * (visits that need someone, the check-in, today's tasks) on a plum band, and "Recently" (the
 * family feed). The rest of the week (the day by the hour, two weeks of steps, the weather, the
 * week ahead) is one click away under "See more about this week".
 */
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

// The editorial page sits on cream; the other screens keep their own ground.
onMounted(() => document.documentElement.classList.add('ed-home'));
onBeforeUnmount(() => document.documentElement.classList.remove('ed-home'));

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

// The family's catch-up, handed up by its card so the hero can offer to read it aloud: in the
// Kokoro voice on the Care+ server when it is there, else the browser's own (`useReadAloud`).
const catchUp = ref<CatchUp | null>(null);
const catchUpState = ref<'loading' | 'ready' | 'none'>('loading');
function onCatchUp(result: CatchUp | null) {
  catchUp.value = result;
  catchUpState.value = result ? 'ready' : 'none';
}
const speech = useReadAloud({
  status: () =>
    personId.value
      ? getMyDayVoice(personId.value)
      : Promise.resolve({ available: false, label: null }),
  audio: (sentence, voice) => getMyDaySpeech(personId.value!, sentence, voice),
});
const listen = computed(() => ({
  available: speech.canSpeak && catchUp.value !== null,
  reading: speech.state.value !== 'idle',
}));
function toggleListen() {
  if (speech.state.value !== 'idle') return speech.stop();
  if (!catchUp.value) return;
  speech.prime();
  void speech.speak([catchUp.value.summary, ...catchUp.value.highlights].join(' '));
}

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
    <!-- 1. Is she okay today? Her day as one headline, beside her watch. -->
    <HomeHero
      :person="person"
      :loading="loading"
      :wearable="wearable"
      :wearable-failed="wearableFailed"
      :history="history"
      :now="now"
      :greeting="greeting"
      :viewer="viewer"
      :elder="elder"
      :no-senior="!loading && personId === null"
      :sample-note="sampleNote"
      :listen="listen"
      @listen="toggleListen"
    />

    <ErrorAlert v-if="error" :message="error" class="mt-4" @retry="load" />

    <!-- 2. What the family has been doing, in the AI companion's own words. -->
    <section
      v-if="!loading && currentGroup && catchUpState !== 'none'"
      id="home-companion"
      class="home-section companion"
    >
      <figure class="family-frame mb-0" aria-hidden="true">
        <span class="family-faces">
          <MemberAvatar :name="elder" colour="senior" size="xl" class="family-face" />
          <MemberAvatar
            v-for="member in state.members.slice(0, 4)"
            :key="member.id"
            :name="member.name"
            :colour="member.colour"
            size="xl"
            class="family-face"
          />
        </span>
        <figcaption class="family-frame-words ed-serif">
          {{ elder
          }}<span class="family-frame-count"
            >{{ state.members.length }}
            {{ state.members.length === 1 ? 'person' : 'people' }} looking after her</span
          >
        </figcaption>
      </figure>
      <CatchUpCard :group-id="currentGroup.group_id" @loaded="onCatchUp" />
    </section>

    <!-- 3. Is there anything I need to do? On the plum band: the words, then the three things. -->
    <section id="home-needs-you" class="home-band" aria-labelledby="needs-you-heading">
      <div class="band-intro">
        <h2 id="needs-you-heading" class="band-title ed-serif">What needs you</h2>
        <p v-if="!loading" class="band-line mb-0">
          Take a visit, tell the family you were in touch, and tick off today’s tasks.
        </p>
      </div>
      <div v-if="loading" class="band-cards" aria-hidden="true">
        <div v-for="n in 2" :key="n" class="sl-panel">
          <span class="sl-skeleton sk-heading"></span>
          <span class="sl-skeleton sk-row"></span>
          <span class="sl-skeleton sk-row"></span>
        </div>
      </div>
      <div v-else class="band-cards">
        <NeedsHelperList
          id="home-needs"
          class="band-wide"
          :appointments="unhelped"
          :elder="elder"
          :can-volunteer="canVolunteer"
          :helper="family.currentMember.value"
          :members="state.members"
          :availability="state.availability"
          :current-member-id="state.currentMemberId"
          @volunteer="goWith"
        />
        <CheckInCard v-if="currentGroup" :elder="elder" :actor="checkInActor" />
        <TaskPanel id="home-tasks" :can-manage="true" />
      </div>
    </section>

    <!-- 4. Recently: what the family has done. -->
    <section v-if="!loading && currentGroup" class="home-section recently">
      <ActivityFeed :elder="elder" :members="state.members" />
    </section>

    <!-- 5. More about this week, one click away. -->
    <section v-if="!loading" id="home-more" class="home-section" aria-labelledby="more-heading">
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
          <span class="more-title ed-serif">{{
            moreOpen ? 'Less about this week' : 'See more about this week'
          }}</span>
          <span class="more-hint"
            >Her day by the hour, her last two weeks, the weather and the week ahead</span
          >
        </span>
        <span class="more-disc" aria-hidden="true">
          <Icon name="chevron-right" class="more-chevron" :class="{ open: moreOpen }" />
        </span>
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

    <p class="home-boundary sl-note d-flex align-items-center gap-2 mb-0">
      <Icon name="shield-check" class="flex-shrink-0" />
      Care+ does not diagnose, predict illness, detect falls, or contact anyone without consent.
    </p>
  </div>
</template>

<style scoped>
/* The hero meets the header: no gap from <main>'s top padding. */
.home {
  margin-top: -1.5rem;
  color: var(--ed-ink);
}

@media (min-width: 768px) {
  .home {
    margin-top: -3rem;
  }
}

/* Phones: room at the end so nothing on Home has to rest under Kaki's floating button. */
@media (max-width: 767.98px) {
  .home {
    padding-bottom: 5.5rem;
  }
}

/* Cream sections: wide, quiet spacing between them, as in an editorial page. */
.home-section {
  padding-top: 4.5rem;
}

@media (max-width: 767.98px) {
  .home-section {
    padding-top: 3rem;
  }
}

/* ---- 2. The family's catch-up: a framed "portrait" of the family beside the statement ---- */
.companion {
  display: grid;
  gap: 2.5rem;
  align-items: start;
}

@media (min-width: 992px) {
  .companion {
    grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
    gap: 4rem;
  }
}

.family-frame {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 2.5rem;
  min-height: 22rem;
  padding: 2.25rem 2rem 2.5rem;
  border-radius: var(--ed-radius) var(--ed-radius) 0 0;
  background: var(--ed-blush);
  /* A torn bottom edge, as on the reference's photographs. */
  clip-path: polygon(
    0 0,
    100% 0,
    100% 96%,
    93% 99%,
    85% 96.5%,
    76% 99.5%,
    66% 97%,
    57% 99.6%,
    46% 96.8%,
    36% 99.3%,
    25% 97%,
    15% 99.5%,
    7% 97.2%,
    0 99%
  );
}

/* Her face first, then the family's, overlapping like a group photograph. */
.family-faces {
  display: flex;
}

.family-face {
  box-shadow: 0 0 0 4px var(--ed-blush);
}

.family-face + .family-face {
  margin-left: -1.1rem;
}

.family-frame-words {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  color: var(--ed-ink);
  font-size: clamp(2.25rem, 3.5vw, 3rem);
  line-height: 1;
}

.family-frame-count {
  color: var(--ed-ink-soft);
  font-family: var(--bs-body-font-family);
  font-size: 1rem;
  letter-spacing: 0;
}

@media (max-width: 991.98px) {
  .family-frame {
    min-height: 0;
    padding: 1.5rem 1.5rem 2rem;
  }
}

/* ---- 3. "What needs you": the plum band, the full width of the window ---- */
.home-band {
  display: grid;
  gap: 2rem;
  margin-top: 4.5rem;
  padding-block: 4rem;
  background: var(--ed-plum);
  box-shadow: 0 0 0 100vmax var(--ed-plum);
  clip-path: inset(0 -100vmax);
}

@media (min-width: 992px) {
  .home-band {
    grid-template-columns: minmax(0, 4fr) minmax(0, 8fr);
    gap: 3.5rem;
    padding-block: 5rem;
  }
}

@media (max-width: 767.98px) {
  .home-band {
    margin-top: 3rem;
    padding-block: 3rem;
  }
}

.band-intro {
  color: var(--ed-on-plum);
}

.band-title {
  margin: 0 0 1rem;
  color: var(--ed-on-plum);
  font-size: clamp(2.5rem, 5vw, 4rem);
  line-height: 0.98;
}

.band-line {
  max-width: 22rem;
  color: var(--ed-on-plum-soft);
  font-size: 1.15rem;
  line-height: 1.5;
}

.band-cards {
  display: grid;
  align-items: start;
  gap: 1.25rem;
  min-width: 0;
}

/* Inside the band, the cards' buttons speak the page's colours: plum for the one action of each
   row ("I'll go"), plum outlines for the rest. */
.band-cards :deep(.btn-primary) {
  --bs-btn-bg: var(--ed-plum);
  --bs-btn-border-color: var(--ed-plum);
  --bs-btn-color: var(--ed-on-plum);
  --bs-btn-hover-bg: var(--ed-plum-deep);
  --bs-btn-hover-border-color: var(--ed-plum-deep);
  --bs-btn-hover-color: var(--ed-on-plum);
  --bs-btn-active-bg: var(--ed-plum-deep);
  --bs-btn-active-border-color: var(--ed-plum-deep);
  --bs-btn-active-color: var(--ed-on-plum);
}

.band-cards :deep(.btn-outline-primary),
.band-cards :deep(.btn-outline-secondary) {
  --bs-btn-color: var(--ed-ink);
  --bs-btn-border-color: var(--ed-ink);
  --bs-btn-hover-bg: var(--ed-ink);
  --bs-btn-hover-border-color: var(--ed-ink);
  --bs-btn-hover-color: var(--ed-card);
  --bs-btn-active-bg: var(--ed-ink);
  --bs-btn-active-border-color: var(--ed-ink);
  --bs-btn-active-color: var(--ed-card);
}

/* The cards' own headings join the page's serif. */
.band-cards :deep(h2),
.band-cards :deep(h3) {
  font-family: var(--ed-serif);
  font-size: 1.85rem;
  font-weight: 400;
  letter-spacing: -0.015em;
}

@media (min-width: 768px) {
  .band-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .band-wide {
    grid-column: 1 / -1;
  }
}

/* The band's cards are cream paper on the plum: one elevation, no border. */
.band-cards > :deep(*) {
  border: 0;
  border-radius: var(--ed-radius);
  background: var(--ed-card);
  box-shadow: none;
}

/* ---- 4. Recently ---- */
.recently :deep(h2),
.recently :deep(h3) {
  font-family: var(--ed-serif);
  font-size: clamp(2.25rem, 4vw, 3rem);
  font-weight: 400;
  letter-spacing: -0.02em;
}

.recently > :deep(*) {
  border: 0;
  border-radius: var(--ed-radius);
  background: var(--ed-card);
  box-shadow: none;
}

/* ---- 5. "See more": a quiet serif line with a round arrow, not a panel ---- */
.more-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  width: 100%;
  min-height: 3.5rem;
  padding: 1.5rem 0;
  border: 0;
  border-top: 1px solid var(--ed-line);
  border-bottom: 1px solid var(--ed-line);
  background: none;
  color: var(--ed-ink);
  text-align: left;
}

.more-toggle:focus-visible {
  outline: 3px solid var(--ed-ink);
  outline-offset: 4px;
}

.more-words {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 0;
}

.more-title {
  font-size: clamp(1.75rem, 3vw, 2.25rem);
  line-height: 1.05;
}

.more-hint {
  color: var(--ed-ink-soft);
  font-size: 1rem;
}

.more-disc {
  display: grid;
  flex: none;
  place-items: center;
  width: 3rem;
  height: 3rem;
  border-radius: 50%;
  background: var(--ed-lime);
  color: var(--ed-lime-ink);
  transition: transform var(--sl-dur-base) var(--sl-ease-out);
}

@media (hover: hover) and (pointer: fine) {
  .more-toggle:hover .more-disc {
    transform: scale(1.06);
  }
}

.more-chevron {
  width: 1.25rem;
  height: 1.25rem;
  transition: transform var(--sl-dur-base) var(--sl-ease);
}

.more-chevron.open {
  transform: rotate(90deg);
}

.more-panel {
  display: grid;
  gap: 1.5rem;
  margin-top: 2rem;
}

.home-boundary {
  margin-top: 4rem;
  color: var(--ed-ink-soft);
}

.sk-heading {
  display: block;
  width: 55%;
  height: 1.5rem;
  margin-bottom: 1.25rem;
}

.sk-row {
  display: block;
  height: 2.75rem;
  margin-top: 0.75rem;
}
</style>
