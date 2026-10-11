"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { Allowance, LibrarySubmission } from "../acquisition-client";
import { ConnectionNotice } from "../connection-notice";
import { LightboxShell } from "../shell/lightbox-shell";
import { getShellState } from "../shell/shell-store";
import { WorkspaceNoAccess } from "../workspace-no-access";
import { useWorkspaceAccess } from "../workspace-access";
import {
  readAllowance,
  readCallActivity,
  readCallSummary,
  readRecentCalls,
  settle,
  type CallActivity,
  type CallSummary,
} from "./dashboard-data";
import {
  DashboardBody,
  toState,
  useDashboardTeam,
  type ReadState,
} from "./dashboard-body";
import { CALL_LABEL_EVENT, type CallLabelChange } from "../call-label-client";
import { PolicyFooter } from "../policy-footer";
import styles from "./dashboard.module.css";

/**
 * The page waits for its reads (they run together) and then appears whole,
 * instead of popping in panel by panel. A slow read gets this long; then the
 * rest shows and that panel keeps its own placeholder.
 */
const REVEAL_WITHIN_MS = 2500;

export default function DashboardPage() {
  const access = useWorkspaceAccess();
  if (access?.authenticated !== false) return <DashboardDetails />;
  return (
    <LightboxShell
      active="dashboard"
      authenticated={false}
      homeHref="/dashboard"
    >
      <section className={styles.emptyCard} aria-labelledby="dashboard-signin">
        <h2 id="dashboard-signin" className={styles.emptyTitle}>
          Sign in to see your dashboard
        </h2>
        <p className={styles.emptyDescription}>
          Your saved calls, reports and minutes appear after you sign in.
        </p>
        <Link
          className={styles.primaryAction}
          href="/login"
          onClick={(event) => {
            if (access.requestAccountSignIn) {
              event.preventDefault();
              access.requestAccountSignIn();
            }
          }}
        >
          Sign in
        </Link>
        <Link className={styles.guestAction} href="/analysis/new">
          Or analyse a call without an account
        </Link>
      </section>
      {/* The public landing ("/" sends visitors here): the site's footer. */}
      <PolicyFooter />
    </LightboxShell>
  );
}

function DashboardDetails() {
  const access = useWorkspaceAccess();

  const [hiddenRecent, setHiddenRecent] = useState(0);
  const [retryCount, setRetryCount] = useState(0);
  const [summaryState, setSummaryState] = useState<
    ReadState<CallSummary | null>
  >({ status: "loading" });
  const [activityState, setActivityState] = useState<
    ReadState<CallActivity | null>
  >({ status: "loading" });
  const [allowanceState, setAllowanceState] = useState<ReadState<Allowance>>({
    status: "loading",
  });
  const [recentState, setRecentState] = useState<
    ReadState<LibrarySubmission[]>
  >({ status: "loading" });

  // A cancelled read (unmount, or a re-run of the effect) must not paint
  // "Not loaded": only the live request may change a panel.
  const loadSummary = useCallback(
    (signal?: AbortSignal) =>
      void settle(readCallSummary(signal)).then((result) => {
        if (!signal?.aborted) setSummaryState(toState(result));
      }),
    [],
  );

  const loadActivity = useCallback(
    (signal?: AbortSignal) =>
      void settle(readCallActivity(signal)).then((result) => {
        if (!signal?.aborted) setActivityState(toState(result));
      }),
    [],
  );

  const loadAllowance = useCallback(
    (signal?: AbortSignal) =>
      void settle(readAllowance(signal)).then((result) => {
        if (!signal?.aborted) setAllowanceState(toState(result));
      }),
    [],
  );

  const loadRecent = useCallback(
    (signal?: AbortSignal) =>
      void settle(readRecentCalls(signal, 5, true)).then((result) => {
        if (!signal?.aborted) setRecentState(toState(result));
      }),
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    loadSummary(controller.signal);
    loadActivity(controller.signal);
    loadAllowance(controller.signal);
    loadRecent(controller.signal);
    return () => controller.abort();
  }, [loadSummary, loadActivity, loadAllowance, loadRecent]);

  // A rename in the sidebar or a report shows in Recent calls at once.
  useEffect(() => {
    const onLabel = (event: Event) => {
      const { submissionId, label } = (event as CustomEvent<CallLabelChange>)
        .detail;
      setRecentState((state) =>
        state.status === "ready"
          ? {
              ...state,
              value: state.value.map((call) =>
                call.id === submissionId &&
                (!call.label || call.label.revision < label.revision)
                  ? { ...call, label }
                  : call,
              ),
            }
          : state,
      );
    };
    window.addEventListener(CALL_LABEL_EVENT, onLabel);
    return () => window.removeEventListener(CALL_LABEL_EVENT, onLabel);
  }, []);

  const team = useDashboardTeam();
  const states = [summaryState, activityState, allowanceState, recentState];
  // 403: this workspace has no Sales Xray access. Say so once, clearly.
  const forbidden = states.some(
    (state) => state.status === "error" && state.forbidden,
  );
  const failing = states.some(
    (state) => state.status === "error" && !state.forbidden,
  );
  // One skeleton, then the whole page: shown once every read has answered
  // and the role (which names the figures) is known, or after the wait.
  const [waited, setWaited] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setWaited(true), REVEAL_WITHIN_MS);
    return () => window.clearTimeout(timer);
  }, []);
  const [revealed, setRevealed] = useState(false);
  const answered = states.every((state) => state.status !== "loading");
  // Once shown it stays: a retry reloads only its own panel.
  if (!revealed && ((answered && team !== null) || waited)) setRevealed(true);
  const retryFailed = () => {
    if (summaryState.status === "error") {
      setSummaryState({ status: "loading" });
      loadSummary();
    }
    if (activityState.status === "error") {
      setActivityState({ status: "loading" });
      loadActivity();
    }
    if (allowanceState.status === "error") {
      setAllowanceState({ status: "loading" });
      loadAllowance();
    }
    if (recentState.status === "error") {
      setRecentState({ status: "loading" });
      loadRecent();
    }
  };
  if (forbidden) {
    const shell = getShellState();
    const workspace =
      shell.workspaces.find(
        (item) => item.tenant_id === access?.context?.tenantId,
      )?.name ?? null;
    return (
      <LightboxShell
        active="dashboard"
        authenticated={access?.authenticated === true}
        homeHref="/dashboard"
      >
        <WorkspaceNoAccess workspace={workspace} />
      </LightboxShell>
    );
  }

  return (
    <LightboxShell
      active="dashboard"
      authenticated={access?.authenticated === true}
      homeHref="/dashboard"
    >
      {revealed ? (
        <DashboardBody
          team={team}
          summary={summaryState}
          activity={activityState}
          allowance={allowanceState}
          recent={recentState}
          viewerId={access?.context?.personId ?? null}
          hiddenRecent={hiddenRecent}
          onHiddenChange={setHiddenRecent}
        />
      ) : (
        <DashboardBody team={team} skeleton />
      )}
      {failing && revealed ? (
        <ConnectionNotice
          title="Some numbers did not load"
          message="Some dashboard numbers could not load. The rest of the page still works."
          failures={retryCount + 1}
          onRetry={() => {
            setRetryCount((count) => count + 1);
            retryFailed();
          }}
        />
      ) : null}
    </LightboxShell>
  );
}
