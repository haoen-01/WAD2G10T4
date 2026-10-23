<script lang="ts">
import { defineComponent } from 'vue';

/** A centred Bootstrap spinner, read out as "Loading…", for a page waiting on the API. */
export default defineComponent({
  name: 'LoadingSpinner',
});
</script>

<template>
  <div class="text-center py-5">
    <div class="spinner-border" role="status"><span class="visually-hidden">Loading…</span></div>
  </div>
</template>
