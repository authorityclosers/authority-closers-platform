"use client";

/**
 * Find my old calls with fictional data, for screenshots (wb-ci --visual, the
 * board's before/after). A stand-in for the phone app's channel and the
 * server answers here; nothing leaves the browser.
 *
 * `?view=card` (default): the card on Calls, first time.
 * `?view=fresh`: the card after a look found new calls.
 * `?view=ask`: the sheet with automatic analysis off: one choice, nothing ticked.
 * `?view=auto`: the sheet with it on: the calls go up by themselves.
 * `?view=old`: an app without findOldRecordings.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AcquisitionShell } from "../../acquisition-shell";
import { OldCallsCard } from "../../calls/old-calls/old-calls-card";
import { OldCallsSheet } from "../../calls/old-calls/old-calls-sheet";
import { CALL_LIMIT_SECONDS } from "../../call-limit";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";

const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const DAY = 86_400_000;
const LEADS: [string, string, number, number, string][] = [
  // id end, name, days ago, seconds, fit
  ["a1", "ashwini salunkhe", 0, 372, "number"],
  ["a2", "mohit das", 1, 228, "number"],
  ["a3", "prachi shinde", 1, 571, "number"],
  ["a4", "rahul more", 3, 125, "contact"],
  ["a5", "isha kulkarni", 4, 662, "number"],
  ["a6", "pankaj rao", 6, 280, "time"],
  ["a7", "mary bhosale", 7, 435, "number"],
  ["a8", "shubham rao", 8, 118, "contact"],
];
const id = (end: string) => `00000000-0000-4000-8000-0000000000${end}`;
const recording = (name: string) => ({
  source: `media:${name}`,
  name,
  size: 2_150_000,
  durationMs: 120_000,
  ext: "m4a",
  mime: "audio/mp4",
  supported: true,
  captured: "dialer",
});

function install(view: string) {
  if (typeof window === "undefined") return true;
  const now = Date.now();
  const at = (days: number) => new Date(now - days * DAY - 2 * 3_600_000);
  const listeners: ((event: { data: unknown }) => void)[] = [];
  (window as unknown as { SXPhone: unknown }).SXPhone = {
    addEventListener: (
      _: string,
      listener: (event: { data: unknown }) => void,
    ) => listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as { id: string; method: string };
      const old = view === "old" && message.method === "findOldRecordings";
      const result =
        message.method === "findOldRecordings"
          ? {
              access: "ok",
              scanned: 47,
              items: LEADS.map(([end, , , , fit]) => ({
                eventId: id(`e${end.slice(1)}`),
                fit,
                recording: recording(`call-${end}.m4a`),
              })),
              unmatched: [
                {
                  startedMs: now - 2 * DAY,
                  seconds: 200,
                  recording: recording("rec-x1.m4a"),
                },
                {
                  startedMs: now - 5 * DAY,
                  seconds: 58,
                  recording: recording("rec-x2.m4a"),
                },
              ],
            }
          : message.method === "callLogSync"
            ? { on: true, access: true, sims: [], sim: "", state: "ok" }
            : {};
      window.setTimeout(
        () =>
          listeners.forEach((listener) =>
            listener({
              data: JSON.stringify(
                old
                  ? { id: message.id, ok: false, error: "unknown_method" }
                  : { id: message.id, ok: true, result },
              ),
            }),
          ),
        300,
      );
    },
  };
  try {
    localStorage.removeItem("sx:old-calls:handled");
    if (view === "fresh") localStorage.setItem("sx:old-calls:looked", "1");
    else localStorage.removeItem("sx:old-calls:looked");
  } catch {
    // Private window: the card shows its first look.
  }
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const day = path.match(
      /\/capture-setup\/missing\/(\d{4}-\d{2}-\d{2})$/,
    )?.[1];
    if (day) {
      const items = LEADS.filter(
        ([, , days]) => at(days).toISOString().slice(0, 10) === day,
      ).map(([end, name, days, seconds]) => ({
        event_id: id(`e${end.slice(1)}`),
        lead_id: id(end),
        lead_name: name,
        at: at(days).toISOString(),
        seconds,
      }));
      return json({
        schema: "sales-xray-missing-recordings/1",
        calls: items.length,
        tried: items.length,
        latest_at: items[0]?.at ?? null,
        items,
      });
    }
    const lead = path.match(/^\/v1\/lead-desk\/leads\/([0-9a-f-]+)$/)?.[1];
    const known = LEADS.find(([end]) => id(end) === lead);
    if (lead && known)
      return json({
        lead: { lead_id: lead, name: known[1] },
        phone: "+910000000000",
        events: [],
      });
    if (path === "/v1/sales-xray/call-ai/auto-analysis")
      return json({
        schema: "sales-xray-auto-analysis/1",
        state: view === "auto" ? "on" : "off",
        can_start: view === "auto",
      });
    if (path === "/v1/conversation/acquisition/upload-policy")
      return json({
        schema: "ac.sales-xray.private-upload-consent/1",
        max_cost_paise: 0,
        policy_sha256: "0".repeat(64),
        title: "Recording terms (sample)",
        description: "Sample terms for screenshots.",
        maximum_file_bytes: 100_000_000,
        maximum_call_seconds: CALL_LIMIT_SECONDS,
        retention_days: 30,
      });
    // Uploads never leave the browser here: they wait, so the progress list shows.
    if (
      path.startsWith("/v1/conversation/acquisition") ||
      path.startsWith("/v1/lead-desk")
    )
      return new Promise<Response>(() => undefined);
    if (path.startsWith("/v1/"))
      return json({ detail: "Sample data only." }, 404);
    return real(input, init);
  };
  return true;
}

function Preview() {
  const view = useSearchParams().get("view") ?? "card";
  useState(() => install(view));
  const sheet = view === "ask" || view === "auto" || view === "old";
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: { personId: SELLER, sessionId: SESSION, tenantId: TENANT },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Homes",
            role: "member",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <AcquisitionShell authenticated active="calls">
        <PageHeader title="Calls" titleInBar />
        {sheet ? (
          <OldCallsSheet open entry="calls" onClose={() => undefined} />
        ) : (
          <OldCallsCard />
        )}
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}

export function OldCallsPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
