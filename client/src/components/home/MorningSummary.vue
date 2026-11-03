<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import { formatSteps } from '@/lib/activity';
import type { MorningSummary, Verdict } from '@/lib/morning-summary';

/**
 * The morning summary: a pop-up on Home once a day. It is a native `<dialog>` opened with
 * `showModal()`, so the browser itself keeps Tab inside it, closes it with Escape and dims the page
 * behind (`::backdrop`). Clicking outside it closes it too. What it says comes from
 * `lib/morning-summary.ts`; Home decides when it opens.
 */
const props = defineProps<{
  open: boolean;
  summary: MorningSummary | null;
  greeting: string;
  viewer: string | null;
  elder: string;
  dateWords: string;
  sample: boolean;
}>();
const eachMorning = defineModel<boolean>('eachMorning', { required: true });
const emit = defineEmits<{ close: [] }>();

const dialog = ref<HTMLDialogElement | null>(null);

function sync(open: boolean) {
  const element = dialog.value;
  if (!element) return;
  if (open && !element.open) element.showModal();
  if (!open && element.open) element.close();
}
watch(() => props.open, sync, { flush: 'post' });
onMounted(() => sync(props.open));

/**
 * A click on the dimmed page (the dialog's own box, outside its panel) closes it. Only when the
 * press also started there, so selecting text and letting go outside the panel does not close it.
 */
let pressedOutside = false;
function onPointerDown(event: PointerEvent) {
  pressedOutside = event.target === dialog.value;
}
function onClick(event: MouseEvent) {
  if (pressedOutside && event.target === dialog.value) dialog.value?.close();
  pressedOutside = false;
}

const TONES: Record<Verdict, string> = {
  good: 'sl-tone-jade',
  watch: 'sl-tone-orange',
  review: 'sl-tone-coral',
  paused: 'sl-tone-blue',
  unread: 'sl-tone-blue',
};
const MARKS: Record<Verdict, 'check-circle' | 'info' | 'alert' | 'pause' | 'watch'> = {
  good: 'check-circle',
  watch: 'info',
  review: 'alert',
  paused: 'pause',
  unread: 'watch',
};
</script>

<template>
  <dialog
    ref="dialog"
    class="morning"
    aria-labelledby="morning-title"
    data-testid="morning-summary"
    @close="emit('close')"
    @pointerdown="onPointerDown"
    @click="onClick"
  >
    <div v-if="summary" class="morning-panel sl-glow">
      <p class="morning-hello">
        <Icon name="sun" />{{ greeting }}<template v-if="viewer">, {{ viewer }}</template> ·
        {{ dateWords }}
      </p>
      <!-- Focus starts on the title (not "Got it" at the bottom), so the panel opens at its top. -->
      <h2 id="morning-title" class="morning-title" tabindex="-1" autofocus>
        {{ elder }}’s day, in brief
      </h2>

      <section class="morning-block" aria-labelledby="morning-yesterday">
        <div class="d-flex flex-wrap align-items-center justify-content-between gap-2">
          <h3 id="morning-yesterday" class="morning-label">{{ summary.dayLabel }}</h3>
          <span v-if="sample" class="badge text-bg-secondary">Sample numbers</span>
        </div>
        <p class="morning-steps">
          <span class="display-num">{{ formatSteps(summary.steps) }}</span>
          <span class="morning-compare">
            <template v-if="summary.percent !== null"
              >{{ summary.percent }}% of a usual day, </template
            >{{ summary.compare }}
          </span>
        </p>
        <div class="morning-verdict" :class="TONES[summary.verdict]" data-testid="morning-verdict">
          <Icon :name="MARKS[summary.verdict]" class="verdict-icon" />
          <p class="mb-0">
            <strong>{{ summary.headline }}</strong> {{ summary.note }}
          </p>
        </div>
      </section>

      <section class="morning-block" aria-labelledby="morning-today">
        <h3 id="morning-today" class="morning-label">Today</h3>
        <ul v-if="summary.todo.length" class="morning-todo">
          <li v-for="item in summary.todo" :key="item.text">
            <RouterLink v-if="item.to.startsWith('/')" :to="item.to" @click="dialog?.close()">
              <span class="todo-icon"><Icon :name="item.icon" /></span>{{ item.text }}
              <Icon name="chevron-right" class="todo-go" />
            </RouterLink>
            <a v-else :href="item.to" @click="dialog?.close()">
              <span class="todo-icon"><Icon :name="item.icon" /></span>{{ item.text }}
              <Icon name="chevron-right" class="todo-go" />
            </a>
          </li>
        </ul>
        <p v-else class="sl-note mb-0">Nothing planned for today. A good day for a call.</p>
      </section>

      <div class="morning-foot">
        <div class="form-check form-switch mb-0">
          <input
            id="morning-each"
            v-model="eachMorning"
            class="form-check-input"
            type="checkbox"
            role="switch"
          />
          <label class="form-check-label" for="morning-each">Show this each morning</label>
        </div>
        <button
          type="button"
          class="btn btn-primary sl-cta"
          data-testid="morning-close"
          @click="dialog?.close()"
        >
          Got it
        </button>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.morning {
  width: min(34rem, calc(100vw - 1.5rem));
  max-height: calc(100dvh - 2rem);
  padding: 0;
  border: 0;
  border-radius: 1.75rem;
  background: transparent;
  color: var(--sl-ink);
  overflow: visible;
}

