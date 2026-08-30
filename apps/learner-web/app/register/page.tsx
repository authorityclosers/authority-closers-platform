import { AuthFlowPage } from "../components/auth-flow-page";
import { RegistrationForm } from "../components/password-auth-forms";
import { ROUTES } from "../lib/routes";

export default function RegisterPage() {
  return (
    <AuthFlowPage
      eyebrow="Create your identity"
      heading="Start with"
      emphasis="one honest rep."
      copy="A verified learner identity keeps your course access, workbook evidence, and recovery attached to you."
      backHref={ROUTES.home}
      backLabel="Back to published programs"
    >
      <RegistrationForm />
    </AuthFlowPage>
  );
}
