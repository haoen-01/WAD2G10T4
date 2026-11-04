<script setup lang="ts">
import type { AuthError } from '@supabase/supabase-js';
import { computed, ref, useId } from 'vue';
import { RouterLink, useRouter } from 'vue-router';

import AuthShell from '@/components/ui/AuthShell.vue';
import Icon from '@/components/ui/Icon.vue';
import { refreshCurrentUser } from '@/composables/useAuth';
import { loadMe } from '@/composables/useMe';
import { AUTH_ENABLED } from '@/lib/config';
import { getSupabase } from '@/lib/supabase';
import { GROUP_START_PATH, parseViewMode, type ViewMode } from '@/lib/view-mode';
import { onboard } from '@/services/careApi';

/**
 * `/signup` (or `/signup/family`, `/signup/senior` to tick a choice already): create an account.
 *
 * It asks only what Care+ keeps: who you are (the senior, or family / a caregiver), your name (shown
 * to the family group), and an email and password to sign in with. Supabase holds the email and
 * password; the API records the role and name (`POST /v1/me/onboard`). When the project asks people
 * to confirm their email first there is no session yet, so that step happens on `/welcome` after
 * their first sign-in instead.
 */
const props = defineProps<{ audience?: string }>();
const router = useRouter();

const ROLES: { value: ViewMode; title: string; text: string; next: string }[] = [
  {
    value: 'senior',
    title: 'I am the senior',
    text: 'Care+ is for me.',
    next: 'Next, you show your family a code so they can join you.',
  },
  {
    value: 'family',
    title: 'I am family or a caregiver',
    text: 'I help look after a senior.',
    next: 'Next, you join your family’s group, or create one with the senior’s code.',
  },
];

const role = ref<ViewMode | null>(parseViewMode(props.audience));
const chosen = computed(() => ROLES.find((option) => option.value === role.value) ?? null);

const nameId = useId();
const emailId = useId();
const passwordId = useId();
const confirmId = useId();
const showId = useId();
const name = ref('');
const email = ref('');
const password = ref('');
const confirmPassword = ref('');
const showPassword = ref(false);
const error = ref<string | null>(null);
const loading = ref(false);
const checkInbox = ref(false);

const mismatch = computed(
  () => confirmPassword.value !== '' && confirmPassword.value !== password.value,
);

function describeSignUpError(authError: AuthError | null): string {
  const reason = authError?.message ?? '';
  if (/already registered|already exists/i.test(reason)) {
    return 'There is already an account with this email. Please sign in instead.';
  }
  if (/password/i.test(reason)) return 'Please choose a longer password (at least 8 characters).';
  if (/rate limit/i.test(reason)) return 'Too many tries. Please wait a few minutes.';
  return "We couldn't create your account. Please try again.";
}

/** The usual checks before an account is made, in plain words. `null` when all is well. */
function checkForm(): string | null {
  if (!role.value) return 'Please choose: are you the senior, or family?';
  if (!name.value.trim()) return 'Please enter your name.';
  if (!email.value.trim()) return 'Please enter your email.';
  if (password.value.length < 8) return 'Please choose a longer password (at least 8 characters).';
  if (password.value !== confirmPassword.value) return 'The two passwords are not the same.';
  return null;
}

