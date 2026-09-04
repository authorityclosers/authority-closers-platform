import { AuthFlowPage } from "../components/auth-flow-page";
import { RegistrationForm } from "../components/password-auth-forms";
import { ROUTES } from "../lib/routes";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";

export default function RegisterPage() {
  const stagingBridge = isStagingAuthenticatedBridge(
    process.env,
    process.env.NODE_ENV,
  );
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
      {stagingBridge ? (
        <StagingAuthHandoff path="/register" action="Account creation" />
      ) : (
        <RegistrationForm />
      )}
    </AuthFlowPage>
  );
}
