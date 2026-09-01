import { ArrowLeft, CheckCircle2, Circle, CircleDot } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { BrandMark } from "@ac/ui";

import { ROUTES } from "../lib/routes";

type AuthFlowPageProps = {
  eyebrow: string;
  heading: string;
  emphasis?: string;
  copy: string;
  backHref?: string;
  backLabel?: string;
  steps?: ReadonlyArray<{
    label: string;
    state: "complete" | "current" | "upcoming" | "outline";
    detail?: string;
  }>;
  variant?: "standard" | "onboarding";
  children: ReactNode;
};

export function AuthFlowPage({
  eyebrow,
  heading,
  emphasis = "",
  copy,
  backHref = ROUTES.login,
  backLabel = "Back to sign in",
  steps = [
    { label: "Sign in", state: "current" },
    { label: "Verify", state: "upcoming" },
    { label: "Start learning", state: "upcoming" },
  ],
  variant = "standard",
  children,
}: AuthFlowPageProps) {
  return (
    <div className="site-frame site-frame--auth">
      <a className="skip-link" href="#main-content">
        {variant === "onboarding"
          ? "Skip to learning setup"
          : "Skip to authentication"}
      </a>
      <main id="main-content" className="auth-main clarity-auth-main">
        <div className={`clarity-auth-shell clarity-auth-shell--${variant}`}>
          <header className="clarity-auth-masthead">
            <Link
              className="clarity-auth-masthead__back"
              href={backHref}
              aria-label={backLabel}
            >
              <ArrowLeft size={18} aria-hidden="true" />
              <span>{backLabel}</span>
            </Link>
            <Link className="clarity-auth-masthead__brand" href={ROUTES.home}>
              <BrandMark aria-hidden="true" />
              <span>Authority Closers</span>
            </Link>
            <span className="clarity-auth-masthead__task">{eyebrow}</span>
          </header>

          <div className="clarity-auth-workspace">
            <aside className="clarity-auth-ledger" aria-label="Account task">
              <div className="clarity-auth-ledger__intro">
                <p className="clarity-auth-ledger__eyebrow">{eyebrow}</p>
                <h1>
                  {heading}
                  {emphasis ? <span>{emphasis}</span> : null}
                </h1>
                <p>{copy}</p>
              </div>
              <ol className="clarity-auth-steps" aria-label="Task progress">
                {steps.map((step) => {
                  const StepIcon =
                    step.state === "complete"
                      ? CheckCircle2
                      : step.state === "current"
                        ? CircleDot
                        : Circle;
                  return (
                    <li
                      className={`is-${step.state}`}
                      key={step.label}
                      aria-current={
                        step.state === "current" ? "step" : undefined
                      }
                    >
                      <StepIcon size={18} aria-hidden="true" />
                      <span>{step.label}</span>
                      <small>
                        {step.state === "complete"
                          ? "Complete"
                          : step.state === "current"
                            ? "Current"
                            : step.state === "upcoming"
                              ? "Upcoming"
                              : (step.detail ?? "Task outline")}
                      </small>
                    </li>
                  );
                })}
              </ol>
            </aside>

            <section
              className="auth-panel clarity-auth-panel"
              aria-label={eyebrow}
            >
              {children}
            </section>
          </div>

          <footer className="clarity-auth-footer">
            <span>Authority Closers learner access</span>
            <nav aria-label="Account policies">
              <Link href={ROUTES.privacy}>Privacy</Link>
              <Link href={ROUTES.terms}>Terms</Link>
            </nav>
          </footer>
        </div>
      </main>
    </div>
  );
}
