/**
 * Motion tokens for the family screens: how long things take, how they ease, how a list staggers.
 * Pure data with no imports (the components in `components/motion` read it), so it can be tested
 * under Node and costs nothing in the entry chunk. The CSS twins are `--sl-ease` and `--sl-dur-*`
 * in `styles/theme.css`.
 */

/** Seconds, as Motion for Vue takes them. */
export const DURATION = {
  /** A press or a hover. */
  fast: 0.15,
  base: 0.25,
  /** A card or list entry arriving. */
  slow: 0.4,
  /** A number counting up. */
  count: 1.1,
} as const;

/** Cubic-bezier control points; `ease` is the same curve as `--sl-ease`. */
export const EASE = {
  ease: [0.2, 0.8, 0.2, 1],
  out: [0, 0, 0.2, 1],
} as const satisfies Record<string, readonly [number, number, number, number]>;

/** A gentle spring: settles quickly and barely overshoots. */
export const SPRING = { type: 'spring', stiffness: 380, damping: 32, mass: 0.9 } as const;

/** Gap between list entries arriving, and the most any one entry may wait. */
export const STAGGER = { step: 0.06, max: 0.5 } as const;

/** Seconds an entry at `index` waits. Capped, so a long list does not take long to appear. */
export function staggerDelay(index: number, reduced = false): number {
  if (reduced || !Number.isFinite(index) || index <= 0) return 0;
  return Math.min(index * STAGGER.step, STAGGER.max);
}

/** The enter animation's start: a small rise, or only a fade when motion is reduced. */
export function enterFrom(reduced: boolean): { opacity: number; y: number } {
  return { opacity: 0, y: reduced ? 0 : 12 };
}

/** Seconds a transition lasts: `0` when motion is reduced, so the change is instant. */
export function durationFor(seconds: number, reduced: boolean): number {
  return reduced ? 0 : seconds;
}

/** When a bottom sheet dragged down is let go: far enough, or fast enough, and it closes. */
export const SHEET_DISMISS = { fraction: 0.3, velocity: 500 } as const;

/**
 * Whether a sheet released after a downward drag should close. `offset` is how far it was pulled
 * down (px), `velocity` how fast it was moving down (px/s) and `height` its own height (px);
 * pulling up, or a sheet with no measurable height, never closes it.
 */
export function shouldDismissSheet(offset: number, velocity: number, height: number): boolean {
  if (!(height > 0) || !(offset > 0)) return false;
  return offset >= height * SHEET_DISMISS.fraction || velocity >= SHEET_DISMISS.velocity;
}
