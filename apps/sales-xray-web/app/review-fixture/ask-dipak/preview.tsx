"use client";

/**
 * Ask Dipak for screenshots on the dev workbench and GitHub (wb-ci
 * --visual): Dipak's own library, with fictional progress (two lessons
 * saved, one mission marked) answered in the browser. Only the lessons
 * themselves are read from the dev API, as the real page reads them.
 */

import { useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { AskDipakView } from "../../ask-dipak/ask-dipak-view";
import { COPY } from "../../ask-dipak/copy";
import { LESSON_PATH } from "../../ask-dipak/lessons";
import { PROGRESS_PATH, loadProgress } from "../../ask-dipak/progress";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";

const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";

const PROGRESS = { saved: ["PB03", "DM02"], missions: ["DM02"] };

/** The coaching API's answers for the Coach's desk (fictional: one active
 * mission, one call waiting for the seller's word; &checkin=0 answers it). */
const COACH = "/v1/sales-xray/ask-dipak";

async function growth(real: typeof fetch) {
  // The mission line is Dipak's own, read from the dev API's lesson.
  let mission: string | null = null;
  try {
    const answer = await real(`${LESSON_PATH}/DM02`, {
      credentials: "same-origin",
    });
    const body = (await answer.json()) as {
      lesson?: { next_call_mission?: string };
    };
    mission = body.lesson?.next_call_mission ?? null;
  } catch {
    mission = null;
  }
  return {
    max_active: 3,
    active: ["DM02"],
    missions: [
      {
        question_id: "DM02",
        title: "Partner question",
        mission,
        active: true,
        ticked: true,
        done_calls: 1,
        not_done_calls: 0,
      },
    ],
  };
}

const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

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
    if (path === `${COACH}/growth`) return json(await growth(real));
    if (path === `${COACH}/calls`) {
      const waiting =
        new URLSearchParams(window.location.search).get("checkin") !== "0";
      return json({
        active: [{ question_id: "DM02", title: "Partner question" }],
        calls: [
          {
            call_id: "sample-call",
            lead_name: "Sample lead",
            called_at: "2026-11-17T11:30:00+05:30",
            answered: waiting ? [] : ["DM02"],
            waiting: waiting ? ["DM02"] : [],
          },
        ],
      });
    }
    // Dipak's lessons come from the dev API itself (16 Nov 2026).
    if (path.startsWith(LESSON_PATH)) return real(input, init);
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
