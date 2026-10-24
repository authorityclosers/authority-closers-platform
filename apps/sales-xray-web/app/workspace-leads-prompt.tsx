"use client";

/**
 * "You have 383 leads in <organisation>": when the open workspace holds none of
 * the person's leads and another of their workspaces does (owner P0, 24 Oct
 * 2026: a tester reinstalled, landed in an empty workspace and thought her leads
 * were wiped). A corner card with one Switch, once per workspace per tab.
 * Sign-in now opens the right workspace on the server; this catches the rest
 * (an older app, a deliberate switch, an invitation accepted later).
 * Rendered inside the app frame: it reads the signed-in workspace from the
 * frame's access context and stays silent until that is ready.
 */
import { useEffect, useRef } from "react";

import { dropEarlyReads } from "./early-reads";
import { dismissNotice, notify } from "./notice-center";
import type { SalesXrayWorkspace } from "./sales-xray-workspaces";
import { useWorkspaceAccess } from "./workspace-access";

const NOTICE = "workspace-leads";
const SHOWN = "sx.workspaceLeadsPrompt";

/** Leads per workspace from /v1/me/sales-xray-workspaces/leads; null for a bad shape. */
export function parseWorkspaceLeads(
  value: unknown,
): Map<string, number> | null {
  if (typeof value !== "object" || value === null) return null;
  const workspaces = (value as { workspaces?: unknown }).workspaces;
  if (!Array.isArray(workspaces)) return null;
  const counts = new Map<string, number>();
  for (const item of workspaces) {
    if (typeof item !== "object" || item === null) return null;
    const { tenant_id: tenantId, leads } = item as Record<string, unknown>;
    if (typeof tenantId !== "string" || typeof leads !== "number" || leads < 0)
      return null;
    counts.set(tenantId, leads);
  }
  return counts;
}

export type LeadsOffer = { tenantId: string; name: string; leads: number };

/** The workspace to offer, or null: the open one has leads, or no other one does. */
export function leadsOffer(
  current: string | null,
  workspaces: readonly SalesXrayWorkspace[],
  counts: Map<string, number>,
): LeadsOffer | null {
  if (current === null || workspaces.length < 2) return null;
  if ((counts.get(current) ?? 0) > 0) return null;
  let best: LeadsOffer | null = null;
  for (const workspace of workspaces) {
    if (workspace.tenant_id === current || !workspace.sales_xray_enabled)
      continue;
    const leads = counts.get(workspace.tenant_id) ?? 0;
    if (leads > 0 && (best === null || leads > best.leads))
      best = { tenantId: workspace.tenant_id, name: workspace.name, leads };
  }
  return best;
}

export function offerWords(offer: LeadsOffer): string {
  return `You have ${offer.leads} ${offer.leads === 1 ? "lead" : "leads"} in ${offer.name}`;
}

async function switchTo(tenantId: string) {
  dismissNotice(NOTICE);
  // Nothing read for this workspace may answer the next one's reads.
  dropEarlyReads();
  let ok = false;
  try {
    const response = await fetch("/v1/context", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({ tenant_id: tenantId }),
    });
    ok = response.ok;
  } catch {
    ok = false;
  }
  if (!ok) {
    notify({
      id: NOTICE,
      tone: "error",
      title: "That didn’t switch",
      message: "Pick the workspace from the menu at the top.",
    });
    return;
  }
  window.location.reload();
}

export function WorkspaceLeadsPrompt() {
  const access = useWorkspaceAccess();
  const ready =
    access?.status === "ready" &&
    access.authenticated === true &&
    access.context !== null;
  const current = ready ? (access.context?.tenantId ?? null) : null;
  const workspaces = ready ? access.workspaces : undefined;
  // One look per open workspace while mounted, however often the frame renders.
  const looked = useRef<string | null>(null);
  useEffect(() => {
    if (current === null || !workspaces || workspaces.length < 2) return;
    if (looked.current === current) return;
    looked.current = current;
    try {
      if (window.sessionStorage.getItem(SHOWN) === current) return;
    } catch {
      // No storage: ask at most once per page.
    }
    const control = new AbortController();
    let settled = false;
    void (async () => {
      const response = await fetch("/v1/me/sales-xray-workspaces/leads", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: control.signal,
        headers: { accept: "application/json" },
      });
      if (!response.ok) return;
      const counts = parseWorkspaceLeads(await response.json());
      const offer = counts ? leadsOffer(current, workspaces, counts) : null;
      if (!offer || control.signal.aborted) return;
      try {
        window.sessionStorage.setItem(SHOWN, current);
      } catch {
        // Fine: the card shows again on the next page.
      }
      notify({
        id: NOTICE,
        tone: "info",
        title: offerWords(offer),
        message: "This workspace has none of your leads yet.",
        action: { label: "Switch", run: () => void switchTo(offer.tenantId) },
        dismissLabel: "Not now",
      });
    })()
      .catch(() => undefined)
      .finally(() => {
        settled = true;
      });
    return () => {
      control.abort();
      // Cut short (a remount, a re-render): look again next time.
      if (!settled) looked.current = null;
    };
  }, [current, workspaces]);
  return null;
}
