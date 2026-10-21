"use client";

/**
 * Settings → Selling for a fictional salesperson, for screenshots on GitHub
 * (wb-ci --visual). Its reads are answered here; nothing leaves the browser.
 */

import { useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { SellingSettings } from "../../settings/selling";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";

const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";

const ANSWERS: Record<string, unknown> = {
  "/v1/lead-desk/me": {
    person_id: SELLER,
    name: "swamini fictional",
    role: "member",
    can_manage: false,
    taking_leads: true,
    paused_until: null,
  },
  "/v1/sales-xray/call-ai": {
    revision: null,
    default: "full",
    people: [],
    you: { level: "full", source: "organisation" },
    levels: [
      {
        id: "full",
        name: "Full",
        hint: "The full report and coaching on every call.",
      },
    ],
    can_edit: false,
  },
};

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if (path in ANSWERS)
      return new Response(JSON.stringify(ANSWERS[path]), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    if (path.startsWith("/v1/"))
      return new Response(JSON.stringify({ detail: "Sample data only." }), {
        status: 404,
      });
    return real(input, init);
  };
  return true;
}

export function SellingPreview() {
  useState(install);
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
      <AcquisitionShell authenticated active="account" pageName="Settings">
        <div style={{ display: "grid", gap: 16, padding: 16 }}>
          <PageHeader title="Selling" />
          <SellingSettings />
        </div>
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}
