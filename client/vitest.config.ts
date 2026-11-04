import { defineConfig, mergeConfig } from 'vitest/config';

import viteConfig from './vite.config.ts';

// The Pinia stores' tests (`src/stores/*.spec.ts`). They run under Vitest, with the app's own Vite
// config, so the `@/` alias and `import.meta.env` work as in the app; each test gets its own Pinia.
// The pure `src/lib/*.test.ts` modules keep running on `node --test` (see `pnpm test`).
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      include: ['src/stores/**/*.spec.ts'],
      environment: 'node',
    },
  }),
);
