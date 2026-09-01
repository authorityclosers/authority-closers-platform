import { ApiError } from "./learner-api";

export function userFacingRequestError(
  error: unknown,
  fallback: string,
): string {
  if (
    error instanceof ApiError &&
    error.status >= 400 &&
    error.status < 500 &&
    error.message.trim()
  ) {
    return error.message;
  }
  return fallback;
}
