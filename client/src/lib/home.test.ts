import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  HOME_LIST_CAP,
  capRows,
  headlineLines,
  longToday,
  readingPastDay,
  readingStamp,
  sampleNotice,
} from './home';

describe('capRows', () => {
  it('shows at most five rows and counts the rest', () => {
    const rows = [1, 2, 3, 4, 5, 6, 7];
    assert.equal(HOME_LIST_CAP, 5);
    assert.deepEqual(capRows(rows), { shown: [1, 2, 3, 4, 5], hidden: 2 });
  });

  it('hides nothing when the list is short', () => {
    assert.deepEqual(capRows([1, 2]), { shown: [1, 2], hidden: 0 });
    assert.deepEqual(capRows([]), { shown: [], hidden: 0 });
  });

  it('takes another cap, and never a negative one', () => {
    assert.deepEqual(capRows([1, 2, 3], 2), { shown: [1, 2], hidden: 1 });
    assert.deepEqual(capRows([1, 2], -1), { shown: [], hidden: 2 });
  });
});

describe('headlineLines', () => {
  it('breaks the headline at its day and its closing "for {elder}"', () => {
    assert.deepEqual(headlineLines('Tue, 18 Aug was a usual day for Mdm Lim', 'Mdm Lim'), [
      'Tue, 18 Aug',
      'was a usual day',
      'for Mdm Lim',
    ]);
    assert.deepEqual(headlineLines('A usual day for Mr Tan', 'Mr Tan'), [
      'A usual day',
      'for Mr Tan',
    ]);
  });

  it('never changes the words, and leaves other headlines whole', () => {
    const headline = 'Mdm Lim has been less active than usual for a few days';
    assert.deepEqual(headlineLines(headline, 'Mdm Lim'), [headline]);
    assert.deepEqual(headlineLines('Not enough readings yet', ''), ['Not enough readings yet']);
    const lines = headlineLines('Thu, 20 Aug was a quieter day than usual for Mdm Lim', 'Mdm Lim');
    assert.equal(lines.join(' '), 'Thu, 20 Aug was a quieter day than usual for Mdm Lim');
  });
});

describe('sampleNotice', () => {
  it('names what is sample in one sentence', () => {
    assert.equal(
      sampleNotice('Mdm Lim', { steps: true, feed: true }),
      'Mdm Lim’s steps and the older family updates are sample data, not real.',
    );
    assert.equal(
      sampleNotice('Mdm Lim', { steps: true, feed: false }),
      'Mdm Lim’s steps are sample data, not real.',
    );
    assert.match(sampleNotice('Mdm Lim', { steps: false, feed: true }) ?? '', /family updates/);
  });

  it('says nothing when everything is live', () => {
    assert.equal(sampleNotice('Mdm Lim', { steps: false, feed: false }), null);
  });
});

describe('the reading’s day', () => {
  it('says today only for today', () => {
    assert.equal(readingPastDay('2026-11-02', '2026-11-02'), null);
    assert.equal(readingStamp('2026-11-02', '2026-11-02'), 'Steps so far today');
  });

  it('names an older reading’s own day', () => {
    assert.equal(readingPastDay('2026-08-18', '2026-11-02'), 'Tue, 18 Aug');
    assert.equal(readingStamp('2026-08-18', '2026-11-02'), 'Latest reading from Tue, 18 Aug');
  });

  it('writes today’s date out in full', () => {
    assert.equal(longToday('2026-11-02'), 'Monday, 2 November');
  });
});
