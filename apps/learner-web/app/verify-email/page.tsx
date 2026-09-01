import { AuthFlowPage } from "../components/auth-flow-page";
import { VerifyEmailFlow } from "../components/password-auth-forms";

export default function VerifyEmailPage() {
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
      <VerifyEmailFlow />
    </AuthFlowPage>
  );
}
