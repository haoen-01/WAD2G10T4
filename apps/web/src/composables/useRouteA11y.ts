import { nextTick, onBeforeUnmount, ref } from 'vue';
import { START_LOCATION, useRouter } from 'vue-router';

/**
 * What a single-page app must do by hand after a route change, since the browser does nothing:
 *
 * - tell a screen reader where it now is (`message`, rendered in a live region by
 *   `RouteAnnouncer.vue`), from the new page's `<h1>`;
 * - put keyboard focus somewhere sensible, but only when focus has been left on `<body>` (the
 *   control that was pressed was removed with the old page). Focus that is still on a working
 *   control, such as the nav link just pressed, is left alone. A view that focuses its own heading
 *   after its data arrives runs later and wins.
 *
 * The first navigation (the page load itself) and navigations that change only the query string or
 * hash are not announced: they are the same page.
 */
export function useRouteA11y() {
  const router = useRouter();
  const message = ref('');

  const stop = router.afterEach((to, from, failure) => {
    if (failure || from === START_LOCATION || to.path === from.path) return;
    // After the new view has rendered, so its heading exists.
    void nextTick().then(async () => {
      const heading = document.querySelector('h1')?.textContent?.trim();
      // Cleared first, so two pages with the same heading (one case, then another) still change
      // the live region's text and are announced.
      message.value = '';
      await nextTick();
      message.value = `Navigated to ${heading || document.title}`;
      if (document.activeElement === document.body || document.activeElement === null) {
        const main = document.getElementById('main') ?? document.querySelector('main');
        main?.focus({ preventScroll: true });
      }
    });
  });
  onBeforeUnmount(stop);

  return { message };
}
