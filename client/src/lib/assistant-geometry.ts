/**
 * The Care+ assistant's body language and where it sits: where each pupil looks, when it blinks,
 * keeping it on screen, snapping it to an edge, and where its chat panel opens so it does not
 * cover more than it must. Pure, so `assistant-geometry.test.ts` can check the arithmetic.
 */

export interface Point {
  x: number;
  y: number;
}
export interface Size {
  width: number;
  height: number;
}
export interface Box extends Point, Size {}

/**
 * How far a pupil moves from the middle of its eye towards `target`: along the angle
 * `atan2(dy, dx)`, never further than `maxR`. Far away it leans fully that way; within `nearR`
 * it eases in, so a pointer right on the face is looked at, not past.
 */
export function pupilOffset(eye: Point, target: Point, maxR: number, nearR = maxR * 12): Point {
  const dx = target.x - eye.x;
  const dy = target.y - eye.y;
  const distance = Math.hypot(dx, dy);
  if (distance < 0.5) return { x: 0, y: 0 };
  const angle = Math.atan2(dy, dx);
  const reach = maxR * Math.min(1, distance / nearR);
  return { x: Math.cos(angle) * reach, y: Math.sin(angle) * reach };
}

/** Eases `from` towards `to`, a fraction `k` of the way each frame (0 < k ≤ 1). */
export function ease(from: Point, to: Point, k: number): Point {
  return { x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k };
}

/** Milliseconds until the next blink: somewhere between 3 and 7 seconds. */
export function nextBlinkMs(random: number): number {
  return 3000 + Math.max(0, Math.min(1, random)) * 4000;
}

/** Room kept clear at each edge of the screen (a phone's tab bar at the bottom, say). */
export interface Insets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/** Keeps something of `size` at `at` (its top left) fully on screen, `margin` from each edge. */
export function clampToViewport(
  at: Point,
  size: Size,
  viewport: Size,
  margin = 12,
  insets: Insets = { top: 0, right: 0, bottom: 0, left: 0 },
): Point {
  const minX = margin + insets.left;
  const minY = margin + insets.top;
  const maxX = Math.max(minX, viewport.width - size.width - margin - insets.right);
  const maxY = Math.max(minY, viewport.height - size.height - margin - insets.bottom);
  return { x: Math.min(maxX, Math.max(minX, at.x)), y: Math.min(maxY, Math.max(minY, at.y)) };
}

/** Let go within `zone` px of the left or right edge, it settles against that edge. */
export function snapToEdge(at: Point, size: Size, viewport: Size, margin = 12, zone = 96): Point {
  if (at.x <= margin + zone) return { ...at, x: margin };
  if (at.x + size.width >= viewport.width - margin - zone) {
    return { ...at, x: viewport.width - size.width - margin };
  }
  return at;
}

/**
 * Where the chat panel opens, next to the assistant and inward from the edge it is near: above it
 * if there is room, else below, else wherever it fits best; always fully on screen. `origin` is
 * the corner the panel grows from (towards the assistant), for the opening animation.
 */
export function placePanel(
  orb: Box,
  panel: Size,
  viewport: Size,
  margin = 12,
): { x: number; y: number; originX: 'left' | 'right'; originY: 'top' | 'bottom' } {
  const orbMidX = orb.x + orb.width / 2;
  const onRight = orbMidX > viewport.width / 2;
  // Line the panel's near edge up with the assistant's, so it grows out of it.
  const x = onRight ? orb.x + orb.width - panel.width : orb.x;
  const roomAbove = orb.y - margin;
  const roomBelow = viewport.height - (orb.y + orb.height) - margin;
  let y: number;
  let originY: 'top' | 'bottom';
  if (roomAbove >= panel.height + 8) {
    y = orb.y - panel.height - 8;
    originY = 'bottom';
  } else if (roomBelow >= panel.height + 8) {
    y = orb.y + orb.height + 8;
    originY = 'top';
  } else {
    // Not enough room either way: as close as it fits, covering the assistant if it must.
    y = roomAbove > roomBelow ? margin : viewport.height - panel.height - margin;
    originY = roomAbove > roomBelow ? 'bottom' : 'top';
  }
  const fitted = clampToViewport({ x, y }, panel, viewport, margin);
  return { x: fitted.x, y: fitted.y, originX: onRight ? 'right' : 'left', originY };
}

/** The panel's size: about 400 × 560 on a computer, most of the screen on a phone. */
export function panelSize(viewport: Size, margin = 12): Size {
  const width = Math.min(420, viewport.width - margin * 2);
  const height = Math.min(580, Math.round(viewport.height * 0.78), viewport.height - margin * 2);
  return { width, height };
}

/** Whether a press that moved `moved` px was a drag (not a tap). */
export const isDrag = (moved: Point, threshold = 6) => Math.hypot(moved.x, moved.y) >= threshold;
