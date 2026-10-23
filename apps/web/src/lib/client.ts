import { SilverLoopClient } from '@silverloop/api-client';

import { API_BASE_URL, AUTH_ENABLED } from './config';

/**
 * Returns an API client that optionally injects a bearer token from the provided
 * async callback, and reports 401s from any call it makes to `onUnauthorized` (see
 * `composables/useAuth.ts`). When AUTH_ENABLED is false (offline demo), neither is wired up —
 * there is no session to expire.
 *
 * Only sign-in uses this (`composables/useAuth.ts`). Screens call the API through the Axios
 * functions in `services/careApi.ts`.
 */
export function createApiClient(
  tokenProvider?: () => Promise<string | null>,
  onUnauthorized?: () => void,
): SilverLoopClient {
  return new SilverLoopClient(
    API_BASE_URL,
    AUTH_ENABLED ? tokenProvider : undefined,
    AUTH_ENABLED ? onUnauthorized : undefined,
  );
}
