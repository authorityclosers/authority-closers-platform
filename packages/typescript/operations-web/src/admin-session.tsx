"use client";

import {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  AdminSessionDenied,
  loadAdminSession,
  type AdminPermission,
  type AdminSession,
} from "./admin-api";
import type { StudioPermission } from "./admin-identity";

export type AdminSessionState =
  | Readonly<{ status: "loading"; session: null; error: null }>
  | Readonly<{ status: "ready"; session: AdminSession; error: null }>
  | Readonly<{
      status: "denied" | "error";
      session: null;
      error: string;
    }>;

const initialState: AdminSessionState = {
  status: "loading",
  session: null,
  error: null,
};

export const ADMIN_SESSION_REFRESH_TIMEOUT_MS = 10_000;

const AdminSessionContext = createContext<AdminSessionState>(initialState);

/** Navigation hint only. The API checks current identity, role and permissions. */
export function canManageSalesXray(state: AdminSessionState): boolean {
  return (
    state.status === "ready" &&
    [
      "admin@authorityclosers.com",
      "dipak@authorityclosers.com",
      "suyash@authorityclosers.com",
    ].includes(state.session.email.trim().toLowerCase()) &&
    Boolean(state.session.emailVerifiedAt) &&
    ["owner", "admin"].includes(state.session.membershipRole) &&
    state.session.permissions.includes("admin_surface")
  );
}

export type AdminSessionInvalidator = (session: AdminSession) => void;

const noOpSessionInvalidator: AdminSessionInvalidator = () => undefined;
const AdminSessionInvalidationContext = createContext<AdminSessionInvalidator>(
  noOpSessionInvalidator,
);

export function canUseAdminPermission(
  state: AdminSessionState,
  permission: AdminPermission,
): boolean {
  return (
    state.status === "ready" &&
    state.session.permissions.includes("admin_surface") &&
    state.session.permissions.includes(permission)
  );
}

/** Presentation hints only; each API action rechecks persisted authority. */
export function canUseStudioPermission(
  state: AdminSessionState,
  permission: StudioPermission,
  programId?: string,
): boolean {
  return (
    state.status === "ready" &&
    state.session.studioCapabilities.some(
      (capability) =>
        capability.tenant_id === state.session.tenantId &&
        capability.permission === permission &&
        (capability.scope_kind === "tenant" ||
          (programId !== undefined && capability.program_id === programId)),
    )
  );
}

export function canBrowseStudio(state: AdminSessionState): boolean {
  return (
    state.status === "ready" &&
    state.session.studioCapabilities.some(
      (capability) =>
        capability.tenant_id === state.session.tenantId &&
        capability.permission === "catalog_read",
    )
  );
}

export function canEnterStudio(state: AdminSessionState): boolean {
  return (
    state.status === "ready" && state.session.studioCapabilities.length > 0
  );
}

type ReadySessionState = Extract<AdminSessionState, { status: "ready" }>;

function sessionIdentity(session: AdminSession) {
  return JSON.stringify([
    session.tenantId,
    session.personId,
    session.sessionId,
  ]);
}

// A checking/error boundary hides this tree without changing its last verified
// context or mounting a new route. That keeps unsaved form state private and
// intact until the identity is verified again. It is never an authorization port.
const PrivateSessionTree = memo(
  function PrivateSessionTree({
    state,
    children,
  }: {
    state: ReadySessionState;
    children: ReactNode;
    frozen: boolean;
  }) {
    return (
      <AdminSessionContext.Provider value={state}>
        {children}
      </AdminSessionContext.Provider>
    );
  },
  (_previous, next) => next.frozen,
);

