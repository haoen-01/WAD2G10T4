import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  AUTO_DEG_PER_S,
  faceFront,
  frontAhead,
  isMoving,
  nearestFace,
  release,
  resting,
  stepSpin,
  turnOver,
  type Spin,
} from './coin-spin';

/** Runs frames of 1/60 s until it stops (or `seconds` pass). */
function run(spin: Spin, seconds = 10): Spin {
  let next = spin;
  for (let t = 0; t < seconds && isMoving(next); t += 1 / 60) next = stepSpin(next, 1 / 60);
  return next;
}

describe('coin spin', () => {
  it('turns slowly by itself', () => {
    const after = stepSpin({ ...resting(), mode: 'auto' }, 1);
    assert.equal(after.angle, AUTO_DEG_PER_S);
    assert.ok(isMoving(after));
  });

  it('settles on the face it is turning towards', () => {
    assert.equal(nearestFace(100, 1), 180);
    assert.equal(nearestFace(100, -1), 0);
    assert.equal(nearestFace(30, 1), 0); // barely past the front: back to it
    assert.equal(nearestFace(-100), -180);
    assert.equal(nearestFace(260), 180);
  });

  it('coasts after a flick, slows, and comes to rest face on', () => {
    const end = run(release({ ...resting(10), mode: 'drag' }, 900));
    assert.equal(end.mode, 'idle');
    assert.ok(end.angle > 10);
    assert.equal(end.angle % 180, 0);
  });

  it('settles straight away when let go gently', () => {
    const let_go = release({ ...resting(70), mode: 'drag' }, 10);
    assert.equal(let_go.mode, 'settle');
    assert.equal(run(let_go).angle, 0);
    assert.equal(run(release({ ...resting(120), mode: 'drag' }, 0)).angle, 180);
  });

  it('turns over to the other face and stays there', () => {
    const back = run(turnOver(resting(0)));
    assert.equal(back.angle, 180);
    assert.equal(back.mode, 'idle');
    assert.equal(run(turnOver(back)).angle, 360);
    // Pressed twice quickly: a whole turn, not stuck half way.
    assert.equal(turnOver(turnOver(resting(0))).target, 360);
  });

  it('goes back to the front by finishing the turn it is on', () => {
    assert.equal(frontAhead(200), 360);
    assert.equal(frontAhead(360), 360);
    assert.equal(run(faceFront({ ...resting(200), mode: 'auto' })).angle, 360);
  });
});
