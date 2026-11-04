/**
 * The arithmetic behind the mouse-following effects (`composables/usePointerGlow.ts`): where the
 * mouse is inside a panel, whether it is near enough to light the panel's edge, and how far the
 * background glows lean towards it. Pure, so it is tested in `pointer-glow.test.ts`.
 */

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** How close (px) the mouse must be to a panel for its edge to light up. */
export const GLOW_REACH = 160;

/** The mouse's position inside a box, in that box's own pixels (it can be outside: negative). */
export function localPoint(box: Box, x: number, y: number): { x: number; y: number } {
  return { x: Math.round(x - box.left), y: Math.round(y - box.top) };
}

/** True when the point is inside the box, or within `reach` pixels of its edge. */
export function isNear(box: Box, x: number, y: number, reach = GLOW_REACH): boolean {
  const dx = Math.max(box.left - x, 0, x - (box.left + box.width));
  const dy = Math.max(box.top - y, 0, y - (box.top + box.height));
  return Math.hypot(dx, dy) <= reach;
}

/**
 * Where the mouse is across the window, from -1 (left or top edge) to 1 (right or bottom edge),
 * rounded to 3 places. The background layers move a few pixels by this, so they seem to lean.
 */
export function lean(position: number, size: number): number {
  if (size <= 0) return 0;
  const value = (position / size) * 2 - 1;
  return Math.round(Math.min(1, Math.max(-1, value)) * 1000) / 1000;
}
