import { z } from "zod";

import { loadAdminSession } from "./admin-api";

/** Normal password authentication and canonical context selection; no local roles. */
export async function loginLocalAdmin(
  email: string,
  password: string,
  tenantId: string,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const parsedTenant = z.uuid().safeParse(tenantId.trim());
  if (!parsedTenant.success) throw new Error("Enter a valid local tenant ID.");
  const tenant = parsedTenant.data;
  let authenticated = false;
  async function post(path: string, body?: unknown): Promise<void> {
    const response = await fetcher(path, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(
        path.endsWith("/login")
          ? "The local email and password could not be verified."
          : "The selected local tenant is unavailable for this account.",
      );
    }
  }
  try {
    await post("/v1/auth/password/login", { email, password });
    authenticated = true;
    await post("/v1/context", { tenant_id: tenant });
    const session = await loadAdminSession(fetcher);
    if (session.tenantId !== tenant) {
      throw new Error("The local session selected a different tenant.");
    }
  } catch (error) {
    if (authenticated) {
      // Best-effort cleanup only. A failed verification never admits the workspace.
      await post("/v1/auth/logout").catch(() => undefined);
    }
    throw error;
  }
}
