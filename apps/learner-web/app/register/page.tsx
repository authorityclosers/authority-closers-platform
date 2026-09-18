import { AuthFlowPage } from "../components/auth-flow-page";
import { RegistrationForm } from "../components/password-auth-forms";
import { ROUTES } from "../lib/routes";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { parseCourseIntent } from "../lib/course-intent";
import { parseActivityIntent } from "../lib/activity-intent";
import type { QueryValue } from "../lib/surface-state";
import { parseSalesAuthNext } from "../lib/sales-auth-return";

export default async function RegisterPage({
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
  const salesOnly = Boolean(salesNext && !courseIntent && !activityIntent);
  const stagingBridge = isStagingAuthenticatedBridge(
    process.env,
    process.env.NODE_ENV,
  );
  return (
    <AuthFlowPage
      eyebrow="Create account"
      heading="Create your account."
      copy={
        salesOnly
          ? "Create your account to continue to Sales Xray."
          : "Set up a verified learner identity for the free course."
      }
      backHref={ROUTES.home}
      backLabel="Back to published programs"
      steps={[
        { label: "Identity", state: "outline", detail: "On this page" },
        { label: "Security", state: "outline", detail: "On this page" },
        { label: "Consent", state: "outline", detail: "On this page" },
      ]}
    >
      {stagingBridge ? (
        <StagingAuthHandoff
          path="/register"
          action="Account creation"
          courseIntent={courseIntent}
          activityIntent={activityIntent}
          salesNext={salesNext}
        />
      ) : (
        <RegistrationForm
          courseIntent={courseIntent}
          activityIntent={activityIntent}
          salesNext={salesNext}
        />
      )}
    </AuthFlowPage>
  );
}
