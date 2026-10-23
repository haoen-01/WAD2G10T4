/**
 * Classifies a caught API failure into what a person can actually do about it.
 *
 * Pure and dependency-free on purpose: it reads the `status` and `code` that `ApiHttpError`
 * (`@silverloop/api-client`) attaches, by shape rather than `instanceof`, so it runs under
 * `node --test` without loading the generated SDK. `lib/api-error.ts` maps the result onto the
 * `ViewError` the views render.
 *
 * The rule the copy follows: the message is always written for the person looking at the screen.
 * Anything the server or the browser said verbatim -- a pydantic validation dump, a stack of JSON,
 * "Failed to fetch" -- is kept only as `technicalDetail`, which the UI puts behind a collapsed
 * disclosure. Nothing here names a framework, a port or a start command, because the person
 * reading it is not necessarily the person running the service, and the service may well be up.
 */

// Type-only: erased at runtime, so this module still loads under `node --test` without the SDK.
import type { ServerErrorCode } from '@silverloop/api-client';

export type ApiErrorKind =
  | 'unauthorized'
  | 'forbidden'
  | 'conflict'
  /** No HTTP response at all: the API could not be reached. */
  | 'unreachable'
  /** The API is up, but stored demo data predates the current contract. A reset fixes it. */
  | 'stored_state'
  /** The API answered with a failure that is not one of the above. */
  | 'server';

export interface ClassifiedApiError {
  kind: ApiErrorKind;
  /** Plain-language copy, safe to render as-is. */
  message: string;
  /** Verbatim text from the server or browser, for a collapsed "Technical detail" only. */
  technicalDetail: string | null;
}

/** The `code` the API puts on a stored snapshot that no longer matches the contract. */
export const STORED_STATE_INCOMPATIBLE_CODE: ServerErrorCode = 'stored_state_incompatible';

export const UNREACHABLE_MESSAGE =
  'Care+ could not reach its service. Check the connection, then retry.';
export const STORED_STATE_MESSAGE =
  "This person's saved data was written by an older version of Care+ and can no longer be read. Starting them over gives them a clean, current state.";
export const SERVER_MESSAGE =
  'Care+ could not complete this request. Try again in a moment, and report it if it keeps happening.';

/** A 409 because a demo reset (or a new simulated day) replaced the story this page was drawn from. */
export const STALE_RUN_CONFLICT_MESSAGE =
  'This person was started over while this page was open — reload to see the current state.';
/** A 409 because this person has no active run yet. */
export const UNSEEDED_CONFLICT_MESSAGE = "This person isn't set up in Care+ yet.";
/** Any other 409 whose server text is not written for a person to read. */
export const CONFLICT_MESSAGE =
  'Something changed while this page was open, so nothing was saved. Reload to see the current state before trying again.';

function statusOf(caught: unknown): number | null {
  if (caught && typeof caught === 'object' && 'status' in caught) {
    const status = (caught as { status: unknown }).status;
    if (typeof status === 'number' && Number.isFinite(status)) return status;
  }
  return null;
}

function codeOf(caught: unknown): string | null {
  if (caught && typeof caught === 'object' && 'code' in caught) {
    const code = (caught as { code: unknown }).code;
    if (typeof code === 'string' && code) return code;
  }
  return null;
}

function rawMessageOf(caught: unknown): string | null {
  if (caught instanceof Error) return caught.message || null;
  if (typeof caught === 'string') return caught || null;
  return null;
}

/**
 * Text that was written for a person, as opposed to something a framework produced. The API's own
 * 4xx details are written to be read ("That day is outside the week being planned"); a serialised
 * validation error, a JSON body or a URL is not.
 */
export function isReadableServerMessage(message: string | null): message is string {
  if (!message) return false;
  const trimmed = message.trim();
  if (!trimmed || trimmed.length > 400) return false;
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) return false;
  // `/v1/...` is a route path and `event_id` an identifier: instructions for whoever calls the API,
  // not for the person looking at the screen.
  return !/validation error|pydantic|field required|traceback|https?:\/\/|localhost|127\.0\.0\.1|port \d+|fastapi|uvicorn|internal server error|\/v\d+\/|\b[a-z]+_id\b/i.test(
    trimmed,
  );
}

/**
 * A 409's server text, sorted into what the reader can do about it. The API has no machine code for
 * these, so the two recoverable families are recognised by the wording the API uses for them
 * (`StaleRunConflict` for a reset run; the uninitialised-run handler for an unseeded person). Neither
 * is ever shown verbatim: both name a route or an identifier.
 */
function conflictMessage(raw: string | null): { message: string; technicalDetail: string | null } {
  if (raw && /\breset\b/i.test(raw) && /request/i.test(raw)) {
    return { message: STALE_RUN_CONFLICT_MESSAGE, technicalDetail: raw };
  }
  if (raw && /not seeded/i.test(raw)) {
    return { message: UNSEEDED_CONFLICT_MESSAGE, technicalDetail: raw };
  }
  if (isReadableServerMessage(raw)) return { message: raw, technicalDetail: null };
  return { message: CONFLICT_MESSAGE, technicalDetail: raw };
}

/** The heading a conflict is shown under, chosen from its already-classified message. */
export function conflictTitle(message: string): string {
  if (message === STALE_RUN_CONFLICT_MESSAGE) return 'This person was started over';
  if (message === UNSEEDED_CONFLICT_MESSAGE) return 'Not set up yet';
  return 'This has already changed';
}

/** A browser-level fetch failure (no HTTP response), for errors that never went through the SDK. */
function looksLikeNetworkFailure(caught: unknown): boolean {
  return (
    caught instanceof TypeError &&
    /failed to fetch|networkerror|network request failed|load failed|fetch failed/i.test(
      caught.message,
    )
  );
}

export function classifyApiError(caught: unknown): ClassifiedApiError {
  const status = statusOf(caught);
  const raw = rawMessageOf(caught);

  if (status === 401) {
    return { kind: 'unauthorized', message: 'Your session has ended.', technicalDetail: null };
  }
  if (status === 403) {
    return {
      kind: 'forbidden',
      message: "You don't have access to this page.",
      technicalDetail: null,
    };
  }
  if (codeOf(caught) === STORED_STATE_INCOMPATIBLE_CODE) {
    return { kind: 'stored_state', message: STORED_STATE_MESSAGE, technicalDetail: raw };
  }
  if (status === 409) {
    return { kind: 'conflict', ...conflictMessage(raw) };
  }
  if (status === 0 || (status === null && looksLikeNetworkFailure(caught))) {
    return { kind: 'unreachable', message: UNREACHABLE_MESSAGE, technicalDetail: raw };
  }
  if (status !== null && status >= 400 && status < 500 && isReadableServerMessage(raw)) {
    return { kind: 'server', message: raw, technicalDetail: null };
  }
  return { kind: 'server', message: SERVER_MESSAGE, technicalDetail: raw };
}
