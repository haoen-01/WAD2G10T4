import { createPinia, setActivePinia } from 'pinia';

/**
 * The app's one Pinia instance, active from the moment this module is imported. `main.ts` imports
 * it before anything else, because some shared composables (`useFamily`, `useWalk`, …) watch the
 * session store at module level, which runs as soon as they are imported, before `app.use` would.
 */
export const pinia = createPinia();
setActivePinia(pinia);
