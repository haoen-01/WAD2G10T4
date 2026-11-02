<script setup lang="ts">
import type { HelperAsk } from '@silverloop/api-client';
import { computed } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { askTag, askTagLabel, askTagShort } from '@/lib/asks';

/**
 * The amber "Asked Emily · waiting" tag, shown in place of the coral "needs a helper" marker while
 * someone has been asked and has not answered. The day still needs a helper. An icon and words, so
 * it never relies on colour; the whole sentence is what a screen reader hears.
 */
const props = defineProps<{
  ask: HelperAsk;
  /** Smaller, and the short words ("Asked Emily"), for the week ahead's narrow columns. */
  small?: boolean;
}>();
const text = computed(() => (props.small ? askTagShort(props.ask) : askTag(props.ask)));
const label = computed(() => askTagLabel(props.ask));
</script>

<template>
  <span class="asked-tag" :class="{ small }" :title="label" data-testid="asked-tag">
    <Icon name="clock" class="asked-icon" />
    <span aria-hidden="true">{{ text }}</span>
    <span class="visually-hidden">{{ label }}</span>
  </span>
</template>

<style scoped>
/* Amber: the sun family. --sl-sun-deep on --sl-sun-soft is 4.6:1 in light and 7:1 in dark. */
.asked-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  max-width: 100%;
  padding: 0.15rem 0.6rem;
  border: 1px solid var(--sl-sun);
  border-radius: 999px;
  background: var(--sl-sun-soft);
  color: var(--sl-sun-deep);
  font-size: 0.85rem;
  font-weight: 700;
  line-height: 1.35;
}

.asked-tag.small {
  padding: 0.05rem 0.45rem;
  font-size: 0.78rem;
}

.asked-icon {
  flex: none;
}
</style>
