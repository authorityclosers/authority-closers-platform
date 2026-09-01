import {
  AlertCircle,
  CheckCircle2,
  CircleDashed,
  LockKeyhole,
  WifiOff,
} from "lucide-react";
import Link from "next/link";

import { stateQuery } from "../lib/surface-state";
import type { SurfaceState } from "../lib/surface-state";

type StatePanelProps = {
  state: SurfaceState;
  retryHref?: string;
  backHref?: string;
  signInHref?: string;
  pageHeadingPresent?: boolean;
};

const stateCopy: Record<
  Exclude<SurfaceState, "DEFAULT">,
  {
    eyebrow: string;
    title: string;
    detail: string;
    actionLabel?: string;
    actionKind?: "retry" | "back" | "sign-in";
  }
> = {
  LOADING: {
    eyebrow: "Loading",
    title: "Getting the next useful thing ready",
    detail: "Keep this tab open while your learning state is loaded.",
  },
  EMPTY: {
    eyebrow: "Nothing here yet",
    title: "This surface has no content to show",
    detail: "The item may not be published for this learner workspace.",
    actionLabel: "Return home",
    actionKind: "back",
  },
  ERROR_RETRYABLE: {
    eyebrow: "Try again",
    title: "This view did not finish loading",
    detail:
      "The problem may be temporary. Retry the read without changing any learner work.",
    actionLabel: "Retry this view",
    actionKind: "retry",
  },
  ERROR_TERMINAL: {
    eyebrow: "Unavailable",
    title: "This view cannot be opened right now",
    detail: "Return to a known surface or try again later.",
    actionLabel: "Return home",
    actionKind: "back",
  },
  OFFLINE: {
    eyebrow: "Offline",
    title: "You are offline",
    detail:
      "Reconnect before saving drafts, submitting evidence, or refreshing progress.",
  },
  PERMISSION_DENIED: {
    eyebrow: "Permission denied",
    title: "This area is private",
    detail:
      "Sign in with the learner identity that owns the enrollment. A guessed URL never grants access.",
    actionLabel: "Go to sign in",
    actionKind: "sign-in",
  },
  LOCKED: {
    eyebrow: "Locked",
    title: "Complete the previous step first",
    detail: "Progression is sequential. Complete the required earlier work.",
    actionLabel: "View the course path",
    actionKind: "back",
  },
  PARTIAL: {
    eyebrow: "Partial",
    title: "Some information is unavailable",
    detail: "Continue with the information currently available on this page.",
  },
  SUCCESS_FEEDBACK: {
    eyebrow: "Success feedback",
    title: "Your next step is clear",
    detail: "Your action finished. Follow the next available step.",
  },
};

function StateIcon({ state }: { state: SurfaceState }) {
  if (state === "OFFLINE") return <WifiOff aria-hidden="true" />;
  if (state === "LOCKED") return <LockKeyhole aria-hidden="true" />;
  if (state === "SUCCESS_FEEDBACK") return <CheckCircle2 aria-hidden="true" />;
  if (state === "ERROR_RETRYABLE" || state === "ERROR_TERMINAL") {
    return <AlertCircle aria-hidden="true" />;
  }
  return <CircleDashed aria-hidden="true" />;
}

export function SurfaceStatePanel({
  state,
  retryHref = "/",
  backHref = "/",
  signInHref = "/login",
  pageHeadingPresent = false,
}: StatePanelProps) {
  if (state === "DEFAULT") return null;

  const copy = stateCopy[state];
  const actionHref =
    copy.actionKind === "retry"
      ? stateQuery(retryHref, "DEFAULT")
      : copy.actionKind === "sign-in"
        ? signInHref
        : backHref;
  const role =
    state === "ERROR_RETRYABLE" || state === "ERROR_TERMINAL"
      ? "alert"
      : "status";
  const Heading = pageHeadingPresent ? "h2" : "h1";

  return (
    <section
      className={`surface-state surface-state--${state.toLowerCase()}`}
      role={role}
      aria-live="polite"
      data-state={state}
    >
      <div className="surface-state__icon">
        <StateIcon state={state} />
      </div>
      <div className="surface-state__body">
        <p className="surface-state__eyebrow">{copy.eyebrow}</p>
        <Heading>{copy.title}</Heading>
        <p>{copy.detail}</p>
        {copy.actionLabel ? (
          <Link className="button button--small button--ink" href={actionHref}>
            {copy.actionLabel}
          </Link>
        ) : null}
      </div>
    </section>
  );
}