async function submit(): Promise<void> {
  error.value = checkForm();
  if (error.value || !role.value) return;
  const mode = role.value;
  loading.value = true;
  try {
    const supabase = getSupabase();
    if (!supabase) {
      error.value = 'Sign-up is not set up in this environment.';
      return;
    }
    const { data, error: authError } = await supabase.auth.signUp({
      email: email.value.trim(),
      password: password.value,
      // Only to pre-fill `/welcome` if email confirmation is on. Not a role: roles live in the API.
      options: { data: { display_name: name.value.trim() } },
    });
    if (authError) {
      error.value = describeSignUpError(authError);
      return;
    }
    if (!data.session) {
      checkInbox.value = true;
      return;
    }
    await onboard(mode, name.value.trim());
    await refreshCurrentUser();
    await loadMe(true);
    await router.replace(mode === 'senior' ? '/senior' : GROUP_START_PATH);
  } catch {
    error.value = 'Something went wrong. Please try again.';
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthShell title="Create your account" lead="It takes about a minute.">
    <div v-if="checkInbox" class="sl-panel" role="status">
      <h2 class="h4">Check your email</h2>
      <p>
        We sent a link to <strong>{{ email }}</strong
        >. Open it to confirm your address, then sign in.
      </p>
      <RouterLink class="btn btn-primary btn-lg" :to="{ name: 'login' }">Go to sign in</RouterLink>
    </div>

    <template v-else>
      <div v-if="!AUTH_ENABLED" class="alert alert-info d-flex gap-2" role="note">
        <Icon name="info" />
        <span>
          Sign-up is switched off in this offline demo, so this form cannot be sent. To try it, run
          the app with a <code>.env</code> that has Supabase set up, or
          <RouterLink :to="{ name: 'login' }">use a demo account</RouterLink>.
        </span>
      </div>

      <form class="sl-panel" novalidate @submit.prevent="submit">
        <fieldset :disabled="!AUTH_ENABLED || loading" class="d-grid gap-4">
          <!-- Step 1: who you are. -->
          <fieldset>
            <legend class="form-label fw-bold">1. Who are you?</legend>
            <div class="row g-3">
              <div v-for="option in ROLES" :key="option.value" class="col-sm-6">
                <input
                  :id="`role-${option.value}`"
                  v-model="role"
                  class="role-input"
                  type="radio"
                  name="role"
                  :value="option.value"
                  :data-testid="`signup-role-${option.value}`"
                />
                <label :for="`role-${option.value}`" class="role-card h-100">
                  <Icon :name="option.value === 'senior' ? 'person' : 'users'" class="role-icon" />
                  <span class="role-title">{{ option.title }}</span>
                  <span class="role-text">{{ option.text }}</span>
                  <span class="role-tick"><Icon name="check" /> Chosen</span>
                </label>
              </div>
            </div>
            <p v-if="chosen" class="form-text mb-0 mt-2">{{ chosen.next }}</p>
          </fieldset>

          <!-- Step 2: your details. -->
          <fieldset class="d-grid gap-3">
            <legend class="form-label fw-bold">2. Your details</legend>
            <div>
              <label :for="nameId" class="form-label">Your name</label>
              <input
                :id="nameId"
                v-model="name"
                class="form-control form-control-lg"
                required
                maxlength="80"
                autocomplete="name"
                data-testid="signup-name"
              />
              <div class="form-text">Your family sees this name.</div>
            </div>
            <div>
              <label :for="emailId" class="form-label">Email</label>
              <input
                :id="emailId"
                v-model="email"
                class="form-control form-control-lg"
                type="email"
                required
                autocomplete="email"
                data-testid="signup-email"
              />
              <div class="form-text">You sign in with this.</div>
            </div>
          </fieldset>

          <!-- Step 3: a password. -->
          <fieldset class="d-grid gap-3">
            <legend class="form-label fw-bold">3. Choose a password</legend>
            <div>
              <label :for="passwordId" class="form-label">Password</label>
              <input
                :id="passwordId"
                v-model="password"
                class="form-control form-control-lg"
                :type="showPassword ? 'text' : 'password'"
                required
                minlength="8"
                autocomplete="new-password"
                data-testid="signup-password"
              />
              <div class="form-text">At least 8 characters.</div>
            </div>
            <div>
              <label :for="confirmId" class="form-label">Type the password again</label>
              <input
                :id="confirmId"
                v-model="confirmPassword"
                class="form-control form-control-lg"
                :class="{ 'is-invalid': mismatch }"
                :type="showPassword ? 'text' : 'password'"
                required
                autocomplete="new-password"
                data-testid="signup-confirm-password"
              />
              <div v-if="mismatch" class="invalid-feedback">
                The two passwords are not the same.
              </div>
            </div>
            <div class="form-check">
              <input :id="showId" v-model="showPassword" class="form-check-input" type="checkbox" />
              <label :for="showId" class="form-check-label">Show password</label>
            </div>
          </fieldset>

          <div v-if="error" class="alert alert-danger mb-0" role="alert">{{ error }}</div>
          <button type="submit" class="btn btn-primary btn-lg" data-testid="signup-submit">
            {{ loading ? 'Creating your account…' : 'Create account' }}
          </button>
        </fieldset>
      </form>
    </template>

    <p class="mt-4 mb-0 fs-5">
      Already have an account?
      <RouterLink :to="{ name: 'login' }" data-testid="signin-link">Sign in</RouterLink>
    </p>
  </AuthShell>
</template>

<style scoped>
/* Reset the browser's fieldset frame: Bootstrap's d-grid does the spacing. */
fieldset {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.role-input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.role-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  min-height: 3.5rem;
  padding: 1rem;
  border: 2px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  text-align: center;
  cursor: var(--sl-cur-press);
  transition: border-color var(--sl-dur-base) ease;
}

.role-card:hover {
  border-color: var(--sl-ink-soft);
}

/* Chosen: a thick border, a tinted background and a "Chosen" tick, so not colour alone. */
.role-input:checked + .role-card {
  border-width: 3px;
  border-color: var(--sl-jade);
  background: var(--sl-jade-soft);
}

.role-input:focus-visible + .role-card {
  outline: 3px solid var(--sl-jade);
  outline-offset: 2px;
}

.role-tick {
  display: none;
  font-weight: 700;
  color: var(--sl-jade-deep);
}

.role-input:checked + .role-card .role-tick {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.role-icon {
  font-size: 1.6rem;
  color: var(--sl-jade-deep);
}

.role-title {
  font-size: 1.15rem;
  font-weight: 800;
}

.role-text {
  color: var(--sl-ink-soft);
}

/* The offline demo shows the form but cannot send it: keep it legible, just clearly inactive. */
.form-control:disabled,
.form-select:disabled {
  border: 1px solid var(--sl-ink-soft);
  background-color: var(--sl-mist);
  color: var(--sl-ink-soft);
  opacity: 1;
}

.btn-primary:disabled {
  border-color: var(--sl-line);
  background: var(--sl-mist);
  color: var(--sl-ink-soft);
  opacity: 1;
}

.role-input:disabled + .role-card {
  cursor: var(--sl-cur-locked);
}
</style>
