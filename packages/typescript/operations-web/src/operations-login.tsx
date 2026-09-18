"use client";

import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
} from "react";
import { PlatformMark } from "@ac/ui";
import { loadAdminSession } from "./admin-api";
import {
  loadPlatformIdentity,
  type PlatformIdentity,
} from "./platform-identity";
import { loginLocalAdmin } from "./local-admin-login";
import {
  loadOperationsWorkspaces,
  operationsSessionMatches,
  selectOperationsWorkspace,
  OperationsWorkspaceError,
  type OperationsWorkspaces,
  type OperationsSurface,
} from "./operations-workspaces";

const subscribeHydration = () => () => {};
const signInError =
  "Sign-in was not confirmed. Check your verified email and password, then try again.";
const safeError = (error: unknown) =>
  error instanceof OperationsWorkspaceError
    ? error.message
    : "Your workspace could not be verified. Please try again.";

function hasMatchingPlatformAccess(
  platform: PlatformIdentity | null,
  choices: OperationsWorkspaces,
): boolean {
  if (!platform) return false;
  if (
    platform.personId !== choices.person_id ||
    platform.sessionId !== choices.session_id ||
    platform.selectedTenantId !== choices.selected_tenant_id
  )
    throw new OperationsWorkspaceError();
  return true;
}

export function OperationsLogin({
  surface,
  local = false,
}: {
  surface: OperationsSurface;
  local?: boolean;
}) {
  return (
    <OperationsLoginForm
      key={surface + ":" + local}
      surface={surface}
      local={local}
    />
  );
}

