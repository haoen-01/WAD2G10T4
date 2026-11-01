import { computed, onBeforeUnmount, shallowRef } from 'vue';

import {
  DEG_PER_PX,
  faceFront,
  isMoving,
  release,
  resting,
  stepSpin,
  turnOver,
  type Spin,
} from '@/lib/coin-spin';

/**
 * Runs a medal's turn (`lib/coin-spin.ts`) each animation frame, and turns a drag across it into
 * a spin: a press that moves more than a few pixels sideways is a drag, anything less is a tap.
 * Frames stop when nothing moves. For someone who asked for less motion nothing turns by itself,
 * and a let-go medal lands on its face at once.
 */
const DRAG_START_PX = 6;

export function useCoinSpin() {
  const spin = shallowRef<Spin>(resting());
  const angle = computed(() => spin.value.angle);
  const dragging = computed(() => spin.value.mode === 'drag');
  let frame = 0;
  let last = 0;

  const reduced = () =>
    typeof window !== 'undefined' &&
    (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);

  function tick(time: number) {
    const dt = last ? Math.min(0.05, (time - last) / 1000) : 0;
    last = time;
    spin.value = stepSpin(spin.value, dt);
    frame = isMoving(spin.value) ? requestAnimationFrame(tick) : 0;
  }

  function set(next: Spin) {
    // Less motion: anything heading for a face lands there at once.
    if (reduced() && next.mode === 'settle') next = resting(next.target);
    spin.value = next;
    if (isMoving(next) && !frame) {
      last = 0;
      frame = requestAnimationFrame(tick);
    }
  }

  /** The slow turn, while the pointer rests on the medal. */
  function auto() {
    if (reduced() || spin.value.mode === 'drag') return;
    set({ ...spin.value, mode: 'auto' });
  }
  /** Back to the front, finishing the turn it is on. */
  function front() {
    if (spin.value.mode === 'drag') return;
    if (spin.value.mode === 'idle' && spin.value.angle % 360 === 0) return;
    set(faceFront(spin.value));
  }
  function turn() {
    set(turnOver(spin.value));
  }
  /** Full turns as the medal arrives (one usually; more to celebrate). */
  function flourish(turns = 1) {
    if (reduced()) return;
    set({ ...resting(0), mode: 'settle', target: 360 * turns });
  }
  function reset() {
    set(resting(0));
  }

  // ---- Dragging ----

  let press: {
    id: number;
    x: number;
    from: number;
    moved: boolean;
    lastX: number;
    lastT: number;
    velocity: number;
  } | null = null;

  function down(event: PointerEvent) {
    if (event.button !== 0) return;
    press = {
      id: event.pointerId,
      x: event.clientX,
      from: spin.value.angle,
      moved: false,
      lastX: event.clientX,
      lastT: event.timeStamp,
      velocity: 0,
    };
  }

  function move(event: PointerEvent) {
    if (!press || event.pointerId !== press.id) return;
    const dx = event.clientX - press.x;
    if (!press.moved) {
      if (Math.abs(dx) < DRAG_START_PX) return;
      press.moved = true;
      (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    }
    const dt = Math.max(1, event.timeStamp - press.lastT) / 1000;
    const instant = ((event.clientX - press.lastX) * DEG_PER_PX) / dt;
    press.velocity = press.velocity * 0.6 + instant * 0.4;
    press.lastX = event.clientX;
    press.lastT = event.timeStamp;
    set({ ...spin.value, mode: 'drag', velocity: 0, angle: press.from + dx * DEG_PER_PX });
  }

  /** Ends a press. True if it was a drag (so the tap it would otherwise be is ignored). */
  function up(event: PointerEvent): boolean {
    if (!press || event.pointerId !== press.id) return false;
    const was = press;
    press = null;
    if (!was.moved) return false;
    // A hand that stopped before letting go has no speed left.
    const still = event.timeStamp - was.lastT > 80;
    set(release(spin.value, still || reduced() ? 0 : was.velocity));
    return true;
  }

  onBeforeUnmount(() => {
    if (frame) cancelAnimationFrame(frame);
  });

  return { angle, dragging, auto, front, turn, flourish, reset, down, move, up };
}
