<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

import AppointmentNotes from '@/components/calendar/AppointmentNotes.vue';
import AssignmentList from '@/components/calendar/AssignmentList.vue';
import KindBadge from '@/components/calendar/KindBadge.vue';
import AskActions from '@/components/family/AskActions.vue';
import AskedTag from '@/components/family/AskedTag.vue';
import AskSomeone from '@/components/family/AskSomeone.vue';
import Icon from '@/components/ui/Icon.vue';
import { openAskOf } from '@/composables/useAsks';
import { showToast } from '@/composables/useToast';
import { needsHelper } from '@/lib/coverage';
import { REPEAT_LABELS } from '@/lib/family';
import type {
  Appointment,
  AvailabilityEntry,
  AvailabilityStatus,
  FamilyMember,
  MemberStatus,
} from '@/lib/family';
import { formatClockTime, formatIsoDay } from '@/lib/format-date';
import { appointmentToIcs, icsFileName, shareText } from '@/lib/ics';
import { relativeDay } from '@/lib/today';

const props = defineProps<{
  appointment: Appointment;
  members: FamilyMember[];
  helperIds: string[];
  statuses: Record<string, MemberStatus>;
  /** Who is using the screen, or `null` before anyone has joined. */
  currentMember: FamilyMember | null;
  elderName: string;
  today: string;
  /** The care group, for the family notes. Without it (or a member) the notes are left out. */
  groupId?: string | null;
  /** Inside the phone's bottom sheet: the sheet has its own close button, and no card frame. */
  sheet?: boolean;
  /** When each member said they are free, for "Ask someone". */
  availability?: AvailabilityEntry[];
}>();

// The open ask for this day, if someone has been asked and not answered. It only counts while
// nobody is going (the API closes it when someone says "I'll go").
const ask = computed(() => (props.helperIds.length === 0 ? openAskOf(props.appointment.id) : null));
defineEmits<{
  back: [];
  volunteer: [];
  'step-back': [];
  respond: [status: AvailabilityStatus];
  remove: [];
  edit: [];
}>();

// A repeating appointment's last day is not on the calendar, so only a one-off one is edited here.
const canEdit = computed(() => !props.appointment.repeat || props.appointment.repeat === 'none');

const isHelping = computed(
  () => props.currentMember !== null && props.helperIds.includes(props.currentMember.id),
);
const myStatus = computed<MemberStatus>(() =>
  props.currentMember ? (props.statuses[props.currentMember.id] ?? 'unknown') : 'unknown',
);
const helperNames = computed(() =>
  props.helperIds
    .map((id) => props.members.find((member) => member.id === id)?.name)
    .filter((name): name is string => name !== undefined),
);

