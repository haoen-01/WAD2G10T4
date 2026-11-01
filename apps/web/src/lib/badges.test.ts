import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  addWalk,
  badgeState,
  BADGES_KEY,
  challengeTarget,
  cleanDays,
  earnedWords,
  evaluateBadges,
  KEEP_WALKS,
  MARATHON_STEPS,
  claimTime,
  finishedWalk,
  isFirstLook,
  mergeStores,
  badgeSentence,
  momentWords,
  newlyEarned,
  readBadgeStore,
  saveBadgeStore,
  seenKey,
  shelfSummary,
  usualSteps,
  withRemembered,
  type BadgeResult,
  type StepDay,
} from './badges';
import { addDays } from './calendar';

/** `steps` for each day from `start`, one per day. */
function run(start: string, steps: number[]): StepDay[] {
  return steps.map((value, index) => ({ day: addDays(start, index), steps: value }));
}

const find = (badges: BadgeResult[], id: string) => {
  const badge = badges.find((item) => item.id === id);
  assert.ok(badge, `no badge ${id}`);
  return badge;
};

class MemoryStorage {
  items = new Map<string, string>();
  getItem(key: string) {
    return this.items.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.items.set(key, value);
  }
}

describe('cleanDays and usualSteps', () => {
  it('drops unreadable days, keeps one per day, oldest first', () => {
    const days = cleanDays([
      { day: '2026-08-03', steps: 10 },
      { day: 'not a day', steps: 5 },
      { day: '2026-08-01', steps: -1 },
      { day: '2026-08-02', steps: Number.NaN },
      { day: '2026-08-01', steps: 7 },
      { day: '2026-08-03', steps: 12 },
    ]);
    assert.deepEqual(days, [
      { day: '2026-08-01', steps: 7 },
      { day: '2026-08-03', steps: 12 },
    ]);
  });

  it('needs a week of readings for a usual day', () => {
    assert.equal(usualSteps(run('2026-08-01', [1, 2, 3, 4, 5, 6])), null);
    assert.equal(usualSteps(run('2026-08-01', [9, 1, 5, 3, 7, 2, 8])), 5);
    assert.equal(usualSteps(run('2026-08-01', [1, 2, 3, 4, 5, 6, 7, 8])), 4.5);
  });
});

describe('day goals', () => {
  it('earns a step goal on the first day that reaches it', () => {
    const badges = evaluateBadges(run('2026-08-01', [2500, 5200, 6000]));
    const five = find(badges, 'steps-5k');
    assert.equal(five.earned, true);
    assert.equal(five.earnedDay, '2026-08-02');
    assert.equal(five.earnedAt, null);
    assert.equal(find(badges, 'first-steps').earnedDay, '2026-08-01');
  });

  it('says how close the best day came, without blame', () => {
    const eight = find(evaluateBadges(run('2026-08-01', [2500, 6400, 6000])), 'steps-8k');
    assert.equal(eight.earned, false);
    assert.deepEqual(eight.progress, {
      value: 6400,
      target: 8000,
      words: 'Best day so far: 6,400 of 8,000 steps.',
    });
  });

  it('earns nothing from no readings', () => {
    const badges = evaluateBadges([]);
    assert.ok(badges.every((badge) => !badge.earned));
    assert.ok(!badges.some((badge) => badge.group === 'challenge'));
  });
});

describe('habits', () => {
  it('Steady Week: 5 walking days inside any 7, gaps allowed', () => {
    // 1, 2, (3 quiet), 4, 5, (6 quiet), 7: the fifth walking day is the 7th.
    const days = run('2026-08-01', [3000, 3000, 900, 3000, 3000, 500, 3000]);
    const week = find(evaluateBadges(days), 'steady-week');
    assert.equal(week.earnedDay, '2026-08-07');
  });

  it('Steady Week: walking days more than 7 days apart do not add up', () => {
    const days = [
      ...run('2026-08-01', [3000, 3000, 3000, 3000]),
      ...run('2026-08-10', [3000, 3000, 3000, 3000]),
    ];
    const week = find(evaluateBadges(days), 'steady-week');
    assert.equal(week.earned, false);
    assert.equal(week.progress.words, 'Best so far: 4 of 5 walking days.');
  });

  it('Weekend Walker: a Saturday and the Sunday after', () => {
    // 2026-08-01 is a Saturday; that weekend Sunday is quiet, the next weekend both walked.
    const days = run('2026-08-01', [3000, 100, 0, 0, 0, 0, 0, 2500, 2600]);
    const weekend = find(evaluateBadges(days), 'weekend-walker');
    assert.equal(weekend.earnedDay, '2026-08-09');
  });

  it('Weekend Walker: a walked Saturday that is the latest reading counts as half', () => {
    const weekend = find(evaluateBadges(run('2026-08-01', [3000])), 'weekend-walker');
    assert.equal(weekend.earned, false);
    assert.equal(weekend.progress.value, 1);
  });

  it('Month of Walks: 20 walking days inside 30', () => {
    const days = run(
      '2026-08-01',
      Array.from({ length: 25 }, (_, i) => (i % 5 === 4 ? 0 : 2400)),
    );
    const month = find(evaluateBadges(days), 'month-of-walks');
    // Every fifth day is quiet: the 20th walking day is day 24.
    assert.equal(month.earnedDay, '2026-08-24');
  });
});

