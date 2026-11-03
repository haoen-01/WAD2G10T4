<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import { useWalk, type WalkAlert } from '@/composables/useWalk';
import { DEMO_SENIOR_PHONE } from '@/lib/demo-walk';

/**
 * What a family member can do about a check-in: call her, message her, see her on the map, tell
 * the rest of the family "I'm checking in", or say she is fine. Care+ never calls or messages
 * anyone itself; these open the phone's own dialler and messages.
 */
const props = withDefaults(defineProps<{ alert: WalkAlert; showMap?: boolean }>(), {
  showMap: true,
});

const walk = useWalk();
const name = walk.seniorName;

const smsHref = computed(() => {
  const body = encodeURIComponent(`Hi ${name.value}, just checking in. Are you OK?`);
  return `sms:${DEMO_SENIOR_PHONE.dial}?&body=${body}`;
});
const checking = computed(() => props.alert.status === 'checking');
</script>

<template>
  <div class="checkin-actions">
    <a
      class="btn btn-primary"
      :href="`tel:${DEMO_SENIOR_PHONE.dial}`"
      data-testid="checkin-call"
      :title="`Call ${DEMO_SENIOR_PHONE.words}`"
    >
      <Icon name="phone" /> Call {{ name }}
    </a>
    <a class="btn btn-outline-primary" :href="smsHref" data-testid="checkin-message">
      <Icon name="chat" /> Message
    </a>
    <RouterLink v-if="showMap" class="btn btn-outline-primary" to="/walk" data-testid="checkin-map">
      <Icon name="map" /> Show on map
    </RouterLink>
    <button
      v-if="!checking"
      type="button"
      class="btn btn-outline-secondary"
      data-testid="checkin-claim"
      @click="walk.checkingIn()"
    >
      <Icon name="hand" /> I’m checking in
    </button>
    <button
      type="button"
      class="btn btn-outline-secondary"
      data-testid="checkin-fine"
      @click="walk.shesFine()"
    >
      <Icon name="check" /> She’s fine
    </button>
  </div>
</template>

<style scoped>
.checkin-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.checkin-actions .btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 2.75rem;
}
</style>
