<script lang="ts">
import { defineComponent } from 'vue';

// Each panel needs its own heading id, so the section can be named after its heading.
let panelCount = 0;

/**
 * The white rounded panel used across the app: a `<section>` named by its `<h2>`.
 *
 * Slots:
 * - default: the panel's content.
 * - `title`: the heading's content, when it needs more than the `title` text (an icon, say).
 * - `actions`: buttons shown on the heading's row (a Refresh button, say).
 *
 * Any class given to `<BasePanel>` (`mb-4`, `h-100`) lands on the section itself.
 */
export default defineComponent({
  name: 'BasePanel',

  props: {
    title: { type: String, default: '' },
    /** Bootstrap heading classes for the `<h2>`. */
    headingClass: { type: String, default: 'h4' },
  },

  data() {
    panelCount += 1;
    return { headingId: `panel-heading-${panelCount}` };
  },
});
</script>

<template>
  <section class="sl-panel" :aria-labelledby="headingId">
    <div v-if="$slots.actions" class="d-flex align-items-center justify-content-between gap-2 mb-2">
      <h2 :id="headingId" :class="headingClass">
        <slot name="title">{{ title }}</slot>
      </h2>
      <slot name="actions" />
    </div>
    <h2 v-else :id="headingId" :class="headingClass">
      <slot name="title">{{ title }}</slot>
    </h2>
    <slot />
  </section>
</template>
