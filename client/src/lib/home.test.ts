import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  crossSplit,
  HOME_LIST_CAP,
  capRows,
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

describe('sampleNotice', () => {
  it('names what is sample in one sentence', () => {
    assert.equal(
      sampleNotice('Mdm Lim', { steps: true, feed: true }),
      'Mdm Lim’s steps and the older family updates are sample data, not real.',
    );
    assert.equal(
      sampleNotice('Mdm Lim', { steps: true, feed: false }),
      'Mdm Lim’s steps are sample data, not her own.',
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
    assert.equal(readingStamp('2026-08-18', '2026-11-02'), 'Steps from Tue, 18 Aug');
  });

  it('writes today’s date out in full', () => {
    assert.equal(longToday('2026-11-02'), 'Monday, 2 November');
  });
});

describe('crossSplit', () => {
  it('puts the cross before "for {elder}"', () => {
    assert.deepEqual(crossSplit('A usual day for Mdm Lim', 'Mdm Lim'), {
      before: 'A usual day',
      after: 'for Mdm Lim',
    });
    assert.deepEqual(crossSplit('Tue, 18 Aug was a quieter day than usual for Mr Tan', 'Mr Tan'), {
      before: 'Tue, 18 Aug was a quieter day than usual',
      after: 'for Mr Tan',
    });
  });

  it('puts it after her name when the headline starts with it', () => {
    assert.deepEqual(
      crossSplit('Mdm Lim has been less active than usual for a few days', 'Mdm Lim'),
      { before: 'Mdm Lim', after: 'has been less active than usual for a few days' },
    );
  });

  it('leaves a headline without her name alone', () => {
    assert.equal(crossSplit('Not enough watch data today', 'Mdm Lim'), null);
    assert.equal(crossSplit('A usual day', ''), null);
  });
});
