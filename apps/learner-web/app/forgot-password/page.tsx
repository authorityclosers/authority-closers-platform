import { AuthFlowPage } from "../components/auth-flow-page";
import { RecoveryRequestForm } from "../components/password-auth-forms";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";

export default function ForgotPasswordPage() {
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
        />
      ) : (
        <RecoveryRequestForm />
      )}
    </AuthFlowPage>
  );
}
