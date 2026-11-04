<script setup lang="ts">
import type { AppointmentRequest, RepeatRule } from '@silverloop/api-client';
import { ref, useId } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import { NEEDS_HELPER_SAVED, needsHelper } from '@/lib/coverage';
import { checkWindow, KIND_LABELS, REPEAT_LABELS } from '@/lib/family';
import type { Appointment, AppointmentKind, FamilyMember } from '@/lib/family';
import { formatIsoDay } from '@/lib/format-date';

/**
 * Adding an appointment, or editing a one-off one. The day and times are models the calendar
 * shares: while this is open, tapping a day on the calendar picks it, and the calendar shades each
 * day by how many of the family are free at these times. Emits `save` with what the API takes.
 */
const props = defineProps<{
  today: string;
  busy: boolean;
  /** The appointment being edited, or nothing to add a new one. */
  appointment?: Appointment | null;
  /** Who is free on the chosen day at the chosen times. */
  free: FamilyMember[];
  /** How many are in the family. */
  familySize: number;
}>();
/** What the API takes, plus `needs_helper` once the backend has it (see `NEEDS_HELPER_SAVED`). */
type SaveRequest = AppointmentRequest & { needs_helper?: boolean };
const emit = defineEmits<{ save: [appointment: SaveRequest]; cancel: [] }>();
const date = defineModel<string>('date', { required: true });
const start = defineModel<string>('start', { required: true });
const end = defineModel<string>('end', { required: true });

const id = useId();
const editing = props.appointment ?? null;
const title = ref(editing?.title ?? '');
const kind = ref<AppointmentKind>(editing?.kind ?? 'activity');
const location = ref(editing?.location ?? '');
const notes = ref(editing?.notes ?? '');
const repeat = ref<RepeatRule>(editing?.repeat ?? 'none');
const until = ref('');
// "Not every event needs a helper". Shown only once the API saves it (`NEEDS_HELPER_SAVED`).
const helperNeeded = ref(editing ? needsHelper(editing) : true);
const error = ref<string | null>(null);

function submit() {
  error.value = null;
  if (!title.value.trim()) {
    error.value = 'Please give it a name.';
    return;
  }
  const problem = checkWindow({ date: date.value, start: start.value, end: end.value });
  if (problem) {
    error.value = problem;
    return;
  }
  if (repeat.value !== 'none' && until.value && until.value < date.value) {
    error.value = 'The repeat cannot end before the first day.';
    return;
  }
  const request: AppointmentRequest = {
    title: title.value.trim(),
    kind: kind.value,
    date: date.value,
    start: start.value,
    end: end.value,
    location: location.value.trim() || null,
    notes: notes.value.trim() || null,
    repeat: repeat.value,
    repeat_until: repeat.value !== 'none' && until.value ? until.value : null,
  };
  // Only sent once the API has the field, so nothing unknown reaches it before then.
  emit('save', NEEDS_HELPER_SAVED ? { ...request, needs_helper: helperNeeded.value } : request);
}
</script>