describe('milestones', () => {
  it('adds steps up to a total and earns on the day it is passed', () => {
    const days = run(
      '2026-08-01',
      Array.from({ length: 20 }, () => 6000),
    );
    const badges = evaluateBadges(days);
    const marathon = find(badges, 'marathon');
    // 65,000 steps: passed on day 11 (66,000).
    assert.equal(MARATHON_STEPS, 65_000);
    assert.equal(marathon.earnedDay, '2026-08-11');
    assert.equal(find(badges, 'steps-100k').earnedDay, '2026-08-17');
    const quarter = find(badges, 'steps-250k');
    assert.equal(quarter.earned, false);
    assert.equal(quarter.progress.words, '120,000 of 250,000 steps in the last 90 days.');
  });

  it('counts only the last 90 days, so a total never mixes in a long-gone season', () => {
    // 60,000 steps on one day, then nothing for 100 days, then 10,000: never 65,000 within 90 days.
    const days = [
      { day: '2026-03-01', steps: 60_000 },
      { day: '2026-06-09', steps: 10_000 },
    ];
    const marathon = find(evaluateBadges(days), 'marathon');
    assert.equal(marathon.earned, false);
    assert.equal(marathon.progress.words, '10,000 of 65,000 steps in the last 90 days.');
    // Within 90 days, it adds up.
    const close = [
      { day: '2026-03-01', steps: 60_000 },
      { day: '2026-05-29', steps: 10_000 },
    ];
    assert.equal(find(evaluateBadges(close), 'marathon').earnedDay, '2026-05-29');
  });

  it('Personal Best waits for 14 days, then needs a day above every earlier one', () => {
    const early = find(evaluateBadges(run('2026-08-01', [9000, 100])), 'personal-best');
    assert.equal(early.earned, false);
    assert.equal(early.progress.words, '2 of 14 days of walking so far.');

    const steps = [...Array.from({ length: 14 }, (_, i) => 4000 + i * 10), 4100, 4200];
    const best = find(evaluateBadges(run('2026-08-01', steps)), 'personal-best');
    // Best of the first 14 is 4,130; day 15 (4,100) does not beat it, day 16 (4,200) does.
    assert.equal(best.earnedDay, '2026-08-16');
    assert.equal(best.progress.words, '4,200 steps, beating 4,130.');
  });
});

