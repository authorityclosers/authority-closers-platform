"use client";

/**
 * Lead OS with a fictional sales team on the "Inside sales with demos" stages,
 * for screenshots on GitHub (wb-ci --visual), the e2e tests and the tutorials.
 * Every Lead Desk read is answered here; nothing leaves the browser. Names come
 * in lower case on purpose: the page shows them with capitals.
 *
 * - `/review-fixture/lead-pipeline`: the board, all nine stages, with late,
 *   no-next-step, meeting, Lost and Junk cards.
 * - `?sheet=move`: the stage sheet for a new lead (where it may go).
 * - `?sheet=meeting|lost|junk|interested`: straight to that move's questions.
 * - `?view=lead`: a lead's booked meeting, its stage path and its history.
 * - `?view=numbers`: the pipeline's numbers (counts only).
 */

import { useState, useSyncExternalStore } from "react";

import { withDisplayNames } from "../../display-name";
import { History } from "../../leads/lead-sheet";
import type { LeadDetail } from "../../leads/leads-client";
import { PipelineBoard } from "../../leads/pipeline/board";
import { PipelineDashboard } from "../../leads/pipeline/dashboard";
import { MeetingCard } from "../../leads/pipeline/meeting-card";
import { StageSheet } from "../../leads/pipeline/stage-sheet";
import {
  CARDS,
  LEAD,
  fixtureBoard,
  fixtureDetail,
  fixtureReport,
  movesFrom,
} from "./lead-pipeline-data";

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const answer = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    if (path.startsWith("/v1/lead-desk/board")) return answer(fixtureBoard());
    if (path.startsWith("/v1/lead-desk/reports/pipeline"))
      return answer(fixtureReport());
    if (/^\/v1\/lead-desk\/leads\/[^/]+\/stage/.test(path))
      return answer({
        leadId: LEAD.lead_id,
        revision: 4,
        stage: "interested",
        step: "interested",
        stepLabel: "Interested (In Follow-Up)",
        stageAt: new Date().toISOString(),
        meetingId: null,
      });
    if (/^\/v1\/lead-desk\/leads\/[^/?]+$/.test(path))
      return answer(fixtureDetail());
    if (path.startsWith("/v1/"))
      return new Response(JSON.stringify({ detail: "Sample data only." }), {
        status: 404,
      });
    return real(input, init);
  };
  return true;
}

const PEOPLE: ReadonlySet<string> = new Set([
  "name",
  "owner_name",
  "actor_name",
  "previous_owner_name",
  "host_name",
]);

const noSubscription = () => () => undefined;

const SHEETS: Record<string, string | null> = {
  move: null,
  meeting: "meeting_scheduled",
  lost: "lost",
  junk: "junk",
  interested: "interested",
};

export function LeadPipelinePreview() {
  useState(install);
  // The address, read in the browser only, so the server's page and the browser's agree.
  const search = useSyncExternalStore(
    noSubscription,
    () => window.location.search,
    () => null,
  );
  const [closed, setClosed] = useState(false);
  // Shown as the API client shows it: names with capitals.
  const [detail, setDetail] = useState<LeadDetail>(() =>
    withDisplayNames(fixtureDetail(), PEOPLE),
  );
  if (search === null) return null;
  const query = new URLSearchParams(search);
  const sheet = query.get("sheet");
  const view = query.get("view");
  const open = !closed && sheet !== null && sheet in SHEETS;
  if (view === "numbers")
    return (
      <main style={{ display: "grid", gap: 16, padding: 16 }}>
        <h1 style={{ margin: 0 }}>Pipeline numbers</h1>
        <PipelineDashboard pipeline="main" />
      </main>
    );
  if (view === "lead")
    return (
      <main
        style={{
          display: "grid",
          gap: 16,
          maxWidth: 640,
          margin: "0 auto",
          padding: 16,
        }}
      >
        <h1 style={{ margin: 0 }}>Sanjay Sample</h1>
        <MeetingCard detail={detail} onChanged={setDetail} />
        <History
          events={detail.events}
          currentLabel={detail.lead.stage_label}
        />
      </main>
    );
  const lead = withDisplayNames(CARDS.new[0], PEOPLE);
  return (
    <main
      style={{
        display: "flex",
        height: "100dvh",
        flexDirection: "column",
        padding: 16,
      }}
    >
      <h1 style={{ margin: "0 0 12px" }}>Leads</h1>
      <PipelineBoard
        filters={{ pipeline: "main" }}
        canManage
        onOpen={() => undefined}
      />
      {sheet !== null && sheet in SHEETS ? (
        <StageSheet
          open={open}
          lead={lead}
          moves={movesFrom("new")}
          initial={SHEETS[sheet]}
          onClose={() => setClosed(true)}
          onMoved={() => setClosed(true)}
        />
      ) : null}
    </main>
  );
}
