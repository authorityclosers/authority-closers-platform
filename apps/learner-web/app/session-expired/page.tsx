import { AuthFlowPage } from "../components/auth-flow-page";
import { LoginForm } from "../components/login-form";
import { ROUTES } from "../lib/routes";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { parseCourseIntent } from "../lib/course-intent";
import type { QueryValue } from "../lib/surface-state";

export default async function SessionExpiredPage({
  searchParams = Promise.resolve({}),
}: { searchParams?: Promise<{ course?: QueryValue }> } = {}) {
  const courseIntent = parseCourseIntent((await searchParams).course);
  const stagingBridge = isStagingAuthenticatedBridge(
    process.env,
    process.env.NODE_ENV,
  );
  return (
    <AuthFlowPage
      eyebrow="Session ended"
      heading="Your session ended."
      copy="Complete sign-in again. We will re-check access before returning you to the learner workspace."
      backHref={ROUTES.home}
      backLabel="Return to the public catalog"
      steps={[
        { label: "Reconnect", state: "current" },
        { label: "Resume", state: "upcoming" },
      ]}
    >
      <LoginForm
        sessionExpired
        stagingBridge={stagingBridge}
        courseIntent={courseIntent}
      />
    </AuthFlowPage>
  );
}