describe('walk badges', () => {
  const at = Date.UTC(2026, 9, 31, 7, 42);
  it('Park Loop: the first finished walk of 2 km, with its time', () => {
    const badges = evaluateBadges(
      [],
      [
        { at: at - 86_400_000, distanceM: 1200 },
        { at, distanceM: 2400 },
      ],
    );
    const loop = find(badges, 'park-loop');
    assert.equal(loop.earnedAt, at);
    assert.equal(loop.earnedDay, null);
    assert.equal(earnedWords(loop), 'Sat, 31 Oct 2026, 3:42 pm');
  });

  it('Regular Walker: three walks of 1 km', () => {
    const walks = [1, 2, 3].map((n) => ({ at: at + n, distanceM: 1500 }));
    const regular = find(evaluateBadges([], walks.slice(0, 2)), 'regular-walker');
    assert.equal(regular.progress.words, '2 of 3 walks finished.');
    assert.equal(find(evaluateBadges([], walks), 'regular-walker').earnedAt, at + 3);
  });

  it('records a walk only when it finishes, while shared, and only the shared part', () => {
    const going = { finished: false };
    const done = { finished: true };
    assert.deepEqual(finishedWalk(going, done, true, 2400.4, at), { at, distanceM: 2400 });
    // Already finished: not counted again.
    assert.equal(finishedWalk(done, done, true, 2400, at), null);
    // Not shared, or too short, or still going: nothing.
    assert.equal(finishedWalk(going, done, false, 2400, at), null);
    assert.equal(finishedWalk(going, done, true, 900, at), null);
    assert.equal(finishedWalk(going, going, true, 2400, at), null);
    assert.equal(finishedWalk(null, null, true, 2400, at), null);
  });

  it('never claims a walk badge before it was earned', () => {
    const loop = find(evaluateBadges([], [{ at, distanceM: 2400 }]), 'park-loop');
    assert.equal(claimTime(loop, at - 5000), at);
    assert.equal(claimTime(loop, at + 5000), at + 5000);
    const five = find(evaluateBadges(run('2026-08-01', [5000])), 'steps-5k');
    assert.equal(claimTime(five, 7), 7);
  });

  it('counts a walk once, and keeps only the latest', () => {
    const one = { at, distanceM: 2000 };
    assert.equal(addWalk(addWalk([], one), one).length, 1);
    let many: { at: number; distanceM: number }[] = [];
    for (let i = 0; i < KEEP_WALKS + 5; i += 1) many = addWalk(many, { at: i, distanceM: 1 });
    assert.equal(many.length, KEEP_WALKS);
    assert.equal(many[0].at, 5);
  });
});

describe('monthly challenges', () => {
  it('sets the goal from about 20 usual days before the month', () => {
    const july = run(
      '2026-07-21',
      Array.from({ length: 11 }, () => 5850),
    );
    assert.equal(challengeTarget(july, '2026-08-01'), 115_000);
    // Too few readings before it: the default goal.
    assert.equal(challengeTarget(july, '2026-07-01'), 100_000);
  });

  it('shows the latest month in progress and hides a past month not won', () => {
    const days = [
      ...run(
        '2026-07-21',
        Array.from({ length: 11 }, () => 5850),
      ),
      ...run(
        '2026-08-01',
        Array.from({ length: 10 }, () => 6000),
      ),
    ];
    const ids = evaluateBadges(days)
      .filter((badge) => badge.group === 'challenge')
      .map((badge) => badge.id);
    assert.deepEqual(ids, ['challenge-2026-08']);
    const august = find(evaluateBadges(days), 'challenge-2026-08');
    assert.equal(august.earned, false);
    assert.equal(august.progress.words, '60,000 of 115,000 steps · 21 days left.');
    assert.equal(august.look.label, 'AUG');
  });

  it('on the month’s last day, says so rather than "0 days left"', () => {
    const days = [
      ...run(
        '2026-07-21',
        Array.from({ length: 11 }, () => 5850),
      ),
      ...run(
        '2026-08-01',
        Array.from({ length: 31 }, () => 1000),
      ),
    ];
    const august = find(evaluateBadges(days), 'challenge-2026-08');
    assert.equal(august.progress.words, '31,000 of 115,000 steps · the month’s last day.');
  });

  it('keeps a won month, newest first', () => {
    const days = [
      ...run(
        '2026-07-01',
        Array.from({ length: 31 }, () => 4000),
      ),
      ...run('2026-08-01', [5000]),
    ];
    const challenges = evaluateBadges(days).filter((badge) => badge.group === 'challenge');
    assert.deepEqual(
      challenges.map((badge) => badge.id),
      ['challenge-2026-08', 'challenge-2026-07'],
    );
    // July: 100,000 by the 25th.
    assert.equal(challenges[1].earnedDay, '2026-07-25');
  });
});