function OperationsLoginForm({
  surface,
  local,
}: {
  surface: OperationsSurface;
  local: boolean;
}) {
  const [pending, setPending] = useState(!local);
  const [error, setError] = useState("");
  const [choices, setChoices] = useState<OperationsWorkspaces | null>(null);
  const [platformAvailable, setPlatformAvailable] = useState(false);
  const [tenantId, setTenantId] = useState("");
  const inFlight = useRef(false);
  const current = useRef<AbortController | null>(null);
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    () => true,
    () => false,
  );
  const destination = surface === "coach" ? "/studio" : "/";

  useEffect(() => {
    const controller = new AbortController();
    current.current = controller;
    if (!local) {
      // Recover an OAuth-returned session using reads only; never select on mount.
      void loadOperationsWorkspaces({ signal: controller.signal })
        .then(async (next) => {
          if (controller.signal.aborted || current.current !== controller)
            return;
          const platform =
            surface === "admin" && next
              ? await loadPlatformIdentity({ signal: controller.signal })
              : null;
          if (controller.signal.aborted || current.current !== controller)
            return;
          const canOpenPlatform = next
            ? hasMatchingPlatformAccess(platform, next)
            : false;
          setPlatformAvailable(canOpenPlatform);
          // A platform grant is an additional destination, not a reason to
          // bypass the academy selector. Never select a tenant on mount.
          if (!canOpenPlatform && next?.selected_tenant_id) {
            try {
              const session = await loadAdminSession((input, init) =>
                fetch(input, { ...init, signal: controller.signal }),
              );
              if (
                !controller.signal.aborted &&
                current.current === controller &&
                operationsSessionMatches(
                  session,
                  next,
                  next.selected_tenant_id,
                  surface,
                )
              ) {
                window.location.assign(destination);
                return;
              }
            } catch {
              /* A different authorized workspace may still be available. */
            }
          }
          if (!controller.signal.aborted && current.current === controller) {
            setChoices(next);
            setTenantId("");
          }
        })
        .catch(() => {
          if (!controller.signal.aborted && current.current === controller)
            setError(
              "Your existing session could not be checked. You can try signing in again.",
            );
        })
        .finally(() => {
          if (!controller.signal.aborted && current.current === controller)
            setPending(false);
        });
    }
    return () => {
      controller.abort();
      current.current?.abort();
      current.current = null;
      inFlight.current = false;
    };
  }, [surface, local, destination]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hydrated || inFlight.current || pending) return;
    inFlight.current = true;
    setPending(true);
    setError("");
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    const active = () =>
      !controller.signal.aborted && current.current === controller;
    const form = event.currentTarget;
    const values = new FormData(form);
    try {
      if (choices) {
        await selectOperationsWorkspace(choices, tenantId, surface, {
          signal: controller.signal,
        });
        if (active()) window.location.assign(destination);
        return;
      }
      if (local) {
        await loginLocalAdmin(
          String(values.get("email") ?? ""),
          String(values.get("password") ?? ""),
          String(values.get("tenant_id") ?? ""),
          (input, init) => fetch(input, { ...init, signal: controller.signal }),
        );
        const session = await loadAdminSession((input, init) =>
          fetch(input, { ...init, signal: controller.signal }),
        );
        const allowed =
          surface === "admin"
            ? session.permissions.includes("admin_surface")
            : session.studioCapabilities.some(
                (item) => item.tenant_id === session.tenantId,
              );
        if (!allowed)
          throw new OperationsWorkspaceError(
            "Your account has no assignment for this workspace.",
          );
        if (active()) window.location.assign(destination);
        return;
      }
      const response = await fetch("/v1/auth/password/login", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: controller.signal,
        headers: {
          "content-type": "application/json",
          accept: "application/json",
        },
        body: JSON.stringify({
          email: values.get("email"),
          password: values.get("password"),
        }),
      });
      // Clear the DOM password after submission; never retain it in React or recovery storage.
      const password = form.elements.namedItem("password");
      if (password instanceof HTMLInputElement) password.value = "";
      if (!response.ok) throw new OperationsWorkspaceError(signInError);
      const next = await loadOperationsWorkspaces({
        signal: controller.signal,
      });
      if (!active()) return;
      if (!next)
        throw new OperationsWorkspaceError(
          "Your sign-in session expired. Please sign in again.",
        );
      const platform =
        surface === "admin"
          ? await loadPlatformIdentity({ signal: controller.signal })
          : null;
      if (!active()) return;
      const canOpenPlatform = hasMatchingPlatformAccess(platform, next);
      setPlatformAvailable(canOpenPlatform);
      if (!canOpenPlatform && next.selected_tenant_id) {
        try {
          const session = await loadAdminSession((input, init) =>
            fetch(input, { ...init, signal: controller.signal }),
          );
          if (
            active() &&
            operationsSessionMatches(
              session,
              next,
              next.selected_tenant_id,
              surface,
            )
          ) {
            window.location.assign(destination);
            return;
          }
        } catch {
          /* Explicit selection remains available; no authority is inferred. */
        }
      }
      if (active()) {
        setChoices(next);
        setTenantId("");
      }
    } catch (failure) {
      if (active()) setError(safeError(failure));
    } finally {
      if (active()) {
        setPending(false);
        inFlight.current = false;
      }
    }
  }

  async function changeAccount() {
    if (pending || inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setError("");
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    try {
      const response = await fetch("/v1/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error();
      if (!controller.signal.aborted && current.current === controller) {
        setChoices(null);
        setPlatformAvailable(false);
        setTenantId("");
      }
    } catch {
      if (!controller.signal.aborted && current.current === controller)
        setError("Sign-out was not confirmed. Please try again.");
    } finally {
      if (!controller.signal.aborted && current.current === controller) {
        setPending(false);
        inFlight.current = false;
      }
    }
  }

  return (
    <main className="dev-admin-login-shell" id="admin-content">
      <form
        className="dev-admin-login-card"
        method="post"
        onSubmit={submit}
        aria-busy={pending}
      >
        <PlatformMark width={40} height={40} aria-hidden="true" />
        <p className="section-eyebrow">
          {surface === "coach" ? "Academy Studio" : "Platform Admin"}
        </p>
        <h1>
          {choices
            ? "Choose your workspace."
            : surface === "coach"
              ? "Make room for better learning."
              : "Your platform, clearly in view."}
        </h1>
        {choices ? (
          <>
            <p>
              {choices.workspaces.length
                ? "Open a workspace assigned to your account. Your permissions are checked before you enter."
                : platformAvailable
                  ? "Your account has platform access. Open Platform Admin to manage the platform."
                  : "No active workspace is assigned to this account. Contact your administrator or use another account."}
            </p>
            {choices.workspaces.length > 0 && (
              <div className="field">
                <label htmlFor="operations-workspace">Workspace</label>
                <select
                  id="operations-workspace"
                  value={tenantId}
                  onChange={(event) => setTenantId(event.target.value)}
                  required
                  disabled={pending || !hydrated}
                >
                  <option value="">Select a workspace</option>
                  {choices.workspaces.map((item) => (
                    <option key={item.tenant_id} value={item.tenant_id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </>
        ) : (
          <>
            <p>
              {local
                ? "Sign in with your local test account."
                : "Sign in with your assigned account to open your workspace."}
            </p>
            {!local && (
              <a
                className="button button-secondary"
                href={
                  "/v1/auth/google/start?action=authenticate&surface=" +
                  surface +
                  "&return_path=%2Flogin"
                }
              >
                Continue with Google
              </a>
            )}
            <label htmlFor="operations-email">Email address</label>
            <input
              id="operations-email"
              name="email"
              type="email"
              autoComplete="username"
              required
              disabled={pending || !hydrated}
            />
            <label htmlFor="operations-password">Password</label>
            <input
              id="operations-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              disabled={pending || !hydrated}
            />
            {local && (
              <>
                <label htmlFor="operations-tenant">Local tenant ID</label>
                <input
                  id="operations-tenant"
                  name="tenant_id"
                  required
                  disabled={pending || !hydrated}
                />
              </>
            )}
          </>
        )}
        {error && (
          <p role="alert" className="dev-admin-login-error">
            {error}
          </p>
        )}
        {(!choices || choices.workspaces.length > 0) && (
          <button
            className="dev-admin-login-submit"
            disabled={pending || !hydrated || (choices !== null && !tenantId)}
          >
            {pending
              ? "Checking your workspace…"
              : choices
                ? "Open workspace"
                : "Sign in"}
          </button>
        )}
        {choices && (
          <>
            {platformAvailable && (
              <button
                className="button button-secondary"
                type="button"
                onClick={() => {
                  if (!pending && !inFlight.current && hydrated)
                    // Re-enter through server admission with a fresh document,
                    // as academy selection does above; discard cached context.
                    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
                    window.location.assign("/platform");
                }}
                disabled={pending || !hydrated}
              >
                Open Platform Admin
              </button>
            )}
            <button
              className="button button-secondary"
              type="button"
              onClick={() => {
                void changeAccount();
              }}
              disabled={pending || !hydrated}
            >
              Use another account
            </button>
          </>
        )}
      </form>
    </main>
  );
}
