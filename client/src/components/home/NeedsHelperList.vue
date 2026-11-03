<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue';
import { RouterLink } from 'vue-router';

import AskActions from '@/components/family/AskActions.vue';
import AskedTag from '@/components/family/AskedTag.vue';
import AskSomeone from '@/components/family/AskSomeone.vue';
import MemberAvatar from '@/components/family/MemberAvatar.vue';
import Icon from '@/components/ui/Icon.vue';
import { openAskOf } from '@/composables/useAsks';
import {
  KIND_LABELS,
  type Appointment,
  type AvailabilityEntry,
  type FamilyMember,
} from '@/lib/family';
import { capRows } from '@/lib/home';
import { visitWhen } from '@/lib/today';

/**
 * "Needs someone to go along": the coming visits nobody has taken yet, each with its actual day and
 * times. The title opens it in the calendar; "I'll go" takes it from here, without the calendar.
 * Home owns the change (`useFamily().volunteer`), so this only emits. At most five rows show; "See
 * all" opens the calendar filtered to visits that need a helper. When every visit has someone, it
 * says so instead of disappearing.
 *
 * A visit with someone asked stays on the list (it still needs a helper) with an amber "Asked
 * Emily · waiting" tag. The asked member answers here instead of "I'll go"; the asker can withdraw;
 * with nobody asked, "Ask someone" sits beside "I'll go".
 */
const props = defineProps<{
  appointments: Appointment[];
  elder: string;
  /** Whether the viewer is in the group and so can take a visit. If not, no button is shown. */
  canVolunteer: boolean;
  /** The viewer, for the "You're going" moment on the button. */
  helper?: Pick<FamilyMember, 'name' | 'colour'> | null;
  /** For "Ask someone": the group, when each said they are free, and who is looking. */
  members: readonly FamilyMember[];
  availability: readonly AvailabilityEntry[];
  currentMemberId: string | null;
}>();

const emit = defineEmits<{ volunteer: [appointment: Appointment] }>();

const rows = computed(() => capRows(props.appointments));

// "12:00 pm" stays on one line: the time and its am/pm never split, now the buttons beside it leave
// the line less room. Display only; screen readers read the same words.
const whenText = (date: string, start: string, end?: string | null) =>
  visitWhen(date, start, end).replace(/ (am|pm)\b/g, '\u00a0$1');

// Taking a visit removes its row, so focus moves on instead of falling to the page: to the next
// "I'll go" (or the one before), or to the heading when none are left.
const root = ref<HTMLElement | null>(null);
const heading = ref<HTMLElement | null>(null);
/** The visit whose button is showing "You're going" for a moment before its row leaves. */
const going = ref<string | null>(null);
/** How long the button shows "You're going": long enough to read, short enough not to wait on. */
const MORPH_MS = 650;

/** The visit taken but not yet handed to Home, while its button shows "You're going". */
let pending: { item: Appointment; timer: number; done: () => void } | null = null;

/** Hands the taken visit to Home now (the morph is only for the eye; the choice is already made). */
function flush() {
  if (!pending) return;
  const { item, timer, done } = pending;
  pending = null;
  window.clearTimeout(timer);
  emit('volunteer', item);
  done();
}

// Leaving Home during the morph still saves the visit the person took.
onBeforeUnmount(flush);

async function go(item: Appointment, index: number) {
  if (going.value) return;
  // The button turns into the helper's face and "You're going", then the row leaves. With reduced
  // motion the row leaves at once (the toast still says what happened).
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  if (reduced) {
    emit('volunteer', item);
  } else {
    going.value = item.id;
    await new Promise<void>((resolve) => {
      pending = { item, timer: window.setTimeout(flush, MORPH_MS), done: resolve };
    });
  }
  going.value = null;
  await nextTick();
  const buttons = root.value?.querySelectorAll<HTMLButtonElement>('.needs-go') ?? [];
  const next = buttons[index] ?? buttons[index - 1];
  (next ?? heading.value)?.focus();
}
</script>

