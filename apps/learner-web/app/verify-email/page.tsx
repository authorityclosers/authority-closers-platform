import { AuthFlowPage } from "../components/auth-flow-page";
import { VerifyEmailFlow } from "../components/password-auth-forms";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { parseCourseIntent } from "../lib/course-intent";
import { parseActivityIntent } from "../lib/activity-intent";
import type { QueryValue } from "../lib/surface-state";
import { parseSalesAuthNext } from "../lib/sales-auth-return";

export default async function VerifyEmailPage({
  searchParams = Promise.resolve({}),
}: {
  searchParams?: Promise<{
    course?: QueryValue;
    activity?: QueryValue;
    next?: QueryValue;
  }>;
} = {}) {
  const query = await searchParams;
  const courseIntent = parseCourseIntent(query.course);
  const activityIntent = parseActivityIntent(query.activity);
  const salesNext = parseSalesAuthNext(query.next);
  const stagingBridge = isStagingAuthenticatedBridge(
    process.env,
    process.env.NODE_ENV,
  );
  return (
    <AuthFlowPage
      eyebrow="Verify email"
      heading="Email verification."
      copy="Use the one-time link within 24 hours to verify your learner identity. This page also lets you request a fresh link if needed."
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
          salesNext={salesNext}
        />
      ) : (
        <VerifyEmailFlow
          courseIntent={courseIntent}
          activityIntent={activityIntent}
          salesNext={salesNext}
        />
      )}
    </AuthFlowPage>
  );
}
