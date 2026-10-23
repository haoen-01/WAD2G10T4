<script lang="ts">
import { defineComponent, type PropType } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import LoopRing from '@/components/ui/LoopRing.vue';
import { timeToMinutes } from '@/lib/calendar';
import type { DailyTask } from '@/lib/daily-tasks';
import { formatClockTime } from '@/lib/format-date';
import { minutesOf, nextTask, untilWords } from '@/lib/today';

/**
 * "Today's tasks": medicine and reminders that tick off, a ring for how many are done and a line
 * for what is next. Used with `v-model`, which holds the ids of the ticked tasks:
 *
 *   <TaskChecklist v-model="done" :tasks="tasks" :now="now" />
 */
export default defineComponent({
  name: 'TaskChecklist',
  components: { Icon, LoopRing },

  props: {
    tasks: { type: Array as PropType<DailyTask[]>, required: true },
    /** The ids of the tasks already ticked. */
    modelValue: { type: Array as PropType<string[]>, required: true },
    /** The current time, so "Next" moves on as the day goes. */
    now: { type: Date, required: true },
  },

  emits: {
    'update:modelValue': (ids: string[]) => Array.isArray(ids),
  },

  computed: {
    doneCount(): number {
      return this.modelValue.length;
    },
    next(): { task: DailyTask; overdue: boolean } | null {
      return nextTask(this.tasks, minutesOf(this.now), new Set(this.modelValue));
    },
    nextWhen(): string {
      if (!this.next) return '';
      if (this.next.overdue) return 'earlier today';
      return untilWords(timeToMinutes(this.next.task.time) - minutesOf(this.now));
    },
  },

  methods: {
    formatClockTime,
    isDone(id: string): boolean {
      return this.modelValue.includes(id);
    },
    toggle(id: string) {
      const ids = this.isDone(id)
        ? this.modelValue.filter((done) => done !== id)
        : [...this.modelValue, id];
      this.$emit('update:modelValue', ids);
    },
  },
});
</script>

<template>
  <section class="sl-panel" aria-labelledby="tasks-heading">
    <div class="d-flex align-items-center gap-3 mb-3">
      <LoopRing
        :value="tasks.length ? doneCount / tasks.length : 0"
        :size="64"
        :stroke="8"
        color="var(--sl-sun)"
        track="var(--sl-sun-soft)"
      >
        <span class="fw-bold tabular">{{ doneCount }}/{{ tasks.length }}</span>
      </LoopRing>
      <div>
        <h2 id="tasks-heading" class="h4 mb-0">Today’s tasks</h2>
        <p class="mb-0 text-body-secondary" aria-live="polite">
          <template v-if="doneCount === tasks.length">All done for today.</template>
          <template v-else>{{ doneCount }} of {{ tasks.length }} done</template>
        </p>
      </div>
    </div>

    <p v-if="next" class="next-up">
      <Icon name="clock" />
      <span>
        Next: <strong>{{ next.task.label }}</strong> at {{ formatClockTime(next.task.time) }},
        {{ nextWhen }}
      </span>
    </p>

    <ul class="tasks">
      <li v-for="task in tasks" :key="task.id" :class="{ done: isDone(task.id) }">
        <input
          :id="`task-${task.id}`"
          class="task-check"
          type="checkbox"
          :checked="isDone(task.id)"
          @change="toggle(task.id)"
        />
        <label :for="`task-${task.id}`" class="task-label">
          <span class="task-box" aria-hidden="true"><Icon name="check" /></span>
          <span class="task-time tabular">{{ formatClockTime(task.time) }}</span>
          <span class="task-text">
            <span class="d-block">{{ task.label }}</span>
            <span v-if="task.kind === 'medicine' || task.notes" class="task-meta">
              <span v-if="task.kind === 'medicine'" class="task-kind">
                <Icon name="pill" />Medicine
              </span>
              <span v-if="task.notes">{{ task.notes }}</span>
            </span>
          </span>
        </label>
      </li>
    </ul>
    <p class="sl-note mt-3 mb-0">
      A sample checklist for demonstration. Checking one off here is not saved anywhere.
    </p>
  </section>
</template>

<style scoped>
.next-up {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-sun-soft);
}

.next-up .sl-icon {
  margin-top: 0.15rem;
}

.tasks {
  display: grid;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.task-check {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.task-label {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  min-height: 3.5rem;
  padding: 0.6rem 0.85rem;
  border: 2px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease;
}

.task-label:hover {
  border-color: var(--sl-ink-soft);
}

.task-check:focus-visible + .task-label {
  outline: 3px solid var(--sl-jade);
  outline-offset: 2px;
}

.task-box {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border: 2px solid var(--sl-ink-soft);
  border-radius: 0.5rem;
  color: transparent;
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    transform 0.2s var(--sl-ease);
}

.task-time {
  flex: none;
  min-width: 5.2rem;
  font-weight: 700;
  white-space: nowrap;
}

.task-text {
  flex: 1 1 10rem;
  min-width: 0;
}

.task-kind {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 0.3rem;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-size: 0.8rem;
  font-weight: 700;
}

.done .task-label {
  border-color: var(--sl-jade-soft);
  background: #f4f9f6;
}

.done .task-box {
  border-color: var(--sl-jade);
  background: var(--sl-jade);
  color: #fff;
  animation: pop 0.3s var(--sl-ease);
}

.done .task-text {
  color: var(--sl-ink-soft);
  text-decoration: line-through;
}

@keyframes pop {
  50% {
    transform: scale(1.2);
  }
}

@media (max-width: 575.98px) {
  .task-label {
    flex-wrap: wrap;
  }

  .task-time {
    min-width: 4.6rem;
  }
}

.task-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 0.6rem;
  margin-top: 0.2rem;
  color: var(--sl-ink-soft);
  font-size: 0.875rem;
}
</style>
