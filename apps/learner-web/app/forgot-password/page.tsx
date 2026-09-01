import { AuthFlowPage } from "../components/auth-flow-page";
import { RecoveryRequestForm } from "../components/password-auth-forms";

export default function ForgotPasswordPage() {
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
      <RecoveryRequestForm />
    </AuthFlowPage>
  );
}
