import { AuthFlowPage } from "../components/auth-flow-page";
import { RegistrationForm } from "../components/password-auth-forms";
import { ROUTES } from "../lib/routes";

export default function RegisterPage() {
  return (
    <AuthFlowPage
      eyebrow="Create account"
      heading="Create your account."
      copy="Set up a verified learner identity for the free course."
      backHref={ROUTES.home}
      backLabel="Back to published programs"
      steps={[
        { label: "Identity", state: "outline", detail: "On this page" },
        { label: "Security", state: "outline", detail: "On this page" },
        { label: "Consent", state: "outline", detail: "On this page" },
      ]}
    >
      <RegistrationForm />
    </AuthFlowPage>
  );
}
