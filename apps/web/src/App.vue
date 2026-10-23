<script setup lang="ts">
import { RouterView } from 'vue-router';

import RouteAnnouncer from '@/components/layout/RouteAnnouncer.vue';
import ToastHost from '@/components/ui/ToastHost.vue';
</script>

<template>
  <RouterView />
  <RouteAnnouncer />
  <ToastHost />
</template>
