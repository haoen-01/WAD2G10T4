<script setup lang="ts">
import { computed } from 'vue';

import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import type { useFamily } from '@/composables/useFamily';
import { useNow } from '@/composables/useNow';
import { needsHelper } from '@/lib/coverage';
import { KIND_LABELS, type Appointment, type FamilyMember } from '@/lib/family';
import { formatClockTime, formatIsoDay, parseIsoDay, WEEKDAYS_SHORT } from '@/lib/format-date';
import { upcomingEvents } from '@/lib/senior-upcoming';

// Read the parent's shared calendar without starting another request.
const props = defineProps<{ family: ReturnType<typeof useFamily> }>();
defineEmits<{ calendar: [] }>();
const now = useNow();
const events = computed(() => {
  const clock = `${String(now.value.getHours()).padStart(2, '0')}:${String(now.value.getMinutes()).padStart(2, '0')}`;
  const upcoming: Appointment[] = upcomingEvents(
    props.family.appointments,
    props.family.today,
    clock,
  );
  return upcoming.map((item) => {
    const helpers = props.family
      .helperIdsOf(item.id)
      .map((id) => props.family.state.members.find((member) => member.id === id))
      .filter((member): member is FamilyMember => member !== undefined);
    const names = helpers.map((member) => member.name);
    const companion =
      names.length === 1
        ? `${names[0]} is coming with you`
        : names.length > 1
          ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)} are coming with you`
          : needsHelper(item)
            ? 'Family is arranging who comes'
            : '';
    const date = parseIsoDay(item.date);
    return {
      ...item,
      companion,
      initial: names[0]?.trim().slice(0, 1).toLocaleUpperCase() ?? '',
      fullDate: formatIsoDay(item.date, { style: 'long' }),
      weekday: date ? WEEKDAYS_SHORT[date.weekday].toUpperCase() : '',
      dayNumber: date?.day ?? '',
      startLabel: formatClockTime(item.start),
      endLabel: formatClockTime(item.end),
      place: item.location
        ? `${KIND_LABELS[item.kind]} at ${item.location}`
        : KIND_LABELS[item.kind],
    };
  });
});
const firstLoad = computed(() => props.family.loading.value && !props.family.loaded.value);
const unavailable = computed(() => Boolean(props.family.error.value) && !props.family.loaded.value);
</script>

<template>
  <BasePanel heading-class="fs-3 d-flex align-items-center gap-2">
    <template #title><Icon name="calendar" />Next up</template>
    <p v-if="firstLoad" class="fs-5" role="status">Loading your plans...</p>
    <p v-else-if="unavailable" class="fs-5">Your plans can't be shown right now.</p>
    <p v-else-if="!events.length" class="fs-5 my-4">
      Nothing planned this week. When your family adds a visit, it shows here.
    </p>
    <ul v-else class="list-unstyled my-3" data-testid="upcoming-events">
      <li v-for="event in events" :key="event.id" class="event-box d-flex align-items-start gap-3">
        <!-- The kind's colour strip; the kind is also written out under the title. -->
        <span class="sl-kind-strip" :class="`kind-${event.kind}`" aria-hidden="true"></span>
        <time
          :datetime="event.date"
          :aria-label="event.fullDate"
          class="date-block rounded-3 text-center"
        >
          <span class="d-block fw-bold date-weekday" aria-hidden="true">{{ event.weekday }}</span>
          <span class="d-block fs-3 fw-bold lh-1 mt-1" aria-hidden="true">{{
            event.dayNumber
          }}</span>
        </time>
        <div class="event-content">
          <p class="event-time d-flex flex-wrap gap-1 fw-bold mb-1">
            <span>{{ event.startLabel }}</span
            ><span aria-hidden="true">&ndash;</span><span class="visually-hidden">to</span
            ><span>{{ event.endLabel }}</span>
          </p>
          <h3 class="fs-5 mb-2">{{ event.title }}</h3>
          <p class="event-place d-flex align-items-start gap-1 text-body-secondary mb-2">
            <Icon :name="event.kind" class="mt-1" /><span>{{ event.place }}</span>
          </p>
          <span
            v-if="event.companion"
            class="companion-pill d-inline-flex align-items-start gap-2 rounded-pill px-2 py-1"
          >
            <span
              v-if="event.initial"
              class="companion-initial rounded-circle fw-bold"
              aria-hidden="true"
              >{{ event.initial }}</span
            >
            <Icon v-else name="users" class="mt-1" />
            <span>{{ event.companion }}</span>
          </span>
        </div>
      </li>
    </ul>
    <button
      type="button"
      class="btn btn-link btn-lg mt-2 text-start calendar-button"
      @click="$emit('calendar')"
    >
      See my calendar <span aria-hidden="true">&rarr;</span>
    </button>
  </BasePanel>
</template>

<style scoped>
/* Rows split by a rule, not boxed, so the words keep the panel's full width. */
.event-box {
  min-width: 0;
  padding: 1rem 0;
  border-top: 1px solid var(--sl-line);
}
.event-box:first-child {
  border-top: 0;
  padding-top: 0.25rem;
}
/* The date chip fits its widest weekday ("WED") and never breaks it. */
.date-block {
  flex: none;
  min-width: 3.5rem;
  padding: 0.5rem 0.6rem;
  background: var(--sl-blue-soft);
  color: var(--sl-blue-deep);
  white-space: nowrap;
}
.date-weekday {
  font-size: 0.85rem;
  letter-spacing: 0.02em;
}
.event-content {
  flex: 1;
  min-width: 0;
  overflow-wrap: break-word;
}
.event-time,
.event-place,
.companion-pill {
  font-size: 1rem;
}
.event-time > span {
  white-space: nowrap;
}
.event-place .sl-icon {
  flex-shrink: 0;
}
.companion-pill {
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  line-height: 1.5;
}
.companion-initial {
  flex: 0 0 1.5rem;
  min-height: 1.5rem;
  text-align: center;
  background: var(--sl-surface);
}
.calendar-button {
  min-height: 48px;
}
/* Narrow (a phone at 150% zoom): the words drop under the date chip rather than squeeze. */
@media (max-width: 575.98px) {
  .event-box {
    flex-wrap: wrap;
    gap: 0.6rem !important;
  }
  .event-content {
    flex: 1 1 12rem;
  }
}
</style>
