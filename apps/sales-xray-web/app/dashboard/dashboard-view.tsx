"use client";

import { useCallback, useEffect, useState } from "react";

import {
  parseSubmissionLibraryPage,
  type Allowance,
  type LibrarySubmission,
} from "../acquisition-client";
import { ConnectionNotice } from "../connection-notice";
import { LightboxShell } from "../shell/lightbox-shell";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { getShellState } from "../shell/shell-store";
import { WorkspaceNoAccess } from "../workspace-no-access";
import { useWorkspaceAccess } from "../workspace-access";
import {
  readAllowance,
  readCallActivity,
  readCallSummary,
  readSandboxFacts,
  settle,
  type CallActivity,
  type CallSummary,
  type SandboxFacts,
} from "./dashboard-data";
import {
  DashboardBody,
  toState,
  useDashboardTeam,
  type ReadState,
} from "./dashboard-body";
import { seededDashboard, type ServerDashboard } from "./dashboard-seed";
import { useServerSeedAllowed } from "../initial-session";
import { CALL_LABEL_EVENT, type CallLabelChange } from "../call-label-client";
import { PolicyFooter } from "../policy-footer";
import {
  cachedCallsPage,
  cachedPanel,
  identityOf,
  readCallsList,
  rememberCallsPage,
  rememberPanel,
} from "../calls-cache";
import { SalesHome } from "./sales-home";

/**
 * The page waits for its reads (they run together) and then appears whole,
 * instead of popping in panel by panel. A slow read gets this long; then the
 * rest shows and that panel keeps its own placeholder.
 */
const REVEAL_WITHIN_MS = 2500;

export function DashboardView({
  initial = null,
}: {
  /** The page's reads made on the server (dev), or null to read here. */
  initial?: ServerDashboard | null;
}) {
  const access = useWorkspaceAccess();
  if (access?.authenticated !== false)
    return <DashboardDetails initial={initial} />;
  return (
    <LightboxShell
      active="dashboard"
      authenticated={false}
      homeHref="/dashboard"
    >
      <SignedOutWelcome
        title="Sign in to see your dashboard"
        text="Your calls, reports and coaching, waiting where you left them."
        guestHref="/analysis/new"
      />
      {/* The public landing ("/" sends visitors here): the site's footer. */}
      <PolicyFooter />
    </LightboxShell>
  );
}

