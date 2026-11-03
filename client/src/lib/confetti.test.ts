import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { burst, MAX_FALL, opacityOf, seeded, shower, stepPieces } from './confetti';

const colours = ['#f2d488', '#14a99b'];

describe('confetti', () => {
  it('throws pieces the way it is aimed, in the colours given', () => {
    const pieces = burst(200, 0, 800, -60, 30, 1000, colours, seeded(1));
    assert.equal(pieces.length, 200);
    for (const p of pieces) {
      assert.ok(p.vy < 0, 'upwards');
      assert.ok(p.vx > 0, 'and to the right');
      assert.ok(colours.includes(p.colour));
      assert.ok(p.life > 0 && p.w > 0 && p.h > 0);
    }
  });

  it('is the same every time from the same seed', () => {
    assert.deepEqual(
      burst(5, 10, 10, -90, 60, 500, colours, seeded(7)),
      burst(5, 10, 10, -90, 60, 500, colours, seeded(7)),
    );
  });

  it('rises, slows, then falls, never faster than a piece of paper can', () => {
    let pieces = burst(1, 100, 500, -90, 0, 1200, colours, seeded(3));
    const startY = pieces[0].y;
    pieces = stepPieces(pieces, 0.1, 1000);
    assert.ok(pieces[0].y < startY, 'goes up first');
    for (let i = 0; i < 40; i += 1) pieces = stepPieces(pieces, 1 / 60, 10_000);
    assert.ok(pieces[0].vy > 0, 'then comes down');
    assert.ok(pieces[0].vy <= MAX_FALL);
  });

  it('is gone after a few seconds, or once below the screen', () => {
    let pieces = shower(50, 400, colours, seeded(2));
    assert.ok(pieces.every((p) => p.y < 0 && p.x >= 0 && p.x <= 400));
    for (let t = 0; t < 6; t += 1 / 30) pieces = stepPieces(pieces, 1 / 30, 800);
    assert.equal(pieces.length, 0);
    assert.equal(stepPieces(burst(3, 0, 900, 90, 0, 100, colours, seeded(4)), 0.5, 800).length, 0);
  });

  it('fades out over its last moments', () => {
    const [p] = burst(1, 0, 0, 0, 0, 0, colours, seeded(5));
    assert.equal(opacityOf({ ...p, life: 3 }), 1);
    assert.equal(opacityOf({ ...p, life: 0.3 }), 0.5);
    assert.equal(opacityOf({ ...p, life: -1 }), 0);
  });
});