describe('once earned, always earned', () => {
  // Early days earn First Steps; later, only quiet days are in view.
  const early = evaluateBadges(run('2026-05-01', [1500, 3200]));
  const later = evaluateBadges(run('2026-08-01', [400, 500]));

  it('remembers what is newly earned, and only once', () => {
    const fresh = newlyEarned(early);
    assert.deepEqual(
      fresh.map((badge) => badge.id),
      ['first-steps', 'steps-3k'],
    );
    const remembered = Object.fromEntries(fresh.map((badge) => [badge.id, badge]));
    assert.deepEqual(newlyEarned(early, remembered), []);
  });

  it('keeps a badge earned, on its first day, after its days roll out of view', () => {
    const remembered = Object.fromEntries(newlyEarned(early).map((badge) => [badge.id, badge]));
    assert.equal(find(later, 'first-steps').earned, false);
    const shown = withRemembered(later, remembered);
    assert.equal(find(shown, 'first-steps').earnedDay, '2026-05-01');
    assert.equal(find(shown, 'steps-3k').earnedDay, '2026-05-02');
    assert.equal(find(shown, 'steps-5k').earned, false);
    assert.equal(shown.length, later.length);
  });

  it('puts back a won challenge from a month no longer in view, with the challenges', () => {
    const july = evaluateBadges(
      run(
        '2026-07-01',
        Array.from({ length: 31 }, () => 4000),
      ),
    );
    const won = find(july, 'challenge-2026-07');
    assert.equal(won.earned, true);
    const shown = withRemembered(later, { [won.id]: won });
    const challenges = shown.filter((badge) => badge.group === 'challenge');
    assert.deepEqual(
      challenges.map((badge) => badge.id),
      ['challenge-2026-08', 'challenge-2026-07'],
    );
    assert.equal(shown[0].id, 'challenge-2026-08');
  });

  it('stores remembered badges, and drops any it could not draw', () => {
    const storage = new MemoryStorage();
    const first = find(early, 'first-steps');
    saveBadgeStore(storage, {
      claims: {},
      earned: { 'mdm-lim': { 'first-steps': first } },
      walks: {},
      seen: {},
    });
    assert.deepEqual(readBadgeStore(storage).earned, { 'mdm-lim': { 'first-steps': first } });
    storage.setItem(
      BADGES_KEY,
      JSON.stringify({
        earned: {
          'mdm-lim': {
            'first-steps': { ...first, look: { ...first.look, tone: 'tartan' } },
            other: { ...first, id: 'not-other' },
            never: { ...first, id: 'never', earnedDay: null, earnedAt: null },
          },
        },
      }),
    );
    assert.deepEqual(readBadgeStore(storage).earned, { 'mdm-lim': {} });
  });
});

describe('claiming', () => {
  const earned = evaluateBadges(run('2026-08-01', [1500]))[0];
  it('is locked until earned, ready until claimed', () => {
    const locked = find(evaluateBadges([]), 'first-steps');
    assert.equal(badgeState(locked, undefined), 'locked');
    assert.equal(badgeState(locked, 5), 'locked');
    const first = find(evaluateBadges(run('2026-08-01', [1500])), 'first-steps');
    assert.equal(badgeState(first, undefined), 'ready');
    assert.equal(badgeState(first, 5), 'claimed');
    assert.ok(earned);
  });

  it('remembers claims and walks, and drops anything unreadable', () => {
    const storage = new MemoryStorage();
    saveBadgeStore(storage, {
      claims: { 'mdm-lim': { 'first-steps': 10 } },
      earned: {},
      walks: { 'mdm-lim': [{ at: 1, distanceM: 2000 }] },
      seen: { 'mdm-lim': { 'self:first-steps': 11 } },
    });
    assert.deepEqual(readBadgeStore(storage), {
      claims: { 'mdm-lim': { 'first-steps': 10 } },
      earned: {},
      walks: { 'mdm-lim': [{ at: 1, distanceM: 2000 }] },
      seen: { 'mdm-lim': { 'self:first-steps': 11 } },
    });
    storage.setItem(
      BADGES_KEY,
      JSON.stringify({
        claims: { a: { ok: 3, bad: 'x' }, b: [] },
        walks: { a: [{ at: 'x' }, { at: 2, distanceM: 5, extra: true }], b: 'no' },
        seen: { a: { 'self:x': 'soon' } },
      }),
    );
    assert.deepEqual(readBadgeStore(storage), {
      claims: { a: { ok: 3 } },
      earned: {},
      walks: { a: [{ at: 2, distanceM: 5 }] },
      seen: { a: {} },
    });
    storage.setItem(BADGES_KEY, 'not json');
    assert.deepEqual(readBadgeStore(storage), { claims: {}, earned: {}, walks: {}, seen: {} });
  });

  it('joins what another tab saved instead of writing over it, each senior apart', () => {
    const first = find(evaluateBadges(run('2026-08-01', [1500])), 'first-steps');
    const theirs = {
      claims: { lim: { 'first-steps': 20 }, ravi: { 'steps-3k': 5 } },
      earned: { lim: { 'first-steps': first } },
      walks: { lim: [{ at: 1, distanceM: 2000 }] },
      seen: { lim: { 'self:first-steps': 50 } },
    };
    const mine = {
      claims: { lim: { 'first-steps': 30, 'steps-3k': 40 } },
      earned: {},
      walks: {
        lim: [
          { at: 1, distanceM: 2000 },
          { at: 3, distanceM: 1500 },
        ],
        ravi: [],
      },
      seen: { lim: { 'self:first-steps': 60, 'family:first-steps': 70 } },
    };
    assert.deepEqual(mergeStores(theirs, mine), {
      claims: { lim: { 'first-steps': 20, 'steps-3k': 40 }, ravi: { 'steps-3k': 5 } },
      earned: { lim: { 'first-steps': first } },
      walks: {
        lim: [
          { at: 1, distanceM: 2000 },
          { at: 3, distanceM: 1500 },
        ],
        ravi: [],
      },
      seen: { lim: { 'self:first-steps': 50, 'family:first-steps': 70 } },
    });
  });

  it('celebrates only the first look at a claimed badge, once for her and once for her family', () => {
    assert.equal(isFirstLook(false, undefined, 'first-steps', 'self'), false);
    assert.equal(isFirstLook(true, undefined, 'first-steps', 'self'), true);
    const seen = { [seenKey('first-steps', 'self')]: 5 };
    assert.equal(isFirstLook(true, seen, 'first-steps', 'self'), false);
    assert.equal(isFirstLook(true, seen, 'first-steps', 'family'), true);
    assert.equal(isFirstLook(true, seen, 'steps-3k', 'self'), true);
  });

  it('works when storage throws', () => {
    const broken = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    };
    assert.deepEqual(readBadgeStore(broken), { claims: {}, earned: {}, walks: {}, seen: {} });
    assert.doesNotThrow(() =>
      saveBadgeStore(broken, { claims: {}, earned: {}, walks: {}, seen: {} }),
    );
  });
});

