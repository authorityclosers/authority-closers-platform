"use client";

/**
 * Each screen's route loading outline, signed in to a fictional organisation,
 * to lay beside the loaded fixture at the same width (Liquid Glass, 22 Oct
 * 2026: nothing may move except the content filling in).
 * `?screen=home` (default, an owner), `home&role=seller`, `leads`, `chats` or
 * `calls`.
 */

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import CallsLoading from "../../calls/loading";
import ChatsLoading from "../../chats/loading";
import DashboardLoading from "../../dashboard/loading";
import LeadsLoading from "../../leads/loading";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";

const SCREENS = {
  home: DashboardLoading,
  leads: LeadsLoading,
  chats: ChatsLoading,
  calls: CallsLoading,
};

function Preview() {
  const params = useSearchParams();
  const seller = params.get("role") === "seller";
  const Screen =
    SCREENS[(params.get("screen") ?? "home") as keyof typeof SCREENS] ??
    DashboardLoading;
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: {
          personId: seller ? SELLER : OWNER,
          sessionId: SESSION,
          tenantId: TENANT,
        },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Homes",
            role: seller ? "member" : "owner",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <Screen />
    </WorkspaceAccessContext.Provider>
  );
}

export function LoadingPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
