/**
 * Confetti for the first look at a new badge: paper pieces thrown up from the bottom corners and
 * out from the medal, falling and fluttering across the whole screen, then gone. Pure (positions
 * in CSS pixels, time in seconds, randomness passed in), so `confetti.test.ts` can check it and
 * `components/badges/BadgeCelebration.vue` only draws it.
 */

export interface Piece {
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** Turn of the piece itself, and how fast it turns. */
  spin: number;
  spinRate: number;
  /** Flutter: a slow side-to-side sway as it falls. */
  sway: number;
  swayRate: number;
  w: number;
  h: number;
  colour: string;
  shape: 'paper' | 'ribbon' | 'dot';
  /** Seconds left before it fades out. */
  life: number;
}

export type Random = () => number;

/** Gravity (px/s²), how much speed air takes each second, and the fastest fall (px/s). */
export const GRAVITY = 900;
export const DRAG_KEEP_PER_S = 0.35;
export const MAX_FALL = 420;

const between = (rand: Random, low: number, high: number) => low + (high - low) * rand();

/**
 * `count` pieces thrown from (`x`, `y`) at an angle around `towards` degrees (0 = right, -90 =
 * straight up), spread over `spread` degrees, at `speed` px/s give or take a third.
 */
export function burst(
  count: number,
  x: number,
  y: number,
  towards: number,
  spread: number,
  speed: number,
  colours: readonly string[],
  rand: Random,
): Piece[] {
  return Array.from({ length: count }, () => {
    const angle = ((towards + between(rand, -spread / 2, spread / 2)) * Math.PI) / 180;
    const v = speed * between(rand, 0.66, 1.33);
    const pick = rand();
    const shape: Piece['shape'] = pick < 0.6 ? 'paper' : pick < 0.85 ? 'ribbon' : 'dot';
    const w = shape === 'ribbon' ? between(rand, 4, 6) : between(rand, 7, 12);
    return {
      x,
      y,
      vx: Math.cos(angle) * v,
      vy: Math.sin(angle) * v,
      spin: between(rand, 0, Math.PI * 2),
      spinRate: between(rand, -9, 9),
      sway: between(rand, 0, Math.PI * 2),
      swayRate: between(rand, 2, 5),
      w,
      h: shape === 'ribbon' ? between(rand, 14, 22) : shape === 'dot' ? w : w * 0.6,
      colour: colours[Math.floor(rand() * colours.length)] ?? '#f2d488',
      shape,
      life: between(rand, 2.6, 4.2),
    };
  });
}

/** A gentle fall from above the top edge, spread across the width. */
export function shower(
  count: number,
  width: number,
  colours: readonly string[],
  rand: Random,
): Piece[] {
  return Array.from({ length: count }, () => ({
    ...burst(1, between(rand, 0, width), between(rand, -120, -10), 90, 30, 60, colours, rand)[0],
    life: between(rand, 3.5, 5.5),
  }));
}

/** Moves every piece on by `dt` seconds and drops those that have faded or fallen out of view. */
export function stepPieces(pieces: readonly Piece[], dt: number, height: number): Piece[] {
  const keep = Math.pow(DRAG_KEEP_PER_S, dt);
  const out: Piece[] = [];
  for (const p of pieces) {
    const vy = Math.min(MAX_FALL, p.vy * keep + GRAVITY * dt);
    const sway = p.sway + p.swayRate * dt;
    const next: Piece = {
      ...p,
      vx: p.vx * keep,
      vy,
      x: p.x + p.vx * keep * dt + Math.sin(sway) * 30 * dt,
      y: p.y + vy * dt,
      spin: p.spin + p.spinRate * dt,
      sway,
      life: p.life - dt,
    };
    if (next.life > 0 && next.y < height + 40) out.push(next);
  }
  return out;
}

/** How visible a piece is: full, then fading over its last 0.6 s. */
export const opacityOf = (piece: Piece) => Math.max(0, Math.min(1, piece.life / 0.6));

/** A small seeded random number generator (mulberry32), so a celebration can be replayed. */
export function seeded(seed: number): Random {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
