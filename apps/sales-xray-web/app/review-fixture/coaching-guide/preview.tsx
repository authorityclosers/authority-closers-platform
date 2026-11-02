"use client";

/**
 * Dipak's answers with the template's three EXAMPLE rows, for screenshots on
 * the dev workbench and GitHub (wb-ci --visual). The real route never shows
 * EXAMPLE content (guide-content.ts); this page is the only place it appears.
 * ?part=entry shows the Coaching page's row instead. Nothing leaves the
 * browser.
 */

import { useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { GuideEntry } from "../../coaching/guide/guide-entry";
import { parseGuide, questionCount } from "../../coaching/guide/guide-content";
import { GUIDE, GuideView } from "../../coaching/guide/guide-view";
import styles from "../../coaching/guide/guide.module.css";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";
import example from "./example.json";

const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";

const EXAMPLE = parseGuide(example);

/** The shell's own reads get a quiet "sample only" answer; nothing is sent. */
function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if (path.startsWith("/v1/"))
      return new Response(JSON.stringify({ detail: "Sample data only." }), {
        status: 404,
      });
    return real(input, init);
  };
  return true;
}

export function CoachingGuideFixture({ part }: { part?: string }) {
  useState(install);
  const entry = part === "entry";
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
      <AcquisitionShell authenticated active="coaching">
        <div className={styles.root} style={{ padding: 16 }}>
          {entry ? (
            <>
              <PageHeader title="My coaching" />
              <GuideEntry
                summary={{
                  version: 1,
                  shown: true,
                  questions: EXAMPLE?.questions.size ?? 0,
                  categories: ["objection handling", "closing", "discovery"],
                }}
              />
            </>
          ) : (
            <>
              <PageHeader
                title={GUIDE.title}
                context={[questionCount(EXAMPLE?.questions.size ?? 0)]}
                back={{ href: "/coaching", label: GUIDE.back }}
              />
              {EXAMPLE ? <GuideView guide={EXAMPLE} /> : null}
            </>
          )}
        </div>
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}
