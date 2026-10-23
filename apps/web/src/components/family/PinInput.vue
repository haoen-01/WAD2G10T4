<script setup lang="ts">
import { useId } from 'vue';

/**
 * A 6-digit PIN field, used with `v-model`. Only the digits 0 to 9 are kept (a pasted "123 456"
 * becomes "123456"), and phones show the number pad.
 */
defineProps<{ label: string; hint?: string; testid?: string }>();
const model = defineModel<string>({ required: true });
const id = useId();

function onInput(event: Event) {
  const input = event.target as HTMLInputElement;
  const digits = input.value.replace(/[^0-9]/g, '').slice(0, 6);
  input.value = digits;
  model.value = digits;
}
</script>

<template>
  <div>
    <label :for="id" class="form-label">{{ label }}</label>
    <input
      :id="id"
      :value="model"
      class="form-control form-control-lg pin-input"
      inputmode="numeric"
      autocomplete="one-time-code"
      maxlength="7"
      pattern="[0-9]{6}"
      required
      :aria-describedby="hint ? `${id}-hint` : undefined"
      :data-testid="testid"
      @input="onInput"
    />
    <div v-if="hint" :id="`${id}-hint`" class="form-text">{{ hint }}</div>
  </div>
</template>

<style scoped>
.pin-input {
  max-width: 13rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.4em;
}
</style>
