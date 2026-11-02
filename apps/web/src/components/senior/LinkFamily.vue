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
  if (busy.value) return;
  // The API keeps one live code per senior: asking for a new one ends the old one, whether or not
  // the answer gets back here. So the old code leaves the screen first, and is never shown dead.
  code.value = null;
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
      <!-- Always in the page, so a screen reader hears the change while focus stays on the button. -->
      <p class="visually-hidden" role="status">
        {{ busy ? 'Getting your code...' : code ? 'Your code is ready.' : '' }}
      </p>
      <!-- One panel for waiting and for the code, so nothing below it moves when the code arrives. -->
      <PinDisplay
        v-if="code || busy"
        class="mb-3"
        :pending="!code"
        :pin="code?.pin ?? ''"
        :expires-at="code?.expires_at ?? ''"
        testid="senior-link-pin"
      />
      <p v-if="error" class="alert alert-danger" role="alert">{{ error }}</p>
      <!-- aria-disabled, not disabled: a disabled button drops keyboard focus to the page. `showCode`
           ignores presses while busy. -->
      <button
        type="button"
        class="btn btn-outline-primary btn-lg"
        :class="{ disabled: busy }"
        :aria-disabled="busy"
        data-testid="show-family-code"
        @click="showCode"
      >
        {{ code || busy ? 'Show a new code' : 'Try getting a code again' }}
      </button>
    </div>
  </div>
</template>
