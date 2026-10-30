<script setup lang="ts">
import type { DailyMetric, Intervention, OutcomeKind, PersonState } from '@silverloop/api-client';
import { nextTick, onMounted, ref } from 'vue';
import ErrorAlert from '@/components/ErrorAlert.vue';
import SeniorCalendar from '@/components/calendar/SeniorCalendar.vue';
import SeniorTaskList from '@/components/senior/SeniorTaskList.vue';
import LinkFamily from '@/components/senior/LinkFamily.vue';
import MyFamily from '@/components/senior/MyFamily.vue';
import UpcomingEvents from '@/components/senior/UpcomingEvents.vue';
import StepsHero from '@/components/senior/StepsHero.vue';
import SuggestionCard from '@/components/senior/SuggestionCard.vue';
import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import ShareWalkCard from '@/components/walk/ShareWalkCard.vue';
import StillnessPrompt from '@/components/walk/StillnessPrompt.vue';
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue';
import { useAction } from '@/composables/useAction';
import { useFamily } from '@/composables/useFamily';
import { loadMe } from '@/composables/useMe';
import { useNow } from '@/composables/useNow';
import { AUTH_ENABLED } from '@/lib/config';
import { formatIsoDay } from '@/lib/format-date';
import { DEMO_PERSON_ID } from '@/lib/labels';
import { adjacentTab, readTab, saveTab } from '@/lib/senior-view';
import type { SeniorTab } from '@/lib/senior-view';
import { greetingFor } from '@/lib/today';
import {
  getInterventions,
  getPersonMetrics,
  getPersonState,
  recordOutcome,
} from '@/services/careApi';
const { busy, error, run } = useAction();
const family = useFamily();
const now = useNow();
const person = ref<PersonState | null>(null);
const suggestion = ref<Intervention | null>(null);
const thanks = ref<string | null>(null);
const loading = ref(true);
// Whose day this is: the signed-in senior's own record. The demo (sign-in off) is always Mdm Lim.
const personId = ref(DEMO_PERSON_ID);
async function refresh() {
  const [state, interventions] = await Promise.all([
    getPersonState(personId.value),
    getInterventions(),
  ]);
  person.value = state;
  // Waiting for a reply = `proposed`. An offer nobody answers is closed by the API after two days.
  suggestion.value =
    interventions
      .filter((item) => item.person_id === personId.value && item.status === 'proposed')
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
}
async function load() {
  await run(async () => {
    if (AUTH_ENABLED) personId.value = (await loadMe()).person_id ?? DEMO_PERSON_ID;
    await refresh();
  });
  loading.value = false;
  if (person.value) void loadWeek();
}
// The last week of readings is extra detail: if it fails, the rest of the screen still shows.
const week = ref<DailyMetric[] | null>(null);
async function loadWeek() {
  try {
    week.value = await getPersonMetrics(personId.value, 7);
  } catch {
    week.value = null;
  }
}
function reply(outcome: OutcomeKind, message: string) {
  const current = suggestion.value;
  if (!current) return;
  return run(async () => {
    await recordOutcome(current.intervention_id, outcome);
    thanks.value = message;
    await refresh();
  });
}
onMounted(load);
const { today } = family;
const activeTab = ref<SeniorTab>('today');
try {
  activeTab.value = readTab(localStorage);
} catch {
  /* Storage access itself may be blocked. */
}
const tabs: { id: SeniorTab; label: string; icon: IconName }[] = [
  { id: 'today', label: 'Today', icon: 'home' },
  { id: 'calendar', label: 'Calendar', icon: 'calendar' },
  { id: 'family', label: 'Family', icon: 'users' },
];
function selectTab(tab: SeniorTab) {
  activeTab.value = tab;
  try {
    saveTab(localStorage, tab);
  } catch {
    /* Storage access itself may be blocked. */
  }
}
async function navigateTabs(event: KeyboardEvent) {
  const next = adjacentTab(activeTab.value, event.key);
  if (!next) return;
  event.preventDefault();
  selectTab(next);
  await nextTick();
  document.getElementById(`senior-tab-${next}`)?.focus();
}
async function seeCalendar() {
  selectTab('calendar');
  await nextTick();
  document.getElementById('senior-panel-calendar')?.focus();
}
</script>

