// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AMIT_PROFILE } from "../review-fixture/prospects/amit-profile";
import type { DocumentReportData } from "../report-document-data";
import {
  amitReport,
  amitTranscript,
} from "../review-fixture/report/story/amit-call";
import { exampleView } from "./example";
import { readCallProspect } from "../prospect-report-facts";
import { WorkspaceAccessContext } from "../workspace-access";
import { ProspectPart } from "./prospect";

vi.mock("../prospect-report-facts", () => ({ readCallProspect: vi.fn() }));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const CALL = "00000000-0000-4000-8000-000000000123";
const PROSPECT = "00000000-0000-4000-8000-000000000456";
let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const flush = async () => {
  await act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve();
  });
};

function data(withProfile: boolean): DocumentReportData {
  return {
    report: {
      ...amitReport,
      structure: withProfile ? { prospect_profile: AMIT_PROFILE } : undefined,
    },
    transcript: amitTranscript,
  } as DocumentReportData;
}

const view = exampleView("decision_pending");
const signedIn = {
  status: "ready",
  authenticated: true,
  context: { personId: PROSPECT, sessionId: PROSPECT, tenantId: PROSPECT },
  retry: () => {},
} as const;
const inWorkspace = (node: React.ReactNode) => (
  <WorkspaceAccessContext.Provider value={signedIn}>
    {node}
  </WorkspaceAccessContext.Provider>
);

it("shows the owner's layout with evidence, AI labels and Unknowns, and saves a confirmation", async () => {
  const puts: unknown[] = [];
  vi.mocked(readCallProspect).mockResolvedValue({
    prospect_id: PROSPECT,
    name: "Amit",
    revision: 3,
    owner_person_id: PROSPECT,
    stage: null,
    tags: [],
    photo_url: null,
    contact: null,
    fields: [],
    buyer_intent: null,
    next_step: null,
    last_promise: null,
    call_count: 1,
    last_call: null,
    profile_fields: {},
    can_edit: true,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, init?: RequestInit) => {
      puts.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 204 });
    }),
  );
  await act(async () =>
    root.render(
      inWorkspace(
        <ProspectPart
          data={data(true)}
          callId={CALL}
          view={view}
          onSelect={vi.fn()}
        />,
      ),
    ),
  );
  await flush();
  const text = host.textContent ?? "";
  expect(text).toContain("Remember Before You Call Again");
  expect(text).toContain("Amit");
  expect(text).toContain("Founder · XYZ Digital");
  expect(text).toContain("Strong Fit");
  expect(text).toContain("Medium Urgency");
  expect(text).toContain("Friday 4 PM");
  expect(text).toContain("Additional Buyer Information");
  expect(text).toContain("Considering a ₹2 lakh investment.");
  // Unknown when the call does not say it.
  expect(text).toContain("Not said in this call");
  expect(text).toContain("AI’s read");
  const confirm = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Confirm",
  );
  expect(confirm).toBeDefined();
  await act(async () => confirm!.click());
  await flush();
  expect(puts[0]).toMatchObject({ expected_revision: 3 });
});

it("shows a skeleton while reading, then a call-only note without a prospect", async () => {
  vi.mocked(readCallProspect).mockReturnValue(new Promise(() => {}));
  await act(async () =>
    root.render(
      inWorkspace(
        <ProspectPart data={data(false)} callId={CALL} view={view} />,
      ),
    ),
  );
  expect(host.querySelector('[aria-busy="true"]')).not.toBeNull();
  await act(async () => root.unmount());
  root = createRoot(host);
  vi.mocked(readCallProspect).mockResolvedValue(null);
  // The detect step is refused: the call keeps its own facts, read-only.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 403 })),
  );
  await act(async () =>
    root.render(
      inWorkspace(
        <ProspectPart data={data(false)} callId={CALL} view={view} />,
      ),
    ),
  );
  await flush();
  const text = host.textContent ?? "";
  expect(text).toContain("isn’t saved to a prospect yet");
  expect(text).toContain("Appears once the call is scored");
  // Confirm saves this call as a prospect first, then the fact.
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${path}`);
      return init?.method === "PUT"
        ? new Response(null, { status: 204 })
        : Response.json({});
    }),
  );
  vi.mocked(readCallProspect).mockResolvedValue({
    prospect_id: PROSPECT,
    name: "Prospect — name not heard",
    revision: 1,
    owner_person_id: PROSPECT,
    stage: null,
    tags: [],
    photo_url: null,
    contact: null,
    fields: [],
    buyer_intent: null,
    next_step: null,
    last_promise: null,
    call_count: 1,
    last_call: null,
    profile_fields: {},
    can_edit: true,
  });
  const add = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Add",
  );
  expect(add).toBeDefined();
  await act(async () => add!.click());
  const input = host.querySelector<HTMLInputElement>("form input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "XYZ Digital");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    input.form!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
  await flush();
  expect(calls[0]).toBe(`POST /v1/conversation/prospects/calls/${CALL}/create`);
  expect(calls[1]).toBe(`PUT /v1/conversation/prospects/${PROSPECT}/fields`);
});

it("reads and saves nothing without a signed-in workspace", async () => {
  vi.mocked(readCallProspect).mockClear();
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  await act(async () =>
    root.render(<ProspectPart data={data(true)} callId={CALL} view={view} />),
  );
  await flush();
  expect(readCallProspect).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Remember Before You Call Again");
  expect(host.querySelectorAll("button")).toHaveLength(0);
});
