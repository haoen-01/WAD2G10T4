<script setup lang="ts">
import { ApiHttpError, type CurrentUser } from '@silverloop/api-client';
import type { AuthError } from '@supabase/supabase-js';
import { computed, ref, useId } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import { useAuth } from '@/composables/useAuth';
import { useViewMode } from '@/composables/useViewMode';
import { AUTH_ENABLED } from '@/lib/config';
import { safeNextPath } from '@/lib/route-guard';
import { getSupabase } from '@/lib/supabase';
import { homeFor, isPathInView, parseViewMode, viewForRole, type ViewMode } from '@/lib/view-mode';
import { getMe } from '@/services/careApi';

/** `/login/family` or `/login/senior`: each view has its own sign-in page. */
const props = defineProps<{ audience: string }>();
const audience = computed<ViewMode>(() => parseViewMode(props.audience) ?? 'family');
const other = computed<ViewMode>(() => (audience.value === 'family' ? 'senior' : 'family'));

const COPY: Record<ViewMode, { title: string; lead: string; side: string }> = {
  family: {
    title: 'Family sign-in',
    lead: 'See how she is doing, share the calendar and arrange who goes along.',
    side: 'Everyday activity, shared only with the people she chooses.',
  },
  senior: {
    title: 'Welcome back.',
    lead: 'Sign in to see your day.',
    side: 'Your day at a glance: your steps, a suggestion and what is planned.',
  },
};
const copy = computed(() => COPY[audience.value]);

/**
 * Supabase's auth error text is provider-generated ("Invalid login credentials",
 * "Email not confirmed", "Request rate limit reached", …) and not written for
 * this product's audience. Map the cases we know about to plain-language,
 * actionable copy; keep an honest generic fallback for anything unmapped rather
 * than inventing a specific cause we can't confirm.
 */
function describeAuthError(authError: AuthError | null): string {
  const reason = authError?.message ?? '';
  if (/invalid login credentials/i.test(reason)) {
    return "That email or password doesn't match. Please check and try again.";
  }
  if (/email not confirmed/i.test(reason)) {
    return 'Please confirm your email address first — check your inbox for the confirmation link.';
  }
  if (/rate limit/i.test(reason)) {
    return "You've tried to sign in too many times. Please wait a few minutes and try again.";
  }
  return "We couldn't sign you in. Please try again.";
}

const route = useRoute();
const router = useRouter();
const { loadCurrentUser } = useAuth();
const { chooseDemoView } = useViewMode();

/** Where to go once in: the `?next=` page when it belongs to this view, else the view's start. */
function destinationFor(mode: ViewMode): string {
  const next = route.query.next;
  const safeNext = safeNextPath(Array.isArray(next) ? next[0] : next);
  return safeNext && isPathInView(mode, safeNext) ? safeNext : homeFor(mode);
}

/** Sign-in off (the offline demo): no account to check, so just enter this view. */
async function continueAsDemo(): Promise<void> {
  chooseDemoView(audience.value);
  await router.replace(destinationFor(audience.value));
}

const emailId = useId();
const passwordId = useId();
const email = ref('');
const password = ref('');
const error = ref<string | null>(null);
const loading = ref(false);

// Small comforts for a fiddly form: see what you typed, and know when Caps Lock is on.
const showPassword = ref(false);
const capsLock = ref(false);
function checkCaps(event: KeyboardEvent) {
  capsLock.value = event.getModifierState?.('CapsLock') ?? false;
}

