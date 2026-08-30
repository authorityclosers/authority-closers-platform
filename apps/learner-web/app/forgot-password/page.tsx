import { AuthFlowPage } from "../components/auth-flow-page";
import { RecoveryRequestForm } from "../components/password-auth-forms";

export default function ForgotPasswordPage() {
  return (
    <AuthFlowPage
      eyebrow="Account recovery"
      heading="Get back to"
      emphasis="the practice floor."
      copy="Recovery links are one-time, short-lived, and never reveal whether an address belongs to an account."
    >
      <RecoveryRequestForm />
    </AuthFlowPage>
  );
}
