"use client";

/**
 * Ask Dipak for screenshots on the dev workbench and GitHub (wb-ci
 * --visual): Dipak's own library, with fictional progress (two lessons
 * saved, one mission marked) answered in the browser. Nothing leaves it.
 */

import { useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { AskDipakView } from "../../ask-dipak/ask-dipak-view";
import { COPY } from "../../ask-dipak/copy";
import { PROGRESS_PATH, loadProgress } from "../../ask-dipak/progress";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";

const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";

const PROGRESS = { saved: ["PB03", "DM02"], missions: ["DM02"] };

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if (path === PROGRESS_PATH)
      return new Response(JSON.stringify({ ...PROGRESS, missions_done: 1 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    if (path.startsWith("/v1/"))
      return new Response(JSON.stringify({ detail: "Sample data only." }), {
        status: 404,
      });
    return real(input, init);
  };
  void loadProgress();
  return true;
}

export function AskDipakFixture({ pick }: { pick: string | null }) {
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
            name: "Fictional workspace",
            role: "member",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <AcquisitionShell authenticated active="coaching" pageName={COPY.title}>
        <PageHeader title={COPY.title} titleInBar />
        <AskDipakView
          initial={
            pick ? { picked: { [pick]: 1 }, deep: { [pick]: true } } : undefined
          }
        />
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}
