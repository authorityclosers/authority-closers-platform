export const LOCAL_PREVIEW_ENV = "AC_ADMIN_LOCAL_PREVIEW";

export type AdminRuntime = "development" | "test" | "production";

export function normalizeAdminRuntime(value: unknown): AdminRuntime {
  return value === "development" || value === "test" ? value : "production";
}

/**
 * This value may only be built by a future server-owned authentication adapter
 * after session, actor, tenant, and admin-surface authorization are verified.
 * Request headers, cookies parsed by this UI, query/body fields, and client role
 * assertions must never be converted directly into this context.
 */
export type ServerOwnedAdminContext = Readonly<{
  source: "verified-server-session";
  authenticated: true;
  adminSurfaceAuthorized: true;
  actorId: string;
  tenantId: string;
  permissions: readonly string[];
}>;

export type AdminAccessDecision =
  | Readonly<{
      allowed: true;
      mode: "authenticated" | "local-preview";
    }>
  | Readonly<{
      allowed: false;
      mode: "denied";
      reason: "missing-server-context" | "preview-not-enabled";
    }>;

function isNonBlank(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isServerOwnedAdminContext(
  value: unknown,
): value is ServerOwnedAdminContext {
  if (typeof value !== "object" || value === null) return false;

  const candidate = value as Partial<ServerOwnedAdminContext>;
  return (
    candidate.source === "verified-server-session" &&
    candidate.authenticated === true &&
    candidate.adminSurfaceAuthorized === true &&
    isNonBlank(candidate.actorId) &&
    isNonBlank(candidate.tenantId) &&
    Array.isArray(candidate.permissions) &&
    candidate.permissions.includes("admin_surface")
  );
}

export function evaluateAdminAccess({
  localPreviewEnabled,
  runtime,
  serverContext,
}: {
  localPreviewEnabled: boolean;
  runtime: AdminRuntime;
  serverContext: unknown;
}): AdminAccessDecision {
  if (isServerOwnedAdminContext(serverContext)) {
    return { allowed: true, mode: "authenticated" };
  }

  if (runtime !== "production" && localPreviewEnabled) {
    return { allowed: true, mode: "local-preview" };
  }

  return {
    allowed: false,
    mode: "denied",
    reason:
      runtime === "production"
        ? "missing-server-context"
        : "preview-not-enabled",
  };
}

export function renderPermissionDeniedDocument() {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,nofollow">
    <title>Admin access denied</title>
    <style>
      :root { color-scheme: dark; font-family: ui-sans-serif, system-ui, sans-serif; background: #10130f; color: #edf0e8; }
      * { box-sizing: border-box; }
      body { min-width: 320px; margin: 0; background: #10130f; }
      a { color: #11140f; }
      .skip { position: fixed; left: 1rem; top: 1rem; padding: .75rem 1rem; background: #d9ff56; transform: translateY(-180%); }
      .skip:focus { transform: translateY(0); }
      main { width: min(44rem, calc(100% - 2rem)); margin: clamp(4rem, 12vh, 8rem) auto; padding: clamp(1.5rem, 5vw, 3rem); border: 1px solid #ff907e; background: #171b16; }
      p { color: #aab3a4; line-height: 1.65; }
      .code { color: #ff907e; font: 600 .75rem ui-monospace, monospace; letter-spacing: .1em; text-transform: uppercase; }
      .sign-in { display: inline-flex; margin-top: 1rem; padding: .8rem 1rem; background: #d9ff56; color: #11140f; font-weight: 700; text-decoration: none; }
      .sign-in:focus-visible { outline: 3px solid #fff; outline-offset: 3px; }
    </style>
  </head>
  <body>
    <a class="skip" href="#admin-denied">Skip to denial reason</a>
    <main id="admin-denied" tabindex="-1">
      <span class="code">Permission denied / fail closed</span>
      <h1>Authenticated admin context required.</h1>
      <p>This server has no verified, server-owned admin actor and tenant context. The admin surface is not published.</p>
      <p>Client role assertions, request parameters, and headers cannot unlock this route.</p>
      <a class="sign-in" href="/v1/auth/google/start?action=authenticate&amp;surface=admin&amp;return_path=%2F">Sign in with Google</a>
    </main>
  </body>
</html>`;
}
