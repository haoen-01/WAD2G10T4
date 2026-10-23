import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  CONFLICT_MESSAGE,
  SERVER_MESSAGE,
  STALE_RUN_CONFLICT_MESSAGE,
  STORED_STATE_MESSAGE,
  UNREACHABLE_MESSAGE,
  UNSEEDED_CONFLICT_MESSAGE,
  classifyApiError,
  conflictTitle,
  isReadableServerMessage,
} from './api-errors';

/** The shape `ApiHttpError` has at runtime, without importing the generated SDK. */
class FakeApiHttpError extends Error {
  readonly status: number;
  readonly code: string | undefined;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = 'ApiHttpError';
    this.status = status;
    this.code = code;
  }
}

const PYDANTIC_TEXT =
  "1 validation error for AdvanceResponse\nstate.decided_by_gate\n  Field required [type=missing, input_value={'person_id': 'mdm-lim'}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing";

const FORBIDDEN_COPY = /FastAPI|port 8000|8000|validation error|pydantic|Failed to fetch|https?:/i;

describe('classifyApiError', () => {
  it('reports a request that never got an HTTP response as unreachable, keeping the raw text as detail only', () => {
    const result = classifyApiError(new FakeApiHttpError(0, 'Failed to fetch'));

    assert.equal(result.kind, 'unreachable');
    assert.equal(result.message, UNREACHABLE_MESSAGE);
    assert.equal(result.technicalDetail, 'Failed to fetch');
    assert.doesNotMatch(result.message, FORBIDDEN_COPY);
  });

  it('treats a bare browser fetch failure outside the SDK as unreachable', () => {
    assert.equal(classifyApiError(new TypeError('Failed to fetch')).kind, 'unreachable');
  });

  it('does not call an ordinary script error an unreachable API', () => {
    const result = classifyApiError(
      new TypeError("Cannot read properties of undefined (reading 'x')"),
    );

    assert.equal(result.kind, 'server');
    assert.equal(result.message, SERVER_MESSAGE);
  });

  it('classifies the stored-state code as its own kind, whatever the message says', () => {
    const result = classifyApiError(
      new FakeApiHttpError(
        500,
        'Stored demo state was saved by an older version.',
        'stored_state_incompatible',
      ),
    );

    assert.equal(result.kind, 'stored_state');
    assert.equal(result.message, STORED_STATE_MESSAGE);
    assert.doesNotMatch(result.message, FORBIDDEN_COPY);
  });

  it('never renders raw pydantic text for a legacy 422, even without a code', () => {
    const result = classifyApiError(new FakeApiHttpError(422, PYDANTIC_TEXT));

    assert.equal(result.kind, 'server');
    assert.equal(result.message, SERVER_MESSAGE);
    assert.equal(result.technicalDetail, PYDANTIC_TEXT);
  });

  it('uses a generic message for any 5xx and keeps the server text as detail', () => {
    const result = classifyApiError(
      new FakeApiHttpError(500, 'Care+ hit a server error.', 'internal_error'),
    );

    assert.equal(result.kind, 'server');
    assert.equal(result.message, SERVER_MESSAGE);
    assert.equal(result.technicalDetail, 'Care+ hit a server error.');
  });

  it('keeps a human-written 4xx domain message', () => {
    const result = classifyApiError(
      new FakeApiHttpError(422, 'That day is outside the week being planned.'),
    );

    assert.deepEqual(result, {
      kind: 'server',
      message: 'That day is outside the week being planned.',
      technicalDetail: null,
    });
  });

  it('does not render a serialised JSON body as a message', () => {
    const body = JSON.stringify({
      detail: [{ loc: ['body', 'event'], msg: 'Input should be a valid string' }],
    });
    const result = classifyApiError(new FakeApiHttpError(422, body));

    assert.equal(result.message, SERVER_MESSAGE);
    assert.equal(result.technicalDetail, body);
  });

  it('keeps the existing session, role and conflict classifications', () => {
    assert.equal(classifyApiError(new FakeApiHttpError(401, 'x')).kind, 'unauthorized');
    assert.equal(classifyApiError(new FakeApiHttpError(403, 'x')).kind, 'forbidden');
    const conflict = classifyApiError(
      new FakeApiHttpError(409, 'That answer was already recorded.'),
    );
    assert.deepEqual(conflict, {
      kind: 'conflict',
      message: 'That answer was already recorded.',
      technicalDetail: null,
    });
  });

  it('says a reset run in fixed copy, keeping the server text as detail only', () => {
    const raw =
      "This person's demo story was reset while this request was waiting, so this request was not applied to the new story. Re-read the person before trying again.";
    const result = classifyApiError(new FakeApiHttpError(409, raw));

    assert.deepEqual(result, {
      kind: 'conflict',
      message: STALE_RUN_CONFLICT_MESSAGE,
      technicalDetail: raw,
    });
    assert.equal(conflictTitle(result.message), 'This person was started over');
  });

  it('never shows the unseeded-run text, which names a route', () => {
    const raw =
      "'No active run for mdm-lim' This person exists but is not seeded for an active run. POST /v1/demo/reset (or run the demo seed step) before retrying.";
    const result = classifyApiError(new FakeApiHttpError(409, raw));

    assert.equal(result.kind, 'conflict');
    assert.equal(result.message, UNSEEDED_CONFLICT_MESSAGE);
    assert.equal(result.technicalDetail, raw);
    assert.doesNotMatch(result.message, /\/v1\/|POST|seed/);
    assert.equal(conflictTitle(result.message), 'Not set up yet');
  });

  it('uses a generic conflict message for 409 text written for a caller, not a person', () => {
    const raw =
      "This simulated day was already advanced by a concurrent request. Re-read the person's state, or pass an event_id to make the call idempotent.";
    const result = classifyApiError(new FakeApiHttpError(409, raw));

    assert.deepEqual(result, { kind: 'conflict', message: CONFLICT_MESSAGE, technicalDetail: raw });
    assert.equal(conflictTitle(result.message), 'This has already changed');

    const empty = classifyApiError(new FakeApiHttpError(409, ''));
    assert.equal(empty.message, CONFLICT_MESSAGE);
    assert.equal(empty.technicalDetail, null);
  });

  it('keeps a readable review-timing conflict, under the generic conflict title', () => {
    const result = classifyApiError(
      new FakeApiHttpError(409, 'This proposal was already decided.'),
    );

    assert.deepEqual(result, {
      kind: 'conflict',
      message: 'This proposal was already decided.',
      technicalDetail: null,
    });
    assert.equal(conflictTitle(result.message), 'This has already changed');
  });

  it('handles a thrown non-error value without inventing an outage', () => {
    const result = classifyApiError({ unexpected: true });

    assert.equal(result.kind, 'server');
    assert.equal(result.technicalDetail, null);
  });
});

describe('isReadableServerMessage', () => {
  it('rejects framework and connection text', () => {
    for (const text of [
      PYDANTIC_TEXT,
      'Start the FastAPI service on port 8000, then retry.',
      'Internal Server Error',
      'connect ECONNREFUSED http://127.0.0.1:8000',
      'POST /v1/demo/reset before retrying.',
      'Pass an event_id to make the call idempotent.',
      '',
    ]) {
      assert.equal(isReadableServerMessage(text), false, text);
    }
  });

  it('accepts plain domain copy', () => {
    assert.equal(isReadableServerMessage('Person not found'), true);
  });
});
