import { AuthFlowPage } from "../components/auth-flow-page";
import { VerifyEmailFlow } from "../components/password-auth-forms";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { parseCourseIntent } from "../lib/course-intent";
import { parseActivityIntent } from "../lib/activity-intent";
import type { QueryValue } from "../lib/surface-state";

export default async function VerifyEmailPage({
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
      eyebrow="Verify email"
      heading="Check your inbox."
      copy="Use the one-time link within 24 hours to verify your learner identity."
      steps={[
        { label: "Identity", state: "complete" },
        { label: "Verify", state: "current" },
        { label: "Start learning", state: "upcoming" },
      ]}
    >
      {stagingBridge ? (
        <StagingAuthHandoff
          path="/verify-email"
          action="Email verification"
          courseIntent={courseIntent}
          activityIntent={activityIntent}
        />
      ) : (
        <VerifyEmailFlow
          courseIntent={courseIntent}
          activityIntent={activityIntent}
        />
      )}
    </AuthFlowPage>
  );
}
