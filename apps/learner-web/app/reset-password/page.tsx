import { AuthFlowPage } from "../components/auth-flow-page";
import { PasswordResetForm } from "../components/password-auth-forms";

export default function ResetPasswordPage() {
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
      <PasswordResetForm />
    </AuthFlowPage>
  );
}
