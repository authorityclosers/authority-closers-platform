"use client";

import { ArrowRight, RefreshCw, ShieldCheck } from "lucide-react";
import {
  type CSSProperties,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";

import { CallStudio } from "./call-studio";
import { AccountNavigation } from "./account-navigation";
import {
  WorkspaceAccessProvider,
  type WorkspaceAccessValue,
} from "./workspace-access";

type Workspace = Readonly<{
  tenant_id: string;
  name: string;
}>;

export type WorkspaceChoices = Readonly<{
  person_id: string;
  session_id: string;
  selected_tenant_id: string | null;
  workspaces: readonly Workspace[];
}>;

type ViewState =
  | { kind: "loading" }
  | { kind: "unauthenticated" }
  | { kind: "ready" }
  | { kind: "empty" }
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
  width: "min(100%, 620px)",
  padding: "34px",
  border: "1px solid var(--border)",
  borderRadius: 14,
  background: "var(--surface)",
  boxShadow: "var(--shadow)",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/** Keep the chooser boundary strict: every identity value comes from the API. */
export function parseWorkspaceChoices(value: unknown): WorkspaceChoices | null {
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
  return choices;
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

export function StandaloneStudio({
  children = <CallStudio />,
}: {
  children?: ReactNode;
}) {
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<ViewState>({ kind: "loading" });
  const generation = useRef(0);
  const activeController = useRef<AbortController | null>(null);

  useEffect(() => {
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
        if (choices === null) {
          setView({ kind: "unauthenticated" });
          return;
        }
        if (choices.selected_tenant_id !== null) {
          setView({ kind: "ready" });
          return;
        }
        setView(
          choices.workspaces.length
            ? { kind: "chooser", choices }
            : { kind: "empty" },
        );
      })
      .catch(() => {
        if (
          !controller.signal.aborted &&
          generation.current === requestGeneration
        )
          setView({ kind: "unavailable", message: GENERIC_LOAD_ERROR });
      });
    return () => {
      controller.abort();
      if (activeController.current === controller)
        activeController.current = null;
      if (generation.current === requestGeneration) generation.current += 1;
    };
  }, [attempt]);

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
      setView({ kind: "ready" });
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
    setView({ kind: "loading" });
    setAttempt((value) => value + 1);
  };
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
  };
  if (view.kind === "ready" || view.kind === "unauthenticated")
    return (
      <WorkspaceAccessProvider value={accessValue}>
        {children}
      </WorkspaceAccessProvider>
    );
  const chooser = view.kind === "chooser" || view.kind === "selecting";
  const heading = chooser
    ? "Choose your Sales Xray workspace."
    : view.kind === "empty"
      ? "No workspace is ready yet."
      : view.kind === "loading"
        ? "Checking workspace access."
        : "Workspace access needs attention.";

  return (
    <WorkspaceAccessProvider value={accessValue}>
      <main
        className="xray-app simple-app"
        data-theme="light"
        style={shellStyle}
        aria-busy={view.kind === "loading" || view.kind === "selecting"}
      >
        <div className="standalone-account-navigation">
          <AccountNavigation compact />
        </div>
        <section
          style={cardStyle}
          aria-labelledby="sales-xray-workspace-heading"
        >
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
          <h1
            id="sales-xray-workspace-heading"
            style={{ margin: "0 0 10px", fontSize: 30, letterSpacing: -0.7 }}
          >
            {heading}
          </h1>
          {view.kind === "loading" ? (
            <p style={{ margin: 0, color: "var(--muted)" }}>
              Confirming the workspace assigned to your session…
            </p>
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
      </main>
    </WorkspaceAccessProvider>
  );
}
