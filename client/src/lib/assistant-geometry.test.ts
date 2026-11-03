import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  clampToViewport,
  ease,
  isDrag,
  nextBlinkMs,
  panelSize,
  placePanel,
  pupilOffset,
  snapToEdge,
} from './assistant-geometry';

const close = (a: number, b: number) => Math.abs(a - b) < 1e-9;

describe('eye tracking', () => {
  it('leans the pupil fully towards a far pointer, never past the edge of the eye', () => {
    const right = pupilOffset({ x: 0, y: 0 }, { x: 500, y: 0 }, 4);
    assert.ok(close(right.x, 4) && close(right.y, 0));
    const up = pupilOffset({ x: 0, y: 0 }, { x: 0, y: -900 }, 4);
    assert.ok(close(up.x, 0) && close(up.y, -4));
    const diagonal = pupilOffset({ x: 10, y: 10 }, { x: 1010, y: 1010 }, 4);
    assert.ok(close(Math.hypot(diagonal.x, diagonal.y), 4));
  });

  it('uses the angle from the eye to the pointer (atan2)', () => {
    const p = pupilOffset({ x: 0, y: 0 }, { x: 300, y: 400 }, 5, 10);
    assert.ok(close(p.x, 3) && close(p.y, 4));
  });

  it('eases in near the face, so a close pointer is looked at, not past', () => {
    const near = pupilOffset({ x: 0, y: 0 }, { x: 12, y: 0 }, 4, 48);
    assert.ok(close(near.x, 1));
    assert.deepEqual(pupilOffset({ x: 3, y: 3 }, { x: 3, y: 3 }, 4), { x: 0, y: 0 });
  });

  it('moves smoothly towards where it is looking', () => {
    assert.deepEqual(ease({ x: 0, y: 0 }, { x: 10, y: -10 }, 0.25), { x: 2.5, y: -2.5 });
  });

  it('blinks every 3 to 7 seconds', () => {
    assert.equal(nextBlinkMs(0), 3000);
    assert.equal(nextBlinkMs(1), 7000);
    assert.equal(nextBlinkMs(5), 7000);
  });
});

describe('where the assistant sits', () => {
  const screen = { width: 400, height: 800 };
  const orb = { width: 64, height: 64 };

  it('stays on screen, clear of a tab bar', () => {
    assert.deepEqual(
      clampToViewport({ x: -50, y: 900 }, orb, screen, 12, {
        top: 0,
        right: 0,
        bottom: 80,
        left: 0,
      }),
      {
        x: 12,
        y: 800 - 64 - 12 - 80,
      },
    );
    assert.deepEqual(clampToViewport({ x: 100, y: 100 }, orb, screen), { x: 100, y: 100 });
  });

  it('snaps to the nearer side edge when let go close to it', () => {
    assert.equal(snapToEdge({ x: 40, y: 300 }, orb, screen).x, 12);
    assert.equal(snapToEdge({ x: 300, y: 300 }, orb, screen).x, 400 - 64 - 12);
    assert.equal(snapToEdge({ x: 170, y: 300 }, orb, screen).x, 170);
  });

  it('tells a drag from a tap', () => {
    assert.equal(isDrag({ x: 2, y: 3 }), false);
    assert.equal(isDrag({ x: 6, y: 0 }), true);
  });
});

describe('where the chat panel opens', () => {
  const screen = { width: 1280, height: 800 };
  const size = { width: 400, height: 560 };

  it('opens above the assistant in the bottom right, growing out of it', () => {
    const at = placePanel({ x: 1190, y: 710, width: 64, height: 64 }, size, screen);
    assert.deepEqual(at, { x: 1254 - 400, y: 710 - 560 - 8, originX: 'right', originY: 'bottom' });
  });

  it('opens below when the assistant is near the top, and inward from the left edge', () => {
    const at = placePanel({ x: 12, y: 40, width: 64, height: 64 }, size, screen);
    assert.deepEqual(at, { x: 12, y: 112, originX: 'left', originY: 'top' });
  });

  it('fits on a small screen however the assistant is placed', () => {
    const phone = { width: 375, height: 667 };
    const fitted = panelSize(phone);
    assert.deepEqual(fitted, { width: 351, height: 520 });
    const at = placePanel({ x: 150, y: 300, width: 64, height: 64 }, fitted, phone);
    assert.ok(at.x >= 12 && at.x + fitted.width <= 375 - 12);
    assert.ok(at.y >= 12 && at.y + fitted.height <= 667 - 12);
  });

  it('is about 420 × 580 on a computer', () => {
    assert.deepEqual(panelSize({ width: 1440, height: 900 }), { width: 420, height: 580 });
  });
});
