import { AuthFlowPage } from "../components/auth-flow-page";
import { PasswordResetForm } from "../components/password-auth-forms";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { parseCourseIntent } from "../lib/course-intent";
import { parseActivityIntent } from "../lib/activity-intent";
import type { QueryValue } from "../lib/surface-state";

export default async function ResetPasswordPage({
  searchParams = Promise.resolve({}),
}: {
  searchParams?: Promise<{ course?: QueryValue; activity?: QueryValue }>;
} = {}) {
  const query = await searchParams;
  const courseIntent = parseCourseIntent(query.course);
  const activityIntent = parseActivityIntent(query.activity);
  const stagingBridge = isStagingAuthenticatedBridge(
    process.env,
    process.env.NODE_ENV,
  );
  return (
    <AuthFlowPage
      eyebrow="Password reset"
      heading="Choose a new password."
      copy="The reset link is valid for 30 minutes. A successful reset signs out earlier sessions."
      steps={[
        { label: "Request", state: "complete" },
        { label: "Reset", state: "current" },
      ]}
    >
      {stagingBridge ? (
        <StagingAuthHandoff
          path="/reset-password"
          action="Password reset"
          courseIntent={courseIntent}
          activityIntent={activityIntent}
        />
      ) : (
        <PasswordResetForm
          courseIntent={courseIntent}
          activityIntent={activityIntent}
        />
      )}
    </AuthFlowPage>
  );
}
