<script setup lang="ts">
import type { DailyMetric, Intervention, OutcomeKind, PersonState } from '@silverloop/api-client';
import { computed, nextTick, onMounted, ref } from 'vue';
import ErrorAlert from '@/components/ErrorAlert.vue';
import BadgeShelf from '@/components/badges/BadgeShelf.vue';
import SeniorCalendar from '@/components/calendar/SeniorCalendar.vue';
import MemberAvatar from '@/components/family/MemberAvatar.vue';
import SeniorTaskList from '@/components/senior/SeniorTaskList.vue';
import LinkFamily from '@/components/senior/LinkFamily.vue';
import MyFamily from '@/components/senior/MyFamily.vue';
import ReadMyDay from '@/components/senior/ReadMyDay.vue';
import UpcomingEvents from '@/components/senior/UpcomingEvents.vue';
import StepsHero from '@/components/senior/StepsHero.vue';
import SuggestionCard from '@/components/senior/SuggestionCard.vue';
import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import ShareWalkCard from '@/components/walk/ShareWalkCard.vue';
import StillnessPrompt from '@/components/walk/StillnessPrompt.vue';
import { useAction } from '@/composables/useAction';
import { useBadges } from '@/composables/useBadges';
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
// Her walking badges: the tab shows how many are waiting to be claimed.
const badges = useBadges(personId);
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
  if (person.value) {
    void loadWeek();
    void badges.load();
  }
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
  { id: 'badges', label: 'Badges', icon: 'star' },
  { id: 'family', label: 'Family', icon: 'users' },
];
const readyBadges = computed(() => badges.readyCount.value);
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

    <!-- Loading: flat bars the size of the greeting and the first two cards, no spinner. -->
    <div v-if="loading">
      <p class="visually-hidden" role="status">Loading your day…</p>
      <div class="senior-head sl-hero-field" aria-hidden="true">
        <span class="sl-skeleton sk-avatar"></span>
        <div class="senior-head-text flex-grow-1">
          <span class="sl-skeleton sk-date"></span>
          <span class="sl-skeleton sk-title"></span>
        </div>
      </div>
      <div class="sl-panel mb-4" aria-hidden="true">
        <span class="sl-skeleton sk-heading"></span>
        <span class="sl-skeleton sk-row"></span>
        <span class="sl-skeleton sk-row"></span>
      </div>
    </div>

    <template v-else-if="person">
      <header class="senior-head sl-hero-field">
        <span class="senior-blob" aria-hidden="true"></span>
        <MemberAvatar :name="person.display_name" colour="senior" size="xl" class="senior-avatar" />
        <div class="senior-head-text">
          <p class="senior-date">{{ formatIsoDay(today, { style: 'long' }) }}</p>
          <h1 class="senior-title">{{ greetingFor(now.getHours()) }}, {{ person.display_name }}</h1>
        </div>
      </header>

      <!-- Asked first, whichever tab is open: "Are you OK?" before the family is told she has been
           still a long time. -->
      <StillnessPrompt class="mb-4" />

      <!-- The same look as the family menu: a pill on a wide screen, a bottom bar on a phone. Still
           tabs (role, arrow keys, the remembered tab), and still before the panels. -->
      <div class="senior-tabs" role="tablist" aria-label="My day sections" @keydown="navigateTabs">
        <button
          v-for="tab in tabs"
          :id="`senior-tab-${tab.id}`"
          :key="tab.id"
          type="button"
          role="tab"
          class="senior-tab"
          :class="{ active: activeTab === tab.id }"
          :aria-selected="activeTab === tab.id"
          :aria-controls="`senior-panel-${tab.id}`"
          :tabindex="activeTab === tab.id ? 0 : -1"
          @click="selectTab(tab.id)"
        >
          <span class="senior-tab-icon"><Icon :name="tab.icon" /></span
          ><span class="senior-tab-label">{{ tab.label }}</span>
          <span
            v-if="tab.id === 'badges' && readyBadges > 0"
            class="tab-count"
            data-testid="badges-ready-count"
          >
            {{ readyBadges }}<span class="visually-hidden"> ready to claim</span>
          </span>
        </button>
      </div>
      <section
        v-show="activeTab === 'today'"
        id="senior-panel-today"
        role="tabpanel"
        aria-labelledby="senior-tab-today"
        tabindex="0"
      >
        <StepsHero :person="person" :week="week" />
        <ReadMyDay :person-id="personId" class="mt-4" />
        <div class="row g-4 mt-1">
          <div class="col-lg-5">
            <UpcomingEvents :family="family" class="h-100" @calendar="seeCalendar" />
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
        v-show="activeTab === 'badges'"
        id="senior-panel-badges"
        role="tabpanel"
        aria-labelledby="senior-tab-badges"
        tabindex="0"
      >
        <BadgeShelf
          :person-id="personId"
          :can-claim="true"
          :senior-name="person.display_name"
          title="My walking badges"
        />
      </section>
      <section
        v-show="activeTab === 'family'"
        id="senior-panel-family"
        role="tabpanel"
        aria-labelledby="senior-tab-family"
        tabindex="0"
      >
        <MyFamily><LinkFamily class="mt-4" /></MyFamily>
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
/* Words break only between words (an over-long word may still wrap rather than overflow). */
.senior {
  font-size: 1.2rem;
  overflow-wrap: break-word;
}
/* The greeting sits on the sun field, like the family's Home hero: the field's own inks, a flat
   paler circle in the corner (decoration), no gradient, no shadow. */