function DashboardDetails({ initial }: { initial: ServerDashboard | null }) {
  const access = useWorkspaceAccess();
  // Reads the server made for this page (dev) seed the panels, for the
  // identity it read them for while the document is new; the browser reads
  // only what is still missing.
  const context = access?.context;
  const seedAllowed = useServerSeedAllowed(
    context
      ? JSON.stringify([context.personId, context.sessionId, context.tenantId])
      : null,
  );
  const [seed] = useState(() => seededDashboard(seedAllowed ? initial : null));
  // What this identity's Home showed last time (calls-cache.ts): the panels
  // paint from it at once and read again quietly (design system v2). Not
  // under test, where every case starts from nothing.
  const identity = identityOf(context);
  const [cached] = useState(() => {
    if (!identity || process.env.NODE_ENV === "test") return null;
    const page = cachedCallsPage(identity);
    const listed: ReadState<LibrarySubmission[]> | undefined = page
      ? { status: "ready", value: page.submissions.slice(0, 5) }
      : undefined;
    return {
      summary: cachedPanel<ReadState<CallSummary | null>>(identity, "summary"),
      activity: cachedPanel<ReadState<CallActivity | null>>(
        identity,
        "activity",
      ),
      allowance: cachedPanel<ReadState<Allowance>>(identity, "allowance"),
      recent:
        cachedPanel<ReadState<LibrarySubmission[]>>(identity, "recent") ??
        listed,
      sandbox: cachedPanel<SandboxFacts>(identity, "sandbox"),
    };
  });

  const [hiddenRecent, setHiddenRecent] = useState(0);
  const [retryCount, setRetryCount] = useState(0);
  const [summaryState, setSummaryState] = useState<
    ReadState<CallSummary | null>
  >(seed.summary ?? cached?.summary ?? { status: "loading" });
  const [activityState, setActivityState] = useState<
    ReadState<CallActivity | null>
  >(seed.activity ?? cached?.activity ?? { status: "loading" });
  const [allowanceState, setAllowanceState] = useState<ReadState<Allowance>>(
    seed.allowance ?? cached?.allowance ?? { status: "loading" },
  );
  const [recentState, setRecentState] = useState<
    ReadState<LibrarySubmission[]>
  >(seed.recent ?? cached?.recent ?? { status: "loading" });
  // The fictional AC Sandbox explains itself to its owner or admins; a failed
  // read simply shows no card (it is never part of the page's figures). It
  // starts from the server's read or this identity's last one, so the card
  // is there from the first paint instead of pushing the figures down.
  const [sandbox, setSandbox] = useState<SandboxFacts | null>(() =>
    seed.sandbox?.status === "ready"
      ? seed.sandbox.value
      : (cached?.sandbox ?? null),
  );

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

  // Home's read of the list is the Calls list's first page too: Calls then
  // opens with its rows (calls-cache.ts).
  const loadRecent = useCallback(
    (signal?: AbortSignal) =>
      void settle(
        readCallsList(identity, signal).then((page) =>
          page.submissions.slice(0, 5),
        ),
      ).then((result) => {
        if (!signal?.aborted) setRecentState(toState(result));
      }),
    [identity],
  );

  // The list the server read for this page is the Calls list's first page
  // too: Calls then opens with its rows.
  useEffect(() => {
    const served = seedAllowed ? initial?.recent : null;
    if (!identity || served?.status !== 200) return;
    try {
      rememberCallsPage(identity, parseSubmissionLibraryPage(served.body));
    } catch {
      // A bad shape stays the server's problem; Calls reads for itself.
    }
  }, [identity, seedAllowed, initial]);

  // Ready panels are kept for this identity's next visit.
  useEffect(() => {
    if (!identity) return;
    const panels = {
      summary: summaryState,
      activity: activityState,
      allowance: allowanceState,
      recent: recentState,
    };
    for (const [name, state] of Object.entries(panels))
      if (state.status === "ready") rememberPanel(identity, name, state);
  }, [identity, summaryState, activityState, allowanceState, recentState]);

  useEffect(() => {
    const controller = new AbortController();
    if (!seed.summary) loadSummary(controller.signal);
    if (!seed.activity) loadActivity(controller.signal);
    if (!seed.allowance) loadAllowance(controller.signal);
    if (!seed.recent) loadRecent(controller.signal);
    return () => controller.abort();
  }, [seed, loadSummary, loadActivity, loadAllowance, loadRecent]);

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
  // In an organisation, Home starts with sales (owner, 22 Oct 2026).
  const inOrganisation =
    access?.workspaces?.find(
      (workspace) => workspace.tenant_id === access.context?.tenantId,
    )?.kind === "organisation";
  const salesRole =
    inOrganisation && team !== null ? (team ? "manager" : "seller") : null;
  const sales = salesRole ? (
    <SalesHome manager={salesRole === "manager"} />
  ) : null;
  useEffect(() => {
    if (team !== true) return;
    const controller = new AbortController();
    void settle(readSandboxFacts(controller.signal)).then((result) => {
      if (controller.signal.aborted) return;
      setSandbox(result.ok ? result.value : null);
      if (result.ok) rememberPanel(identity, "sandbox", result.value);
    });
    return () => controller.abort();
  }, [team, identity]);
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
  const answered = states.every((state) => state.status !== "loading");
  // Server-read pages (dev) start shown, so their HTML already has the data.
  const [revealed, setRevealed] = useState(() => answered && team !== null);
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
          sandbox={sandbox}
          summary={summaryState}
          activity={activityState}
          allowance={allowanceState}
          recent={recentState}
          viewerId={access?.context?.personId ?? null}
          hiddenRecent={hiddenRecent}
          onHiddenChange={setHiddenRecent}
          sales={sales}
          salesRole={salesRole}
        />
      ) : (
        <DashboardBody
          team={team}
          sandbox={sandbox}
          skeleton
          sales={sales}
          salesRole={salesRole}
        />
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
