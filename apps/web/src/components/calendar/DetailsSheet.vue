<script lang="ts">
import { defineComponent } from 'vue';

/**
 * Holds an appointment's details. On a wide screen it simply fades in beside the calendar; on a
 * phone it rises from the bottom as a sheet over a dimmed page, and tapping the dimmed part emits
 * `close`. What goes inside comes from the default slot:
 *
 *   <DetailsSheet :open="selected !== null" :narrow="narrow" @close="closeDetails">
 *     <AppointmentDetails ... />
 *   </DetailsSheet>
 */
export default defineComponent({
  name: 'DetailsSheet',

  props: {
    open: { type: Boolean, required: true },
    /** True below the large breakpoint, where the details float as a sheet. */
    narrow: { type: Boolean, required: true },
  },

  emits: ['close'],
});
</script>

<template>
  <div
    v-if="narrow && open"
    class="sheet-backdrop"
    aria-hidden="true"
    @click="$emit('close')"
  ></div>
  <Transition :name="narrow ? 'sheet' : 'page'">
    <div v-if="open" class="sheet" :class="{ floating: narrow }">
      <span v-if="narrow" class="sheet-handle" aria-hidden="true"></span>
      <slot />
    </div>
  </Transition>
</template>

<style scoped>
.sheet.floating {
  position: fixed;
  z-index: 1045;
  right: 0;
  bottom: 0;
  left: 0;
  max-height: 88vh;
  overflow-y: auto;
  padding: 0.6rem 0.5rem calc(0.5rem + env(safe-area-inset-bottom));
  border-radius: var(--sl-radius) var(--sl-radius) 0 0;
  background: var(--sl-mist);
  box-shadow: var(--sl-float);
  overscroll-behavior: contain;
}

.sheet-handle {
  display: block;
  width: 3rem;
  height: 0.35rem;
  margin: 0 auto 0.6rem;
  border-radius: 999px;
  background: var(--sl-line);
}

.sheet-backdrop {
  position: fixed;
  z-index: 1040;
  inset: 0;
  background: rgb(16 42 38 / 45%);
}

.sheet-enter-active,
.sheet-leave-active {
  transition: transform 0.3s var(--sl-ease);
}

.sheet-enter-from,
.sheet-leave-to {
  transform: translateY(100%);
}
</style>
