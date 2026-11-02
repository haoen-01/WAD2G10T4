import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { backTextScale, inset, motifParts, roundedPolygon, SHAPES, TONES } from './badge-art';
import { evaluateBadges, type BadgeShape } from './badges';
import { addDays } from './calendar';

const plenty = Array.from({ length: 60 }, (_, i) => ({
  day: addDays('2026-07-01', i),
  steps: 12_000 + i,
}));
const everyBadge = evaluateBadges(
  plenty,
  [1, 2, 3].map((at) => ({ at, distanceM: 3000 })),
);

describe('badge art', () => {
  it('draws every outline as a closed path with real numbers', () => {
    for (const [shape, d] of Object.entries(SHAPES)) {
      assert.match(d, /^M/, shape);
      assert.match(d, /Z$/, shape);
      assert.doesNotMatch(d, /NaN|Infinity/, shape);
    }
  });

  it('rounds the corners of a polygon', () => {
    const d = roundedPolygon(
      [
        [0, 0],
        [100, 0],
        [100, 100],
      ],
      10,
    );
    assert.equal((d.match(/Q/g) ?? []).length, 3);
    // The first corner, at 0 0, is cut 10 along each side: towards 100 100 and towards 100 0.
    assert.match(d, /^M7.1 7.1 Q0 0 10 0 /);
  });

  it('scales copies about the centre', () => {
    assert.equal(inset(0.5), 'translate(100 100) scale(0.5) translate(-100 -100)');
  });

  it('gives every badge a picture in colours it has', () => {
    for (const badge of everyBadge) {
      const parts = motifParts(badge.look);
      assert.ok(parts.length > 0, badge.id);
      assert.ok(TONES[badge.look.tone], badge.id);
      for (const part of parts) {
        for (const value of Object.values(part.attrs)) {
          assert.doesNotMatch(String(value), /NaN|undefined/, badge.id);
        }
        if (part.tag === 'text') assert.ok(part.text !== undefined, badge.id);
      }
    }
  });

  it('writes the label on the badge itself', () => {
    const five = everyBadge.find((badge) => badge.id === 'steps-5k');
    assert.ok(five);
    assert.ok(motifParts(five.look).some((part) => part.text === '5K'));
  });

  it('keeps the back’s engraving inside narrow outlines', () => {
    const shapes: BadgeShape[] = ['star', 'rosette', 'circle'];
    assert.deepEqual(shapes.map(backTextScale), [0.78, 0.92, 1]);
  });
});
