<script lang="ts">
import { defineComponent, type PropType } from 'vue';

// Each panel needs its own heading id, so the section can be named after its heading.
let panelCount = 0;

/**
 * The white rounded panel used across the app: a `<section>` named by its heading (`<h2>` unless
 * `heading-tag` says otherwise).
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
    /** Bootstrap heading classes for the heading. */
    headingClass: { type: String, default: 'h4' },
    /** `h3` when the panel sits under a section heading of its own (Home's "Needs you"). */
    headingTag: { type: String as PropType<'h2' | 'h3'>, default: 'h2' },
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
      <component :is="headingTag" :id="headingId" :class="headingClass">
        <slot name="title">{{ title }}</slot>
      </component>
      <slot name="actions" />
    </div>
    <component :is="headingTag" v-else :id="headingId" :class="headingClass">
      <slot name="title">{{ title }}</slot>
    </component>
    <slot />
  </section>
</template>
