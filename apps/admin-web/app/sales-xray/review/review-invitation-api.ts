import { z } from "zod";

import {
  newReviewIdempotencyKey,
  reviewLenses,
  ReviewApiProblem,
  type ReviewMode,
} from "./review-api";

const uuid = z
  .string()
  .uuid()
  .refine((value) => value === value.toLowerCase());
const email = z.string().email().max(320);
const invitationSchema = z
  .object({
    id: uuid,
    run_id: uuid,
    invited_email: email,
    allowed_lenses: z.array(z.enum(reviewLenses)).min(1).max(3),
    created_at_epoch: z.number().int().positive(),
    expires_at_epoch: z.number().int().positive(),
    state: z.enum(["pending", "accepted", "revoked", "expired"]),
    assignment_id: uuid.nullable(),
  })
  .strict()
  .superRefine((value, context) => {
    if (new Set(value.allowed_lenses).size !== value.allowed_lenses.length) {
      context.addIssue({
        code: "custom",
        path: ["allowed_lenses"],
        message: "Invitation lenses must be unique.",
      });
    }
    if (value.expires_at_epoch <= value.created_at_epoch) {
      context.addIssue({
        code: "custom",
        path: ["expires_at_epoch"],
        message: "Invitation expiry must follow creation.",
      });
    }
    if (value.state === "accepted" && !value.assignment_id) {
      context.addIssue({
        code: "custom",
        path: ["assignment_id"],
        message: "Accepted invitations require an assignment.",
      });
    }
  });

export type ReviewInvitation = z.infer<typeof invitationSchema>;
export type CreateReviewInvitationInput = Readonly<{
  runId: string;
  invitedEmail: string;
  allowedLenses: readonly ReviewMode[];
  expiresAtEpoch: number;
  idempotencyKey: string;
  origin?: string;
  fetcher?: typeof fetch;
  signal?: AbortSignal;
}>;

function origin(): string | undefined {
  return typeof window === "undefined" ? undefined : window.location.origin;
}

function boundedKey(value: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$/.test(value)) {
    throw new TypeError("idempotencyKey must be a bounded request key.");
  }
  return value;
}

async function parseProblem(response: Response): Promise<ReviewApiProblem> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    /* generic response */
  }
  const detail =
    typeof body === "object" &&
    body !== null &&
    typeof (body as Record<string, unknown>).detail === "string"
      ? String((body as Record<string, unknown>).detail)
      : "The review invitation request was rejected.";
  return new ReviewApiProblem({
    status: response.status,
    requestId: null,
    detail,
  });
}

async function requestInvitation(
  path: string,
  init: RequestInit,
  fetcher: typeof fetch,
): Promise<ReviewInvitation> {
  const response = await fetcher(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    mode: "same-origin",
    redirect: "error",
  });
  if (!response.ok) throw await parseProblem(response);
  return invitationSchema.parse(await response.json());
}

export function createReviewInvitation({
  runId,
  invitedEmail,
  allowedLenses,
  expiresAtEpoch,
  idempotencyKey,
  origin: requestOrigin = origin(),
  fetcher = fetch,
  signal,
}: CreateReviewInvitationInput): Promise<ReviewInvitation> {
  const body = {
    schema: "ac.sales-xray.review-invitation-create/1" as const,
    run_id: uuid.parse(runId),
    invited_email: email.parse(invitedEmail.trim()),
    allowed_lenses: z
      .array(z.enum(reviewLenses))
      .min(1)
      .max(3)
      .parse([...allowedLenses]),
    expires_at_epoch: z.number().int().positive().parse(expiresAtEpoch),
  };
  const headers = new Headers({
    accept: "application/json",
    "content-type": "application/json",
    "Idempotency-Key": boundedKey(idempotencyKey),
  });
  if (requestOrigin) headers.set("origin", requestOrigin);
  return requestInvitation(
    "/v1/admin/conversation/review-invitations",
    { method: "POST", headers, body: JSON.stringify(body), signal },
    fetcher,
  ).then((invitation) => {
    if (
      invitation.run_id !== body.run_id ||
      invitation.invited_email.toLowerCase() !==
        body.invited_email.toLowerCase() ||
      invitation.expires_at_epoch !== body.expires_at_epoch ||
      invitation.allowed_lenses.length !== body.allowed_lenses.length ||
      invitation.allowed_lenses.some(
        (lens) => !body.allowed_lenses.includes(lens),
      )
    ) {
      throw new Error(
        "The service returned a different invitation. Your request is preserved.",
      );
    }
    return invitation;
  });
}

export function revokeReviewInvitation({
  invitationId,
  idempotencyKey = newReviewIdempotencyKey(),
  origin: requestOrigin = origin(),
  fetcher = fetch,
  signal,
}: {
  invitationId: string;
  idempotencyKey?: string;
  origin?: string;
  fetcher?: typeof fetch;
  signal?: AbortSignal;
}): Promise<ReviewInvitation> {
  const headers = new Headers({
    accept: "application/json",
    "Idempotency-Key": boundedKey(idempotencyKey),
  });
  if (requestOrigin) headers.set("origin", requestOrigin);
  const checkedId = uuid.parse(invitationId);
  return requestInvitation(
    `/v1/admin/conversation/review-invitations/${encodeURIComponent(checkedId)}/revoke`,
    { method: "POST", headers, signal },
    fetcher,
  ).then((invitation) => {
    if (invitation.id !== checkedId || invitation.state !== "revoked")
      throw new Error(
        "The service did not confirm this invitation's revocation.",
      );
    return invitation;
  });
}

export { invitationSchema };