<template>
  <div class="senior">
    <ErrorAlert v-if="error" :message="error" @retry="load" />

    <LoadingSpinner v-if="loading" />

    <template v-else-if="person">
      <header class="senior-head">
        <p class="senior-date">{{ formatIsoDay(today, { style: 'long' }) }}</p>
        <h1 class="senior-title">{{ greetingFor(now.getHours()) }}, {{ person.display_name }}</h1>
      </header>

      <!-- Asked first, whichever tab is open: "Are you OK?" before the family is told she has been
           still a long time. -->
      <StillnessPrompt class="mb-4" />

      <nav
        class="senior-tabs nav nav-pills nav-fill rounded-4 p-2 mb-4 shadow-sm"
        role="tablist"
        aria-label="My day sections"
        @keydown="navigateTabs"
      >
        <button
          v-for="tab in tabs"
          :id="`senior-tab-${tab.id}`"
          :key="tab.id"
          type="button"
          role="tab"
          class="nav-link fs-4 fw-semibold d-flex align-items-center justify-content-center gap-2"
          :class="{ active: activeTab === tab.id }"
          :aria-selected="activeTab === tab.id"
          :aria-controls="`senior-panel-${tab.id}`"
          :tabindex="activeTab === tab.id ? 0 : -1"
          @click="selectTab(tab.id)"
        >
          <Icon :name="tab.icon" />{{ tab.label }}
        </button>
      </nav>
      <section
        v-show="activeTab === 'today'"
        id="senior-panel-today"
        role="tabpanel"
        aria-labelledby="senior-tab-today"
        tabindex="0"
      >
        <StepsHero :person="person" :week="week" />
        <div class="row g-4 mt-1">
          <div class="col-lg-5">
            <UpcomingEvents
              :family="family"
              class="h-100 p-4 rounded-4 shadow-sm coming-card"
              @calendar="seeCalendar"
            />
          </div>
          <div class="col-lg-7">
            <SeniorTaskList class="h-100" />
          </div>
        </div>
        <p v-if="thanks" class="thanks mt-4" role="status" data-testid="thanks">
          <Icon name="check" />{{ thanks }}
        </p>
        <SuggestionCard
          v-if="suggestion"
          class="mt-4"
          :suggestion="suggestion"
          :busy="busy"
          @reply="reply"
        />
        <ShareWalkCard id="my-walks" class="mt-4" />
      </section>
      <section
        v-show="activeTab === 'calendar'"
        id="senior-panel-calendar"
        role="tabpanel"
        aria-labelledby="senior-tab-calendar"
        tabindex="0"
      >
        <SeniorCalendar id="my-calendar" />
      </section>
      <section
        v-show="activeTab === 'family'"
        id="senior-panel-family"
        role="tabpanel"
        aria-labelledby="senior-tab-family"
        tabindex="0"
      >
        <MyFamily class="p-4 rounded-4 shadow-sm family-card"><LinkFamily class="mt-4" /></MyFamily>
      </section>

      <!-- 6. Always last: styled as the first line of the site footer just below it. -->
      <p class="senior-footnote d-flex align-items-start gap-2 text-body-secondary">
        <Icon name="info" />
        <span>
          Care+ only suggests something when it might help, and it never books anything for you.
        </span>
      </p>
    </template>
  </div>
</template>

<style scoped>
.senior {
  font-size: 1.2rem;
  overflow-wrap: anywhere;
}
.senior-head {
  margin-bottom: 2rem;
}
.senior-date {
  color: var(--sl-ink-soft);
  margin-bottom: 0.25rem;
  font-weight: 700;
}
.senior-title {
  font-size: clamp(2rem, 5vw, 3.4rem);
  font-weight: 800;
}
.senior-tabs {
  background: var(--sl-surface);
  border: 1px solid var(--sl-line);
}
.senior-tabs .nav-link {
  min-height: 56px;
  color: var(--sl-ink);
  flex: 1 1 0;
}
.senior-tabs .nav-link.active {
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}
.senior-tabs .nav-link:focus-visible,
[role='tabpanel']:focus-visible {
  outline: 3px solid var(--sl-blue-deep);
  outline-offset: 3px;
}
.senior :deep(.senior-cal-nav .btn) {
  min-width: 48px;
  min-height: 48px;
}
.coming-card {
  border-top: 0.35rem solid var(--sl-blue-deep);
}
.family-card {
  border-top: 0.35rem solid var(--sl-purple-deep);
}
.thanks {
  padding: 1rem;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  border-radius: var(--sl-radius);
}
.senior-footnote {
  margin: 2rem 0 0;
  padding: 1.25rem 0;
  border-top: 1px solid var(--sl-line);
  font-size: 1rem;
}
@media (max-width: 767.98px) {
  /* Reserve space after the global footer as well as inside this page. */
  :global(body:has(.senior-tabs)) {
    padding-bottom: calc(6rem + env(safe-area-inset-bottom));
  }
  .senior {
    padding-bottom: calc(7rem + env(safe-area-inset-bottom));
  }
  .senior-tabs {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 1030;
    margin: 0 !important;
    border-radius: 0 !important;
    padding-bottom: calc(0.5rem + env(safe-area-inset-bottom)) !important;
  }
  .senior-tabs .nav-link {
    flex-direction: column;
    gap: 0.15rem !important;
    padding: 0.5rem 0.25rem;
    font-size: 1.1rem !important;
  }
}
</style>
