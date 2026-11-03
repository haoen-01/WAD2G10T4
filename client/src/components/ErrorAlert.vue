<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue';

defineProps<{ message: string }>();
defineEmits<{ retry: [] }>();
</script>

<template>
  <div class="alert alert-danger d-flex flex-wrap align-items-center gap-3" role="alert">
    <Icon name="alert" class="fs-4" />
    <span class="flex-grow-1">{{ message }}</span>
    <button type="button" class="btn btn-outline-danger" @click="$emit('retry')">
      <Icon name="refresh" class="me-1" />Try again
    </button>
  </div>
</template>
