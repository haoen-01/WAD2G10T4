import 'bootstrap/dist/css/bootstrap.min.css';
import '@/styles/theme.css';

import { createApp } from 'vue';

import App from '@/App.vue';
import { initAuth } from '@/composables/useAuth';
// Applies the saved zoom and light/dark choice before the first paint, so nothing flashes.
import '@/composables/useDisplay';
import router from '@/router';

initAuth(router);
createApp(App).use(router).mount('#app');
