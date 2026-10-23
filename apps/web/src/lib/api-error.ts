import { ApiHttpError } from '@silverloop/api-client';

import { classifyApiError, type ApiErrorKind } from './api-errors';

/**
 * `SilverLoopClient` (see `@silverloop/api-client`) attaches the real HTTP status to
 * every failed request as `ApiHttpError`. This module is the app's classification
 * layer on top of that: it turns a caught error into the copy/variant the views
 * render, so a session expiry (401) or a wrong-role account (403) never gets the
 * same "cannot reach the API" message as a genuine network outage. The classification
 * itself lives in the dependency-free `lib/api-errors.ts`, which is unit-tested.
 */
export function isUnauthorized(error: unknown): error is ApiHttpError {
  return error instanceof ApiHttpError && error.status === 401;
}

export function isForbidden(error: unknown): error is ApiHttpError {
  return error instanceof ApiHttpError && error.status === 403;
}

/**
 * A 409 means the server correctly rejected a request that raced another one for the same
 * resource (e.g. two `advance` calls for the same simulated day) — the API is healthy and the
 * other request most likely succeeded. It is a conflict to resolve, never an outage to report.
 */
export function isConflict(error: unknown): error is ApiHttpError {
  return error instanceof ApiHttpError && error.status === 409;
}

/**
 * `network` means no HTTP response was produced (the API cannot be reached); `stored_state`
 * means the API is up but stored demo data predates the current contract; `server` is every
 * other failed response.
 */
export type ViewErrorVariant =
  'unauthorized' | 'forbidden' | 'conflict' | 'network' | 'stored_state' | 'server';

export interface ViewError {
  variant: ViewErrorVariant;
  /** Plain-language copy, always safe to render. Never raw server or browser text. */
  message: string;
  /** Verbatim server/browser text, for a collapsed "Technical detail" disclosure only. */
  technicalDetail?: string;
}

const VARIANT_FOR_KIND: Record<ApiErrorKind, ViewErrorVariant> = {
  unauthorized: 'unauthorized',
  forbidden: 'forbidden',
  conflict: 'conflict',
  unreachable: 'network',
  stored_state: 'stored_state',
  server: 'server',
};

/** Shared mapping from a caught API error to the copy/variant the views render. */
export function toViewError(caught: unknown): ViewError {
  const classified = classifyApiError(caught);
  const view: ViewError = {
    variant: VARIANT_FOR_KIND[classified.kind],
    message: classified.message,
  };
  if (classified.technicalDetail) view.technicalDetail = classified.technicalDetail;
  return view;
}
