import { AuthFlowPage } from "../components/auth-flow-page";
import { RegistrationForm } from "../components/password-auth-forms";
import { ROUTES } from "../lib/routes";

export default function RegisterPage() {
  return (
    <AuthFlowPage
      eyebrow="Create your identity"
      heading="Learn. Practice."
      emphasis="Prove progress."
      copy="Build the skill, put it to work, and keep the evidence attached to your verified learner identity."
      backHref={ROUTES.home}
      backLabel="Back to published programs"
    >
      <RegistrationForm />
    </AuthFlowPage>
  );
}
