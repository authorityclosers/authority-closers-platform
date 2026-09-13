import { useSyncExternalStore } from "react";

export const REVIEW_INVITATION_PATH = "/sales-xray/review/invite" as const;
const INTERNAL_FRAGMENT_KEY = "review_invitation";
const EMAIL_FRAGMENT_KEY = "token";

function validToken(value: string | null): string | null {
  if (!value || value.length < 40 || value.length > 512 || /\s/.test(value))
    return null;
  return value;
}

/** Read an invitation token without writing it to storage, analytics, or query parameters. */
export function readReviewInvitationToken(
  hash: string,
  includeEmailToken = false,
): string | null {
  const parameters = new URLSearchParams(
    hash.startsWith("#") ? hash.slice(1) : hash,
  );
  return (
    validToken(parameters.get(INTERNAL_FRAGMENT_KEY)) ??
    (includeEmailToken ? validToken(parameters.get(EMAIL_FRAGMENT_KEY)) : null)
  );
}

export function reviewInvitationFragment(token: string): string {
  const checked = validToken(token);
  if (!checked) throw new TypeError("The review invitation token is invalid.");
  return `#${INTERNAL_FRAGMENT_KEY}=${encodeURIComponent(checked)}`;
}

export function reviewInvitationHref(token: string): string {
  return `${REVIEW_INVITATION_PATH}${reviewInvitationFragment(token)}`;
}

export function withReviewInvitationToken(
  path: string,
  token: string | null,
): string {
  return token ? `${path}${reviewInvitationFragment(token)}` : path;
}

const subscribeHash = (onChange: () => void) => {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
};

const clientHash = () =>
  typeof window === "undefined"
    ? null
    : readReviewInvitationToken(window.location.hash);

/** Keeps the handoff in the URL fragment while normal auth pages transition. */
export function useReviewInvitationToken(): string | null {
  return useSyncExternalStore(subscribeHash, clientHash, () => null);
}

export function clearReviewInvitationFragment(): void {
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${window.location.search}`,
  );
}
