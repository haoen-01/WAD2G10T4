import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  createNavigationGenerations,
  mayContinueRetry,
  mayReport,
  shouldClearAfterNavigation,
} from './connection';

describe('createNavigationGenerations', () => {
  it('starts a new generation for every guard run', () => {
    const generations = createNavigationGenerations();
    assert.equal(generations.latest(), 0);
    const first = generations.begin();
    assert.equal(generations.isCurrent(first), true);
    const second = generations.begin();
    assert.equal(generations.isCurrent(first), false);
    assert.equal(generations.isCurrent(second), true);
    assert.equal(generations.latest(), second);
  });
});

describe('mayReport', () => {
  it('lets the newest navigation show the panel', () => {
    const generations = createNavigationGenerations();
    const mine = generations.begin();
    assert.equal(mayReport(mine, generations), true);
  });

  it('ignores a guard overtaken by a newer navigation (e.g. signing out while it waited)', () => {
    const generations = createNavigationGenerations();
    const stale = generations.begin();
    generations.begin(); // to /login, committed meanwhile
    assert.equal(mayReport(stale, generations), false);
  });
});

describe('mayContinueRetry', () => {
  it('reopens the screen when nothing has happened since Try again was pressed', () => {
    const generations = createNavigationGenerations();
    generations.begin();
    const startedAt = generations.latest();
    assert.equal(mayContinueRetry({ startedAt, generations, panelShowing: true }), true);
  });

  it('stops when the person navigated meanwhile (signed out, went back, opened another screen)', () => {
    const generations = createNavigationGenerations();
    generations.begin();
    const startedAt = generations.latest();
    generations.begin();
    assert.equal(mayContinueRetry({ startedAt, generations, panelShowing: true }), false);
  });

  it('stops when the panel has already gone', () => {
    const generations = createNavigationGenerations();
    const startedAt = generations.latest();
    assert.equal(mayContinueRetry({ startedAt, generations, panelShowing: false }), false);
  });
});

describe('shouldClearAfterNavigation', () => {
  const committed = { failed: false, panelShowing: true, reportedForThisNavigation: false };

  it('clears the panel once a navigation the guard let through is committed', () => {
    assert.equal(shouldClearAfterNavigation(committed), true);
  });

  it('keeps it for a failed or cancelled navigation', () => {
    assert.equal(shouldClearAfterNavigation({ ...committed, failed: true }), false);
  });

  it('keeps it when the guard found Care+ unreachable for this navigation', () => {
    assert.equal(
      shouldClearAfterNavigation({ ...committed, reportedForThisNavigation: true }),
      false,
    );
  });

  it('has nothing to do when no panel shows', () => {
    assert.equal(shouldClearAfterNavigation({ ...committed, panelShowing: false }), false);
  });
});
