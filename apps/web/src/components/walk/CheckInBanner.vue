<script setup lang="ts">
import CheckInActions from '@/components/walk/CheckInActions.vue';
import Icon from '@/components/ui/Icon.vue';
import { useWalk } from '@/composables/useWalk';

/**
 * The check-in banner at the top of every family screen while one is waiting: what has happened in
 * plain words, and what to do about it. Calm on purpose: it says she has been in one place a long
 * time, nothing more. Screen readers hear it once, when it appears.
 */
const walk = useWalk();
</script>

<template>
  <Transition name="page">
    <section
      v-if="walk.openAlert.value"
      class="checkin-banner"
      aria-labelledby="checkin-banner-title"
      data-testid="checkin-banner"
    >
      <div class="checkin-banner-icon" aria-hidden="true"><Icon name="bell" /></div>
      <div class="flex-grow-1 min-w-0">
        <h2 id="checkin-banner-title" class="h6 mb-1">
          Check in with {{ walk.seniorName.value }}?
        </h2>
        <!-- Read out once, in the words fixed when it was raised; the line below keeps time. -->
        <p class="visually-hidden" role="alert">
          {{ walk.openAlert.value.words }} You may want to check in.
        </p>
        <p class="mb-2" aria-hidden="true">
          {{ walk.alertWords(walk.openAlert.value) }} You may want to check in.
        </p>
        <p v-if="walk.openAlert.value.checkingBy" class="fw-bold mb-2" role="status">
          {{ walk.openAlert.value.checkingBy }} is checking in.
        </p>
        <CheckInActions :alert="walk.openAlert.value" />
      </div>
    </section>
  </Transition>
</template>

<style scoped>
.checkin-banner {
  display: flex;
  gap: 0.9rem;
  margin-bottom: 1.5rem;
  padding: 1rem 1.15rem;
  border: 1px solid var(--sl-sun);
  border-radius: var(--sl-radius);
  background: var(--sl-sun-soft);
  box-shadow: var(--sl-float);
}

.checkin-banner-icon {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 50%;
  background: var(--sl-sun);
  color: #3a2a00;
}

.checkin-banner-icon .sl-icon {
  width: 1.3rem;
  height: 1.3rem;
}

.checkin-banner p {
  color: var(--sl-ink);
}
</style>
