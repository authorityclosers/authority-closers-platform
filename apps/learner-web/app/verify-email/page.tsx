import { AuthFlowPage } from "../components/auth-flow-page";
import { VerifyEmailFlow } from "../components/password-auth-forms";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";

export default function VerifyEmailPage() {
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
        <StagingAuthHandoff path="/verify-email" action="Email verification" />
      ) : (
        <VerifyEmailFlow />
      )}
    </AuthFlowPage>
  );
}
