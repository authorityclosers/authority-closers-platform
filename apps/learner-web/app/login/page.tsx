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
      eyebrow="Learner access"
      heading="Return to the"
      emphasis="practice floor."
      copy="A named identity keeps enrollment, progress, and implementation evidence in the right hands."
      backHref={ROUTES.home}
      backLabel="Back to the public catalog"
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