<template>
  <section
    ref="root"
    data-ask-region
    class="needs sl-panel"
    :class="{ covered: !appointments.length }"
    aria-labelledby="needs-heading"
  >
    <h3
      id="needs-heading"
      ref="heading"
      tabindex="-1"
      data-ask-fallback
      class="h4 d-flex align-items-center gap-2 mb-1 needs-heading"
    >
      <Icon :name="appointments.length ? 'user-plus' : 'check-circle'" class="needs-icon" />
      Needs someone to go along
    </h3>

    <p v-if="!appointments.length" class="mb-0 text-body-secondary">
      Every visit has someone going for the next 2 weeks. Thank you.
    </p>

    <template v-else>
      <p class="mb-3 text-body-secondary">
        {{ appointments.length }}
        {{ appointments.length === 1 ? 'visit still needs' : 'visits still need' }}
        someone in the next 2 weeks
      </p>
      <ul class="needs-list">
        <li
          v-for="(item, index) in rows.shown"
          :key="item.id"
          data-ask-scope
          tabindex="-1"
          class="needs-item"
        >
          <span class="sl-kind-strip" :class="`kind-${item.kind}`" aria-hidden="true"></span>
          <RouterLink
            class="needs-link"
            :to="{ path: '/calendar', query: { appointment: item.id } }"
          >
            <span class="needs-title">{{ item.title }}</span>
            <span class="needs-kind">{{ KIND_LABELS[item.kind] }}</span>
            <span class="needs-when">
              <Icon name="clock" class="me-1" />{{ whenText(item.date, item.start, item.end) }}
            </span>
            <AskedTag
              v-if="openAskOf(item.id)"
              :ask="openAskOf(item.id)!"
              class="needs-asked mt-1"
            />
          </RouterLink>
          <div v-if="canVolunteer" class="needs-actions">
            <button
              v-if="!openAskOf(item.id)?.can_answer"
              type="button"
              class="btn needs-go"
              :class="[
                index === 0 ? 'btn-primary' : 'btn-outline-primary',
                { going: going === item.id },
              ]"
              :aria-label="
                going === item.id
                  ? `You’re going with ${elder} to ${item.title}`
                  : `I’ll go with ${elder} to ${item.title}, ${visitWhen(item.date, item.start, item.end)}`
              "
              :aria-disabled="going === item.id ? 'true' : undefined"
              :data-go="item.id"
              @click="go(item, index)"
            >
              <span v-if="going === item.id" class="going-face" data-testid="needs-going">
                <MemberAvatar
                  v-if="helper"
                  :name="helper.name"
                  :colour="helper.colour"
                  size="sm"
                  class="me-2"
                />
                <span>You’re going</span>
              </span>
              <template v-else><Icon name="user-plus" class="me-1" />I’ll go</template>
            </button>
            <AskActions v-if="openAskOf(item.id)" :ask="openAskOf(item.id)!" :title="item.title" />
            <AskSomeone
              v-else
              :appointment="item"
              :members="members"
              :availability="availability"
              :current-member-id="currentMemberId"
              :helper-ids="[]"
              :elder="elder"
            />
          </div>
        </li>
      </ul>
      <RouterLink
        v-if="rows.hidden"
        class="see-all"
        :to="{ path: '/calendar', query: { help: '1' } }"
        data-testid="needs-see-all"
      >
        See all {{ appointments.length }} on the calendar<Icon name="chevron-right" />
      </RouterLink>
    </template>
  </section>
</template>

<style scoped>
.needs {
  display: flex;
  flex-direction: column;
}

.needs-heading:focus {
  outline: none;
}

.needs-heading:focus-visible {
  outline: 3px solid var(--sl-focus);
  outline-offset: 3px;
}

.needs-icon {
  width: 1.6rem;
  height: 1.6rem;
  flex: none;
  color: var(--sl-coral);
}

.covered .needs-icon {
  color: var(--sl-jade);
}

.needs-list {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* Bootstrap cannot express "the link takes the room, the button keeps its size, and the button
   drops under the link when the row gets too narrow". Rows are split by a rule, not boxed. */
.needs-item {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 0.5rem;
  padding: 0.6rem 0;
  border-top: 1px solid var(--sl-line);
}

.needs-item:first-child {
  border-top: 0;
  padding-top: 0;
}

.needs-link {
  display: flex;
  flex: 1 1 10rem;
  flex-direction: column;
  justify-content: center;
  gap: 0.15rem;
  min-height: 2.75rem;
  padding: 0.25rem 0;
  border-radius: var(--sl-radius-sm);
  color: var(--sl-ink);
  text-decoration: none;
}

.needs-link:hover .needs-title {
  text-decoration: underline;
}

.needs-title {
  font-weight: 700;
}

.needs-kind {
  color: var(--sl-ink-soft);
  font-size: 0.875rem;
  font-weight: 700;
}

/* The tag keeps its own width rather than stretching across the card. */
.needs-asked {
  align-self: flex-start;
}

/* Focus lands on the heading (or a card) after an ask changes the list: no ring on non-controls. */
#needs-heading:focus,
.needs-item:focus {
  outline: none;
}

.needs-when {
  display: inline-flex;
  align-items: center;
  color: var(--sl-ink-soft);
  font-size: 0.95rem;
}

/* "I'll go" with "Ask someone" (or the answer to an ask) beside it; an open "Ask someone" list
   takes a whole row under them. */
.needs-actions {
  display: flex;
  flex: 1 1 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-start;
  align-self: center;
  gap: 0.4rem;
}

.needs-actions :deep(.btn) {
  display: inline-flex;
  align-items: center;
  min-height: 2.75rem;
  font-weight: 700;
}

.needs-go {
  flex: none;
}

/* "You're going": the button fills with the pale jade of a taken visit, and the helper's face fades
   up in place of the icon (CSS @starting-style, 200 ms, strong ease-out). */
.needs-go.going {
  --bs-btn-bg: var(--sl-jade-soft);
  --bs-btn-color: var(--sl-jade-deep);
  --bs-btn-border-color: transparent;
  --bs-btn-hover-bg: var(--sl-jade-soft);
  --bs-btn-hover-color: var(--sl-jade-deep);
  --bs-btn-hover-border-color: transparent;
  --bs-btn-active-bg: var(--sl-jade-soft);
  --bs-btn-active-color: var(--sl-jade-deep);
  cursor: default;
}

.going-face {
  display: inline-flex;
  align-items: center;
  opacity: 1;
  transform: none;
  transition:
    opacity var(--sl-dur-base) ease,
    transform var(--sl-dur-base) var(--sl-ease-out);
}

@starting-style {
  .going-face {
    opacity: 0;
    transform: scale(0.94);
  }
}

.see-all {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  gap: 0.25rem;
  min-height: 2.75rem;
  margin-top: 0.5rem;
  font-weight: 700;
}
</style>
