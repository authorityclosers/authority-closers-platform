"use client";

import { ArrowLeft, CheckCircle2, ChevronRight, Circle } from "lucide-react";
import Link from "next/link";
import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useContext,
  useMemo,
  useState,
} from "react";

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
  liveProgress?: boolean;
  variant?: "standard" | "onboarding";
  children?: ReactNode;
};

export type AuthFlowProgressStep = 1 | 2 | 3;

export function authFlowStepState(
  index: number,
  currentStep: AuthFlowProgressStep,
): "complete" | "current" | "upcoming" {
  return index < currentStep
    ? "complete"
    : index === currentStep
      ? "current"
      : "upcoming";
}

type AuthFlowProgressContextValue = {
  currentStep: AuthFlowProgressStep | null;
  setCurrentStep: Dispatch<SetStateAction<AuthFlowProgressStep | null>>;
  currentDetail: string;
  setCurrentDetail: Dispatch<SetStateAction<string>>;
};

const AuthFlowProgressContext =
  createContext<AuthFlowProgressContextValue | null>(null);

export function useAuthFlowProgress(): AuthFlowProgressContextValue | null {
  return useContext(AuthFlowProgressContext);
}

export function AuthFlowPage({
  eyebrow,
  heading,
  emphasis = "",
  copy,
  backHref = ROUTES.login,
  backLabel = "Back to sign in",
  liveProgress = false,
  steps = [
    { label: "Sign in", state: "current" },
    { label: "Verify", state: "upcoming" },
    { label: "Start learning", state: "upcoming" },
  ],
  variant = "standard",
  children,
}: AuthFlowPageProps) {
  const [currentStep, setCurrentStep] = useState<AuthFlowProgressStep | null>(
    null,
  );
  const [currentDetail, setCurrentDetail] = useState("Loading setup");
  const progress = useMemo(
    () => ({
      currentStep,
      setCurrentStep,
      currentDetail,
      setCurrentDetail,
    }),
    [currentDetail, currentStep],
  );
  const displayedSteps = liveProgress
    ? currentStep === null
      ? steps.map((step) => ({ ...step, state: "upcoming" as const }))
      : steps.map((step, index) => ({
          ...step,
          state: authFlowStepState(index + 1, currentStep),
        }))
    : steps;

  return (
    <AuthFlowProgressContext.Provider value={progress}>
      <div className="site-frame site-frame--auth">
        <a className="skip-link" href="#main-content">
          {variant === "onboarding"
            ? "Skip to learning setup"
            : "Skip to authentication"}
        </a>
        <main
          id="main-content"
          className="auth-main clarity-auth-main"
          tabIndex={-1}
        >
          {liveProgress ? (
            <p className="sr-only" aria-live="polite" aria-atomic="true">
              {currentStep === null
                ? "Loading setup."
                : `Step ${currentStep} of ${steps.length}. ${currentDetail}`}
            </p>
          ) : null}
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
              <span className="clarity-auth-masthead__task">
                <span>{eyebrow}</span>
                {liveProgress ? (
                  <span aria-hidden="true">
                    {currentStep === null
                      ? "Loading setup"
                      : `Step ${currentStep} of 3`}
                  </span>
                ) : null}
              </span>
            </header>

            <div className="clarity-auth-workspace">
              <aside className="clarity-auth-ledger" aria-label="Account task">
                {liveProgress ? (
                  <p
                    className="clarity-auth-compact-progress"
                    aria-hidden="true"
                  >
                    {currentStep === null ? (
                      "Loading setup"
                    ) : (
                      <>
                        Step {currentStep} of 3 ·{" "}
                        {displayedSteps[currentStep - 1]?.label}
                      </>
                    )}
                  </p>
                ) : null}
                <div className="clarity-auth-ledger__intro">
                  <p className="clarity-auth-ledger__eyebrow">{eyebrow}</p>
                  <h1>
                    {heading}
                    {emphasis ? <span>{emphasis}</span> : null}
                  </h1>
                  <p>{copy}</p>
                </div>
                <ol className="clarity-auth-steps" aria-label="Task progress">
                  {displayedSteps.map((step, index) => {
                    const StepIcon =
                      step.state === "complete" ? CheckCircle2 : Circle;
                    return (
                      <li
                        className={`is-${step.state}`}
                        key={step.label}
                        aria-current={
                          step.state === "current" ? "step" : undefined
                        }
                      >
                        <span
                          className="clarity-auth-step-marker"
                          aria-hidden="true"
                        >
                          <StepIcon size={26} />
                          {step.state !== "complete" ? (
                            <span className="clarity-auth-step-number">
                              {index + 1}
                            </span>
                          ) : null}
                        </span>
                        <span className="clarity-auth-step-label">
                          {step.label}
                        </span>
                        <small>
                          {step.state === "complete"
                            ? "Complete"
                            : step.state === "current"
                              ? "Current"
                              : step.state === "upcoming"
                                ? "Upcoming"
                                : (step.detail ?? "Task outline")}
                        </small>
                        <ChevronRight
                          className="clarity-auth-step-chevron"
                          size={17}
                          aria-hidden="true"
                        />
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
    </AuthFlowProgressContext.Provider>
  );
}
