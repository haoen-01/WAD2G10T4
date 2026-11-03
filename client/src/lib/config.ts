/**
 * Build-time configuration, and the ONLY module that reads `import.meta.env`.
 *
 * Every other module imports these constants, so the pure `lib/*.ts` modules that `node --test`
 * loads never touch Vite's env object (Node has none). Only `VITE_*` keys reach the browser: the
 * API's own `AUTH_ENABLED`, `SUPABASE_URL` and secret keys in the same `.env` stay server-side.
 * These four are public by design (the Supabase key is the publishable, browser-safe one).
 */
const env = import.meta.env;

/** Sign-in is on unless explicitly switched off (the offline demo and the e2e run set `false`). */
export const AUTH_ENABLED: boolean = env.VITE_AUTH_ENABLED !== 'false';

/** The FastAPI base URL. The only other calls are the public APIs in `services/publicApis.ts`. */
export const API_BASE_URL: string = env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';

export const SUPABASE_URL: string = env.VITE_SUPABASE_URL ?? '';
export const SUPABASE_KEY: string = env.VITE_SUPABASE_PUBLISHABLE_KEY ?? '';
