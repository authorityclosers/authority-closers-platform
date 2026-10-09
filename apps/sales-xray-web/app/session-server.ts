import "server-only";
import { cache } from "react";
import { headers } from "next/headers";
import {
  parseSessionSeed,
  parseDashboardSnapshot,
  sessionContextKey,
  type SessionSeed,
} from "./session-data";

/** Exact deployment origin only. Cookie values stay in the request, never logs. */
export function internalApiOrigin(value: string | undefined): string | null {
  if (!value) return null;
  const url = new URL(value);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error("Invalid internal API origin");
  return url.origin;
}
async function serverRead(path: string) {
  const origin = internalApiOrigin(process.env.AC_CONVERSATION_API_ORIGIN);
  if (!origin) return null;
  const incoming = await headers();
  return fetch(origin + path, {
    method: "GET",
    cache: "no-store",
    redirect: "error",
    headers: {
      accept: "application/json",
      cookie: incoming.get("cookie") ?? "",
      host: incoming.get("host") ?? new URL(origin).host,
    },
    signal: AbortSignal.timeout(10_000),
  });
}
export const readSessionSeed = cache(async (): Promise<SessionSeed | null> => {
  if (
    process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1" ||
    (process.env.NODE_ENV === "development" &&
      process.env.AC_SALES_XRAY_REVIEW === "1")
  )
    return null;
  try {
    const response = await serverRead("/v1/me/sales-xray-bootstrap");
    if (response?.status === 401)
      return { view: { kind: "unauthenticated" }, profile: null };
    return response?.ok ? parseSessionSeed(await response.json()) : null;
  } catch {
    return null;
  }
});
export async function readDashboardSnapshot(seed: SessionSeed | null) {
  const key = sessionContextKey(seed);
  const choices = seed?.view.kind === "ready" ? seed.view.choices : null;
  if (
    !key ||
    !choices ||
    choices.salesXrayWorkspaces?.find(
      (item) => item.tenant_id === choices.selected_tenant_id,
    )?.sales_xray_enabled === false
  )
    return null;
  try {
    const response = await serverRead("/v1/conversation/acquisition/dashboard");
    return response?.ok
      ? parseDashboardSnapshot(await response.json(), key)
      : null;
  } catch {
    return null;
  }
}
