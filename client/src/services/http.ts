import axios from 'axios';
import { ApiHttpError, type ServerErrorCode } from '@silverloop/api-client';

import { getAccessToken, onUnauthorized } from '@/composables/useAuth';
import { demoSub } from '@/composables/useViewMode';
import { API_BASE_URL, AUTH_ENABLED } from '@/lib/config';

/**
 * The one Axios instance for the Care+ API. Every screen goes through the small functions in
 * `services/careApi.ts`, which use this instance, so the base URL, the sign-in token and the error
 * handling live in one place.
 */
export const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15_000,
  // Always ask for fresh data: the demo day can change between two visits to a page.
  headers: { 'Cache-Control': 'no-store' },
});

// Request interceptor: with sign-in on, attach the signed-in person's token to every request.
// With sign-in off (the offline demo) there is no token; the demo view chosen on the sign-in page
// says whether the API should treat this browser as the demo family member or the demo senior.
http.interceptors.request.use(async (config) => {
  if (AUTH_ENABLED) {
    const token = await getAccessToken();
    if (token) config.headers.Authorization = `Bearer ${token}`;
  } else {
    const sub = demoSub();
    if (sub) config.headers['X-Demo-Sub'] = sub;
  }
  return config;
});

const SERVER_ERROR_CODES: ServerErrorCode[] = ['stored_state_incompatible', 'internal_error'];

/** The API's own words from a failed response (`{ detail }` or `{ code, message }`), if any. */
function messageOf(data: unknown, fallback: string): string {
  if (typeof data === 'string' && data) return data;
  if (data && typeof data === 'object') {
    const body = data as { detail?: unknown; message?: unknown };
    if (typeof body.detail === 'string') return body.detail;
    if (typeof body.message === 'string') return body.message;
    return JSON.stringify(data);
  }
  return fallback;
}

// Response interceptor: turn every failure into an `ApiHttpError` carrying the HTTP status
// (0 when the API could not be reached at all), so `lib/api-errors.ts` can pick the right
// plain-language message. A 401 also sends the person back to sign in.
http.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (!axios.isAxiosError(error)) return Promise.reject(error);
    const status = error.response?.status ?? 0;
    if (status === 401 && AUTH_ENABLED) onUnauthorized();
    const data: unknown = error.response?.data;
    const rawCode =
      data && typeof data === 'object' ? (data as { code?: unknown }).code : undefined;
    const code = SERVER_ERROR_CODES.find((known) => known === rawCode);
    return Promise.reject(new ApiHttpError(status, messageOf(data, error.message), code));
  },
);
