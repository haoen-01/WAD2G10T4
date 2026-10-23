<script setup lang="ts">
import type { AccountRole } from '@silverloop/api-client';
import { onMounted, ref, useId } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { refreshCurrentUser, useAuth } from '@/composables/useAuth';
import { loadMe } from '@/composables/useMe';
import { AUTH_ENABLED } from '@/lib/config';
import { GROUP_START_PATH, parseViewMode } from '@/lib/view-mode';
import { onboard } from '@/services/careApi';
import { useAction } from '@/composables/useAction';

/**
 * `/welcome`: signed in, but the account has not said yet whether it is the senior or family. This
 * happens after confirming an email address, when sign-up could not finish on its own. Asked once.
 */
const route = useRoute();
const router = useRouter();
const { ready, session } = useAuth();
const { busy, error, run } = useAction();

const nameId = useId();
const name = ref('');
const role = ref<AccountRole>(parseViewMode(route.query.as) === 'senior' ? 'senior' : 'family');

onMounted(async () => {
  if (!AUTH_ENABLED) {
    await router.replace({ name: 'login' });
    return;
  }
  await ready;
  if (!session.value) {
    await router.replace({ name: 'login' });
    return;
  }
  const suggested = session.value.user.user_metadata?.display_name;
  if (typeof suggested === 'string') name.value = suggested;
  const me = await loadMe().catch(() => null);
  if (me && !me.needs_onboarding) await router.replace('/');
});

function submit() {
  void run(async () => {
    await onboard(role.value, name.value.trim());
    await refreshCurrentUser();
    await loadMe(true);
    await router.replace(role.value === 'senior' ? '/senior' : GROUP_START_PATH);
  });
}
</script>

<template>
  <div class="welcome">
    <header class="mb-4">
      <h1>One last step</h1>
      <p class="text-body-secondary mt-2 mb-0">Tell us who you are. You only do this once.</p>
    </header>

    <form class="sl-panel d-grid gap-4" @submit.prevent="submit">
      <fieldset>
        <legend class="form-label">I am</legend>
        <div class="form-check">
          <input
            id="role-family"
            v-model="role"
            class="form-check-input"
            type="radio"
            value="family"
          />
          <label class="form-check-label" for="role-family"
            >Family, helping to care for someone</label
          >
        </div>
        <div class="form-check">
          <input
            id="role-senior"
            v-model="role"
            class="form-check-input"
            type="radio"
            value="senior"
          />
          <label class="form-check-label" for="role-senior">The senior</label>
        </div>
      </fieldset>
      <div>
        <label :for="nameId" class="form-label">Your name</label>
        <input
          :id="nameId"
          v-model="name"
          class="form-control form-control-lg"
          required
          maxlength="80"
          autocomplete="name"
        />
      </div>
      <div v-if="error" class="alert alert-danger mb-0" role="alert">{{ error }}</div>
      <button type="submit" class="btn btn-primary btn-lg" :disabled="busy">Continue</button>
    </form>
  </div>
</template>

<style scoped>
.welcome {
  max-width: 34rem;
  margin: 0 auto;
}

.welcome h1 {
  font-size: clamp(2rem, 5vw, 2.6rem);
  font-weight: 800;
}
</style>
