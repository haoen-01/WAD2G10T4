<script setup lang="ts">
import type { PinResponse } from '@silverloop/api-client';
import { ref } from 'vue';

import PinDisplay from '@/components/family/PinDisplay.vue';
import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import { useAction } from '@/composables/useAction';
import { getSeniorLinkPin } from '@/services/careApi';

/**
 * "Link your family": the senior shows a short code to the family member setting up their group.
 * Showing it is how the senior agrees to being linked, so only the senior's own screen can make one.
 */
const { busy, error, run } = useAction();
const code = ref<PinResponse | null>(null);

function show() {
  void run(async () => {
    code.value = await getSeniorLinkPin();
  });
}
</script>

<template>
  <BasePanel heading-class="h3 d-flex align-items-center gap-2">
    <template #title><Icon name="users" />Link your family</template>
    <p>
      Setting up Care+ for you? Show this code to your family member. It works once, for 15 minutes.
    </p>
    <PinDisplay
      v-if="code"
      class="mb-3"
      :pin="code.pin"
      :expires-at="code.expires_at"
      testid="senior-link-pin"
    />
    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>
    <button
      type="button"
      class="btn btn-outline-primary btn-lg"
      :disabled="busy"
      data-testid="show-family-code"
      @click="show"
    >
      {{ code ? 'Show a new code' : 'Show a code for my family' }}
    </button>
  </BasePanel>
</template>
