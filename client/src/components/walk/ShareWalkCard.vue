<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue';
import { useWalk } from '@/composables/useWalk';
import { limitWords, MINUTE_MS } from '@/lib/stillness';

/**
 * The senior's own choices about her walks: whether her family can see where she is while she is
 * out, and whether they are told if she stays in one place a long time. Both start off, and only
 * she can turn them on. Big switches with the words beside them.
 */
const walk = useWalk();

function onShare(event: Event) {
  walk.setShareWalk((event.target as HTMLInputElement).checked);
}

function onStill(event: Event) {
  walk.setStillnessAlerts((event.target as HTMLInputElement).checked);
}
</script>

<template>
  <section class="sl-panel share-walk" aria-labelledby="my-walks-heading">
    <h2 id="my-walks-heading" class="h4 d-flex align-items-center gap-2">
      <Icon name="walk" /> My walks
    </h2>
    <p class="mb-3">You choose what your family can see. You can change this at any time.</p>

    <div class="form-check form-switch share-switch">
      <input
        id="share-walk"
        class="form-check-input"
        type="checkbox"
        role="switch"
        :checked="walk.settings.shareWalk"
        data-testid="share-walk"
        @change="onShare"
      />
      <label class="form-check-label" for="share-walk">
        <span class="fw-bold">Share my walk with my family</span>
        <span class="d-block sl-note">They can see where I am while I am out walking.</span>
      </label>
    </div>

    <div class="form-check form-switch share-switch">
      <input
        id="share-still"
        class="form-check-input"
        type="checkbox"
        role="switch"
        :checked="walk.settings.stillnessAlerts"
        :disabled="!walk.settings.shareWalk"
        data-testid="share-still"
        @change="onStill"
      />
      <label class="form-check-label" for="share-still">
        <span class="fw-bold">Tell my family if I stay in one place for a long time</span>
        <span class="d-block sl-note">
          After {{ limitWords(walk.settings.limitMin * MINUTE_MS) }} in one place away from home. I
          am asked first, so I can say I am OK. Never at home.
        </span>
      </label>
    </div>

    <p v-if="walk.settings.shareWalk" class="share-on mb-0" role="status">
      <Icon name="eye" /> Your family can see your walk.
    </p>
  </section>
</template>

<style scoped>
.share-switch {
  display: flex;
  gap: 0.85rem;
  align-items: flex-start;
  margin-bottom: 1rem;
  padding-left: 0;
}

.share-switch .form-check-input {
  flex: none;
  width: 3.25rem;
  height: 1.75rem;
  margin: 0.1rem 0 0;
}

.share-switch .form-check-label {
  font-size: 1.1rem;
}

.share-on {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.5rem 0.85rem;
  border-radius: 999px;
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-weight: 700;
}
</style>
