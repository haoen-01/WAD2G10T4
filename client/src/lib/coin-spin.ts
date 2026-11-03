/**
 * How a badge medal turns: slowly by itself, by hand (drag and let go, and it coasts), and then
 * settling face on, front or back, like a coin coming to rest. Pure, so `coin-spin.test.ts` can
 * check it; `composables/useCoinSpin.ts` runs it each animation frame.
 *
 * Angles are degrees about the upright axis: 0 is the front facing her, 180 the back.
 */

export type SpinMode = 'idle' | 'auto' | 'drag' | 'coast' | 'settle';

export interface Spin {
  angle: number;
  /** Degrees per second, while coasting. */
  velocity: number;
  mode: SpinMode;
  /** Where a settle is heading. */
  target: number;
}

/** The slow turn on hover: about one turn every seven seconds. */
export const AUTO_DEG_PER_S = 360 / 7;
/** Below this, a coasting medal stops turning freely and settles onto a face. */
export const SETTLE_BELOW_DEG_PER_S = 90;
/** How much of its speed a coasting medal keeps each second. */
export const COAST_KEEP_PER_S = 0.05;
/** Degrees turned per pixel dragged. */
export const DEG_PER_PX = 0.9;

export const resting = (angle = 0): Spin => ({ angle, velocity: 0, mode: 'idle', target: angle });

/** The face (a multiple of 180) a medal turning in `direction` comes to rest on. */
export function nearestFace(angle: number, direction = 0): number {
  const faces = angle / 180;
  const face =
    direction > 0
      ? Math.ceil(faces - 0.25)
      : direction < 0
        ? Math.floor(faces + 0.25)
        : Math.round(faces);
  return face * 180 + 0; // + 0 turns -0 into 0
}

/** The front (a multiple of 360) ahead of `angle`, so a turn finishes the way it was going. */
export function frontAhead(angle: number): number {
  return Math.ceil(angle / 360 - 1e-6) * 360 + 0;
}

/** One animation frame of `dt` seconds. */
export function stepSpin(spin: Spin, dt: number): Spin {
  switch (spin.mode) {
    case 'auto':
      return { ...spin, angle: spin.angle + AUTO_DEG_PER_S * dt };
    case 'coast': {
      const velocity = spin.velocity * Math.pow(COAST_KEEP_PER_S, dt);
      const angle = spin.angle + velocity * dt;
      if (Math.abs(velocity) < SETTLE_BELOW_DEG_PER_S) {
        return { angle, velocity: 0, mode: 'settle', target: nearestFace(angle, velocity) };
      }
      return { ...spin, angle, velocity };
    }
    case 'settle': {
      const gap = spin.target - spin.angle;
      if (Math.abs(gap) < 0.3) return resting(spin.target);
      return { ...spin, angle: spin.angle + gap * Math.min(1, dt * 7) };
    }
    default:
      return spin;
  }
}

/** Whether anything is moving (so frames can stop when nothing is). */
export const isMoving = (spin: Spin) => spin.mode !== 'idle' && spin.mode !== 'drag';

/** Let go after a drag: coast at the speed of the hand, or settle if it was barely moving. */
export function release(spin: Spin, velocity: number): Spin {
  if (Math.abs(velocity) < SETTLE_BELOW_DEG_PER_S) {
    return { ...spin, velocity: 0, mode: 'settle', target: nearestFace(spin.angle) };
  }
  return { ...spin, velocity, mode: 'coast' };
}

/** Half a turn to the other face (the button that does what the drag does). */
export function turnOver(spin: Spin): Spin {
  const from = spin.mode === 'settle' ? spin.target : nearestFace(spin.angle);
  return { ...spin, velocity: 0, mode: 'settle', target: from + 180 };
}

/** Back to the front, finishing the turn it was on. */
export function faceFront(spin: Spin): Spin {
  return { ...spin, velocity: 0, mode: 'settle', target: frontAhead(spin.angle) };
}
