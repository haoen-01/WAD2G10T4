<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import { useConnection } from '@/composables/useConnection';
import { SERVER_MESSAGE, STORED_STATE_MESSAGE, UNREACHABLE_MESSAGE } from '@/lib/api-errors';

/**
 * Shown by `AppLayout` in place of the page when the router guard could not reach Care+: what
 * happened, in the app's usual words, and one way forward ("Try again", which reads the account
 * and `/v1/me` again and reopens the same screen). CSS only: the layout loads no motion library.
 */
const { problem, retrying, retry } = useConnection();
const router = useRouter();
const heading = ref<HTMLElement | null>(null);

const message = computed(() => {
  if (problem.value === 'stored_state') return STORED_STATE_MESSAGE;
  if (problem.value === 'unreachable') return UNREACHABLE_MESSAGE;
  return SERVER_MESSAGE;
});

// Focus moves to the heading, so a keyboard or screen-reader user starts at the explanation. While
// trying again the button is only aria-disabled (a disabled button would drop focus to the page);
// `retryConnection` ignores a second press.
onMounted(async () => {
  await nextTick();
  heading.value?.focus();
});
</script>

<template>
  <section class="connection sl-panel" role="alert" data-testid="connection-problem">
    <span class="connection-icon" aria-hidden="true"><Icon name="cloud" /></span>
    <div class="connection-body">
      <h1 ref="heading" class="connection-title" tabindex="-1">Can’t connect to Care+ right now</h1>
      <p class="mb-3">{{ message }}</p>
      <button
        type="button"
        class="btn btn-primary"
        :aria-disabled="retrying ? 'true' : undefined"
        data-testid="connection-retry"
        @click="retry(router)"
      >
        <span
          v-if="retrying"
          class="spinner-border spinner-border-sm me-2"
          aria-hidden="true"
        ></span>
        <Icon v-else name="refresh" class="me-1" />{{ retrying ? 'Trying again…' : 'Try again' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.connection {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  max-width: 40rem;
  margin: 2.5rem auto;
}

.connection-icon {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 3rem;
  height: 3rem;
  border-radius: 50%;
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink-soft);
}

.connection-icon .sl-icon {
  width: 1.5rem;
  height: 1.5rem;
}

.connection-body {
  min-width: 0;
}

.connection-title {
  margin-bottom: 0.5rem;
  font-size: 1.5rem;
}

.connection-title:focus {
  outline: none;
}

@media (max-width: 575.98px) {
  .connection {
    flex-direction: column;
  }
}
</style>
