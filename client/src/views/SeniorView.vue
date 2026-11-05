<script setup lang="ts">
import type { DailyMetric, Intervention, OutcomeKind, PersonState } from '@silverloop/api-client';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import ErrorAlert from '@/components/ErrorAlert.vue';
import BadgeShelf from '@/components/badges/BadgeShelf.vue';
import SeniorCalendar from '@/components/calendar/SeniorCalendar.vue';
import SeniorTaskList from '@/components/senior/SeniorTaskList.vue';
import LinkFamily from '@/components/senior/LinkFamily.vue';
import MyFamily from '@/components/senior/MyFamily.vue';
import UpcomingEvents from '@/components/senior/UpcomingEvents.vue';
import StepsHero from '@/components/senior/StepsHero.vue';
import ReadMyDay from '@/components/senior/ReadMyDay.vue';
import SuggestionCard from '@/components/senior/SuggestionCard.vue';
import Icon from '@/components/ui/Icon.vue';
import type { IconName } from '@/components/ui/Icon.vue';
import ShareWalkCard from '@/components/walk/ShareWalkCard.vue';
import StillnessPrompt from '@/components/walk/StillnessPrompt.vue';
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue';
import { useAction } from '@/composables/useAction';
import { useBadges } from '@/composables/useBadges';
import { useFamily } from '@/composables/useFamily';
import { loadMe } from '@/composables/useMe';
import { useNow } from '@/composables/useNow';
import { seniorTabBarHeight } from '@/composables/useSeniorTabBar';
import { AUTH_ENABLED } from '@/lib/config';
import { formatIsoDay } from '@/lib/format-date';
import { DEMO_PERSON_ID } from '@/lib/labels';
import { adjacentTab, readTab, saveTab } from '@/lib/senior-view';
import { sectionTabLayout, type SectionTabLook } from '@/lib/tab-rows';
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
// ---- The section bar: whole words at the chosen text size, more rows when they do not fit ----
// On a phone the bar is fixed to the bottom of the screen. Its labels grow with the text size and
// are never shrunk or broken mid-word: when the four tabs no longer fit side by side (icon above
// word), it takes a second row, with each icon beside its word where that fits so the rows stay
// short (`sectionTabLayout`). Its real height goes to `--sl-senior-tabbar-height` on <html>, so
// the page and toasts stay clear of it, and to Kaki (`seniorTabBarHeight`), who sits above it.
const PHONE = '(max-width: 767.98px)';
const tabBar = ref<HTMLElement | null>(null);
const tabFit = ref<{ rows: number; perRow: number; look: SectionTabLook }>({
  rows: 1,
  perRow: tabs.length,
  look: 'stacked',
});
let tabBarObserver: ResizeObserver | null = null;
let fitFrame = 0;
function px(value: string) {
  return parseFloat(value) || 0;
}
function widthOf(el: Element | null) {
  return el ? el.getBoundingClientRect().width : 0;
}
function reportTabBar() {
  const bar = tabBar.value;
  const height =
    bar && getComputedStyle(bar).position === 'fixed'
      ? Math.ceil(bar.getBoundingClientRect().height)
      : 0;
  if (height === seniorTabBarHeight.value) return;
  seniorTabBarHeight.value = height;
  const root = document.documentElement.style;
  if (height) root.setProperty('--sl-senior-tabbar-height', `${height}px`);
  else root.removeProperty('--sl-senior-tabbar-height');
}
function fitTabs() {
  const bar = tabBar.value;
  if (!bar) return;
  const barStyle = getComputedStyle(bar);
  const inside = bar.clientWidth - px(barStyle.paddingLeft) - px(barStyle.paddingRight);
  // Each tab's icon, word and count at their real size, whichever way they are laid out now.
  const measured = [...bar.querySelectorAll<HTMLElement>('.senior-tab-inner')].map((inner) => ({
    icon: widthOf(inner.querySelector('.sl-icon')),
    label: widthOf(inner.querySelector('.senior-tab-label')),
    extra: widthOf(inner.querySelector('.tab-count')),
  }));
  // The gap between icon, word and count is 0.5rem (see `.senior-tab-inner`).
  const gap = px(getComputedStyle(document.documentElement).fontSize) / 2;
  const fit = sectionTabLayout(measured, inside, gap, window.matchMedia?.(PHONE).matches ?? true);
  const now = tabFit.value;
  if (fit.rows !== now.rows || fit.perRow !== now.perRow || fit.look !== now.look) {
    tabFit.value = fit;
  }
  reportTabBar();
}
/** Measures in the next frame, never while the observer is delivering, so it cannot loop. */
function fitSoon() {
  if (fitFrame) return;
  fitFrame = requestAnimationFrame(() => {
    fitFrame = 0;
    fitTabs();
  });
}
// The bar appears once the day has loaded. Watch it, and its words: a new text size changes their
// width even when the bar's own width stays the same.
watch(
  tabBar,
  (bar) => {
    tabBarObserver?.disconnect();
    if (!bar) {
      reportTabBar();
      return;
    }
    fitTabs();
    if (typeof ResizeObserver === 'undefined') return;
    tabBarObserver ??= new ResizeObserver(fitSoon);
    tabBarObserver.observe(bar);
    for (const inner of bar.querySelectorAll('.senior-tab-inner')) tabBarObserver.observe(inner);
  },
  { flush: 'post' },
);
onMounted(() => void document.fonts?.ready.then(fitSoon));
onBeforeUnmount(() => {
  tabBarObserver?.disconnect();
  cancelAnimationFrame(fitFrame);
  seniorTabBarHeight.value = 0;
  document.documentElement.style.removeProperty('--sl-senior-tabbar-height');
});
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
        ref="tabBar"
        class="senior-tabs nav nav-pills nav-fill rounded-4 p-2 mb-4 shadow-sm"
        :class="[`is-${tabFit.look}`, { 'is-rows': tabFit.rows > 1 }]"
        :style="{ '--tab-per-row': tabFit.perRow }"
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
          class="nav-link fs-4 fw-semibold d-flex align-items-center justify-content-center"
          :class="{ active: activeTab === tab.id }"
          :aria-selected="activeTab === tab.id"
          :aria-controls="`senior-panel-${tab.id}`"
          :tabindex="activeTab === tab.id ? 0 : -1"
          @click="selectTab(tab.id)"
        >
          <span class="senior-tab-inner">
            <Icon :name="tab.icon" /><span class="senior-tab-label">{{ tab.label }}</span>
            <span
              v-if="tab.id === 'badges' && readyBadges > 0"
              class="tab-count"
              data-testid="badges-ready-count"
            >
              {{ readyBadges }}<span class="visually-hidden"> ready to claim</span>
            </span>
          </span>
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
        <ReadMyDay :person-id="personId" class="mt-4" />
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
  min-width: 0;
  min-height: 56px;
  color: var(--sl-ink);
  flex: 1 1 0;
}
/* More than one row (see `fitTabs`): tabs of one size, a row's worth each. */
.senior-tabs.is-rows .nav-link {
  flex: 0 0 calc(100% / var(--tab-per-row));
}
/* The icon and the words keep their natural size: never shrunk into the tab, so `fitTabs` measures
   what they really need. */
