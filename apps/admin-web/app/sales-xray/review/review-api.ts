/**
 * The DTO is intentionally not guessed here. The Sales service owns the
 * assignment/read/submit route and will bind this adapter once its contract is
 * frozen. Keeping the route client isolated prevents the UI from inventing a
 * permission or persistence shape.
 */
export type ReviewMode = "sales" | "technical" | "ux";

export type ReviewQueueState =
  | { status: "loading" }
  | { status: "ready"; payload: unknown }
  | { status: "error"; message: string; retryable: boolean };

export function reviewError(error: unknown): {
  message: string;
  retryable: boolean;
} {
  if (error instanceof Error) {
    return {
      message: error.message || "The review queue could not be loaded.",
      retryable: (error as Error & { retryable?: boolean }).retryable ?? true,
    };
  }
  return {
    message:
      "The review queue could not be loaded. Retry when the service is available.",
    retryable: true,
  };
}
