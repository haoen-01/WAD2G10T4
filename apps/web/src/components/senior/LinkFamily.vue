<script setup lang="ts">
import { ref, useId } from 'vue';

import FamilyCodeCard from '@/components/senior/FamilyCodeCard.vue';
import Icon from '@/components/ui/Icon.vue';

/**
 * "Add a family member": the link code, folded away until the senior asks for it. Folding only
 * hides it (`v-show`), so a code already on screen and its countdown carry on as before.
 */
const id = useId();
const open = ref(false);
</script>

<template>
  <section aria-label="Link your family">
    <button
      type="button"
      class="btn btn-outline-primary btn-lg d-inline-flex align-items-center gap-2"
      :aria-expanded="open"
      :aria-controls="`${id}-code`"
      data-testid="add-family-member"
      @click="open = !open"
    >
      <Icon name="user-plus" />Add a family member
      <Icon :name="open ? 'chevron-left' : 'chevron-right'" class="toggle-chevron" />
    </button>
    <div v-show="open" :id="`${id}-code`" class="mt-3">
      <FamilyCodeCard />
    </div>
  </section>
</template>

<style scoped>
/* Points down when closed and up when open, as a disclosure arrow does. */
.toggle-chevron {
  transform: rotate(90deg);
}
</style>