.senior-tab-inner {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 0.5rem;
}
/* A label is one whole word at the chosen size, never broken across lines. */
.senior-tab-label {
  white-space: nowrap;
  overflow-wrap: normal;
}
.tab-count {
  display: inline-grid;
  place-items: center;
  min-width: 1.6rem;
  height: 1.6rem;
  padding: 0 0.4rem;
  border-radius: 999px;
  background: linear-gradient(135deg, #f8e3a0, #c4953a 55%, #8a6418);
  color: #2e1f03;
  font-size: 0.95rem;
  font-weight: 800;
  line-height: 1;
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
  /* The count floats on the icon's top-right corner, so it never widens its tab. */
  .tab-count {
    position: absolute;
    top: -0.2rem;
    left: calc(50% + 0.55rem);
    min-width: 1.35rem;
    height: 1.35rem;
    font-size: 0.8rem;
  }
  /* The bar's measured height (it grows with the text size and can take two rows) and a little
     room, or the one-row height until it has been measured. */
  :global(body:has(.senior-tabs)) {
    padding-bottom: calc(
      var(--sl-senior-tabbar-height, calc(5rem + env(safe-area-inset-bottom))) + 1rem
    );
  }
  :global(:root:has(.senior-tabs) .sl-toasts) {
    bottom: calc(var(--sl-senior-tabbar-height, 6rem) + 1rem);
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
    position: relative;
    padding: 0.5rem 0.25rem;
    font-size: 1.1rem !important;
    line-height: 1.2;
  }
  .senior-tab-inner {
    position: relative;
    flex-direction: column;
    gap: 0.15rem;
  }
  /* More than one row: the icon beside the word (or the word alone) where that fits, so each row
     is about the 56 px minimum rather than an icon and a word tall. */
  .senior-tabs.is-beside .senior-tab-inner,
  .senior-tabs.is-words .senior-tab-inner {
    flex-direction: row;
    gap: 0.5rem;
  }
  /* Beside the word, the count is a slightly smaller badge (its figure still 0.85rem) on the icon's
     top-right corner. Its right edge stops before the word (the icon is 1.25em of 1.1rem =
     1.375rem wide, then a 0.5rem gap), and a longer count grows leftwards over the icon, never over
     the word. */
  .senior-tabs.is-beside .tab-count {
    top: -0.55rem;
    right: calc(100% - 1.85rem);
    left: auto;
    min-width: 1.25rem;
    height: 1.25rem;
    padding: 0 0.3rem;
    font-size: 0.85rem;
  }
  /* The word alone (a narrow phone at the largest text): no icon, and the count raised just after
     the word, a quarter rem away, like a superscript (the bar leaves room for it; see
     `sectionTabLayout`). The icon is hidden but keeps its size, so `fitTabs` still measures it. */
  .senior-tabs.is-words .senior-tab-inner {
    gap: 0;
  }
  .senior-tabs.is-words .senior-tab-inner > .sl-icon {
    position: absolute;
    visibility: hidden;
  }
  .senior-tabs.is-words .tab-count {
    position: static;
    margin-left: 0.25rem;
    align-self: flex-start;
    transform: translateY(-40%);
  }
}
</style>
