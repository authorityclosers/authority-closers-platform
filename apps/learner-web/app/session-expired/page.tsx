import { AuthFlowPage } from "../components/auth-flow-page";
import { LoginForm } from "../components/login-form";
import { ROUTES } from "../lib/routes";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";

export default function SessionExpiredPage() {
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
      <LoginForm sessionExpired stagingBridge={stagingBridge} />
    </AuthFlowPage>
  );
}
