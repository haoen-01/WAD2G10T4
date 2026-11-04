<script setup lang="ts">
import { computed, ref } from 'vue';

import CheckInActions from '@/components/walk/CheckInActions.vue';
import Icon from '@/components/ui/Icon.vue';
import { useWalk, type AlertStatus, type WalkAlert } from '@/composables/useWalk';
import { LIMIT_CHOICES_MIN, limitWords, MINUTE_MS } from '@/lib/stillness';
import { clockTime, formatDuration } from '@/lib/walk';

/**
 * The "Still for a while" check-in on the Walk page: what it is watching, when the family would be
 * told, the family's limit, notifications on this device, and today's alerts and how each ended.
 */
const walk = useWalk();
const name = walk.seniorName;
const notifyProblem = ref<string | null>(null);
const canNotify = typeof Notification !== 'undefined';

const line = computed(() => {
  const result = walk.stillness.value;
  if (result.kind === 'none') return 'Watching for long stops away from home.';
  if (result.kind === 'no_signal') {
    return 'No readings from the watch, so no check-in until it is back in signal.';
  }
  switch (result.quietBecause) {
    case 'home':
      return 'At home. There are no check-ins at home.';
    case 'usual_place':
      return `At ${result.quietLabel}, where long stays are normal.`;
    case 'appointment':
      return `Probably at ${result.quietLabel} (on the calendar now).`;
    case 'dismissed':
      return 'Marked fine for this stop.';
    default:
      break;
  }
  if (result.forMs < 5 * MINUTE_MS) return 'On the move. No long stops.';
  const stay = `In one place for ${formatDuration(result.forMs)}.`;
  if (result.phase === 'alert') return `${stay} The family has been told.`;
  if (result.phase === 'soon') {
    return `${stay} ${name.value} is being asked if they are OK. The family will be told at ${clockTime(result.alertAt ?? 0)}.`;
  }
  return `${stay} The family will be told at ${clockTime(result.alertAt ?? 0)} if ${name.value} is still there.`;
});

const OUTCOMES: Record<AlertStatus, (alert: WalkAlert) => string> = {
  open: () => 'Waiting for someone to check in',
  checking: (alert) => `${alert.checkingBy} is checking in`,
  ok: (alert) => `${alert.closedBy} said they are OK, ${clockTime(alert.closedAt ?? 0)}`,
  fine: (alert) => `${alert.closedBy} marked ${name.value} fine, ${clockTime(alert.closedAt ?? 0)}`,
  moved: (alert) => `${name.value} moved on, ${clockTime(alert.closedAt ?? 0)}`,
  stopped: () => 'Check-ins were turned off',
};

function changeLimit(event: Event) {
  walk.setLimit(Number((event.target as HTMLSelectElement).value));
}

async function toggleNotify() {
  notifyProblem.value = null;
  if (walk.settings.notify) {
    walk.disableNotifications();
    return;
  }
  const on = await walk.enableNotifications();
  if (!on) {
    notifyProblem.value =
      'The browser did not allow notifications. You can allow them in its site settings. The banner still shows.';
  }
}
</script>

<template>
  <section class="sl-panel checkin-panel" aria-labelledby="checkin-heading">
    <h2 id="checkin-heading" class="h5 d-flex align-items-center gap-2 mb-2">
      <Icon name="bell" /> Still for a while
    </h2>

    <template v-if="!walk.settings.stillnessAlerts">
      <p class="mb-0" data-testid="checkin-off">
        {{ name }} has not turned on check-ins. Only they can, on their own page (“Tell my family if
        I stay in one place for a long time”).
      </p>
    </template>

    <template v-else>
      <p class="mb-3" data-testid="checkin-line">{{ line }}</p>

      <div v-if="walk.openAlert.value" class="checkin-now mb-3">
        <p class="fw-bold mb-2">{{ walk.alertWords(walk.openAlert.value) }}</p>
        <CheckInActions :alert="walk.openAlert.value" :show-map="false" />
      </div>

      <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
        <label for="still-limit" class="form-label mb-0">Tell the family after</label>
        <select
          id="still-limit"
          class="form-select w-auto"
          data-testid="still-limit"
          :value="walk.settings.limitMin"
          @change="changeLimit"
        >
          <option v-for="minutes in LIMIT_CHOICES_MIN" :key="minutes" :value="minutes">
            {{ limitWords(minutes * MINUTE_MS) }}
          </option>
        </select>
        <span class="sl-note">in one place, away from home</span>
      </div>

      <div v-if="canNotify" class="mb-2">
        <button
          type="button"
          class="btn btn-quiet btn-sm"
          :aria-pressed="walk.settings.notify"
          data-testid="checkin-notify"
          @click="toggleNotify"
        >
          <Icon name="bell" />
          {{
            walk.settings.notify
              ? 'Notifications on for this device. Turn off'
              : 'Also notify me on this device'
          }}
        </button>
        <p v-if="notifyProblem" class="sl-note mt-1 mb-0" role="status">{{ notifyProblem }}</p>
      </div>
    </template>

    <template v-if="walk.alerts.length">
      <h3 class="h6 mt-3 mb-2">Check-ins today</h3>
      <ul class="checkin-log list-unstyled mb-0" data-testid="checkin-log">
        <li v-for="alert in walk.alerts" :key="alert.id">
          <span class="fw-bold tabular">{{ clockTime(alert.raisedAt) }}</span>
          near {{ alert.place }}:
          <span>{{ OUTCOMES[alert.status](alert) }}</span>
        </li>
      </ul>
    </template>

    <p class="sl-note checkin-boundary mt-3 mb-0">
      This only notices how long {{ name }} stays in one place. It does not detect falls or
      emergencies, and it never contacts anyone by itself. In an emergency, call 995.
    </p>
  </section>
</template>

<style scoped>
.checkin-now {
  padding: 0.85rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-sun-soft);
  box-shadow: inset 4px 0 0 var(--sl-sun);
}

.checkin-log li {
  padding: 0.4rem 0;
  border-top: 1px solid var(--sl-line);
}

.checkin-boundary {
  padding-top: 0.75rem;
  border-top: 1px dashed var(--sl-line);
}
</style>
