import { AuthFlowPage } from "../components/auth-flow-page";
import { PasswordResetForm } from "../components/password-auth-forms";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";

export default function ResetPasswordPage() {
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
        <StagingAuthHandoff path="/reset-password" action="Password reset" />
      ) : (
        <PasswordResetForm />
      )}
    </AuthFlowPage>
  );
}
