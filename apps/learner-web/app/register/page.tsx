import { AuthFlowPage } from "../components/auth-flow-page";
import { RegistrationForm } from "../components/password-auth-forms";
import { ROUTES } from "../lib/routes";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { parseCourseIntent } from "../lib/course-intent";
import type { QueryValue } from "../lib/surface-state";

export default async function RegisterPage({
  searchParams = Promise.resolve({}),
}: { searchParams?: Promise<{ course?: QueryValue }> } = {}) {
  const courseIntent = parseCourseIntent((await searchParams).course);
  const stagingBridge = isStagingAuthenticatedBridge(
    process.env,
    process.env.NODE_ENV,
  );
  return (
    <AuthFlowPage
      eyebrow="Create account"
      heading="Create your account."
      copy="Set up a verified learner identity for the free course."
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
        />
      ) : (
        <RegistrationForm courseIntent={courseIntent} />
      )}
    </AuthFlowPage>
  );
}
