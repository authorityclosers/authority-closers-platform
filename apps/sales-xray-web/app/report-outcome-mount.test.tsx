import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { ReportModes } from "./report-modes";
import {
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "./workspace-access";

// This test is about outcomes: Coaching's recurring-pattern read stays out.
vi.mock("./coaching/recurring-issue", () => ({
  recurringIssue: async () => null,
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const call = "c2793fdf-4948-47e4-a4bc-973f2b7720bc";
const person = "11111111-1111-4111-8111-111111111111";
const tenant = "22222222-2222-4222-8222-222222222222";
const session = "33333333-3333-4333-8333-333333333333";
const access: WorkspaceAccessValue = {
  status: "ready",
  authenticated: true,
  context: { personId: person, tenantId: tenant, sessionId: session },
  retry: () => {},
};
const record = (revision: number, value: unknown) => ({
  schema: "ac.sales-xray.call-outcome/1",
  submission_id: call,
  person_id: person,
  tenant_id: tenant,
  session_id: session,
  revision,
  value,
  basis: value ? "person" : null,
  locked: Boolean(value),
  set_by_person_id: value ? person : null,
  set_at: value ? "2026-10-11T12:00:00+00:00" : null,
  prospect_binding: null,
  can_edit: true,
});
const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

/** These tests are about outcome reads; the Report's Prospect part reads its own link. */
function outcomeReads(fetch: { mock: { calls: unknown[][] } }) {
  return fetch.mock.calls.filter(([input]) =>
    String(input).endsWith("/outcome"),
  );
}

async function settle() {
  for (let i = 0; i < 6; i += 1) await act(async () => Promise.resolve());
}

it("records a person's outcome in one tap and shows it as the call outcome", async () => {
  const won = {
    outcome: "won",
    lost_reason: null,
    follow_up_on: null,
    deal_value: null,
  };
  const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
    init?.method === "PUT" ? json(record(1, won)) : json(record(0, null)),
  );
  vi.stubGlobal("fetch", fetch);
  window.history.replaceState(null, "", `/?call=${call}`);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access}>
        <ReportModes
          panels={[]}
          boundCallId={call}
          documentData={{ report: amitReport, transcript: amitTranscript }}
        />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await settle();
  const picture = () =>
    host.querySelector<HTMLElement>('[data-xray-part="overview"]')!;
  const outcome = () =>
    host.querySelector<HTMLElement>('[data-xray-part="outcome"]')!;
  expect(outcomeReads(fetch)[0][0]).toBe(
    `/v1/conversation/prospects/calls/${call}/outcome`,
  );
  // Until a person records it, the analysis's reading stays labelled as such.
  expect(outcome().textContent).toContain("As heard on the call");
  expect(picture().textContent).toContain("Not set yet");
  const wonButton = [
    ...picture().querySelectorAll<HTMLButtonElement>("button"),
  ].find((b) => b.textContent === "Won")!;
  await act(async () => wonButton.click());
  await settle();
  const put = fetch.mock.calls.find(([, init]) => init?.method === "PUT")!;
  expect(JSON.parse(String(put[1]!.body))).toEqual({
    value: won,
    expected_revision: 0,
    expected_membership_id: null,
    expected_prospect_stage_revision: null,
  });
  expect(outcome().textContent).toContain("Set by your team");
  expect(outcome().dataset.outcome).toBe("won");
  expect(
    picture().querySelector('button[aria-pressed="true"]')?.textContent,
  ).toBe("Won");
  await act(async () => root.unmount());
});

it("never reads an outcome for a guest preview or without a signed-in workspace", async () => {
  const fetch = vi.fn(async () => json(record(0, null)));
  vi.stubGlobal("fetch", fetch);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <ReportModes
        panels={[]}
        boundCallId={call}
        documentData={{ report: amitReport, transcript: amitTranscript }}
      />,
    ),
  );
  await settle();
  expect(outcomeReads(fetch)).toHaveLength(0);
  expect(host.textContent).not.toContain("Not set yet");
  await act(async () => root.unmount());
});

it("stays quiet on a teammate's call the person cannot record", async () => {
  const fetch = vi.fn(
    async () =>
      new Response(JSON.stringify({ detail: "not_call_owner" }), {
        status: 403,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetch);
  window.history.replaceState(null, "", `/?call=${call}`);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access}>
        <ReportModes
          panels={[]}
          boundCallId={call}
          documentData={{ report: amitReport, transcript: amitTranscript }}
        />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await settle();
  expect(outcomeReads(fetch)).toHaveLength(1);
  const report = host.querySelector("[data-report-modes]")!;
  expect(report.textContent).not.toContain("couldn't be read");
  expect(report.textContent).not.toContain("Not set yet");
  expect(
    host.querySelector('[data-xray-part="outcome"]')!.textContent,
  ).toContain("As heard on the call");
  await act(async () => root.unmount());
});
