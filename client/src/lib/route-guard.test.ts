import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  PROTECTED_PREFIXES,
  attempt,
  decideAccess,
  isConnectionProblem,
  isProtectedPath,
  needsMe,
  type AccessInput,
  type Attempt,
  type MeSummary,
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
    assert.deepEqual([...PROTECTED_PREFIXES].sort(), ['/calendar', '/family', '/senior', '/walk']);
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

const fail = (
  kind: 'unauthorized' | 'forbidden' | 'unreachable' | 'stored_state' | 'server',
  status: number | null,
) => ({ ok: false, kind, status }) as const;
const groups = (activeGroups: number, needsOnboarding = false): Attempt<MeSummary> => ({
  ok: true,
  value: { activeGroups, needsOnboarding },
});

const demo: AccessInput = {
  authEnabled: false,
  hasSession: false,
  path: '/',
  demoView: 'family',
  currentUser: null,
  me: groups(1),
};
const signedIn: AccessInput = {
  authEnabled: true,
  hasSession: true,
  path: '/calendar',
  demoView: null,
  currentUser: { ok: true, value: { role: 'family' } },
  me: groups(1),
};

describe('attempt', () => {
  it('reports a value or the kind of failure, never throwing', async () => {
    assert.deepEqual(await attempt(async () => 3), { ok: true, value: 3 });
    assert.deepEqual(
      await attempt(async () => {
        throw Object.assign(new Error('x'), { status: 0 });
      }),
      { ok: false, kind: 'unreachable', status: 0 },
    );
    assert.deepEqual(
      await attempt(async () => {
        throw Object.assign(new Error('x'), { status: 503 });
      }),
      { ok: false, kind: 'server', status: 503 },
    );
  });
});

describe('isConnectionProblem', () => {
  it('is no response, a 5xx or stored data from an older version', () => {
    assert.equal(isConnectionProblem(fail('unreachable', 0)), true);
    assert.equal(isConnectionProblem(fail('server', 500)), true);
    assert.equal(isConnectionProblem(fail('server', null)), true);
    assert.equal(isConnectionProblem(fail('stored_state', 500)), true);
  });

  it('is not an answer about this person', () => {
    assert.equal(isConnectionProblem(fail('unauthorized', 401)), false);
    assert.equal(isConnectionProblem(fail('forbidden', 403)), false);
    assert.equal(isConnectionProblem(fail('server', 422)), false);
  });
});

describe('decideAccess', () => {
  it('leaves sign-in, welcome and not-found pages alone', () => {
    for (const path of ['/login', '/signup/family', '/welcome', '/nope']) {
      assert.deepEqual(decideAccess({ ...signedIn, path, currentUser: fail('unreachable', 0) }), {
        action: 'allow',
      });
    }
  });

  it('shows the connection panel when /v1/me cannot be reached, never "join a group"', () => {
    for (const me of [fail('unreachable', 0), fail('server', 502), fail('stored_state', 500)]) {
      const decision = decideAccess({ ...demo, me });
      assert.equal(decision.action, 'unreachable');
    }
  });

  it('shows the connection panel, not sign-in, when /v1/auth/me cannot be reached', () => {
    const decision = decideAccess({ ...signedIn, currentUser: fail('unreachable', 0), me: null });
    assert.deepEqual(decision, { action: 'unreachable', kind: 'unreachable' });
  });

  it('still sends a real 401 to sign in', () => {
    assert.deepEqual(decideAccess({ ...signedIn, currentUser: fail('unauthorized', 401) }), {
      action: 'redirect',
      to: '/login?next=%2Fcalendar',
    });
    assert.deepEqual(decideAccess({ ...signedIn, me: fail('unauthorized', 401) }), {
      action: 'redirect',
      to: '/login?next=%2Fcalendar',
    });
  });

  it('sends someone with no session to sign in', () => {
    assert.deepEqual(
      decideAccess({ ...signedIn, hasSession: false, currentUser: null, me: null }),
      { action: 'redirect', to: '/login?next=%2Fcalendar' },
    );
  });

  it('sends a new account with no role to finish signing up', () => {
    const input = { ...signedIn, currentUser: fail('forbidden', 403), me: groups(0, true) };
    assert.deepEqual(decideAccess(input), { action: 'redirect', to: '/welcome' });
  });

  it('shows the panel for a new account whose /v1/me cannot be reached', () => {
    const input = { ...signedIn, currentUser: fail('forbidden', 403), me: fail('unreachable', 0) };
    assert.equal(decideAccess(input).action, 'unreachable');
  });

  it('sends a family member to "join a group" only when /v1/me loaded with none', () => {
    assert.deepEqual(decideAccess({ ...demo, me: groups(0) }), {
      action: 'redirect',
      to: '/groups/start',
    });
    assert.deepEqual(decideAccess({ ...demo, me: groups(2) }), { action: 'allow' });
    assert.deepEqual(decideAccess({ ...demo, me: fail('forbidden', 403) }), { action: 'allow' });
    assert.deepEqual(decideAccess({ ...demo, path: '/groups/start', me: null }), {
      action: 'allow',
    });
  });

  it('keeps each view to its own screens', () => {
    assert.deepEqual(decideAccess({ ...demo, demoView: 'senior', path: '/calendar', me: null }), {
      action: 'redirect',
      to: '/senior',
    });
    assert.deepEqual(
      decideAccess({ ...signedIn, currentUser: { ok: true, value: { role: 'senior' } }, me: null }),
      { action: 'redirect', to: '/senior' },
    );
  });

  it('leaves every screen open in the demo before a view is chosen', () => {
    assert.deepEqual(decideAccess({ ...demo, demoView: null, me: null }), { action: 'allow' });
  });
});

describe('needsMe', () => {
  it('reads /v1/me for a family screen, and for a signed-in account with no role', () => {
    assert.equal(needsMe(demo), true);
    assert.equal(needsMe({ ...signedIn, currentUser: fail('forbidden', 403) }), true);
  });

  it('skips it when the answer is already known', () => {
    assert.equal(needsMe({ ...demo, path: '/groups/start' }), false);
    assert.equal(needsMe({ ...demo, demoView: 'senior', path: '/senior' }), false);
    assert.equal(needsMe({ ...signedIn, currentUser: fail('unreachable', 0) }), false);
    assert.equal(needsMe({ ...signedIn, currentUser: fail('unauthorized', 401) }), false);
    assert.equal(needsMe({ ...demo, path: '/login' }), false);
  });
});
