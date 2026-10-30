import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';

import { useAuth } from '@/composables/useAuth';
import { activeGroups, loadMe } from '@/composables/useMe';
import { resolveViewMode } from '@/composables/useViewMode';
import AppLayout from '@/layouts/AppLayout.vue';
import { AUTH_ENABLED } from '@/lib/config';
import { loginPathFor, stringifyStrictQuery } from '@/lib/route-guard';
import { GROUP_START_PATH, homeFor, isPathInView, isViewPath } from '@/lib/view-mode';

/**
 * The whole route table: one layout, and every screen a lazy `import()` so its code loads the
 * first time it is visited. Anything else falls through to the not-found screen.
 */
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', name: 'home', component: () => import('@/views/HomeView.vue') },
      // Sign-in: `/login` asks who you are, then the family and the senior each have their own page.
      { path: 'login', name: 'login', component: () => import('@/views/LoginChooserView.vue') },
      {
        path: 'login/:audience(family|senior)',
        name: 'login-as',
        component: () => import('@/views/LoginView.vue'),
        props: true,
      },
      {
        // `/signup` asks who you are; `/signup/family` or `/signup/senior` ticks it already.
        path: 'signup/:audience(family|senior)?',
        name: 'signup',
        component: () => import('@/views/SignUpView.vue'),
        props: true,
      },
      // Signed in, but has not yet said whether they are the senior or family.
      { path: 'welcome', name: 'welcome', component: () => import('@/views/WelcomeView.vue') },
      // `/groups` on its own is easier to type and remember.
      { path: 'groups', redirect: GROUP_START_PATH },
      {
        path: 'groups/start',
        name: 'group-start',
        component: () => import('@/views/GroupStartView.vue'),
      },
      { path: 'senior', name: 'senior', component: () => import('@/views/SeniorView.vue') },
      { path: 'walk', name: 'walk', component: () => import('@/views/WalkView.vue') },
      { path: 'calendar', name: 'calendar', component: () => import('@/views/CalendarView.vue') },
      { path: 'family', name: 'family', component: () => import('@/views/FamilyView.vue') },
      // The Care Team screens were removed. Old bookmarks and shared links land on the calendar.
      { path: 'care-team/:rest(.*)*', redirect: '/calendar' },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/views/NotFoundView.vue'),
      },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
  // Strict percent-encoding, so the sign-in redirect reads `?next=%2Fcalendar`.
  stringifyQuery: stringifyStrictQuery,
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition;
    if (to.hash) return { el: to.hash };
    return { top: 0 };
  },
});

/**
 * Each view keeps to its own screens: the family gets Home, Calendar and Family, the senior gets
 * only their own screen, and asking for the other view's screen lands on your own start page. With
 * sign-in on, every screen needs a session (the sign-in link carries `?next=` back). With sign-in
 * off and no demo view chosen, every screen stays open, as it always was. The API enforces every
 * role itself, so this is a courtesy for the screen, not the security boundary.
 */
router.beforeEach(async (to) => {
  if (!isViewPath(to.path)) return true; // the sign-in pages, welcome and not-found
  const mode = await resolveViewMode();
  if (!mode) {
    if (!AUTH_ENABLED) return true;
    // Signed in but no role yet: a new account finishes signing up first.
    if (useAuth().session.value) {
      const me = await loadMe().catch(() => null);
      if (me?.needs_onboarding) return { name: 'welcome' };
    }
    return loginPathFor(to.path);
  }
  if (!isPathInView(mode, to.path)) return homeFor(mode);
  // A family member who is not yet in a family group joins or creates one first.
  if (mode === 'family' && to.path.toLowerCase() !== GROUP_START_PATH) {
    const me = await loadMe().catch(() => null);
    if (me && activeGroups(me).length === 0) return GROUP_START_PATH;
  }
  return true;
});

export default router;
