import { AuthFlowPage } from "../components/auth-flow-page";
import { LoginForm } from "../components/login-form";
import { ROUTES } from "../lib/routes";

export default function SessionExpiredPage() {
  return (
    <AuthFlowPage
      eyebrow="Session ended"
      heading="Your session ended."
      copy="Complete sign-in again. We will re-check access before returning you to the learner workspace."
      backHref={ROUTES.home}
      backLabel="Return to the public catalog"
      steps={[
        { label: "Reconnect", state: "current" },
        { label: "Resume", state: "upcoming" },
      ]}
    >
      <LoginForm sessionExpired />
    </AuthFlowPage>
  );
}
