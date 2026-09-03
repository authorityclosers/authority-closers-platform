"use client";

import {
  createLearnerApi,
  type LearnerApi,
  type MeResponse,
} from "../lib/learner-api";
import { SignOutControl } from "./sign-out-control";

const defaultApi = createLearnerApi();

export function hasMembershipRole(me: MeResponse): boolean {
  return me.membership_role === "learner";
}

export type MembershipDraftCleanup = {
  status: "idle" | "pending" | "success" | "failed";
  retry: () => void;
};

export function MembershipDraftCleanupNotice({
  cleanup,
}: {
  cleanup: MembershipDraftCleanup;
}) {
  if (cleanup.status === "idle" || cleanup.status === "success") return null;
  if (cleanup.status === "pending") {
    return (
      <p className="surface-state__supporting" role="status">
        Securing cleanup of this person&apos;s local recovery copies…
      </p>
    );
  }
  return (
    <div className="surface-state__supporting" role="alert">
      <p>
        Local recovery cleanup could not complete. No other person&apos;s copy
        was touched, and learner content remains blocked by the server.
      </p>
      <button className="text-button" type="button" onClick={cleanup.retry}>
        Retry local cleanup
      </button>
    </div>
  );
}

export function MembershipUnavailable({
  api = defaultApi,
  draftCleanup,
}: {
  api?: LearnerApi;
  draftCleanup?: MembershipDraftCleanup;
}) {
  return (
    <section
      className="surface-state surface-state--permission_denied"
      role="alert"
    >
      <h1>Learner membership is unavailable.</h1>
      <p>
        This signed-in identity does not have the exact learner membership role.
        Protected course, progress, and evidence content remains unavailable
        until the server authorizes learner access.
      </p>
      {draftCleanup ? (
        <MembershipDraftCleanupNotice cleanup={draftCleanup} />
      ) : null}
      <SignOutControl api={api} />
    </section>
  );
}
