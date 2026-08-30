import { ArrowLeft, CheckCircle2, Circle, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { PublicShell } from "../../components/site-shell";
import { SurfaceStatePanel } from "../../components/surface-state";
import { ROUTES } from "../../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../../lib/surface-state";

type CallbackPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

const callbackSteps = [
  {
    label: "Auth transaction",
    detail: "State and nonce created server-side",
    done: false,
  },
  {
    label: "Provider assertion",
    detail: "Issuer and audience verified",
    done: false,
  },
  {
    label: "Named session",
    detail: "Session linked to the person record",
    done: false,
  },
];

export default async function CallbackPage({
  searchParams,
}: CallbackPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <PublicShell>
      <main id="main-content" className="auth-main">
        <div className="narrow-container">
          <Link className="text-link" href={ROUTES.login}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to sign in
          </Link>
          <section className="callback-card" aria-labelledby="callback-title">
            <div className="callback-card__icon">
              <ShieldCheck size={22} aria-hidden="true" />
            </div>
            <p className="eyebrow">
              <span aria-hidden="true" /> Secure callback boundary
            </p>
            <h1 id="callback-title">
              Sign-in callback
              <br />
              <em>status.</em>
            </h1>
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.callback}
              backHref={ROUTES.login}
              pageHeadingPresent
            />
            {isContentVisible(state) ? (
              <>
                <p className="callback-card__intro">
                  No callback payload is present in this preview. The connected
                  route would consume a one-time assertion and create a session
                  only after server checks pass.
                </p>
                <ol className="callback-steps">
                  {callbackSteps.map((step) => (
                    <li key={step.label}>
                      <span className="callback-steps__icon">
                        {step.done ? (
                          <CheckCircle2 size={16} aria-hidden="true" />
                        ) : (
                          <Circle size={16} aria-hidden="true" />
                        )}
                      </span>
                      <span>
                        <strong>{step.label}</strong>
                        <small>{step.detail}</small>
                      </span>
                      <span className="callback-steps__status">
                        Not started
                      </span>
                    </li>
                  ))}
                </ol>
                <div className="boundary-card boundary-card--dark" role="note">
                  <strong>Preview boundary</strong>
                  <span>
                    A successful-looking browser return cannot grant access.
                    Identity, session, and entitlement remain server concerns.
                  </span>
                </div>
              </>
            ) : null}
          </section>
        </div>
      </main>
    </PublicShell>
  );
}