.morning::backdrop {
  background: rgb(4 17 13 / 55%);
  -webkit-backdrop-filter: blur(6px);
  backdrop-filter: blur(6px);
}

/* Opening: it rises a little and fades in. (Reduced motion: the rule in theme.css stops it.) */
.morning[open] .morning-panel {
  animation: morning-in 0.45s var(--sl-ease);
}

@keyframes morning-in {
  from {
    opacity: 0;
    transform: translateY(16px) scale(0.98);
  }
}

.morning-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-height: calc(100dvh - 2rem);
  overflow-y: auto;
  padding: 1.5rem;
  border: 1px solid var(--sl-panel-border);
  border-radius: inherit;
  background-color: var(--sl-surface);
  box-shadow: var(--sl-float);
}

@media (min-width: 576px) {
  .morning-panel {
    padding: 1.75rem 2rem;
  }
}

.morning-hello {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  color: var(--sl-ink-soft);
  font-weight: 600;
}

.morning-hello .sl-icon {
  color: var(--sl-sun-deep);
}

.morning-title {
  margin: -0.4rem 0 0;
  outline: none;
  font-family: 'Bricolage Grotesque', var(--bs-body-font-family);
  font-size: clamp(1.6rem, 5vw, 2rem);
  font-weight: 800;
  letter-spacing: -0.02em;
}

.morning-block {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding-top: 1rem;
  border-top: 1px solid var(--sl-line);
}

.morning-label {
  margin: 0;
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.morning-steps {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.25rem 0.75rem;
  margin: 0;
}

.morning-steps .display-num {
  font-size: 2.6rem;
}

.morning-compare {
  color: var(--sl-ink-soft);
}

.morning-verdict {
  display: flex;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--tone-soft);
  color: var(--sl-ink);
}

.morning-verdict strong {
  color: var(--tone-deep);
}

.verdict-icon {
  flex: none;
  margin-top: 0.15rem;
  color: var(--tone-deep);
}

.morning-todo {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.morning-todo a {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: 2.75rem;
  padding: 0.5rem 0.6rem 0.5rem 0.5rem;
  border-radius: var(--sl-radius-sm);
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink);
  text-decoration: none;
  transition: background-color var(--sl-dur-base) ease;
}

.morning-todo a:hover {
  background: var(--sl-jade-soft);
}

.todo-icon {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 50%;
  background: var(--sl-surface);
  color: var(--sl-jade-deep);
}

.todo-go {
  flex: none;
  margin-left: auto;
  color: var(--sl-ink-soft);
}

.morning-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--sl-line);
}
</style>
