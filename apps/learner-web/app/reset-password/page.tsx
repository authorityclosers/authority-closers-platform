import { AuthFlowPage } from "../components/auth-flow-page";
import { PasswordResetForm } from "../components/password-auth-forms";

export default function ResetPasswordPage() {
  return (
    <AuthFlowPage
      eyebrow="Secure password reset"
      heading="Reset access."
      emphasis="Keep the evidence."
      copy="A successful reset revokes earlier sessions while preserving your canonical learner work."
    >
      <PasswordResetForm />
    </AuthFlowPage>
  );
}
