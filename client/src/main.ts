// Pinia first: imports run in order, and shared composables read its stores as they load.
import { pinia } from '@/stores/pinia';

import 'bootstrap/dist/css/bootstrap.min.css';
import '@/styles/theme.css';

import { createApp } from 'vue';

import App from '@/App.vue';
import { initAuth } from '@/composables/useAuth';
// Applies the saved zoom and light/dark choice before the first paint, so nothing flashes.
import '@/composables/useDisplay';
import router from '@/router';

initAuth(router);
// Pinia before the router: its first navigation already reads the session store (`loadMe`).
createApp(App).use(pinia).use(router).mount('#app');
