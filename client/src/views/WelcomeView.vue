<script setup lang="ts">
import type { AccountRole } from '@silverloop/api-client';
import { onMounted, ref, useId } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import AuthShell from '@/components/ui/AuthShell.vue';
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
  <AuthShell
    title="One last step"
    lead="Tell us who you are. You only do this once."
    width="narrow"
  >
    <form class="sl-panel d-grid gap-4" @submit.prevent="submit">
      <fieldset class="d-grid gap-2">
        <legend class="form-label">I am</legend>
        <div class="role-row">
          <input
            id="role-family"
            v-model="role"
            class="form-check-input mt-0"
            type="radio"
            value="family"
          />
          <label class="role-label" for="role-family">Family, helping to care for someone</label>
        </div>
        <div class="role-row">
          <input
            id="role-senior"
            v-model="role"
            class="form-check-input mt-0"
            type="radio"
            value="senior"
          />
          <label class="role-label" for="role-senior">The senior</label>
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
      <button type="submit" class="btn btn-primary btn-lg sl-cta" :disabled="busy">Continue</button>
    </form>
  </AuthShell>
</template>

<style scoped>
fieldset {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

/* Each choice is a whole bordered row you can tap, not just the small radio. */
.role-row {
  display: flex;
  align-items: center;
  min-height: 3rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
}

.role-row:has(:checked) {
  border-color: var(--sl-jade);
  background: var(--sl-jade-soft);
}

.role-row:has(:focus-visible) {
  outline: 3px solid var(--sl-jade);
  outline-offset: 2px;
}

.role-row .form-check-input {
  flex: none;
  margin-left: 0.9rem;
}

.role-label {
  flex: 1;
  align-self: stretch;
  display: flex;
  align-items: center;
  padding: 0.5rem 0.9rem;
  cursor: var(--sl-cur-press);
}
</style>
