import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  PROTECTED_PREFIXES,
  isProtectedPath,
  loginPathFor,
  nextForPath,
  safeNextPath,
  stringifyStrictQuery,
} from './route-guard';

describe('isProtectedPath', () => {
  it('protects each section and everything under it', () => {
    for (const path of [
      '/senior',
      '/senior/anything',
      '/calendar',
      '/calendar/',
      '/family',
      '/family/anything',
    ]) {
      assert.equal(isProtectedPath(path), true, path);
    }
  });

  it('leaves Overview and sign-in public, as the middleware matcher did', () => {
    assert.equal(isProtectedPath('/'), false);
    assert.equal(isProtectedPath('/login'), false);
  });

  it('does not guard paths that are no longer screens (they are plain 404s now)', () => {
    for (const path of ['/screen-preview', '/coordinator', '/operations']) {
      assert.equal(isProtectedPath(path), false, path);
    }
  });

  it('does not guard the removed Care Team paths: the router redirects them to the calendar', () => {
    // The redirect is resolved before the guard runs, so the guard only ever sees `/calendar`.
    for (const path of ['/care-team', '/care-team/cases/case-1']) {
      assert.equal(isProtectedPath(path), false, path);
    }
  });

  it('matches whole path segments only', () => {
    assert.equal(isProtectedPath('/seniors'), false);
    assert.equal(isProtectedPath('/senior-preview'), false);
    assert.equal(isProtectedPath('/calendars'), false);
    assert.equal(isProtectedPath('/family-tree'), false);
  });

  it('ignores case, because the router matches paths case-insensitively', () => {
    assert.equal(isProtectedPath('/Calendar'), true);
    assert.equal(isProtectedPath('/SENIOR/privacy'), true);
  });

  it('lists exactly the sections the spec names', () => {
    assert.deepEqual([...PROTECTED_PREFIXES].sort(), ['/calendar', '/family', '/senior']);
  });
});

describe('safeNextPath', () => {
  it('accepts a same-origin absolute path', () => {
    assert.equal(safeNextPath('/calendar'), '/calendar');
    assert.equal(safeNextPath('/calendar/2026-09'), '/calendar/2026-09');
    assert.equal(safeNextPath('/'), '/');
    assert.equal(safeNextPath('/senior/privacy#suggestions'), '/senior/privacy#suggestions');
  });

  it('rejects anything that could leave the origin', () => {
    for (const raw of [
      '//evil.example',
      '//evil.example/calendar',
      'https://evil.example',
      'javascript:alert(1)',
      '/\\evil.example',
      '/calendar\\..\\x',
      'calendar',
      '',
      '/\t/evil.example',
      '/a\nb',
    ]) {
      assert.equal(safeNextPath(raw), null, JSON.stringify(raw));
    }
  });

  it('rejects a missing value', () => {
    assert.equal(safeNextPath(null), null);
    assert.equal(safeNextPath(undefined), null);
  });
});

describe('nextForPath', () => {
  it('carries the path alone and falls back to Overview', () => {
    assert.equal(nextForPath('/calendar'), '/calendar');
    assert.equal(nextForPath('/calendar/x'), '/calendar/x');
    assert.equal(nextForPath('//evil.example'), '/');
    assert.equal(nextForPath(''), '/');
  });
});

describe('loginPathFor', () => {
  it('writes the sign-in link the way the old middleware did', () => {
    assert.equal(loginPathFor('/calendar'), '/login?next=%2Fcalendar');
    assert.equal(loginPathFor('/calendar/2026-09'), '/login?next=%2Fcalendar%2F2026-09');
  });

  it('falls back to Overview for a path that is not safe to return to', () => {
    assert.equal(loginPathFor('//evil.example'), '/login?next=%2F');
  });
});

describe('stringifyStrictQuery', () => {
  it('percent-encodes a path the way the old app wrote it', () => {
    assert.equal(stringifyStrictQuery({ next: '/calendar' }), 'next=%2Fcalendar');
    assert.equal(
      stringifyStrictQuery({ returnTo: '/simulator?scenario=a&b=1#x' }),
      'returnTo=%2Fsimulator%3Fscenario%3Da%26b%3D1%23x',
    );
  });

  it('writes a space as %20 and encodes plus, ampersand and equals', () => {
    assert.equal(stringifyStrictQuery({ q: 'a b+c&d=e' }), 'q=a%20b%2Bc%26d%3De');
  });

  it('repeats a key for an array, writes a bare key for null, and skips undefined', () => {
    assert.equal(stringifyStrictQuery({ a: ['1', '2'], b: null, c: undefined }), 'a=1&a=2&b');
    assert.equal(stringifyStrictQuery({ n: 3, ok: true }), 'n=3&ok=true');
  });

  it('is empty for no query', () => {
    assert.equal(stringifyStrictQuery({}), '');
    assert.equal(stringifyStrictQuery(undefined), '');
    assert.equal(stringifyStrictQuery(null), '');
  });
});
