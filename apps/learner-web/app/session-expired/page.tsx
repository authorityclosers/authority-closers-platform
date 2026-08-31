import { AuthFlowPage } from "../components/auth-flow-page";
import { LoginForm } from "../components/login-form";
import { ROUTES } from "../lib/routes";

export default function SessionExpiredPage() {
  return (
    <AuthFlowPage
      eyebrow="Session ended"
      heading="Your work is"
      emphasis="still safe."
      copy="Your secure browser session ended. Sign in again to return to the server-authoritative learner workspace; this page never guesses or restores access in the browser."
      backHref={ROUTES.home}
      backLabel="Return to the public catalog"
    >
      <LoginForm />
    </AuthFlowPage>
  );
}
