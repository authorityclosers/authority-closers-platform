import { AuthFlowPage } from "../components/auth-flow-page";
import { LoginForm } from "../components/login-form";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../lib/surface-state";

type LoginPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <AuthFlowPage
      eyebrow="Account access"
      heading="Sign in to your account."
      copy="Sign in to continue your Authority Closers learning."
      backHref={ROUTES.home}
      backLabel="Back to the public catalog"
      steps={[
        { label: "Sign in", state: "current" },
        { label: "Verify", state: "upcoming" },
        { label: "Start learning", state: "upcoming" },
      ]}
    >
      {state !== "DEFAULT" ? (
        <SurfaceStatePanel
          state={state}
          retryHref={ROUTES.login}
          backHref={ROUTES.home}
          pageHeadingPresent
        />
      ) : null}
      {isContentVisible(state) ? <LoginForm /> : null}
    </AuthFlowPage>
  );
}
