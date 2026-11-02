<script setup lang="ts">
import type { HelperAsk } from '@silverloop/api-client';
import { ref } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { answerAsk, focusAfterAsk, withdrawAsk } from '@/composables/useAsks';
import { currentGroup } from '@/composables/useMe';

/**
 * What the people an open ask concerns can do about it, on a card: the asked member answers
 * "Yes, I'll go" or "Can't go"; the asker can withdraw it. Anyone else gets nothing here (they
 * still have "I'll go", which the card shows itself). The buttons wait while the API answers, and
 * focus then moves to whatever replaced them (`focusAfterAsk`).
 */
const props = defineProps<{ ask: HelperAsk; title: string; small?: boolean }>();

const busy = ref(false);

async function run(event: Event, work: () => Promise<boolean>) {
  if (busy.value) return;
  busy.value = true;
  const refocus = focusAfterAsk(event.currentTarget as Element | null);
  try {
    await work();
  } finally {
    busy.value = false;
  }
  await refocus();
}

function answer(event: Event, yes: boolean) {
  const group = currentGroup.value?.group_id;
  if (!group) return;
  void run(event, () =>
    answerAsk(group, props.ask.ask_id, yes, {
      title: props.title,
      askerName: props.ask.asker_name,
    }),
  );
}
</script>

<template>
  <template v-if="ask.can_answer">
    <button
      type="button"
      class="btn btn-primary"
      :class="{ 'btn-sm': small }"
      :disabled="busy"
      :aria-label="`Yes, I’ll go to ${title}`"
      data-testid="ask-yes"
      data-ask-focus
      @click="answer($event, true)"
    >
      <Icon name="user-check" class="me-1" />Yes, I’ll go
    </button>
    <button
      type="button"
      class="btn btn-outline-secondary"
      :class="{ 'btn-sm': small }"
      :disabled="busy"
      :aria-label="`Can’t go to ${title}`"
      data-testid="ask-no"
      @click="answer($event, false)"
    >
      <Icon name="user-x" class="me-1" />Can’t go
    </button>
  </template>
  <button
    v-else-if="ask.can_withdraw"
    type="button"
    class="btn btn-outline-secondary"
    :class="{ 'btn-sm': small }"
    :disabled="busy"
    :aria-label="`Withdraw your ask to ${ask.asked_name} for ${title}`"
    data-testid="ask-withdraw"
    data-ask-focus
    @click="run($event, () => withdrawAsk(ask))"
  >
    <Icon name="x" class="me-1" />Withdraw
  </button>
</template>