async function handleSubmit(): Promise<void> {
  error.value = null;
  loading.value = true;
  try {
    const supabase = getSupabase();
    if (!supabase) {
      error.value = 'Sign-in is not set up in this environment.';
      return;
    }

    const { data, error: authError } = await supabase.auth.signInWithPassword({
      email: email.value,
      password: password.value,
    });

    if (authError || !data.session) {
      error.value = describeAuthError(authError ?? null);
      return;
    }

    // Shared with the session listener, which reads the same account on its `SIGNED_IN` event: one
    // `GET /v1/auth/me` for the two of them.
    let currentUser: CurrentUser;
    try {
      currentUser = await loadCurrentUser(data.session.access_token);
    } catch (caught) {
      // An HTTP answer means the API is reachable and does not know this account; anything else
      // (the API unreachable) is the generic failure below.
      if (!(caught instanceof ApiHttpError) || caught.status === 0) throw caught;
      // A new account that has not said yet whether it is the senior or family finishes that first.
      const me = await getMe().catch(() => null);
      if (me?.needs_onboarding) {
        await router.replace({ name: 'welcome', query: { as: audience.value } });
        return;
      }
      error.value = 'Account not provisioned in this application.';
      await supabase.auth.signOut();
      return;
    }

    // A senior account cannot open the family view, nor a family account the senior's.
    const mode = viewForRole(currentUser.role);
    if (mode !== audience.value) {
      error.value =
        mode === 'senior'
          ? 'This is a senior account. Please use the senior sign-in instead.'
          : mode === 'family'
            ? 'This is a family account. Please use the family sign-in instead.'
            : 'Account not provisioned in this application.';
      await supabase.auth.signOut();
      return;
    }

    await router.replace(destinationFor(mode));
  } catch {
    error.value = 'An unexpected error occurred. Please try again.';
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login">
    <aside class="login-side" aria-hidden="true">
      <svg class="login-loop" viewBox="0 0 200 200">
        <circle
          cx="100"
          cy="100"
          r="78"
          fill="none"
          stroke="rgb(255 255 255 / 18%)"
          stroke-width="22"
        />
        <circle
          cx="100"
          cy="100"
          r="78"
          fill="none"
          stroke="var(--sl-sun)"
          stroke-width="22"
          stroke-linecap="round"
          stroke-dasharray="360 490"
          transform="rotate(-90 100 100)"
        />
      </svg>
      <p class="login-side-text">{{ copy.side }}</p>
    </aside>

    <div class="login-main">
      <header class="mb-4">
        <h1>{{ copy.title }}</h1>
        <p class="text-body-secondary mt-2 mb-0">{{ copy.lead }}</p>
      </header>

      <div v-if="!AUTH_ENABLED" class="sl-panel d-grid gap-3">
        <p class="mb-0">Sign-in is switched off in this demo, so there is no password to enter.</p>
        <button
          type="button"
          class="btn btn-primary btn-lg"
          :data-testid="`continue-${audience}`"
          @click="continueAsDemo"
        >
          Continue as {{ audience === 'family' ? 'family' : 'the senior' }}
        </button>
      </div>

      <form v-else class="sl-panel d-grid gap-4" @submit.prevent="handleSubmit">
        <div>
          <label :for="emailId" class="form-label">Email</label>
          <input
            :id="emailId"
            v-model="email"
            class="form-control form-control-lg"
            type="email"
            required
            autocomplete="email"
          />
        </div>
        <div>
          <label :for="passwordId" class="form-label">Password</label>
          <div class="pw">
            <input
              :id="passwordId"
              v-model="password"
              class="form-control form-control-lg"
              :type="showPassword ? 'text' : 'password'"
              required
              autocomplete="current-password"
              @keyup="checkCaps"
              @keydown="checkCaps"
            />
            <button
              type="button"
              class="btn btn-quiet pw-toggle"
              :aria-label="showPassword ? 'Hide password' : 'Show password'"
              :aria-controls="passwordId"
              @click="showPassword = !showPassword"
            >
              <Icon :name="showPassword ? 'eye-off' : 'eye'" class="me-1" />
              {{ showPassword ? 'Hide' : 'Show' }}
            </button>
          </div>
          <p v-if="capsLock" class="caps mb-0" role="status">Caps Lock is on.</p>
        </div>
        <div v-if="error" class="alert alert-danger mb-0" role="alert">{{ error }}</div>
        <button type="submit" class="btn btn-primary btn-lg" :disabled="loading">
          <span
            v-if="loading"
            class="spinner-border spinner-border-sm me-2"
            aria-hidden="true"
          ></span>
          {{ loading ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>

      <p class="mt-4 mb-0 fs-5">
        New to Care+?
        <RouterLink :to="{ name: 'signup', params: { audience } }" data-testid="signup-link">
          Create an account
        </RouterLink>
      </p>
      <p class="mt-3 mb-0">
        <RouterLink :to="{ name: 'login-as', params: { audience: other }, query: route.query }">
          {{ other === 'senior' ? 'Are you the senior? Sign in here' : 'Family? Sign in here' }}
        </RouterLink>
      </p>
    </div>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  gap: 2rem;
  max-width: 60rem;
  margin: 0 auto;
}

@media (min-width: 992px) {
  .login {
    grid-template-columns: 1fr 1.1fr;
    align-items: center;
    gap: 3rem;
  }
}

.login-side {
  display: none;
}

@media (min-width: 992px) {
  .login-side {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 26rem;
    padding: 2.5rem;
    border-radius: var(--sl-radius);
    background: var(--sl-jade);
    color: #fff;
  }
}

.login-loop {
  width: 9rem;
  height: 9rem;
}

.login-side-text {
  max-width: 18rem;
  margin: 0;
  font-size: 1.6rem;
  font-weight: 700;
  line-height: 1.25;
}

.login-main h1 {
  font-size: clamp(2rem, 5vw, 2.8rem);
  font-weight: 800;
}

.pw {
  position: relative;
}

.pw .form-control {
  padding-right: 6.5rem;
}

.pw-toggle {
  position: absolute;
  top: 50%;
  right: 0.35rem;
  transform: translateY(-50%);
}

.caps {
  margin-top: 0.4rem;
  color: var(--sl-coral-deep);
  font-weight: 600;
}
</style>