export function AdminSessionProvider({
  children,
  refreshKey,
  revalidateOnFocus = false,
  renderBoundary,
}: {
  children: ReactNode;
  refreshKey?: string;
  revalidateOnFocus?: boolean;
  /** Optional public chrome around the session boundary while access is checked. */
  renderBoundary?: (boundary: ReactNode, state: AdminSessionState) => ReactNode;
}) {
  const [view, setView] = useState<{
    key: string | undefined;
    state: AdminSessionState;
    confirmed: ReadySessionState | null;
  }>({ key: refreshKey, state: initialState, confirmed: null });
  const viewRef = useRef(view);
  useLayoutEffect(() => {
    viewRef.current = view;
  }, [view]);
  const generation = useRef(0);
  const pending = useRef(false);
  const activeRefresh = useRef<{
    request: number;
    controller: AbortController;
    timeout: ReturnType<typeof setTimeout>;
  } | null>(null);
  const privateRoot = useRef<HTMLDivElement>(null);
  const suspendedDialogs = useRef(
    new Map<HTMLDialogElement, { identity: string; modal: boolean }>(),
  );
  const suspensionCloseEvents = useRef(new WeakMap<EventTarget, number>());
  const attachPrivateRoot = useCallback((scope: HTMLDivElement | null) => {
    privateRoot.current = scope;
    if (!scope) return;
    const captureClose = (event: Event) => {
      const target = event.target;
      const remaining = target
        ? suspensionCloseEvents.current.get(target)
        : undefined;
      if (target && remaining) {
        if (remaining === 1) suspensionCloseEvents.current.delete(target);
        else suspensionCloseEvents.current.set(target, remaining - 1);
        event.stopPropagation();
      }
    };
    scope.addEventListener("close", captureClose, true);
    return () => {
      scope.removeEventListener("close", captureClose, true);
      privateRoot.current = null;
    };
  }, []);
  const invalidate = useCallback(() => {
    ++generation.current;
    const active = activeRefresh.current;
    if (active) {
      clearTimeout(active.timeout);
      active.controller.abort();
      activeRefresh.current = null;
    }
    pending.current = false;
  }, []);
  const invalidateSession = useCallback<AdminSessionInvalidator>(
    (expectedSession) => {
      const expectedIdentity = sessionIdentity(expectedSession);
      if (
        !viewRef.current.confirmed ||
        sessionIdentity(viewRef.current.confirmed.session) !== expectedIdentity
      ) {
        return;
      }
      invalidate();
      setView((current) => {
        if (
          !current.confirmed ||
          sessionIdentity(current.confirmed.session) !== expectedIdentity
        ) {
          return current;
        }
        return {
          key: refreshKey,
          state: {
            status: "denied",
            session: null,
            error: "Your product session is no longer valid.",
          },
          confirmed: null,
        };
      });
    },
    [invalidate, refreshKey],
  );
  const settle = useCallback((request: number) => {
    const active = activeRefresh.current;
    if (request !== generation.current || active?.request !== request)
      return false;
    clearTimeout(active.timeout);
    activeRefresh.current = null;
    pending.current = false;
    return true;
  }, []);
  const refresh = useCallback(
    (force = false) => {
      if (pending.current && !force) return;
      if (force && activeRefresh.current) invalidate();
      pending.current = true;
      const request = ++generation.current;
      const controller = new AbortController();
      const timeout = setTimeout(() => {
        if (request !== generation.current) return;
        ++generation.current;
        activeRefresh.current = null;
        pending.current = false;
        controller.abort();
        setView((current) => ({
          key: refreshKey,
          state: {
            status: "error",
            session: null,
            error: "The product session check timed out.",
          },
          confirmed: current.confirmed,
        }));
      }, ADMIN_SESSION_REFRESH_TIMEOUT_MS);
      activeRefresh.current = { request, controller, timeout };
      setView((current) => ({
        ...current,
        key: refreshKey,
        state: initialState,
      }));
      void loadAdminSession(fetch, controller.signal).then(
        (session) => {
          if (!settle(request)) return;
          setView((current) => {
            const confirmed: ReadySessionState =
              current.confirmed &&
              JSON.stringify(current.confirmed.session) ===
                JSON.stringify(session)
                ? current.confirmed
                : { status: "ready", session, error: null };
            return { key: refreshKey, state: confirmed, confirmed };
          });
        },
        (error: unknown) => {
          if (!settle(request)) return;
          const denied = error instanceof AdminSessionDenied;
          setView((current) => ({
            key: refreshKey,
            state: {
              status: denied ? "denied" : "error",
              session: null,
              error: denied
                ? error.message
                : "The product session could not be checked.",
            },
            confirmed: denied ? null : current.confirmed,
          }));
        },
      );
    },
    [invalidate, refreshKey, settle],
  );

  useEffect(() => {
    refresh(true);
    return invalidate;
  }, [refresh, invalidate]);

  useEffect(() => {
    if (!revalidateOnFocus) return;
    const focus = () => {
      if (document.visibilityState !== "hidden") refresh();
    };
    const blur = () => {
      // A response begun before focus was lost must not verify a later account.
      if (pending.current) invalidate();
    };
    const visibility = () => {
      if (document.visibilityState === "hidden") {
        blur();
        setView((current) => ({ ...current, state: initialState }));
      } else focus();
    };
    window.addEventListener("focus", focus);
    window.addEventListener("blur", blur);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("focus", focus);
      window.removeEventListener("blur", blur);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [refresh, invalidate, revalidateOnFocus]);

  const state = view.key === refreshKey ? view.state : initialState;
  const hidden = state.status !== "ready";
  const identity = view.confirmed
    ? sessionIdentity(view.confirmed.session)
    : undefined;
  useLayoutEffect(() => {
    const scope = privateRoot.current;
    if (!scope || !identity) {
      suspendedDialogs.current.clear();
      return;
    }
    if (!hidden) {
      for (const [dialog, saved] of suspendedDialogs.current) {
        if (
          saved.identity === identity &&
          scope.contains(dialog) &&
          !dialog.open
        ) {
          if (saved.modal) dialog.showModal();
          else dialog.show();
        }
      }
      suspendedDialogs.current.clear();
      return;
    }
    // A hidden modal still makes the rest of the document inert. Suspend its
    // native top-layer state, not the form's React state, so Reconnect works.
    const suspend = () => {
      for (const dialog of scope.querySelectorAll<HTMLDialogElement>(
        "dialog[open]",
      )) {
        suspendedDialogs.current.set(dialog, {
          identity,
          modal: dialog.matches(":modal"),
        });
        suspensionCloseEvents.current.set(
          dialog,
          (suspensionCloseEvents.current.get(dialog) ?? 0) + 1,
        );
        dialog.close();
      }
    };
    suspend();
    const observer = new MutationObserver(suspend);
    observer.observe(scope, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["open"],
    });
    return () => observer.disconnect();
  }, [hidden, identity]);

  if (refreshKey === undefined && !revalidateOnFocus) {
    return (
      <AdminSessionInvalidationContext.Provider value={invalidateSession}>
        <AdminSessionContext.Provider value={state}>
          {children}
        </AdminSessionContext.Provider>
      </AdminSessionInvalidationContext.Provider>
    );
  }
  if (state.status === "denied") {
    return (
      <AdminSessionInvalidationContext.Provider value={invalidateSession}>
        <AdminSessionContext.Provider value={state}>
          {children}
        </AdminSessionContext.Provider>
      </AdminSessionInvalidationContext.Provider>
    );
  }
  return (
    <AdminSessionInvalidationContext.Provider value={invalidateSession}>
      <>
        {hidden &&
          (() => {
            const boundary = (
              <section
                className="studio-boundary panel"
                role={state.status === "error" ? "alert" : "status"}
              >
                <div>
                  <h2>
                    {state.status === "error"
                      ? "We couldn’t check your account"
                      : "Checking your account…"}
                  </h2>
                  <p>
                    {state.status === "error"
                      ? "Your open work is kept privately in this tab. Reconnect to continue."
                      : "Your workspace will return after your session is verified."}
                  </p>
                  {state.status === "error" && (
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => refresh()}
                    >
                      Reconnect
                    </button>
                  )}
                </div>
              </section>
            );
            return renderBoundary ? renderBoundary(boundary, state) : boundary;
          })()}
        <div
          ref={attachPrivateRoot}
          hidden={hidden}
          inert={hidden}
          aria-hidden={hidden || undefined}
          data-private-session-tree=""
        >
          {view.confirmed && (
            <PrivateSessionTree
              key={sessionIdentity(view.confirmed.session)}
              state={view.confirmed}
              frozen={hidden}
            >
              {children}
            </PrivateSessionTree>
          )}
        </div>
      </>
    </AdminSessionInvalidationContext.Provider>
  );
}

export function useAdminSession(): AdminSessionState {
  return useContext(AdminSessionContext);
}

export function useInvalidateAdminSession(): AdminSessionInvalidator {
  return useContext(AdminSessionInvalidationContext);
}

export function AdminSessionStatus() {
  const state = useAdminSession();
  if (state.status === "loading") {
    return (
      <div
        className="environment-chip"
        aria-label="Checking product admin session"
      >
        <span className="status-dot" aria-hidden="true" />
        <span>Checking session</span>
        <small>Checking your workspace access</small>
      </div>
    );
  }
  if (state.status === "ready") {
    return (
      <div
        className="environment-chip"
        aria-label="Product admin session verified"
      >
        <span className="status-dot status-dot-live" aria-hidden="true" />
        <span>Session verified</span>
        <small>
          {state.session.membershipRole} · {state.session.email}
        </small>
      </div>
    );
  }
  return (
    <div
      className="environment-chip environment-chip-denied"
      aria-label="Product admin session denied"
    >
      <span className="status-dot status-dot-error" aria-hidden="true" />
      <span>Admin access unavailable</span>
      <small>
        {state.status === "denied" ? "Permission denied" : "Retry required"}
      </small>
    </div>
  );
}
