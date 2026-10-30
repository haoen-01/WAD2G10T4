<script setup lang="ts">
import type { PinResponse } from '@silverloop/api-client';
import { ref, useId } from 'vue';
import PinDisplay from '@/components/family/PinDisplay.vue';
import Icon from '@/components/ui/Icon.vue';
import { useAction } from '@/composables/useAction';
import { getSeniorLinkPin } from '@/services/careApi';
const id = useId();
const open = ref(false);
const code = ref<PinResponse | null>(null);
const { busy, error, run } = useAction();
function showCode() {
  void run(async () => {
    code.value = await getSeniorLinkPin();
  });
}
function toggle() {
  open.value = !open.value;
  if (open.value && !code.value) showCode();
}
</script>

<template>
  <div>
    <button
      type="button"
      class="btn btn-outline-primary btn-lg d-inline-flex align-items-center gap-2"
      :aria-expanded="open"
      :aria-controls="`${id}-code`"
      data-testid="add-family-member"
      @click="toggle"
    >
      <Icon name="user-plus" />Add a family member
    </button>
    <div v-show="open" :id="`${id}-code`" class="mt-4">
      <p class="fs-5">Show this code to your family member. It works once.</p>
      <p v-if="busy" class="fs-5" role="status">Getting your code...</p>
      <PinDisplay
        v-if="code"
        class="mb-3"
        :pin="code.pin"
        :expires-at="code.expires_at"
        testid="senior-link-pin"
      />
      <p v-if="error" class="alert alert-danger" role="alert">{{ error }}</p>
      <button
        type="button"
        class="btn btn-outline-primary btn-lg"
        :disabled="busy"
        data-testid="show-family-code"
        @click="showCode"
      >
        {{ code ? 'Show a new code' : 'Try getting a code again' }}
      </button>
    </div>
  </div>
</template>
