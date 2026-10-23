<script setup lang="ts">
import type { DailyMetric, Intervention, OutcomeKind, PersonState } from '@silverloop/api-client';
import { computed, onMounted, ref } from 'vue';

import ErrorAlert from '@/components/ErrorAlert.vue';
import SeniorCalendar from '@/components/calendar/SeniorCalendar.vue';
import TaskPanel from '@/components/home/TaskPanel.vue';
import LinkFamily from '@/components/senior/LinkFamily.vue';
import MyFamily from '@/components/senior/MyFamily.vue';
import OutingsList from '@/components/senior/OutingsList.vue';
import SeniorStatus from '@/components/senior/SeniorStatus.vue';
import SuggestionCard from '@/components/senior/SuggestionCard.vue';
import TodayStats from '@/components/senior/TodayStats.vue';
import Icon from '@/components/ui/Icon.vue';
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue';
import { useAction } from '@/composables/useAction';
import { useFamily } from '@/composables/useFamily';
import { loadMe } from '@/composables/useMe';
import { useNow } from '@/composables/useNow';
import { AUTH_ENABLED } from '@/lib/config';
import type { FamilyMember } from '@/lib/family';
import { formatIsoDay } from '@/lib/format-date';
import { DEMO_PERSON_ID } from '@/lib/labels';
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

// Today's outings from the family calendar, and who is going with her.
const { today, appointments, state } = family;
const todays = computed(() => appointments.filter((item) => item.date === today));
function companions(appointmentId: string): FamilyMember[] {
  return family
    .helperIdsOf(appointmentId)
    .map((id) => state.members.find((member) => member.id === id))
    .filter((member): member is FamilyMember => member !== undefined);
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

      <!-- 1. The one status line. -->
      <SeniorStatus id="status" :person="person" :today="today" />

      <Transition name="page">
        <div v-if="thanks" class="thanks mt-4" data-testid="thanks">
          <span class="thanks-mark" aria-hidden="true"><Icon name="check" /></span>
          <span>{{ thanks }}</span>
        </div>
      </Transition>

      <SuggestionCard
        v-if="suggestion"
        class="mt-4"
        :suggestion="suggestion"
        :busy="busy"
        @reply="reply"
      />

      <!-- 2. Today: tasks beside activities (stacked on phones). -->
      <div class="row g-4 mt-1">
        <div class="col-lg-7">
          <TaskPanel id="tasks" :key="personId" :person-id="personId" can-manage />
        </div>

        <div class="col-lg-5 d-grid gap-4 align-content-start">
          <OutingsList
            id="today"
            title="Today’s activities"
            empty-text="Nothing planned today."
            :appointments="todays"
            :today="today"
            :companions-of="companions"
            data-testid="todays-activities"
          />
          <MyFamily />
        </div>
      </div>

      <!-- Full width, so no column is left empty beside a long section. -->
      <SeniorCalendar id="my-calendar" class="mt-4" />
      <TodayStats id="activity" class="mt-4" :person="person" :week="week" :today="today" />
      <LinkFamily id="link-family" class="mt-4" />

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
}

.senior-head {
  margin-bottom: 1.5rem;
}

.senior-date {
  margin-bottom: 0.25rem;
  color: var(--sl-ink-soft);
  font-weight: 700;
}

.senior-title {
  font-size: clamp(2.2rem, 6vw, 3.4rem);
  font-weight: 800;
  letter-spacing: -0.035em;
}

.thanks {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  border-radius: var(--sl-radius);
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-weight: 700;
}

.thanks-mark {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 50%;
  background: var(--sl-jade);
  color: #fff;
  animation: pop 0.4s var(--sl-ease);
}

/*
 * Matches AppLayout's `.site-footer` (a line above, 1.25rem padding, 0.9rem muted text, the same
 * container edge) and pulls down through <main>'s bottom padding (py-4, py-md-5) so it sits right
 * on the footer and the two read as one block.
 */
.senior-footnote {
  margin: 3rem 0 -1.5rem;
  padding: 1.25rem 0;
  border-top: 1px solid var(--sl-line);
  font-size: 0.9rem;
}

.senior-footnote .sl-icon {
  margin-top: 0.1rem;
}

@media (min-width: 768px) {
  .senior-footnote {
    margin-bottom: -3rem;
  }
}

.thanks-mark .sl-icon {
  width: 1.5rem;
  height: 1.5rem;
}

@keyframes pop {
  50% {
    transform: scale(1.15);
  }
}
</style>
