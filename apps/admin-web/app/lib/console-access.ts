import { connection } from "next/server";
import { cache } from "react";

import { LOCAL_PREVIEW_ENV } from "./admin-access";
import type { ConsoleAccess } from "./nav";
import { normalizeWorkspaces, type Workspace } from "./workspaces";
import {
  adminRead,
  devEdgeTransport,
  internalTransport,
  read,
} from "./server-api";

const ENVIRONMENTS: Readonly<Record<string, string>> = {
  "api.production.ac.internal.invalid": "production",
  "api.staging.ac.internal.invalid": "staging",
  "api.development.ac.internal.invalid": "development",
};

export function consoleEnvironment(
  env: Readonly<Record<string, string | undefined>> = process.env,
): string | null {
  if (devEdgeTransport(env)) return "development";
  if (internalTransport(env))
    return ENVIRONMENTS[env.AC_INTERNAL_API_HOST ?? ""] ?? null;
  return env[LOCAL_PREVIEW_ENV] === "1" ? "preview" : null;
}

/**
 * Who is signed in, for the shell's navigation and account row. The proxy has
 * already admitted the request; this only decides which sections to list.
 */
export async function readConsoleAccess(
  env: Readonly<Record<string, string | undefined>> = process.env,
): Promise<ConsoleAccess> {
  if (!internalTransport(env)) {
    const preview =
      env.NODE_ENV !== "production" && env[LOCAL_PREVIEW_ENV] === "1";
    return {
      state: preview ? "preview" : "unavailable",
      email: null,
      displayName: null,
      role: null,
      permissions: [],
      platform: [],
    };
  }
  const [me, context, platform] = await Promise.all([
    adminRead("/v1/me", read.object, { env }),
    adminRead("/v1/context", read.object, { env }),
    adminRead("/v1/me/platform-access", read.object, { env }),
  ]);
  if (!me.ok || !context.ok)
    return {
      state: "unavailable",
      email: null,
      displayName: null,
      role: null,
      permissions: [],
      platform: platform.ok
        ? read.strings(platform.data.platform_permissions)
        : [],
    };
  return {
    state: read.optionalString(me.data.email_verified_at)
      ? "verified"
      : "unavailable",
    email: read.optionalString(me.data.email),
    displayName: read.optionalString(me.data.display_name),
    role: read.optionalString(context.data.membership_role),
    permissions: read.strings(context.data.permissions),
    platform: platform.ok
      ? read.strings(platform.data.platform_permissions)
      : [],
  };
}

/** One read per request, shared by the layout and the page. */
export const loadConsoleAccess = cache(async () => {
  // Who is signed in differs per request: never prerender a console page.
  await connection();
  return readConsoleAccess();
});

/** Platform read: every workspace and what it is, for the person menu. */
export const WORKSPACES_PERMISSION = "platform_tenants_read";

export async function readConsoleWorkspaces(
  access: ConsoleAccess,
  env: Readonly<Record<string, string | undefined>> = process.env,
): Promise<Workspace[] | null> {
  if (
    access.state !== "verified" ||
    !access.platform.includes(WORKSPACES_PERMISSION) ||
    !internalTransport(env)
  )
    return null;
  const listed = await adminRead(
    "/v1/platform/workspaces",
    normalizeWorkspaces,
    {
      env,
    },
  );
  return listed.ok ? listed.data : null;
}

export const loadConsoleWorkspaces = cache(async (access: ConsoleAccess) =>
  readConsoleWorkspaces(access),
);