describe('words', () => {
  it('says when, in Singapore time', () => {
    assert.equal(momentWords(Date.UTC(2026, 9, 31, 8, 52)), 'Sat, 31 Oct 2026, 4:52 pm');
    const five = find(evaluateBadges(run('2026-08-06', [5000])), 'steps-5k');
    assert.equal(earnedWords(five), 'Thu, 6 Aug 2026');
    assert.equal(earnedWords(find(evaluateBadges([]), 'steps-5k')), 'Not earned yet');
  });

  it('says in one line what she did, the way a medal is shown off', () => {
    const five = find(evaluateBadges(run('2026-08-06', [5000])), 'steps-5k');
    assert.equal(
      badgeSentence(five, 'You'),
      'You earned this for walking 5,000 steps in one day, on Thu, 6 Aug 2026.',
    );
    assert.equal(
      badgeSentence(five, 'Mdm Lim'),
      'Mdm Lim earned this for walking 5,000 steps in one day, on Thu, 6 Aug 2026.',
    );
    const tenK = find(evaluateBadges(run('2026-08-06', [5000])), 'steps-10k');
    assert.equal(badgeSentence(tenK, 'You'), 'Walk 10,000 steps in one day.');
    // A badge remembered from before deeds were kept still reads sensibly.
    assert.equal(
      badgeSentence({ ...five, deed: undefined }, 'You'),
      'You earned this for walking 5,000 steps in one day, on Thu, 6 Aug 2026.',
    );
  });

  it('sums up the shelf', () => {
    const badges = evaluateBadges(run('2026-08-01', [1500]));
    assert.match(shelfSummary(badges), /^1 of \d+ earned$/);
  });

  it('every badge has a name, a way to earn it and a look', () => {
    const days = run(
      '2026-08-01',
      Array.from({ length: 30 }, (_, i) => 12_000 + i),
    );
    const walks = [1, 2, 3].map((at) => ({ at, distanceM: 3000 }));
    for (const badge of evaluateBadges(days, walks)) {
      assert.ok(badge.name && badge.how && badge.look.shape && badge.look.tone, badge.id);
      assert.ok(badge.progress.target > 0, badge.id);
      assert.ok(badge.earned, `${badge.id} should be earned with this much walking`);
    }
  });
});