// A short reading of who is going. Avoids the word used by the "Helping" badges in the list below,
// so the list stays the one place that says who has taken it.
const coverage = computed(() => {
  const names = helperNames.value;
  if (names.length === 0 && !needsHelper(props.appointment)) return 'No one needs to go along.';
  if (names.length === 0 && ask.value) return 'Nobody is going yet. Someone has been asked.';
  if (names.length === 0) return 'Nobody has said they will go yet.';
  if (names.length === 1) return `${names[0]} is going with ${props.elderName}.`;
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1)} are going with ${props.elderName}.`;
});

// A screen reader user who chose an appointment should land on what they chose.
const heading = ref<HTMLElement | null>(null);
onMounted(() => heading.value?.focus());
watch(
  () => props.appointment.id,
  () => heading.value?.focus(),
);

/** Saves a calendar file that any phone or email calendar can open. */
function addToCalendar() {
  const text = appointmentToIcs(props.appointment, props.elderName, helperNames.value);
  const url = URL.createObjectURL(new Blob([text], { type: 'text/calendar;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = icsFileName(props.appointment, props.elderName);
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  showToast('Calendar file saved. Open it to add this to your own calendar.');
}

/** The phone's share sheet where there is one, otherwise a copy for pasting into a family chat. */
async function share() {
  const text = shareText(props.appointment, props.elderName, helperNames.value);
  if (typeof navigator.share === 'function') {
    try {
      await navigator.share({ title: `${props.elderName}: ${props.appointment.title}`, text });
      return;
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return;
    }
  }
  try {
    await navigator.clipboard.writeText(text);
    showToast('Details copied. Paste them into your family chat.');
  } catch {
    showToast('Copying is blocked in this browser. Select the details and copy them instead.');
  }
}
</script>

<template>
  <article
    class="details"
    data-ask-scope
    data-ask-region
    :class="[`kind-${appointment.kind}`, { 'in-sheet': sheet }]"
    aria-labelledby="details-heading"
  >
    <div class="details-top">
      <button v-if="!sheet" type="button" class="btn btn-quiet back" @click="$emit('back')">
        <Icon name="chevron-left" class="me-1" />Back
      </button>
      <KindBadge :kind="appointment.kind" />
    </div>

    <p class="details-when-chip">{{ relativeDay(appointment.date, today) }}</p>
    <h2 id="details-heading" ref="heading" tabindex="-1" class="details-title">
      {{ appointment.title }}
    </h2>

    <dl class="facts">
      <div class="fact">
        <dt><Icon name="clock" /><span class="visually-hidden">When</span></dt>
        <dd>
          <span class="d-block fw-bold">{{
            formatIsoDay(appointment.date, { style: 'long' })
          }}</span>
          {{ formatClockTime(appointment.start) }} to {{ formatClockTime(appointment.end) }}
          <span v-if="appointment.repeat && appointment.repeat !== 'none'" class="d-block">
            {{ REPEAT_LABELS[appointment.repeat] }}
          </span>
        </dd>
      </div>
      <div v-if="appointment.location" class="fact">
        <dt><Icon name="pin" /><span class="visually-hidden">Where</span></dt>
        <dd>{{ appointment.location }}</dd>
      </div>
      <div v-if="appointment.notes" class="fact">
        <dt><Icon name="note" /></dt>
        <dd>
          <span class="d-block fw-bold">Details</span>
          {{ appointment.notes }}
        </dd>
      </div>
    </dl>

    <div class="take-away">
      <button type="button" class="btn btn-outline-secondary" @click="addToCalendar">
        <Icon name="calendar-plus" class="me-2" />Add to my calendar
      </button>
      <button type="button" class="btn btn-outline-secondary" @click="share">
        <Icon name="share" class="me-2" />Share these details
      </button>
    </div>

    <hr class="my-4" />

    <h3 class="h5 mb-1">Who is helping?</h3>
    <!-- Focus comes here after an ask control replaces itself and nothing else takes its place. -->
    <p
      class="coverage"
      :class="{
        open: helperNames.length === 0 && needsHelper(appointment) && !ask,
        asked: !!ask,
      }"
      tabindex="-1"
      data-ask-fallback
    >
      <Icon :name="helperNames.length ? 'check-circle' : 'user-plus'" class="me-2" />{{ coverage }}
    </p>
    <p v-if="ask" class="mb-3">
      <AskedTag :ask="ask" />
    </p>
    <AssignmentList
      :members="members"
      :helper-ids="helperIds"
      :statuses="statuses"
      :current-member-id="currentMember?.id ?? null"
      :asked-member-id="ask?.asked_member_id ?? null"
    />

    <div v-if="currentMember" class="mt-4">
      <template v-if="isHelping">
        <p class="alert alert-success d-flex align-items-center gap-2" role="status">
          <Icon name="check-circle" />
          <span>
            You’re helping with this, {{ currentMember.name }}. Everyone in the group can see it.
          </span>
        </p>
        <button type="button" class="btn btn-outline-primary" @click="$emit('step-back')">
          Step back
        </button>
      </template>
      <template v-else>
        <!-- Asked by name: answer the ask (a yes makes you the helper) instead of "I'll help". -->
        <div v-if="ask?.can_answer" class="ask-answer">
          <AskActions :ask="ask" :title="appointment.title" />
        </div>
        <button
          v-else
          type="button"
          class="btn btn-primary btn-lg w-100"
          @click="$emit('volunteer')"
        >
          <Icon name="user-plus" class="me-2" />I’ll help
        </button>
        <!-- Nobody asked yet: ask one person by name. You asked: you can take it back. -->
        <div v-if="ask?.can_withdraw" class="ask-more">
          <AskActions :ask="ask" :title="appointment.title" />
        </div>
        <div
          v-else-if="!ask && helperNames.length === 0 && needsHelper(appointment)"
          class="ask-more"
        >
          <AskSomeone
            :appointment="appointment"
            :members="members"
            :availability="availability ?? []"
            :current-member-id="currentMember.id"
            :helper-ids="helperIds"
            :elder="elderName"
          />
        </div>
        <p class="mt-3 mb-2 text-body-secondary">Not sure yet? Let the family know:</p>
        <div class="answer" role="group" aria-label="Your availability for this appointment">
          <button
            type="button"
            class="btn"
            :class="myStatus === 'available' ? 'btn-primary' : 'btn-outline-primary'"
            :aria-pressed="myStatus === 'available'"
            @click="$emit('respond', 'available')"
          >
            I’m available
          </button>
          <button
            type="button"
            class="btn"
            :class="myStatus === 'unavailable' ? 'btn-primary' : 'btn-outline-primary'"
            :aria-pressed="myStatus === 'unavailable'"
            @click="$emit('respond', 'unavailable')"
          >
            I can’t make it
          </button>
        </div>
      </template>
    </div>
    <p v-else class="mt-4 mb-0 text-body-secondary">
      <RouterLink to="/family">Join the family group</RouterLink> to help with this.
    </p>

    <template v-if="groupId && currentMember && appointment.seriesId">
      <hr class="my-4" />
      <AppointmentNotes
        :key="appointment.id"
        :group-id="groupId"
        :appointment-id="appointment.seriesId"
        :date="appointment.date"
        :members="members"
      />
    </template>

    <div v-if="currentMember" class="mt-4 pt-3 border-top d-flex gap-2">
      <button
        v-if="canEdit"
        type="button"
        class="btn btn-outline-primary"
        data-testid="edit-appointment"
        @click="$emit('edit')"
      >
        Edit
      </button>
      <button
        type="button"
        class="btn btn-outline-danger ms-auto"
        data-testid="remove-appointment"
        @click="$emit('remove')"
      >
        Delete
      </button>
    </div>
  </article>
</template>

<style scoped>
.details {
  padding: 1.25rem;
  border: 1px solid var(--sl-line);
  border-top: 6px solid var(--kind, var(--sl-jade));
  border-radius: var(--sl-radius);
  background: var(--sl-surface);
}

@media (min-width: 768px) {
  .details {
    padding: 1.5rem;
  }
}

/* In the bottom sheet the sheet is the card: no frame of its own, and the kind's colour moves up. */
.details.in-sheet {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.details.in-sheet .details-top {
  justify-content: flex-start;
  margin: 0 0 0.5rem;
}

.details-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin: -0.5rem -0.5rem 0.75rem;
}

.back {
  --bs-btn-padding-x: 0.6rem;
}

.details-when-chip {
  display: inline-block;
  margin-bottom: 0.4rem;
  padding: 0.15rem 0.7rem;
  border-radius: 999px;
  background: var(--sl-sun-soft);
  font-size: 0.9rem;
  font-weight: 700;
}

.details-title {
  margin-bottom: 1rem;
  font-size: 1.7rem;
  font-weight: 800;
}

.details-title:focus {
  outline: none;
}

.facts {
  display: grid;
  gap: 0.75rem;
  margin: 0;
}

.fact {
  display: flex;
  gap: 0.75rem;
}

.fact dt {
  flex: none;
  padding-top: 0.1rem;
  color: var(--sl-ink-soft);
}

.fact dd {
  margin: 0;
}

.take-away {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 1.25rem;
}

.coverage {
  display: flex;
  align-items: center;
  margin-bottom: 0.75rem;
  color: var(--sl-jade-deep);
  font-weight: 600;
}

.coverage.open {
  color: var(--sl-coral-deep);
}

/* Asked and waiting: amber like the tag under it, not the coral of "nobody yet". */
.coverage.asked {
  color: var(--sl-sun-deep);
}

.coverage:focus {
  outline: none;
}

/* The asked member's two answers, side by side and as big as "I'll help". */
.ask-answer {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}

.ask-answer :deep(.btn) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 3rem;
  font-weight: 700;
}

.ask-more {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.answer {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}
</style>
