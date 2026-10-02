"use client";

import { callIdFromPath } from "./analysis-routes";
import { ArrowRight, RefreshCw, ShieldCheck } from "lucide-react";
import {
  type CSSProperties,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { CallStudio } from "./call-studio";
import { AccountNavigation } from "./account-navigation";
import { AccountAuth } from "./account-auth";
import { AccountProfile } from "./account-profile";
import { readAccountProfileEligibility } from "./account-profile-client";
import { AcquisitionShell } from "./acquisition-shell";
import { PersistentShell } from "./shell/lightbox-shell";
import { PageSkeleton } from "./shell/page-skeleton";
import { ConnectionNotice } from "./connection-notice";
import {
  WorkspaceAccessProvider,
  type WorkspaceAccessValue,
} from "./workspace-access";
import {
  PendingAnalysisProvider,
  usePendingAnalysis,
} from "./pending-analysis";
import { useProcessingReview } from "./processing-review-port";
import { SalesXrayFixturePreview } from "./sales-xray-fixture-preview";
import {
  readSalesXrayWorkspaces,
  type SalesXrayWorkspaceChoices,
} from "./sales-xray-workspaces";
import { WorkspaceNoAccess } from "./workspace-no-access";

type Workspace = Readonly<{
  tenant_id: string;
  name: string;
}>;

type IdentityWorkspaceChoices = Readonly<{
  person_id: string;
  session_id: string;
  selected_tenant_id: string | null;
  workspaces: readonly Workspace[];
}>;

export type WorkspaceChoices = SalesXrayWorkspaceChoices &
  Pick<IdentityWorkspaceChoices, "person_id" | "session_id">;

type ViewState =
  | { kind: "loading" }
  | { kind: "unauthenticated" }
  | { kind: "ready"; choices: WorkspaceChoices }
  | { kind: "empty"; choices: WorkspaceChoices }
  | { kind: "unavailable"; message: string }
  | {
      kind: "chooser" | "selecting";
      choices: WorkspaceChoices;
      selectedTenantId?: string;
      error?: string;
    };

const GENERIC_LOAD_ERROR =
  "Workspace access could not be checked. Try again in a moment.";
const GENERIC_SELECTION_ERROR =
  "That workspace could not be selected. Choose another workspace or try again.";

const shellStyle: CSSProperties = {
  minHeight: "100vh",
  display: "grid",
  placeItems: "center",
  padding: "32px 20px",
  background: "var(--canvas)",
};
const cardStyle: CSSProperties = {
  width: "min(100%, 520px)",
  padding: "28px 30px",
  border: "1px solid var(--lx-line, var(--border))",
  borderRadius: 20,
  background: "var(--lx-surface, var(--surface))",
  boxShadow: "var(--lx-shadow-2, var(--shadow))",
  animation: "gate-in 320ms cubic-bezier(0.2, 0.7, 0.2, 1) both",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/** Keep the chooser boundary strict: every identity value comes from the API. */
export function parseWorkspaceChoices(
  value: unknown,
): IdentityWorkspaceChoices | null {
  if (!isRecord(value)) return null;
  const keys = ["person_id", "session_id", "selected_tenant_id", "workspaces"];
  if (Object.keys(value).some((key) => !keys.includes(key))) return null;
  if (!nonEmptyString(value.person_id) || !nonEmptyString(value.session_id))
    return null;
  if (
    value.selected_tenant_id !== null &&
    !nonEmptyString(value.selected_tenant_id)
  )
    return null;
  if (!Array.isArray(value.workspaces)) return null;
  const workspaces: Workspace[] = [];
  const ids = new Set<string>();
  for (const item of value.workspaces) {
    if (!isRecord(item)) return null;
    const itemKeys = ["tenant_id", "name"];
    if (Object.keys(item).some((key) => !itemKeys.includes(key))) return null;
    if (!nonEmptyString(item.tenant_id) || !nonEmptyString(item.name))
      return null;
    if (ids.has(item.tenant_id)) return null;
    ids.add(item.tenant_id);
    workspaces.push({ tenant_id: item.tenant_id, name: item.name });
  }
  if (value.selected_tenant_id !== null && !ids.has(value.selected_tenant_id))
    return null;
  return {
    person_id: value.person_id,
    session_id: value.session_id,
    selected_tenant_id: value.selected_tenant_id,
    workspaces,
  };
}

async function readWorkspaceChoices(signal: AbortSignal) {
  const response = await fetch("/v1/me/workspaces", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json" },
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("workspace_read_rejected");
  const choices = parseWorkspaceChoices(await response.json());
  if (!choices) throw new Error("workspace_shape_invalid");
  // The legacy endpoint confirms session identity only. Sales Xray choices
  // and selection come exclusively from its own directory.
  const directory = await readSalesXrayWorkspaces(signal);
  const personal = directory.workspaces.find(
    (item) => item.kind === "personal",
  );
  let selected = directory.selected_tenant_id;
  if (selected === null && personal) {
    await selectWorkspace(personal.tenant_id, signal);
    selected = personal.tenant_id;
  }
  return {
    person_id: choices.person_id,
    session_id: choices.session_id,
    ...directory,
    selected_tenant_id: selected,
  };
}

async function selectWorkspace(tenantId: string, signal: AbortSignal) {
  const response = await fetch("/v1/context", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: {
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify({ tenant_id: tenantId }),
  });
  if (!response.ok) throw new Error("workspace_selection_rejected");
  const body: unknown = await response.json();
  if (!isRecord(body) || body.tenant_id !== tenantId)
    throw new Error("workspace_selection_mismatch");
}

/** Standalone app pages share one persistent frame; embeds keep their own. */
function AppFrame({
  embedded,
  children,
}: {
  embedded: boolean;
  children: ReactNode;
}) {
  return embedded ? children : <PersistentShell>{children}</PersistentShell>;
}

export function StandaloneStudio({
  children = <CallStudio />,
  variant = "standalone",
  openingExistingCall = false,
}: {
  children?: ReactNode;
  variant?: "standalone" | "embedded";
  openingExistingCall?: boolean;
}) {
  return (
    <PendingAnalysisProvider>
      <StandaloneStudioView
        variant={variant}
        openingExistingCall={openingExistingCall}
      >
        {children}
      </StandaloneStudioView>
    </PendingAnalysisProvider>
  );
}

function StandaloneStudioView({
  children = <CallStudio />,
  variant = "standalone",
  openingExistingCall = false,
}: {
  children?: ReactNode;
  variant?: "standalone" | "embedded";
  openingExistingCall?: boolean;
}) {
  const embedded = variant === "embedded";
  const Main = embedded ? "div" : "main";
  const pathname = usePathname();
  const activeFor = (
    path: string,
  ): "dashboard" | "analyse" | "calls" | "account" | "organisation" => {
    if (path === "/dashboard") return "dashboard";
    if (path === "/organisation") return "organisation";
    if (
      path === "/calls" ||
      path === "/analysis" ||
      path === "/analysis/calls" ||
      callIdFromPath(path) !== null
    )
      return "calls";
    if (path === "/account") return "account";
    return "analyse";
  };
  const skeletonVariant = (
    path: string,
  ): "dashboard" | "list" | "account" | "studio" | "call" => {
    if (path === "/dashboard") return "dashboard";
    if (callIdFromPath(path) !== null) return "call";
    if (path === "/calls" || path === "/analysis" || path === "/analysis/calls")
      return "list";
    if (path === "/account") return "account";
    return "studio";
  };
  const [attempt, setAttempt] = useState(0);
  // Failed access checks in a row, for the corner notice's retry pace.
  const [failures, setFailures] = useState(0);
  const [view, setView] = useState<ViewState>({ kind: "loading" });
  const [authRequested, setAuthRequested] = useState(false);
  const [dismissedAuthIntentId, setDismissedAuthIntentId] = useState<
    string | null
  >(null);
  const [gateIntentId, setGateIntentId] = useState<string | null>(null);
  const [eligibleReceipt, setEligibleReceipt] = useState<string | null>(null);
  const eligibleReceiptRef = useRef<string | null>(null);
  const gateIntentRef = useRef<string | null>(null);
  const generation = useRef(0);
  const activeController = useRef<AbortController | null>(null);
  const pending = usePendingAnalysis();
  const observeAccount = pending?.observeAccount;
  const review = useProcessingReview(null);

  useEffect(() => {
    // The development review port confirms its local bridge before any
    // account read. Production returns false synchronously and uses the normal
    // server-confirmed workspace path.
    if (review.readOnly === null) return;
    if (review.fixtureRequested) return;
    const controller = new AbortController();
    const requestGeneration = ++generation.current;
    activeController.current?.abort();
    activeController.current = controller;
    void readWorkspaceChoices(controller.signal)
      .then((choices) => {
        if (
          controller.signal.aborted ||
          generation.current !== requestGeneration
        )
          return;
        setFailures(0);
        if (choices === null) {
          observeAccount?.(null);
          setView({ kind: "unauthenticated" });
          return;
        }
        observeAccount?.({
          personId: choices.person_id,
          sessionId: choices.session_id,
        });
        if (choices.selected_tenant_id !== null) {
          setView({ kind: "ready", choices });
          return;
        }
        setView(
          choices.workspaces.length
            ? { kind: "chooser", choices }
            : { kind: "empty", choices },
        );
      })
      .catch(() => {
        if (
          !controller.signal.aborted &&
          generation.current === requestGeneration
        ) {
          setFailures((count) => count + 1);
          setView({ kind: "unavailable", message: GENERIC_LOAD_ERROR });
        }
      });
    return () => {
      controller.abort();
      if (activeController.current === controller)
        activeController.current = null;
      if (generation.current === requestGeneration) generation.current += 1;
    };
  }, [attempt, observeAccount, review.fixtureRequested, review.readOnly]);

  useEffect(
    () => () => {
      generation.current += 1;
      activeController.current?.abort();
    },
    [],
  );

  async function chooseWorkspace(choices: WorkspaceChoices, tenantId: string) {
    if (view.kind !== "chooser") return;
    if (!choices.workspaces.some((item) => item.tenant_id === tenantId)) return;
    const controller = new AbortController();
    const requestGeneration = ++generation.current;
    activeController.current?.abort();
    activeController.current = controller;
    setView({ kind: "selecting", choices, selectedTenantId: tenantId });
    try {
      await selectWorkspace(tenantId, controller.signal);
      if (controller.signal.aborted || generation.current !== requestGeneration)
        return;
      setView({
        kind: "ready",
        choices: { ...choices, selected_tenant_id: tenantId },
      });
    } catch {
      if (
        !controller.signal.aborted &&
        generation.current === requestGeneration
      )
        setView({
          kind: "chooser",
          choices,
          error: GENERIC_SELECTION_ERROR,
        });
    } finally {
      if (activeController.current === controller)
        activeController.current = null;
    }
  }

  const retry = () => {
    if (view.kind !== "unauthenticated" && view.kind !== "ready")
      setView({ kind: "loading" });
    setAttempt((value) => value + 1);
  };
  const selected = pending?.selection ?? null;
  const accountChoices =
    view.kind === "ready" ||
    view.kind === "chooser" ||
    view.kind === "selecting" ||
    view.kind === "empty"
      ? view.choices
      : null;
  const identityKey = accountChoices
    ? JSON.stringify([accountChoices.person_id, accountChoices.session_id])
    : null;
  const selectedWorkspace = accountChoices?.workspaces.find(
    (item) => item.tenant_id === accountChoices.selected_tenant_id,
  );
  const salesXrayEnabled = selectedWorkspace?.sales_xray_enabled !== false;
  const eligibilityKey =
    review.readOnly === false &&
    !review.fixtureRequested &&
    selected &&
    salesXrayEnabled &&
    view.kind === "ready" &&
    view.choices.selected_tenant_id &&
    selected.boundContextKey ===
      JSON.stringify([
        view.choices.person_id,
        view.choices.session_id,
        view.choices.selected_tenant_id,
      ])
      ? JSON.stringify([
          selected.intentId,
          view.choices.person_id,
          view.choices.session_id,
          view.choices.selected_tenant_id,
        ])
      : null;
  const eligibleForSelection = Boolean(
    eligibilityKey && eligibleReceipt === eligibilityKey,
  );
  const openProfileGate = (intentId: string) => {
    gateIntentRef.current = intentId;
    setGateIntentId(intentId);
  };
  const requestAccountSignIn = () => {
    if (review.fixtureRequested || review.readOnly !== false) return;
    if (selected) openProfileGate(selected.intentId);
    setAuthRequested(true);
  };
  const requestAnalysisAccess = () => {
    if (review.fixtureRequested || review.readOnly !== false || !selected)
      return false;
    if (view.kind === "unauthenticated") {
      openProfileGate(selected.intentId);
      setAuthRequested(true);
      return false;
    }
    if (!salesXrayEnabled) return false;
    if (view.kind !== "ready") {
      if (accountChoices) openProfileGate(selected.intentId);
      return false;
    }
    if (eligibilityKey && eligibleReceiptRef.current === eligibilityKey)
      return true;
    openProfileGate(selected.intentId);
    return false;
  };
  useEffect(() => {
    if (view.kind !== "ready" || !view.choices.selected_tenant_id) return;
    pending?.bindContext({
      personId: view.choices.person_id,
      sessionId: view.choices.session_id,
      tenantId: view.choices.selected_tenant_id,
    });
  }, [view, pending]);
  useEffect(() => {
    if (
      !eligibilityKey ||
      eligibleReceiptRef.current === eligibilityKey ||
      gateIntentId === selected?.intentId
    )
      return;
    const controller = new AbortController();
    const intentId = selected?.intentId;
    void readAccountProfileEligibility(controller.signal)
      .then((status) => {
        if (
          controller.signal.aborted ||
          status !== "eligible" ||
          gateIntentRef.current === intentId
        )
          return;
        eligibleReceiptRef.current = eligibilityKey;
        setEligibleReceipt(eligibilityKey);
      })
      .catch(() => {
        // A failed read never grants access. The explicit click opens recovery.
      });
    return () => controller.abort();
  }, [eligibilityKey, gateIntentId, selected?.intentId]);
  const accessValue: WorkspaceAccessValue = {
    status: view.kind,
    authenticated:
      view.kind === "chooser" ||
      view.kind === "selecting" ||
      view.kind === "ready" ||
      view.kind === "empty"
        ? true
        : view.kind === "unauthenticated"
          ? false
          : null,
    retry,
    workspaces: accountChoices?.workspaces,
    ...(review.readOnly === false && !review.fixtureRequested
      ? { requestAccountSignIn, requestAnalysisAccess }
      : {}),
    context:
      view.kind === "ready" && view.choices.selected_tenant_id
        ? {
            personId: view.choices.person_id,
            sessionId: view.choices.session_id,
            tenantId: view.choices.selected_tenant_id,
          }
        : null,
  };
  if (
    review.fixtureRequested &&
    (!review.fixtureFrame ||
      review.fixtureFrame.kind === "processing" ||
      review.fixtureFrame.kind === "auth" ||
      review.fixtureFrame.id === "upload.selected")
  )
    return (
      <WorkspaceAccessProvider
        value={{
          status: "unauthenticated",
          authenticated: false,
          context: null,
          retry: () => {},
        }}
      >
        <SalesXrayFixturePreview
          frame={review.fixtureFrame}
          message={review.message}
        />
      </WorkspaceAccessProvider>
    );
  if (review.fixtureRequested)
    return (
      <WorkspaceAccessProvider
        value={{
          status: "unauthenticated",
          authenticated: false,
          context: null,
          retry: () => {},
        }}
      >
        {children}
      </WorkspaceAccessProvider>
    );
  if (
    review.readOnly === false &&
    view.kind === "unauthenticated" &&
    (authRequested || (selected && dismissedAuthIntentId !== selected.intentId))
  )
    return (
      <WorkspaceAccessProvider value={accessValue}>
        <AccountAuth
          selectedFile={selected?.file ?? null}
          onCancel={() => {
            setDismissedAuthIntentId(selected?.intentId ?? null);
            setAuthRequested(false);
          }}
          onAuthenticated={() => {
            if (selected) openProfileGate(selected.intentId);
            setAuthRequested(false);
            setView({ kind: "loading" });
            setAttempt((value) => value + 1);
          }}
        />
      </WorkspaceAccessProvider>
    );
  if (
    review.readOnly === false &&
    selected &&
    identityKey &&
    gateIntentId === selected.intentId &&
    !eligibleForSelection
  ) {
    const profile = (
      <AccountProfile
        key={`${identityKey}:${selected.intentId}`}
        selectedFile={selected.file}
        onEligible={() => {
          if (eligibilityKey) {
            eligibleReceiptRef.current = eligibilityKey;
            setEligibleReceipt(eligibilityKey);
          }
          gateIntentRef.current = null;
          setGateIntentId((current) =>
            current === selected.intentId ? null : current,
          );
        }}
        onSignIn={() => {
          setAuthRequested(true);
          setView({ kind: "loading" });
          setAttempt((value) => value + 1);
        }}
      />
    );
    return (
      <WorkspaceAccessProvider value={accessValue}>
        <AppFrame embedded={embedded}>
          {embedded ? (
            <div style={{ ...shellStyle, minHeight: "auto" }}>{profile}</div>
          ) : (
            <AcquisitionShell authenticated homeHref="/">
              {profile}
            </AcquisitionShell>
          )}
        </AppFrame>
      </WorkspaceAccessProvider>
    );
  }
  if (view.kind === "ready" || (!embedded && view.kind === "unauthenticated"))
    return (
      <WorkspaceAccessProvider value={accessValue}>
        <AppFrame embedded={embedded}>
          {view.kind === "ready" && !salesXrayEnabled ? (
            <AcquisitionShell authenticated active={activeFor(pathname)}>
              <WorkspaceNoAccess workspace={null} />
            </AcquisitionShell>
          ) : (
            children
          )}
        </AppFrame>
      </WorkspaceAccessProvider>
    );
  // A failed check keeps the app frame and skeleton; a corner card explains
  // and tries again by itself.
  if (
    view.kind === "loading" ||
    (!embedded && view.kind === "unauthenticated") ||
    (!embedded && view.kind === "unavailable")
  )
    return (
      <WorkspaceAccessProvider value={accessValue}>
        <AppFrame embedded={embedded}>
          <AcquisitionShell
            authenticated={false}
            loading
            active={activeFor(pathname)}
          >
            <PageSkeleton variant={skeletonVariant(pathname)} />
          </AcquisitionShell>
          {view.kind === "unavailable" ? (
            <ConnectionNotice
              message={view.message}
              failures={failures}
              onRetry={retry}
            />
          ) : null}
        </AppFrame>
      </WorkspaceAccessProvider>
    );
  const chooser = view.kind === "chooser" || view.kind === "selecting";
  const heading = chooser
    ? "Choose your Sales Xray workspace."
    : view.kind === "empty"
      ? "No workspace is ready yet."
      : view.kind === "unauthenticated"
        ? openingExistingCall
          ? "Sign in to open your saved call."
          : "Sign in to analyse your calls."
        : "Workspace access needs attention.";

  return (
    <WorkspaceAccessProvider value={accessValue}>
      <Main
        className="xray-app simple-app"
        data-theme="light"
        data-variant={variant}
        style={
          embedded
            ? {
                ...shellStyle,
                minHeight: "auto",
                padding: "24px 0",
                background: "transparent",
              }
            : shellStyle
        }
        aria-busy={view.kind === "selecting"}
      >
        {!embedded && (
          <div className="standalone-account-navigation">
            <AccountNavigation compact />
          </div>
        )}
        <section
          style={cardStyle}
          aria-labelledby="sales-xray-workspace-heading"
        >
          {!embedded && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 11,
                marginBottom: 22,
                color: "var(--mint)",
                fontSize: 13,
                fontWeight: 650,
              }}
            >
              <ShieldCheck size={20} aria-hidden="true" />
              <span>Authority Closers · Sales Xray</span>
            </div>
          )}
          <h1
            id="sales-xray-workspace-heading"
            style={{
              margin: "0 0 8px",
              fontFamily: "var(--lx-font-ui, inherit)",
              fontSize: 24,
              fontWeight: 700,
              letterSpacing: -0.4,
            }}
          >
            {heading}
          </h1>
          {view.kind === "unauthenticated" ? (
            <>
              <p>
                {openingExistingCall
                  ? "Sign in with the account that owns this saved call."
                  : "Use your AC account to keep your calls, reports and remaining minutes together."}
              </p>
              {review.readOnly === false ? (
                <button
                  type="button"
                  className="primary-button"
                  onClick={requestAccountSignIn}
                >
                  Sign in <ArrowRight size={16} aria-hidden="true" />
                </button>
              ) : (
                <Link href="/login" className="primary-button">
                  Sign in <ArrowRight size={16} aria-hidden="true" />
                </Link>
              )}
            </>
          ) : chooser ? (
            <>
              <p style={{ margin: "0 0 22px", color: "var(--muted)" }}>
                Select a workspace to open its calls and reports.
              </p>
              {view.error ? (
                <p
                  role="alert"
                  style={{
                    margin: "0 0 18px",
                    padding: "11px 13px",
                    border: "1px solid var(--danger)",
                    borderRadius: 7,
                    background: "var(--danger-bg)",
                    color: "var(--danger)",
                    fontSize: 12,
                  }}
                >
                  {view.error}
                </p>
              ) : null}
              <div style={{ display: "grid", gap: 10 }}>
                {view.choices.workspaces.map((workspace) => (
                  <button
                    key={workspace.tenant_id}
                    type="button"
                    className="secondary-button"
                    data-tenant-id={workspace.tenant_id}
                    disabled={view.kind === "selecting"}
                    onClick={() =>
                      void chooseWorkspace(view.choices, workspace.tenant_id)
                    }
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      width: "100%",
                      textAlign: "left",
                    }}
                  >
                    <span>{workspace.name}</span>
                    {view.kind === "selecting" &&
                    view.selectedTenantId === workspace.tenant_id ? (
                      <span aria-live="polite">Opening…</span>
                    ) : (
                      <ArrowRight size={17} aria-hidden="true" />
                    )}
                  </button>
                ))}
              </div>
            </>
          ) : view.kind === "empty" ? (
            <>
              <p style={{ margin: "0 0 22px", color: "var(--muted)" }}>
                Your account has no Sales Xray workspace assignment yet. Contact
                your administrator, then try again.
              </p>
              <button
                type="button"
                className="secondary-button"
                onClick={retry}
              >
                <RefreshCw size={16} aria-hidden="true" /> Try again
              </button>
            </>
          ) : (
            <>
              <p
                role={view.kind === "unavailable" ? "alert" : undefined}
                style={{ margin: "0 0 22px", color: "var(--muted)" }}
              >
                {view.kind === "unavailable"
                  ? view.message
                  : "Workspace access is unavailable right now."}
              </p>
              <button
                type="button"
                className="secondary-button"
                onClick={retry}
              >
                <RefreshCw size={16} aria-hidden="true" /> Try again
              </button>
            </>
          )}
        </section>
      </Main>
    </WorkspaceAccessProvider>
  );
}
