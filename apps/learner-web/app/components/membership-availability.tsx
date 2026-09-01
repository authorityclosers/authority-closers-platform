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

export function MembershipUnavailable({
  api = defaultApi,
}: {
  api?: LearnerApi;
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
      <SignOutControl api={api} />
    </section>
  );
}
