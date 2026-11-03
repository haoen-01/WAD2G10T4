import { createClient, type SupabaseClient } from '@supabase/supabase-js';

import { AUTH_ENABLED, SUPABASE_KEY, SUPABASE_URL } from './config';

let client: SupabaseClient | null | undefined;

/**
 * The browser's Supabase client, or `null` when sign-in is off or no Supabase URL is configured.
 * Memoised: one client, so one session listener.
 *
 * Supabase is used for SIGN-IN AND THE SESSION ONLY. Every domain read and write goes through the
 * FastAPI via `@silverloop/api-client`; the database denies `anon` and `authenticated` outright,
 * so there is nothing here to query and no table access anywhere in this app.
 *
 * `detectSessionInUrl` is off because password sign-in is the only flow: a URL hash such as
 * `#care-team-group-…` must never be parsed as a session. The session is kept in the library's
 * default `localStorage`.
 */
export function getSupabase(): SupabaseClient | null {
  if (client !== undefined) return client;
  client =
    AUTH_ENABLED && SUPABASE_URL
      ? createClient(SUPABASE_URL, SUPABASE_KEY || 'placeholder', {
          auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
        })
      : null;
  return client;
}