<template>
  <form
    class="sl-panel d-grid gap-3"
    aria-labelledby="add-title"
    data-testid="appointment-form"
    @submit.prevent="submit"
  >
    <h2 id="add-title" class="h5 mb-0">{{ editing ? 'Edit' : 'New appointment' }}</h2>
    <div>
      <label :for="`${id}-title`" class="form-label">What</label>
      <input
        :id="`${id}-title`"
        v-model="title"
        class="form-control"
        maxlength="120"
        required
        data-testid="add-title"
      />
    </div>
    <div>
      <span class="form-label d-block">Category</span>
      <div class="kinds" role="radiogroup" aria-label="Category">
        <label
          v-for="(label, value) in KIND_LABELS"
          :key="value"
          class="sl-chip kind-choice"
          :class="`kind-${value}`"
        >
          <input v-model="kind" type="radio" class="visually-hidden" :value="value" />
          <span class="sl-chip-swatch" aria-hidden="true"></span>{{ label }}
        </label>
      </div>
    </div>
    <div class="row g-3">
      <div class="col-12">
        <label :for="`${id}-date`" class="form-label">Date</label>
        <input :id="`${id}-date`" v-model="date" class="form-control" type="date" required />
        <span class="sl-note d-block mt-1">or tap a day on the calendar</span>
      </div>
      <div class="col-6">
        <label :for="`${id}-start`" class="form-label">From</label>
        <input :id="`${id}-start`" v-model="start" class="form-control" type="time" required />
      </div>
      <div class="col-6">
        <label :for="`${id}-end`" class="form-label">To</label>
        <input :id="`${id}-end`" v-model="end" class="form-control" type="time" required />
      </div>
    </div>

    <p class="free mb-0" role="status" data-testid="free-then">
      <template v-if="free.length">
        <span class="free-avatars">
          <MemberAvatar
            v-for="member in free"
            :key="member.id"
            :name="member.name"
            :colour="member.colour"
            size="sm"
          />
        </span>
        <span
          ><strong>{{ free.length }}/{{ familySize }}</strong> free · {{ formatIsoDay(date) }}</span
        >
      </template>
      <span v-else class="text-body-secondary">Nobody free yet · {{ formatIsoDay(date) }}</span>
    </p>

    <div v-if="NEEDS_HELPER_SAVED" class="form-check">
      <input
        :id="`${id}-helper`"
        v-model="helperNeeded"
        class="form-check-input"
        type="checkbox"
        data-testid="needs-helper"
      />
      <label :for="`${id}-helper`" class="form-check-label">Someone needs to go along</label>
    </div>

    <div class="row g-3">
      <div class="col-sm-6">
        <label :for="`${id}-repeat`" class="form-label">Repeats</label>
        <select :id="`${id}-repeat`" v-model="repeat" class="form-select" data-testid="add-repeat">
          <option v-for="(label, value) in REPEAT_LABELS" :key="value" :value="value">
            {{ label }}
          </option>
        </select>
      </div>
      <div v-if="repeat !== 'none'" class="col-sm-6">
        <label :for="`${id}-until`" class="form-label">Until (optional)</label>
        <input :id="`${id}-until`" v-model="until" class="form-control" type="date" />
      </div>
      <div class="col-sm-6">
        <label :for="`${id}-where`" class="form-label">Where (optional)</label>
        <input :id="`${id}-where`" v-model="location" class="form-control" maxlength="160" />
      </div>
      <div class="col-sm-6">
        <label :for="`${id}-notes`" class="form-label">Notes (optional)</label>
        <input :id="`${id}-notes`" v-model="notes" class="form-control" maxlength="1000" />
      </div>
    </div>
    <div v-if="error" class="alert alert-danger mb-0" role="alert">{{ error }}</div>
    <div class="d-flex flex-wrap gap-2">
      <button type="submit" class="btn btn-primary" :disabled="busy">
        {{ editing ? 'Save' : 'Add' }}
      </button>
      <button type="button" class="btn btn-outline-secondary" @click="emit('cancel')">
        Cancel
      </button>
    </div>
  </form>
</template>

<style scoped>
.kinds {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

/* The chosen category is a filled chip in its own colour. */
.kind-choice {
  --chip: var(--kind);
  min-height: 2.4rem;
  cursor: var(--sl-cur-press);
}

.kind-choice:has(input:checked) {
  border-color: var(--kind);
  background: color-mix(in srgb, var(--kind) 14%, var(--sl-surface));
}

.kind-choice:not(:has(input:checked)) .sl-chip-swatch {
  background: transparent;
  box-shadow: inset 0 0 0 2px var(--kind);
}

.kind-choice:has(input:focus-visible) {
  outline: 3px solid var(--sl-jade);
  outline-offset: 2px;
}

.free {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-jade-soft);
}

.free-avatars {
  display: inline-flex;
}

.free-avatars > * + * {
  margin-left: -0.4rem;
  box-shadow: 0 0 0 2px var(--sl-jade-soft);
}
</style>
