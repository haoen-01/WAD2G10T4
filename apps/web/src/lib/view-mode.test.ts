import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  homeFor,
  isLoginPath,
  isPathInView,
  isViewPath,
  parseViewMode,
  viewForRole,
} from './view-mode';

describe('viewForRole', () => {
  it('gives a senior the senior view and a family account the family view', () => {
    assert.equal(viewForRole('senior'), 'senior');
    assert.equal(viewForRole('family'), 'family');
    assert.equal(viewForRole('coordinator'), 'family');
    assert.equal(viewForRole('demo_operator'), 'family');
  });

  it('knows no view for an unknown or missing role', () => {
    assert.equal(viewForRole('admin'), null);
    assert.equal(viewForRole(''), null);
    assert.equal(viewForRole(null), null);
    assert.equal(viewForRole(undefined), null);
  });
});

describe('homeFor', () => {
  it('starts the family on Home and the senior on their own screen', () => {
    assert.equal(homeFor('family'), '/');
    assert.equal(homeFor('senior'), '/senior');
  });
});

describe('isPathInView', () => {
  it('lets the family open Home, Walk, Calendar and Family, but not the senior screen', () => {
    for (const path of [
      '/',
      '/walk',
      '/calendar',
      '/calendar/',
      '/family',
      '/Family',
      '/groups/start',
    ]) {
      assert.equal(isPathInView('family', path), true, path);
    }
    assert.equal(isPathInView('family', '/senior'), false);
  });

  it('lets the senior open only their own screen', () => {
    assert.equal(isPathInView('senior', '/senior'), true);
    assert.equal(isPathInView('senior', '/senior/anything'), true);
    for (const path of ['/', '/walk', '/calendar', '/family', '/groups/start']) {
      assert.equal(isPathInView('senior', path), false, path);
    }
  });

  it('matches whole segments, so a sibling path is not part of a view', () => {
    assert.equal(isPathInView('senior', '/seniors'), false);
    assert.equal(isPathInView('family', '/calendars'), false);
    assert.equal(isPathInView('family', '/x'), false);
  });
});

describe('isViewPath', () => {
  it('is true for every screen of either view and false for anything else', () => {
    for (const path of ['/', '/walk', '/calendar', '/family', '/senior']) {
      assert.equal(isViewPath(path), true, path);
    }
    for (const path of ['/login', '/nowhere']) assert.equal(isViewPath(path), false, path);
  });
});

describe('isLoginPath', () => {
  it('covers the chooser, both sign-in pages and the sign-up pages only', () => {
    for (const path of [
      '/login',
      '/login/family',
      '/login/senior',
      '/Login',
      '/signup',
      '/signup/family',
    ]) {
      assert.equal(isLoginPath(path), true, path);
    }
    assert.equal(isLoginPath('/loginx'), false);
    assert.equal(isLoginPath('/signupx'), false);
    assert.equal(isLoginPath('/'), false);
  });
});

describe('parseViewMode', () => {
  it('accepts the two views and nothing else', () => {
    assert.equal(parseViewMode('family'), 'family');
    assert.equal(parseViewMode('senior'), 'senior');
    for (const raw of ['', 'Family', 'coordinator', null, undefined, 1]) {
      assert.equal(parseViewMode(raw), null, String(raw));
    }
  });
});
