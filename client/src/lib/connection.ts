/**
 * The decisions behind the connection panel ("Can't connect to Care+ right now",
 * `composables/useConnection.ts`), kept pure and import-free so `lib/connection.test.ts` can pin
 * them under Node's type stripping. The composable only wires them to the router and Vue state.
 */

/**
 * Counts the router guard's runs, so a result that arrives late can tell whether it still belongs
 * to the navigation in progress. Every `beforeEach` run starts a new generation (a redirect runs
 * the guard again, so it starts one too); anything that captured an older generation has been
 * overtaken by a newer navigation.
 */
export interface NavigationGenerations {
  /** A guard run starts: its generation. It is the one waiting until it returns or is overtaken. */
  begin(): number;
  /** The newest generation started so far (0 before any). */
  latest(): number;
  /** Whether nothing newer has started since `generation` was captured. */
  isCurrent(generation: number): boolean;
  /** That guard run has returned (allowed, redirected, stopped or reported). */
  finish(generation: number): void;
  /**
   * A navigation that ran no guard cancelled the one waiting: a new generation that belongs to no
   * guard run, so after it nothing is waiting.
   */
  overtake(): void;
  /** Whether a guard run is waiting (on `/v1/me`, say) that a navigation would still cancel. */
  waiting(): boolean;
}

export function createNavigationGenerations(): NavigationGenerations {
  let latest = 0;
  /** The guard run that is waiting, or null: none, it returned, or it was cancelled. */
  let waitingRun: number | null = null;
  return {
    begin: () => {
      latest += 1;
      waitingRun = latest;
      return latest;
    },
    latest: () => latest,
    isCurrent: (generation) => generation === latest,
    finish: (generation) => {
      if (generation === waitingRun) waitingRun = null;
    },
    overtake: () => {
      latest += 1;
      waitingRun = null;
    },
    waiting: () => waitingRun !== null,
  };
}

/**
 * From the router's `afterEach`: whether a finished navigation overtakes a guard still waiting
 * even though no guard ran for it. A push to the screen already showing (a duplicated navigation,
 * such as pressing the current screen's tab) skips `beforeEach`, yet the router still cancels the
 * navigation in progress for it; so it must overtake it (`NavigationGenerations.overtake`), or that cancelled guard could
 * still show the panel and point Try again at the screen the person left. With no guard waiting
 * it cancels nothing, so it changes nothing: a Try again still waiting on its own reads carries on.
 */
export function overtakesWithoutGuard(input: {
  duplicated: boolean;
  generations: NavigationGenerations;
}): boolean {
  return input.duplicated && input.generations.waiting();
}

/**
 * Whether a guard that found Care+ unreachable may still show the panel: only while its own
 * navigation is the newest one. A guard overtaken by a newer navigation (someone signed out or
 * went elsewhere while its request was still waiting, up to the 15 s timeout) must not cover the
 * newer screen with the panel, nor point Try again at the screen they left.
 */
export function mayReport(generation: number, generations: NavigationGenerations): boolean {
  return generations.isCurrent(generation);
}

/**
 * Whether "Try again" may go on to reopen the screen it was pressed on, after its reads have come
 * back: only if the panel is still showing and no navigation has started since it was pressed.
 * Otherwise the person has moved on (signed out, gone back, opened another screen) and the retry
 * must not pull them back.
 */
export function mayContinueRetry(input: {
  startedAt: number;
  generations: NavigationGenerations;
  panelShowing: boolean;
}): boolean {
  return input.panelShowing && input.generations.isCurrent(input.startedAt);
}

/**
 * From the router's `afterEach`: whether the panel gives way now that a navigation has finished.
 * Only for a navigation that was committed (not failed or cancelled) and that the guard did not
 * itself find Care+ unreachable for; and only if the panel is showing at all.
 */
export function shouldClearAfterNavigation(input: {
  failed: boolean;
  panelShowing: boolean;
  reportedForThisNavigation: boolean;
}): boolean {
  return !input.failed && input.panelShowing && !input.reportedForThisNavigation;
}
