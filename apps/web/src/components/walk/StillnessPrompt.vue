<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { useWalk } from '@/composables/useWalk';
import { clockTime } from '@/lib/walk';

/**
 * The senior is asked first. Shortly before her family would be told that she has been in one
 * place a long time, her page asks "Are you OK?" with one big button. Pressing it restarts the clock
 * and, if her family was already told, tells them she is OK.
 */
const walk = useWalk();
const thanks = ref(false);

const phase = computed(() => {
  if (walk.openAlert.value) return 'told';
  const result = walk.stillness.value;
  return result.kind === 'still' && result.phase === 'soon' ? 'soon' : null;
});

const tellAt = computed(() => {
  const result = walk.stillness.value;
  return result.kind === 'still' && result.alertAt ? clockTime(result.alertAt) : null;
});

watch(phase, (next) => {
  if (next) thanks.value = false;
});

function ok() {
  walk.imOk();
  thanks.value = true;
}
</script>

<template>
  <section
    v-if="phase"
    class="still-prompt"
    role="alert"
    aria-labelledby="still-prompt-heading"
    data-testid="still-prompt"
  >
    <h2 id="still-prompt-heading" class="h4 mb-2">Are you OK?</h2>
    <p v-if="phase === 'soon'" class="mb-3">
      You have been in one place for a while. Your family will be told at {{ tellAt }}. Let them
      know you are OK?
    </p>
    <p v-else class="mb-3">
      Your family has been told you have been in one place for a long time. Let them know you are
      OK?
    </p>
    <button type="button" class="btn btn-primary btn-lg" data-testid="im-ok" @click="ok">
      <Icon name="thumbs-up" /> I’m OK
    </button>
  </section>
  <p v-else-if="thanks" class="still-thanks" role="status" data-testid="im-ok-thanks">
    <Icon name="check" /> Thank you. Your family knows you are OK.
  </p>
</template>

<style scoped>
.still-prompt {
  padding: 1.25rem 1.4rem;
  border: 2px solid var(--sl-sun);
  border-radius: var(--sl-radius);
  background: var(--sl-sun-soft);
}

.still-prompt p {
  font-size: 1.15rem;
}

.still-prompt .btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 3.5rem;
  padding-inline: 1.75rem;
  font-size: 1.25rem;
}

.still-thanks {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-weight: 700;
}
</style>
