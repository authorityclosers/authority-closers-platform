import { AuthFlowPage } from "../components/auth-flow-page";
import { VerifyEmailFlow } from "../components/password-auth-forms";

export default function VerifyEmailPage() {
  return (
    <AuthFlowPage
      eyebrow="Email verification"
      heading="Confirm the"
      emphasis="right hands."
      copy="This one-time link verifies your learner identity before enrollment or progress can begin."
    >
      <VerifyEmailFlow />
    </AuthFlowPage>
  );
}
