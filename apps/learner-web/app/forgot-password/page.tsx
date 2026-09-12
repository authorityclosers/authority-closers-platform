import { AuthFlowPage } from "../components/auth-flow-page";
import { RecoveryRequestForm } from "../components/password-auth-forms";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { parseCourseIntent } from "../lib/course-intent";
import { parseActivityIntent } from "../lib/activity-intent";
import type { QueryValue } from "../lib/surface-state";

export default async function ForgotPasswordPage({
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
      eyebrow="Account recovery"
      heading="Recover your access."
      copy="Request a one-time reset link. We never reveal whether an address belongs to an account."
      steps={[
        { label: "Request", state: "current" },
        { label: "Reset", state: "upcoming" },
      ]}
    >
      {stagingBridge ? (
        <StagingAuthHandoff
          path="/forgot-password"
          action="Password recovery"
          courseIntent={courseIntent}
          activityIntent={activityIntent}
        />
      ) : (
        <RecoveryRequestForm
          courseIntent={courseIntent}
          activityIntent={activityIntent}
        />
      )}
    </AuthFlowPage>
  );
}
