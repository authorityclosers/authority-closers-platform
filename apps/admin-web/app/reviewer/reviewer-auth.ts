import { z } from "zod";

import { ReviewerApiProblem } from "./reviewer-api";

const uuid = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
const opaqueToken = z.string().min(40).max(512).refine((value) => !/\s/u.test(value), "Token is malformed.");
const email = z.string().trim().toLowerCase().email().max(320);

export const reviewerIdentitySchema = z.object({
  person_id: uuid,
  email,
  display_name: z.string().nullable(),
  expires_at_epoch: z.number().int().positive(),
});
export const reviewerVerificationSchema = reviewerIdentitySchema.extend({
  assignment_id: uuid.nullable(),
});
export type ReviewerIdentity = z.infer<typeof reviewerIdentitySchema>;
export type ReviewerVerification = z.infer<typeof reviewerVerificationSchema>;

export const REVIEWER_INVITATION_PATH = "/reviewer/invite";
export const REVIEWER_VERIFICATION_PATH = "/reviewer/verify";

function readFragmentToken(hash: string, key = "token"): string | null {
  if (!hash.startsWith("#")) return null;
  const params = new URLSearchParams(hash.slice(1));
  const value = params.get(key);
  if (!value) return null;
  const parsed = opaqueToken.safeParse(value);
  return parsed.success ? parsed.data : null;
}

export function readReviewerToken(hash: string): string | null {
  return readFragmentToken(hash);
}

export function clearReviewerFragment(): void {
  if (typeof window !== "undefined" && window.location.hash) {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  }
}

export function withReviewerToken(path: string, token: string): string {
  const parsed = opaqueToken.parse(token);
  return `${path}#token=${encodeURIComponent(parsed)}`;
}

async function request<T>(path: string, init: RequestInit, schema?: z.ZodType<T>): Promise<T | undefined> {
  if (!path.startsWith("/v1/reviewer/") || path.startsWith("//")) throw new TypeError("Reviewer auth must use a dedicated same-origin path.");
  const response = await fetch(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    mode: "same-origin",
    redirect: "error",
    headers: { accept: "application/json", ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    let body: unknown = null;
    try { body = await response.json(); } catch { /* empty problem response */ }
    const candidate = typeof body === "object" && body !== null ? body as Record<string, unknown> : {};
    throw new ReviewerApiProblem(
      response.status,
      typeof candidate.detail === "string" && candidate.detail.trim() ? candidate.detail : "The reviewer sign-in request was rejected.",
      typeof candidate.request_id === "string" ? candidate.request_id : null,
    );
  }
  if (!schema || response.status === 204) return undefined;
  let body: unknown;
  try { body = await response.json(); } catch { throw new Error("The reviewer service returned an empty response."); }
  return schema.parse(body);
}

export function loadReviewerSession(signal?: AbortSignal): Promise<ReviewerIdentity | undefined> {
  return request("/v1/reviewer/me", { method: "GET", signal }, reviewerIdentitySchema);
}

export function requestReviewerSignIn(emailAddress: string, invitationToken?: string): Promise<void> {
  const body = { email: email.parse(emailAddress), ...(invitationToken ? { invitation_token: opaqueToken.parse(invitationToken) } : {}) };
  return request("/v1/reviewer/auth/request", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }).then(() => undefined);
}

export function verifyReviewerSignIn(token: string): Promise<ReviewerVerification> {
  return request("/v1/reviewer/auth/verify", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token: opaqueToken.parse(token) }) }, reviewerVerificationSchema) as Promise<ReviewerVerification>;
}

export function logoutReviewer(): Promise<void> {
  return request("/v1/reviewer/auth/logout", { method: "POST" }).then(() => undefined);
}

export function reviewerAuthErrorMessage(error: unknown): string {
  if (error instanceof ReviewerApiProblem) {
    if (error.status === 401) return "That sign-in link is invalid or expired. Request a fresh link.";
    if (error.status === 403) return "Reviewer access is not active for this address.";
    if (error.status === 404) return "That reviewer link is unavailable.";
    if (error.status === 429) return "Too many requests. Wait a moment and try again.";
  }
  return error instanceof Error && !(error instanceof z.ZodError) ? error.message : "Reviewer sign-in could not be completed.";
}
