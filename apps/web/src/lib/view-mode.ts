/**
 * The two views of Care+: the family's (Home, Calendar, Family) and the senior's own (one screen,
 * `/senior`). Which one someone gets follows from how they signed in. Pure and import-free so
 * `lib/view-mode.test.ts` can pin it under Node's type stripping.
 *
 * A family account has the API's `family` role. The provisioned `coordinator` and `demo_operator`
 * accounts see the family view too. Like the route guard, this is a courtesy for the screen, not
 * the security boundary: every API route checks the role itself.
 */
export type ViewMode = 'family' | 'senior';

export const VIEW_MODES: readonly ViewMode[] = ['family', 'senior'];

/** The screens each view may open. The first one is where that view starts. */
export const VIEW_PATHS: Record<ViewMode, readonly string[]> = {
  // `/groups/start` (or `/groups`): join or create a family group. Reached from the Family page;
  // the guard also sends a family member there until they are in a group.
  family: ['/', '/calendar', '/family', '/groups'],
  senior: ['/senior'],
};

/** Which view an API role gets, or `null` for a role this app does not know. */
export function viewForRole(role: string | null | undefined): ViewMode | null {
  if (role === 'senior') return 'senior';
  if (role === 'family' || role === 'coordinator' || role === 'demo_operator') return 'family';
  return null;
}

/** Where a view starts. */
export function homeFor(mode: ViewMode): string {
  return VIEW_PATHS[mode][0];
}

/**
 * Whether `pathname` belongs to `mode`. Whole path segments, ignoring case (the router matches
 * paths case-insensitively), and `/` matches only itself.
 */
export function isPathInView(mode: ViewMode, pathname: string): boolean {
  const path = pathname.toLowerCase();
  return VIEW_PATHS[mode].some((prefix) =>
    prefix === '/' ? path === '/' : path === prefix || path.startsWith(`${prefix}/`),
  );
}

/** Whether `pathname` belongs to any view (anything else is a sign-in page or not found). */
export function isViewPath(pathname: string): boolean {
  return VIEW_MODES.some((mode) => isPathInView(mode, pathname));
}

/** The sign-in and sign-up pages: `/login`, one sign-in page per view, and `/signup` (`/signup/…`). */
export function isLoginPath(pathname: string): boolean {
  const path = pathname.toLowerCase();
  return (
    path === '/login' ||
    path.startsWith('/login/') ||
    path === '/signup' ||
    path.startsWith('/signup/')
  );
}

/** Where a family member joins or creates a family group. */
export const GROUP_START_PATH = '/groups/start';

/** `'family'` or `'senior'` from untrusted text (a stored value, a route param), else `null`. */
export function parseViewMode(raw: unknown): ViewMode | null {
  return raw === 'family' || raw === 'senior' ? raw : null;
}
