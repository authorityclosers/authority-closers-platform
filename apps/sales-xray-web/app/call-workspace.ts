import { UUID } from "./acquisition-client";
import { requestWorkspace } from "./call-ownership";

const DIRECTORY = "/v1/me/sales-xray-workspaces";

async function read(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json" },
  });
  return response.ok ? response.json().catch(() => null) : null;
}

const tenant = (body: unknown, field: string): string | null => {
  const value =
    body && typeof body === "object" && field in body
      ? (body as Record<string, unknown>)[field]
      : null;
  return typeof value === "string" && UUID.test(value) ? value : null;
};

/**
 * Which of the signed-in person's workspaces holds a saved call, or null.
 * Each device keeps its own selected workspace, so a link to a call can open
 * while another workspace is selected (owner, 16 Oct). The server names only a
 * workspace the person belongs to and may read the call in.
 */
export async function callWorkspace(
  submissionId: string,
  signal?: AbortSignal,
): Promise<string | null> {
  if (!UUID.test(submissionId)) return null;
  try {
    return tenant(
      await read(`${DIRECTORY}/call/${submissionId}`, signal),
      "tenant_id",
    );
  } catch {
    return null;
  }
}

/**
 * Opens the call in its own workspace when that differs from the selected one.
 * Returns true when it asked the shell to switch (the page reopens there).
 */
export async function openInCallWorkspace(
  submissionId: string,
  signal?: AbortSignal,
): Promise<boolean> {
  const home = await callWorkspace(submissionId, signal);
  if (!home || signal?.aborted) return false;
  let selected: string | null = null;
  try {
    selected = tenant(await read(DIRECTORY, signal), "selected_tenant_id");
  } catch {
    return false;
  }
  if (home === selected || signal?.aborted) return false;
  requestWorkspace(
    home,
    `${window.location.pathname}${window.location.search}`,
  );
  return true;
}
