"use client";

/** Fictional dev-only seller; all API requests stay in this browser. */
import { useEffect, useState } from "react";
import { WorkspaceAccessContext } from "../../workspace-access";
import { PersonView } from "./person-view";

const OWNER = "00000000-0000-4000-8000-000000000001";
const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const LEAD = "00000000-0000-4000-8000-000000000006";

function install() {
  const options = new URLSearchParams(window.location.search);
  const quiet = options.has("quiet");
  const empty = options.has("empty");
  const now = Date.now();
  const at = new Date(now - (quiet ? 86_400_000 : 4 * 60_000)).toISOString();
  let name = options.has("long")
    ? "Alexandria Fictional Sampleworth Extended"
    : "Mira Fictional";
  const member = () => ({
    person_id: SELLER,
    invite_id: null,
    name,
    email: "mira@example.test",
    role: "member",
    status: "active",
    joined_at: "2026-09-01T12:00:00Z",
    last_active_at: at,
    minutes_used_30d: 0,
    calls_30d: 0,
  });
  const counts = { call: 8, connected: 5, note: 6, message: 4, stage: 2 };
  const lead = {
    lead_id: LEAD,
    name: "Rowan Example",
    city: "Sample city",
    interest: null,
    source_label: "Referral",
    stage: "follow_up",
    stage_label: "Follow up",
    overdue: true,
    calls: 1,
    last_contact_at: at,
    updated_at: at,
    created_at: at,
  };
  const original = window.fetch;
  window.fetch = async (input, init) => {
    const url = new URL(
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
      window.location.origin,
    );
    if (!url.pathname.startsWith("/v1/")) return original(input, init);
    let body: unknown = {};
    let status = 200;
    if (url.pathname === "/v1/me/sales-xray-profile") {
      if (init?.method === "PUT")
        name = JSON.parse(String(init.body)).full_name;
      body = {
        name,
        email: "mira@example.test",
        phone_number_e164: null,
        phone_verified: false,
        profile_complete: true,
        revision: 1,
      };
    } else if (url.pathname === "/v1/organisation/members")
      body = { members: [member()] };
    else if (
      url.pathname.startsWith("/v1/organisation/people/") ||
      url.pathname === "/v1/organisation/activity"
    )
      body = { members: [], per_day: [], per_rep: [], calls: [] };
    else if (url.pathname.includes("/activity"))
      body = {
        items: empty
          ? []
          : [
              {
                event_id: "note",
                lead_id: LEAD,
                lead_name: "Rowan Example",
                stage_label: "Follow up",
                event: {
                  kind: "note",
                  at,
                  actor_name: name,
                  note: "Asked for a call after lunch. Send the details first.",
                },
              },
              {
                event_id: "message",
                lead_id: LEAD,
                lead_name: "Rowan Example",
                stage_label: "Follow up",
                event: {
                  kind: "message",
                  at,
                  actor_name: name,
                  channel: "SMS",
                  template_label: "Follow-up details",
                },
              },
              {
                event_id: "call",
                lead_id: LEAD,
                lead_name: "Rowan Example",
                stage_label: "Follow up",
                event: {
                  kind: "call",
                  at,
                  actor_name: name,
                  direction: "outgoing",
                  via: "phone",
                  duration_seconds: 152,
                },
              },
              {
                event_id: "stage",
                lead_id: LEAD,
                lead_name: "Rowan Example",
                stage_label: "Follow up",
                event: {
                  kind: "stage",
                  at,
                  actor_name: name,
                  from_label: "New",
                  stage_label: "Follow up",
                },
              },
            ],
        next_before: null,
        counts: empty ? {} : counts,
        today_counts: quiet || empty ? {} : counts,
        week_counts: empty ? {} : counts,
        last_active_at: empty ? null : at,
        last_call_at: empty ? null : at,
        timezone: "Asia/Kolkata",
      };
    else if (url.pathname === "/v1/lead-desk/leads")
      body = { leads: empty ? [] : [lead], total: empty ? 0 : 1 };
    else if (url.pathname === "/v1/lead-desk/team")
      body = {
        reps: [
          {
            person_id: SELLER,
            name,
            role: "member",
            available: true,
            revision: 1,
            max_open: null,
            languages: [],
            areas: [],
            interests: [],
            open_leads: 1,
            due_now: 1,
            calls_today: quiet ? 0 : 8,
            connected_today: quiet ? 0 : 5,
            first_call_minutes: 4,
          },
        ],
        settings: { revision: 0 },
        by_stage: { follow_up: 1 },
      };
    else if (url.pathname.includes("/display-name") && init?.method === "PUT") {
      name = JSON.parse(String(init.body)).display_name;
      body = { display_name: name };
    } else {
      status = 404;
      body = { detail: "Not available in this fictional fixture." };
    }
    if (options.has("loading") && url.pathname.includes("/activity"))
      return new Promise<Response>(() => undefined);
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return () => {
    window.fetch = original;
  };
}

export function PersonPreview() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const clean = install();
    queueMicrotask(() => setReady(true));
    return clean;
  }, []);
  return ready ? (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        retry: () => undefined,
        authenticated: true,
        context: {
          personId: new URLSearchParams(window.location.search).has("own")
            ? SELLER
            : OWNER,
          sessionId: SESSION,
          tenantId: TENANT,
        },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Studio",
            role: new URLSearchParams(window.location.search).has("viewer")
              ? "viewer"
              : "owner",
            sales_xray_enabled: true,
          },
        ],
      }}
    >
      <PersonView id={SELLER} />
    </WorkspaceAccessContext.Provider>
  ) : null;
}