.senior-head {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 1.25rem;
  margin-bottom: 2rem;
  padding: 1.5rem 1.25rem;
  border-radius: var(--sl-radius-lg);
  background: var(--sl-hero);
  color: var(--sl-hero-ink);
  --bs-heading-color: var(--sl-hero-ink);
  --sl-skeleton: var(--sl-hero-line);
}
.senior-blob {
  position: absolute;
  z-index: -1;
  top: -4rem;
  right: -3rem;
  width: 14rem;
  height: 14rem;
  border-radius: 50%;
  background: var(--sl-hero-blob);
  pointer-events: none;
}
@media (min-width: 768px) {
  .senior-head {
    padding: 2rem 2.25rem;
  }
}
.sk-avatar {
  flex: none;
  width: 5.5rem;
  height: 5.5rem;
  border-radius: 50%;
}
.sk-date {
  width: min(14rem, 60%);
  height: 1.2rem;
  margin-bottom: 0.75rem;
}
.sk-title {
  width: min(22rem, 85%);
  height: 2.5rem;
}
.sk-heading {
  width: 45%;
  height: 1.75rem;
  margin-bottom: 1.25rem;
}
.sk-row {
  height: 3.5rem;
  margin-top: 0.75rem;
}
.senior-head-text {
  min-width: 0;
}
/* Phones: the avatar sits above the greeting, so the greeting has the field's full width and its
   words never break (150% zoom included). */
@media (max-width: 575.98px) {
  .senior-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.75rem;
  }
  .senior-head .senior-title {
    font-size: 1.85rem;
  }
  .senior-head .senior-avatar {
    width: 4rem;
    height: 4rem;
    font-size: 1.4rem;
  }
}
.senior-date {
  color: var(--sl-hero-ink-soft);
  margin-bottom: 0.25rem;
  font-weight: 700;
}
.senior-title {
  margin-bottom: 0;
  color: var(--sl-hero-ink);
  font-size: clamp(2rem, 5vw, 3.4rem);
  font-weight: 800;
}
/* Wide screens: one pill holding the tabs, the current one a solid ink pill with light words, as
   in the family menu. Every tab is at least 56px tall. */
.senior-tabs {
  display: flex;
  gap: 0.25rem;
  width: fit-content;
  max-width: 100%;
  margin: 0 auto 1.5rem;
  padding: 0.3rem;
  border: 1px solid var(--sl-glass-border);
  border-radius: 999px;
  background: var(--sl-surface);
}
.senior-tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  min-height: 56px;
  padding: 0.5rem 1.5rem;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--sl-ink);
  font-size: 1.25rem;
  font-weight: 700;
  white-space: nowrap;
  transition:
    background-color var(--sl-dur-base) ease,
    color var(--sl-dur-base) ease;
}
.senior-tab-icon {
  display: inline-flex;
}
.senior-tab-icon .sl-icon {
  width: 1.5rem;
  height: 1.5rem;
}
@media (hover: hover) and (pointer: fine) {
  .senior-tab:hover:not(.active) {
    background: var(--bs-tertiary-bg);
  }
}
.senior-tab.active {
  background: var(--sl-jade);
  color: var(--sl-jade-on);
}
/* Phones: the family's bottom bar, fixed to the bottom edge above the device's safe area: icon
   above the word, the current tab tinted and underlined (shape as well as colour). */
@media (max-width: 767.98px) {
  .senior-tabs {
    position: fixed;
    z-index: var(--sl-nav-z);
    right: 0;
    bottom: 0;
    left: 0;
    width: auto;
    margin: 0;
    padding: 0.25rem 0.5rem calc(0.25rem + env(safe-area-inset-bottom, 0px));
    border: 0;
    border-top: 1px solid var(--sl-glass-border);
    border-radius: 0;
    background: var(--sl-glass-bg);
    -webkit-backdrop-filter: var(--sl-glass-filter);
    backdrop-filter: var(--sl-glass-filter);
    box-shadow: var(--sl-elev-2);
  }
  .senior-tab {
    flex: 1 1 0;
    flex-direction: column;
    gap: 0.1rem;
    min-width: 0;
    padding: 0.3rem 0.25rem;
    border-radius: var(--sl-radius-sm);
    font-size: 0.95rem;
  }
  .senior-tab.active {
    background: var(--sl-jade-soft);
    color: var(--sl-ink);
    box-shadow: inset 0 -3px 0 var(--sl-jade);
  }
  .tab-count {
    position: absolute;
    top: 0.15rem;
    right: calc(50% - 1.9rem);
  }
}
.tab-count {
  display: inline-grid;
  place-items: center;
  min-width: 1.6rem;
  height: 1.6rem;
  padding: 0 0.4rem;
  border-radius: 999px;
  background: var(--sl-sun);
  color: var(--sl-hero-ink);
  font-size: 0.95rem;
  font-weight: 800;
  line-height: 1;
}
.senior-tab:focus-visible,
[role='tabpanel']:focus-visible {
  outline: 3px solid var(--sl-focus);
  outline-offset: 3px;
}
.senior :deep(.senior-cal-nav .btn) {
  min-width: 48px;
  min-height: 48px;
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
  /* Room inside the page for the bottom tab bar (the layout keeps room under its footer too). */
  .senior {
    padding-bottom: 2rem;
  }
}
</style>
