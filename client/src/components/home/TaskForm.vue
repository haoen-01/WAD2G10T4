<script setup lang="ts">
import { reactive, ref, useId } from 'vue';

import { TASK_REPEAT_LABELS as repeats, checkTask } from '@/lib/tasks';
import type { TaskInput, TaskSchedule } from '@/lib/tasks';

/**
 * Adding or editing one task, used by the Tasks panel and the calendar's day list. Editing also
 * offers Delete, which deletes straight away. The parent saves; this only checks and emits.
 */
const props = defineProps<{
  /** The task being edited, or nothing for a new one. */
  task?: TaskSchedule | null;
  /** A new task's first day. */
  day: string;
  /** The form's id, so a button elsewhere (the panel's "Add task") can submit it. */
  formId?: string;
}>();
const emit = defineEmits<{ save: [input: TaskInput]; delete: []; cancel: [] }>();
const id = useId();
const error = ref('');
const form = reactive<TaskInput>(
  props.task
    ? {
        title: props.task.title,
        start_date: props.task.start_date,
        time: props.task.time,
        repeat: props.task.repeat,
        repeat_until: props.task.repeat_until,
        notes: props.task.notes,
        kind: props.task.kind ?? 'task',
      }
    : {
        title: '',
        start_date: props.day,
        time: '09:00',
        repeat: 'none',
        repeat_until: null,
        notes: '',
        kind: 'task',
      },
);

function save() {
  error.value = checkTask(form) ?? '';
  if (!error.value) emit('save', { ...form });
}
function remove() {
  if (props.task) emit('delete');
}
</script>

<template>
  <form :id="formId" class="d-grid gap-3" data-testid="task-form" @submit.prevent="save">
    <h3 class="h5 mb-0">{{ task ? 'Edit task' : 'New task' }}</h3>
    <p v-if="error" role="alert" class="alert alert-danger mb-0">{{ error }}</p>
    <div>
      <label :for="`${id}-title`" class="form-label">Name</label
      ><input
        :id="`${id}-title`"
        v-model="form.title"
        class="form-control"
        maxlength="120"
        required
      />
    </div>
    <div class="row g-2">
      <div class="col-sm-6">
        <label :for="`${id}-start`" class="form-label">Date</label
        ><input
          :id="`${id}-start`"
          v-model="form.start_date"
          class="form-control"
          type="date"
          required
        />
      </div>
      <div class="col-sm-6">
        <label :for="`${id}-time`" class="form-label">Time</label
        ><input :id="`${id}-time`" v-model="form.time" class="form-control" type="time" required />
      </div>
    </div>
    <div class="row g-2">
      <div class="col-sm-6">
        <label :for="`${id}-repeat`" class="form-label">Repeat</label
        ><select :id="`${id}-repeat`" v-model="form.repeat" class="form-select">
          <option v-for="(label, value) in repeats" :key="value" :value="value">{{ label }}</option>
        </select>
      </div>
      <div v-if="form.repeat !== 'none'" class="col-sm-6">
        <label :for="`${id}-until`" class="form-label">Until (optional)</label
        ><input
          :id="`${id}-until`"
          v-model="form.repeat_until"
          type="date"
          :min="form.start_date"
          class="form-control"
        />
      </div>
    </div>
    <div>
      <label :for="`${id}-notes`" class="form-label">Notes (optional)</label
      ><textarea
        :id="`${id}-notes`"
        v-model="form.notes"
        class="form-control"
        maxlength="1000"
        rows="2"
      />
    </div>
    <div class="d-flex flex-wrap gap-2">
      <button type="submit" class="btn btn-primary">{{ task ? 'Save' : 'Add task' }}</button
      ><button type="button" class="btn btn-outline-secondary" @click="emit('cancel')">
        Cancel</button
      ><button v-if="task" type="button" class="btn btn-outline-danger ms-auto" @click="remove">
        Delete
      </button>
    </div>
  </form>
</template>
