import { ArrowLeft, KeyRound } from "lucide-react";
import Link from "next/link";

import { LoginForm } from "../components/login-form";
import { PublicShell } from "../components/site-shell";
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
    <PublicShell>
      <main id="main-content" className="auth-main">
        <div className="auth-layout">
          <div className="auth-context">
            <Link className="text-link" href={ROUTES.home}>
              <ArrowLeft size={15} aria-hidden="true" /> Back to home
            </Link>
            <p className="eyebrow">
              <span aria-hidden="true" /> Learner access
            </p>
            <h1>
              Return to the
              <br />
              <em>practice floor.</em>
            </h1>
            <p className="auth-context__copy">
              A named identity keeps enrollment, progress, evidence, and
              certificates in the right hands.
            </p>
            <div className="auth-principle">
              <KeyRound size={18} aria-hidden="true" />
              <span>Secure session lifecycle · preview boundary</span>
            </div>
          </div>
          <div className="auth-panel">
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.login}
              backHref={ROUTES.home}
              pageHeadingPresent
            />
            {isContentVisible(state) ? <LoginForm /> : null}
          </div>
        </div>
      </main>
    </PublicShell>
  );
}
