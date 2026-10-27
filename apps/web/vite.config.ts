import { fileURLToPath, URL } from 'node:url';
import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vite';

const port = process.env.E2E_WEB_PORT ?? 'dev';

export default defineConfig({
  plugins: [vue()],
  // Repo-root .env (the same file the API reads). Only VITE_* keys reach browser code; never change envPrefix.
  envDir: fileURLToPath(new URL('../..', import.meta.url)),
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { host: '127.0.0.1', port: 3000, strictPort: true },
  preview: { host: '127.0.0.1', port: 3000, strictPort: true },
  // Several dev servers can run at once (parallel e2e runs): one dep cache per port, and listing the
  // deps up front stops the mid-test "optimized dependencies changed, reloading" flake.
  cacheDir: `node_modules/.vite/${port}`,
  optimizeDeps: { include: ['vue', 'vue-router', '@supabase/supabase-js', 'maplibre-gl'] },
});
