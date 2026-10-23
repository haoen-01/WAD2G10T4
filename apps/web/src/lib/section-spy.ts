/**
 * Which section of a page is being read, for `SectionNav`'s highlight. Pure and import-free so
 * `section-spy.test.ts` can pin it under Node's type stripping.
 */
export interface SectionPosition {
  id: string;
  /** Distance from the top of the screen to the section's top edge, in px. */
  top: number;
  /** Distance from the top of the screen to the section's bottom edge, in px. */
  bottom: number;
}

export interface SpyView {
  /** How much of the top of the screen is covered by pinned bars, in px. */
  covered: number;
  /** The screen's height, in px. */
  height: number;
  /** Whether the page is scrolled all the way down. */
  atBottom: boolean;
  /** A section just jumped to stays highlighted while it is on screen. */
  jumpedTo?: string | null;
}

/** How far below the pinned bars a section's top counts as "reached". */
export const READING_GAP = 24;

/**
 * The section being read: of those on screen, the one whose top most recently passed just under the
 * pinned bars. At the very bottom of the page, the lowest one on screen (a short last section can
 * never reach the top). `null` before the first section has been reached.
 */
export function currentSection(sections: readonly SectionPosition[], view: SpyView): string | null {
  const onScreen = sections.filter(
    (section) => section.bottom > view.covered && section.top < view.height,
  );
  if (view.jumpedTo && onScreen.some((section) => section.id === view.jumpedTo)) {
    return view.jumpedTo;
  }
  const line = view.covered + READING_GAP;
  const pool = view.atBottom ? onScreen : onScreen.filter((section) => section.top <= line);
  if (pool.length === 0) return null;
  return pool.reduce((best, section) => (section.top > best.top ? section : best)).id;
}
