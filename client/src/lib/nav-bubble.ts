/**
 * The menu's bubble (`components/ui/MainNav.vue`) moves like liquid: before it settles on the
 * link it is moving to, it first stretches to cover both that link and the one it came from.
 * This works out that stretched shape. Pure, so it is tested in `nav-bubble.test.ts`.
 */

/** A span along the menu: how far from its left edge (`x`) and how wide (`w`), in pixels. */
export interface Span {
  x: number;
  w: number;
}

/** How long (ms) the bubble stays stretched before it shrinks onto the new link. */
export const STRETCH_MS = 170;

/** The one span that covers both `from` and `to`. */
export function stretchSpan(from: Span, to: Span): Span {
  const left = Math.min(from.x, to.x);
  const right = Math.max(from.x + from.w, to.x + to.w);
  return { x: left, w: right - left };
}

/** True when the two spans are the same place (so there is nothing to stretch). */
export function sameSpan(a: Span, b: Span): boolean {
  return Math.round(a.x) === Math.round(b.x) && Math.round(a.w) === Math.round(b.w);
}
