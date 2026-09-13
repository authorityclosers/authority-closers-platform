import { z } from "zod";

import { reviewAssignmentTransportSchema } from "./review-assignment-api";

const invitationTokenSchema = z
  .string()
  .min(40)
  .max(512)
  .refine((value) => !/\s/.test(value), "The invitation token is invalid.");

export type AcceptedReviewInvitation = z.infer<
  typeof reviewAssignmentTransportSchema
>;

export class ReviewInvitationApiProblem extends Error {
  readonly status: number;
  readonly retryable: boolean;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ReviewInvitationApiProblem";
    this.status = status;
    this.retryable = status >= 500 || status === 408 || status === 429;
  }
}

type Fetcher = typeof fetch;

async function problem(
  response: Response,
): Promise<ReviewInvitationApiProblem> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Keep the invitation error generic when the service does not return JSON.
  }
  const detail =
    typeof body === "object" &&
    body !== null &&
    typeof (body as Record<string, unknown>).detail === "string"
      ? String((body as Record<string, unknown>).detail)
      : "The invitation could not be accepted.";
  return new ReviewInvitationApiProblem(response.status, detail);
}

export async function acceptReviewInvitation(
  token: string,
  fetcher: Fetcher = fetch,
): Promise<AcceptedReviewInvitation> {
  const checked = invitationTokenSchema.parse(token);
  const response = await fetcher("/v1/conversation/review-invitations/accept", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    mode: "same-origin",
    redirect: "error",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      schema: "ac.sales-xray.review-invitation-accept/1",
      token: checked,
    }),
  });
  if (!response.ok) throw await problem(response);
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The invitation service returned no assignment.");
  }
  return reviewAssignmentTransportSchema.parse(payload);
}

export function reviewInvitationErrorMessage(error: unknown): string {
  if (error instanceof ReviewInvitationApiProblem) {
    if (error.status === 401 || error.status === 403) {
      return "Sign in with the invited email address before accepting this invitation.";
    }
    if (error.status === 404) {
      return "This invitation is unavailable, expired, revoked, or linked to another verified email.";
    }
    if (error.status === 409) {
      return "The saved review binding changed. Ask the administrator for a new invitation.";
    }
  }
  return error instanceof Error
    ? error.message
    : "The invitation service could not be reached.";
}
