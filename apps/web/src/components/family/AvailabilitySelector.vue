<script setup lang="ts">
import { computed, ref, useId } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { addDays } from '@/lib/calendar';
import { DAY_PARTS, checkWindow } from '@/lib/family';
import type { AvailabilityStatus } from '@/lib/family';
import { WEEKDAYS_LONG, WEEKDAYS_SHORT, parseIsoDay } from '@/lib/format-date';

const props = defineProps<{ minDate: string }>();
const emit = defineEmits<{
  save: [window: { date: string; start: string; end: string; status: AvailabilityStatus }];
}>();

const dateId = useId();
const partId = useId();
const startId = useId();
const endId = useId();

const CUSTOM = 'custom';

const date = ref('');
const part = ref<string>(DAY_PARTS[0].key);
const start = ref('09:00');
const end = ref('12:00');
const status = ref<AvailabilityStatus>('available');
const error = ref<string | null>(null);
const saved = ref(false);

const custom = computed(() => part.value === CUSTOM);

// The next week as one-tap choices, so nobody has to open a date picker for "this Saturday".
const quickDays = computed(() =>
  Array.from({ length: 7 }, (_, offset) => {
    const iso = addDays(props.minDate, offset);
    const parts = parseIsoDay(iso);
    const short =
      offset === 0
        ? 'Today'
        : offset === 1
          ? 'Tomorrow'
          : parts
            ? WEEKDAYS_SHORT[parts.weekday]
            : iso;
    return {
      iso,
      short,
      day: parts?.day ?? '',
      long: parts ? `${WEEKDAYS_LONG[parts.weekday]} ${parts.day}` : iso,
    };
  }),
);

function submit() {
  const preset = DAY_PARTS.find((option) => option.key === part.value);
  const chosen = {
    date: date.value,
    start: preset ? preset.start : start.value,
    end: preset ? preset.end : end.value,
  };
  error.value = checkWindow(chosen);
  // A typed date can get past the picker's `min`. A past day is never listed, so refuse it here
  // rather than say "Saved" for something nobody will see.
  if (!error.value && chosen.date < props.minDate) {
    error.value = 'Please choose today or a later day.';
  }
  saved.value = false;
  if (error.value) return;
  emit('save', { ...chosen, status: status.value });
  saved.value = true;
  date.value = '';
}
</script>

<template>
  <form novalidate @submit.prevent="submit">
    <div class="quick" role="group" aria-label="Pick a day this week">
      <button
        v-for="day in quickDays"
        :key="day.iso"
        type="button"
        class="quick-day"
        :aria-pressed="date === day.iso"
        :aria-label="day.long"
        @click="date = day.iso"
      >
        <span class="quick-wd">{{ day.short }}</span>
        <span class="quick-dn tabular">{{ day.day }}</span>
      </button>
    </div>

    <div class="row g-3">
      <div class="col-sm-6 col-lg-4">
        <label :for="dateId" class="form-label">Date</label>
        <input :id="dateId" v-model="date" class="form-control" type="date" :min="minDate" />
      </div>
      <div class="col-sm-6 col-lg-4">
        <label :for="partId" class="form-label">Time of day</label>
        <select :id="partId" v-model="part" class="form-select">
          <option v-for="option in DAY_PARTS" :key="option.key" :value="option.key">
            {{ option.label }}
          </option>
          <option :value="CUSTOM">Choose the times…</option>
        </select>
      </div>
      <template v-if="custom">
        <div class="col-6 col-lg-2">
          <label :for="startId" class="form-label">From</label>
          <input :id="startId" v-model="start" class="form-control" type="time" />
        </div>
        <div class="col-6 col-lg-2">
          <label :for="endId" class="form-label">Until</label>
          <input :id="endId" v-model="end" class="form-control" type="time" />
        </div>
      </template>
    </div>

    <fieldset class="mt-3">
      <legend class="fs-6 fw-semibold">Can you help?</legend>
      <div class="choice">
        <input
          :id="`${dateId}-yes`"
          v-model="status"
          class="choice-input"
          type="radio"
          value="available"
        />
        <label class="choice-label yes" :for="`${dateId}-yes`">
          <Icon name="check-circle" class="me-2" />I can help
        </label>
        <input
          :id="`${dateId}-no`"
          v-model="status"
          class="choice-input"
          type="radio"
          value="unavailable"
        />
        <label class="choice-label no" :for="`${dateId}-no`">
          <Icon name="x" class="me-2" />I can’t help
        </label>
      </div>
    </fieldset>

    <div v-if="error" class="alert alert-danger mt-3 mb-0" role="alert">{{ error }}</div>
    <div v-else-if="saved" class="alert alert-success mt-3 mb-0" role="status">
      Saved. The family can see this now.
    </div>

    <button type="submit" class="btn btn-primary mt-3">Save availability</button>
  </form>
</template>

<style scoped>
.quick {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 0.35rem;
  margin-bottom: 1rem;
}

.quick-day {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-height: 3.4rem;
  padding: 0.35rem 0.1rem;
  border: 2px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
  color: var(--sl-ink);
  line-height: 1.15;
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease;
}

.quick-day:hover {
  border-color: var(--sl-ink-soft);
}

.quick-day[aria-pressed='true'] {
  border-color: var(--sl-ink);
  background: var(--sl-ink);
  color: #fff;
}

.quick-wd {
  font-size: 0.72rem;
  font-weight: 700;
}

.quick-dn {
  font-size: 1.15rem;
  font-weight: 800;
}

.choice {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}

.choice-input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.choice-label {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 3rem;
  border: 2px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  font-weight: 700;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease;
}

.choice-label:hover {
  border-color: var(--sl-ink-soft);
}

.choice-input:focus-visible + .choice-label {
  outline: 3px solid var(--sl-jade);
  outline-offset: 2px;
}

.choice-input:checked + .choice-label.yes {
  border-color: var(--sl-jade);
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}

.choice-input:checked + .choice-label.no {
  border-color: var(--sl-ink-soft);
  background: var(--sl-mist);
}
</style>
