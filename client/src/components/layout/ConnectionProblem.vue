<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import { useConnection } from '@/composables/useConnection';
import { SERVER_MESSAGE, STORED_STATE_MESSAGE, UNREACHABLE_MESSAGE } from '@/lib/api-errors';

/**
 * Shown by `AppLayout` in place of the page when the router guard could not reach Care+ (no
 * response, or a 5xx): what happened, in the app's usual words, and one way forward. "Try again"
 * reads the account and `/v1/me` again and reopens the same screen; the address never changes and
 * nobody is sent to sign in. CSS only: the layout loads no motion library.
 *
 * `senior`: the senior's screen, so larger type and a larger button, like the rest of that screen.
 */
defineProps<{ senior?: boolean }>();

const { problem, retrying, failedRetries, retry } = useConnection();
const router = useRouter();
const heading = ref<HTMLElement | null>(null);

const message = computed(() => {
  if (problem.value === 'stored_state') return STORED_STATE_MESSAGE;
  if (problem.value === 'unreachable') return UNREACHABLE_MESSAGE;
  return SERVER_MESSAGE;
});

// One announcement path, no alert region: focus moves to the heading when the panel appears, so a
// keyboard or screen-reader user starts at the explanation (read out with the focus), and the
// `role="status"` line below reports a retry that failed again. That retry keeps this same panel
// (it is not mounted again), so focus stays on Try again. While trying, the button is only
// aria-disabled (a disabled button would drop focus to the page); `retryConnection` ignores a
// second press.
onMounted(async () => {
  await nextTick();
  heading.value?.focus();
});
</script>

<template>
  <section
    class="connection sl-panel"
    :class="{ 'connection--senior': senior }"
    aria-labelledby="connection-title"
    data-testid="connection-problem"
  >
    <span class="connection-icon" aria-hidden="true"><Icon name="cloud" /></span>
    <div class="connection-body">
      <h1 id="connection-title" ref="heading" class="connection-title" tabindex="-1">
        Can’t connect to Care+ right now
      </h1>
      <p class="connection-message">{{ message }}</p>
      <p class="connection-again" role="status" data-testid="connection-again">
        <template v-if="failedRetries > 0 && !retrying">
          Still can’t connect. You’re still signed in; try again in a moment.
        </template>
      </p>
      <button
        type="button"
        class="btn btn-primary connection-retry"
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

.connection-icon :deep(.sl-icon) {
  width: 1.5rem;
  height: 1.5rem;
}

.connection-body {
  min-width: 0;
}

.connection-title {
  margin-bottom: 0.5rem;
  font-size: 1.5rem;
  overflow-wrap: anywhere;
}

/* Focus is moved here for screen readers; the heading is not a control, so no ring. */
.connection-title:focus {
  outline: none;
}

.connection-message {
  margin-bottom: 0.5rem;
}

.connection-again {
  min-height: 1.5em;
  margin-bottom: 0.75rem;
  color: var(--sl-ink-soft);
  font-weight: 600;
}

.connection-again:empty {
  min-height: 0;
  margin-bottom: 0.5rem;
}

/* At least 44px, like every button; 48px and larger type on the senior's screen. */
.connection-retry {
  display: inline-flex;
  align-items: center;
  min-height: 2.75rem;
}

.connection--senior .connection-title {
  font-size: 1.9rem;
}

.connection--senior .connection-message,
.connection--senior .connection-again {
  font-size: 1.2rem;
}

.connection--senior .connection-retry {
  min-height: 3.5rem;
  padding-inline: 1.5rem;
  font-size: 1.2rem;
}

@media (max-width: 575.98px) {
  .connection {
    flex-direction: column;
    margin-block: 1.5rem;
  }

  .connection--senior .connection-retry {
    width: 100%;
    justify-content: center;
  }
}
</style>
