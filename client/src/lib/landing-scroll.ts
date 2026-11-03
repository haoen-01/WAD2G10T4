/**
 * The arithmetic of the landing page's scroll story (`components/landing/LandingStory.vue`). Each
 * part of the story is a tall section with a "stage" pinned (`position: sticky`) inside it; how far
 * the reader has scrolled through the section, 0 to 1, drives everything on the stage. Pure, so
 * `lib/landing-scroll.test.ts` can run it under Node's type stripping.
 */

/** Keeps a number between 0 and 1. */
export function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/**
 * How far through a pinned section the reader is: 0 when its top reaches the pin line (the
 * bottom of the header), 1 when its bottom is about to push the stage away.
 * `top` and `height` are the section's box on screen, `stage` the pinned stage's height.
 */
export function sectionProgress(top: number, height: number, stage: number, pinTop = 0): number {
  const travel = height - stage;
  if (travel <= 0) return top <= pinTop ? 1 : 0;
  return clamp01((pinTop - top) / travel);
}

/**
 * The app tour shows `count` screens in a row. Each one rests in the middle for the first half of
 * its share of the scroll, then glides to the next (smoothstep easing). Returns 0 to 1 along the
 * row.
 */
export function holdThenMove(progress: number, count: number): number {
  if (count < 2) return 0;
  const along = clamp01(progress) * (count - 1);
  const index = Math.min(count - 2, Math.floor(along));
  const t = clamp01((along - index - 0.5) / 0.5);
  const eased = t * t * (3 - 2 * t);
  return (index + eased) / (count - 1);
}

/** Which screen (1 to `count`) is in the middle of the row. */
export function shotNumber(row: number, count: number): number {
  if (count < 1) return 0;
  return Math.round(clamp01(row) * (count - 1)) + 1;
}

/** The phone's step counter as the card fills: from `from` up to `to`. */
export function countUp(fill: number, from: number, to: number): number {
  return Math.round(from + (to - from) * clamp01(fill));
}
