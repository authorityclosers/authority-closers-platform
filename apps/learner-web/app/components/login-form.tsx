import { ArrowRight, LockKeyhole, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { ROUTES } from "../lib/routes";
import { googleAuthStartUrl } from "../lib/auth-links";

export function LoginForm() {
  const authenticateUrl = googleAuthStartUrl("authenticate");
  const registerUrl = googleAuthStartUrl("register");

  return (
    <div className="auth-card">
      <div className="auth-card__topline">
        <span className="auth-card__icon">
          <ShieldCheck size={18} aria-hidden="true" />
        </span>
        <span>Secure session boundary</span>
      </div>
      <h2>Come back to the work.</h2>
      <p className="auth-card__intro">
        Google sign-in starts a one-time server transaction. Provider tokens
        stay behind the API; this browser receives only an opaque session
        cookie.
      </p>
      <div className="stack-form" aria-label="Google learner access">
        <a className="button button--ink button--full" href={authenticateUrl}>
          Continue with Google <ArrowRight size={17} aria-hidden="true" />
        </a>
        <a className="button button--outline button--full" href={registerUrl}>
          Create a free learner account
        </a>
        <p className="field-help">
          Google must return a verified email. A successful-looking callback
          cannot create enrollment or progress by itself.
        </p>
      </div>
      <form className="stack-form" aria-label="Disabled email sign-in preview">
        <div className="field-group">
          <label htmlFor="login-email">Email address</label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            disabled
            aria-describedby="login-email-help"
          />
          <p id="login-email-help" className="field-help">
            No address is collected or sent. Authentication is not connected in
            this preview.
          </p>
        </div>
        <button
          className="button button--ink button--full"
          type="button"
          disabled
        >
          <LockKeyhole size={17} aria-hidden="true" /> Email sign-in unavailable
          in preview
        </button>
      </form>
      <div className="auth-card__footer">
        <span>Need the callback state?</span>
        <Link href={ROUTES.callback}>Open callback status</Link>
      </div>
    </div>
  );
}
