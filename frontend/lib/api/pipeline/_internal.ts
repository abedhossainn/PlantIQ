/**
 * Pipeline API - Internal Utilities
 *
 * Shared helpers used by ingestion-sse.ts and optimization-sse.ts.
 * Not part of the public barrel export.
 */

export function isAbortLikeError(error: unknown): boolean {
  if (error instanceof DOMException) {
    return error.name === 'AbortError';
  }
  if (error instanceof Error) {
    return error.name === 'AbortError' || /aborted/i.test(error.message);
  }
  return false;
}
