<script setup lang="ts">
import { computed, nextTick, ref, useId } from 'vue';
import { RouterLink } from 'vue-router';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import Icon from '@/components/ui/Icon.vue';
import { askMember, focusAfterAsk } from '@/composables/useAsks';
import { useNow } from '@/composables/useNow';
import { askCandidates, canStillAsk } from '@/lib/asks';
import type { Appointment, AvailabilityEntry, FamilyMember } from '@/lib/family';

/**
 * "Ask someone": for a day that needs a helper and has nobody asked yet. The button opens a short
 * list of the other members, each with when they said they are free that day, and an "Ask" button.
 * It opens in place (a disclosure, not a dialog), so it works the same inside the phone's bottom
 * sheet, on Home and on the timeline: Tab walks through it, Escape closes it and puts focus back
 * on the button. Asking goes through `useAsks`, which re-reads the screens and shows any refusal.
 */
const props = defineProps<{
  appointment: Appointment;
  members: readonly FamilyMember[];
  availability: readonly AvailabilityEntry[];
  currentMemberId: string | null;
  helperIds: readonly string[];
  /** The senior's name, for the button's full name. */
  elder?: string;
  /** A smaller button, beside an "I'll go" that is small too. */
  small?: boolean;
}>();

const open = ref(false);
const busy = ref(false);
const toggle = ref<HTMLButtonElement | null>(null);
const panelId = `ask-${useId()}`;

const candidates = computed(() =>
  askCandidates(props.members, props.availability, props.appointment, {
    currentMemberId: props.currentMemberId,
    helperIds: props.helperIds,
  }),
);

function close() {
  open.value = false;
  void nextTick(() => toggle.value?.focus());
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    // Only this list closes, not a sheet or panel around it.
    event.stopPropagation();
    close();
  }
}

async function ask(event: Event, member: FamilyMember) {
  if (busy.value) return;
  busy.value = true;
  // On success this list is replaced by the ask's tag and Withdraw: focus moves there.
  const refocus = focusAfterAsk(event.currentTarget as Element | null);
  let asked = false;
  try {
    asked = await askMember(props.appointment.id, { id: member.id, name: member.name });
  } finally {
    busy.value = false;
  }
  if (asked) {
    open.value = false;
    await refocus();
  }
}

// Once the day has started the API refuses an ask, so the button goes (checked every 30 s).
const now = useNow();
const askable = computed(() => canStillAsk(props.appointment, now.value));
</script>

<template>
  <div v-if="askable" class="ask" :class="{ 'is-open': open }" @keydown="onKeydown">
    <button
      ref="toggle"
      type="button"
      class="btn btn-outline-primary ask-toggle"
      :class="{ 'btn-sm': small }"
      :aria-expanded="open"
      :aria-controls="panelId"
      :aria-label="`Ask someone to go${elder ? ` with ${elder}` : ''} to ${appointment.title}`"
      data-testid="ask-someone"
      data-ask-focus
      @click="open = !open"
    >
      <Icon name="hand" class="me-1" />Ask someone
    </button>

    <div v-if="open" :id="panelId" class="ask-panel" role="group" aria-label="Who to ask">
      <p class="ask-hint mb-2">Ask one person by name. They can say yes or no from their bell.</p>
      <ul v-if="candidates.length" class="ask-list">
        <li v-for="candidate in candidates" :key="candidate.member.id" class="ask-row">
          <MemberAvatar :name="candidate.member.name" :colour="candidate.member.colour" size="sm" />
          <span class="ask-who">
            <strong class="d-block">{{ candidate.member.name }}</strong>
            <span
              class="ask-note"
              :class="{
                free: candidate.status === 'available',
                busy: candidate.status === 'unavailable',
              }"
              >{{ candidate.note }}</span
            >
          </span>
          <button
            type="button"
            class="btn btn-primary btn-sm ask-pick"
            :disabled="busy"
            :aria-label="`Ask ${candidate.member.name} to go to ${appointment.title}`"
            @click="ask($event, candidate.member)"
          >
            Ask
          </button>
        </li>
      </ul>
      <p v-else class="mb-2">
        There is no one else to ask yet.
        <RouterLink to="/family">Invite family</RouterLink>
      </p>
      <button type="button" class="btn btn-link btn-sm px-0" @click="close">Cancel</button>
    </div>
  </div>
</template>

<style scoped>
.ask {
  display: contents;
}

/* Open, the list takes a whole row under the buttons beside it. */
.ask-panel {
  flex: 1 1 100%;
  width: 100%;
  margin-top: 0.25rem;
  padding: 0.75rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
  text-align: left;
}

.ask-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.ask-hint {
  color: var(--sl-ink-soft);
  font-size: 0.875rem;
}

.ask-list {
  display: grid;
  gap: 0.4rem;
  margin: 0 0 0.25rem;
  padding: 0;
  list-style: none;
}

.ask-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.35rem 0.25rem;
}

.ask-who {
  flex: 1 1 auto;
  min-width: 0;
  line-height: 1.3;
}

.ask-note {
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
}

.ask-note.free {
  color: var(--sl-jade-deep);
  font-weight: 600;
}

.ask-pick {
  flex: none;
  min-width: 4rem;
  min-height: 2.5rem;
  font-weight: 700;
}
</style>
