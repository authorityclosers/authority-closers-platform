import { ArrowLeft, KeyRound } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { ROUTES } from "../lib/routes";
import { PublicShell } from "./site-shell";

type AuthFlowPageProps = {
  eyebrow: string;
  heading: string;
  emphasis: string;
  copy: string;
  backHref?: string;
  backLabel?: string;
  children: ReactNode;
};

export function AuthFlowPage({
  eyebrow,
  heading,
  emphasis,
  copy,
  backHref = ROUTES.login,
  backLabel = "Back to sign in",
  children,
}: AuthFlowPageProps) {
  return (
    <PublicShell>
      <main id="main-content" className="auth-main">
        <div className="auth-layout">
          <div className="auth-context">
            <Link className="text-link" href={backHref}>
              <ArrowLeft size={15} aria-hidden="true" /> {backLabel}
            </Link>
            <p className="eyebrow">
              <span aria-hidden="true" /> {eyebrow}
            </p>
            <h1>
              {heading}
              <br />
              <em>{emphasis}</em>
            </h1>
            <p className="auth-context__copy">{copy}</p>
            <div className="auth-principle">
              <KeyRound size={18} aria-hidden="true" />
              <span>Opaque sessions · bounded learner identity</span>
            </div>
          </div>
          <div className="auth-panel">{children}</div>
        </div>
      </main>
    </PublicShell>
  );
}
