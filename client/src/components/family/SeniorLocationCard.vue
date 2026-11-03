<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue';

/**
 * A reserved spot for a possible future "share my location" feature. It does nothing today: no
 * location is read, shown or stored.
 */
defineProps<{ elder: string }>();
</script>

<template>
  <div class="location sl-note d-flex align-items-center gap-2" data-slot="senior-location">
    <Icon name="pin" aria-hidden="true" />
    <span>
      Location sharing: not available yet. If {{ elder }} ever chooses to share it, it would appear
      here.
    </span>
  </div>
</template>

<style scoped>
.location {
  padding: 0.75rem 1rem;
  border: 1px dashed var(--sl-line);
  border-radius: var(--sl-radius-sm);
}
</style>
