<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue';
import { useToasts } from '@/composables/useToast';

const { toasts, dismiss } = useToasts();

function act(id: number, action?: () => void) {
  action?.();
  dismiss(id);
}
</script>

<template>
  <div class="sl-toasts" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="toast in toasts" :key="toast.id" class="sl-toast">
        <span class="flex-grow-1">{{ toast.message }}</span>
        <button
          v-if="toast.action && toast.actionLabel"
          type="button"
          class="btn btn-sm"
          @click="act(toast.id, toast.action)"
        >
          {{ toast.actionLabel }}
        </button>
        <button
          type="button"
          class="btn btn-sm toast-close"
          aria-label="Dismiss this message"
          @click="dismiss(toast.id)"
        >
          <Icon name="x" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-close {
  --bs-btn-color: #fff;
  --bs-btn-padding-x: 0.6rem;
}
</style>
