import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../tests/fixtures/dipak-overview.json";
import { KeyFacts } from "./key-facts";
import { ReportReadingProvider } from "./report-reading-context";
import type { SalesReport, Transcript } from "./report-contract";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "./workspace-access";
import { syntheticProspect } from "./review-fixture/prospects/synthetic-prospect";
import * as client from "./prospects-client";
import * as notices from "./notice-center";
import { PROSPECT_FIELD_LABELS } from "./prospect-profile-contract";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const CALL = "5b7a0d2e-8c4f-4a61-9d3e-2f1b0c9a8e77";
const report = fixture.report as SalesReport;
const transcript = fixture.transcript as Transcript;
const access: WorkspaceAccessValue = {
  status: "ready",
  authenticated: true,
  context: {
    personId: "person-one",
    sessionId: "session-one",
    tenantId: "tenant-one",
  },
  retry: vi.fn(),
};
let root: Root, host: HTMLDivElement;
let fetcher: ReturnType<typeof vi.fn>;
const detail = (prospect = syntheticProspect) => ({
  schema: "ac.sales-xray.prospects/1",
  prospect,
  calls: [],
  next_offset: null,
  promises: [],
  next_steps: [],
  buyer_intent_history: [],
});
beforeEach(() => {
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          schema: "ac.sales-xray.prospect-link/1",
          submission_id: CALL,
          membership: {
            prospect_id: syntheticProspect.prospect_id,
            membership_id: "22222222-2222-4222-8222-222222222222",
          },
        }),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(client, "fetchProspectDetail").mockResolvedValue(detail());
  vi.spyOn(notices, "notify").mockImplementation(() => {});
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function render(value = access, documentView = false) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={value}>
        <ReportReadingProvider
          reading={documentView}
          documentView={documentView}
        >
          <KeyFacts
            callId={CALL}
            transcript={transcript}
            report={report}
            durationMs={transcript.duration_ms}
            onSeek={vi.fn()}
          />
        </ReportReadingProvider>
      </WorkspaceAccessContext.Provider>,
    ),
  );
}
it("reads server fields and their sources without using or changing legacy device facts", async () => {
  const legacy = JSON.stringify({
    values: { industry: "Invented local industry" },
  });
  localStorage.setItem(`ac.xray.facts.v1:${CALL}`, legacy);
  await render();
  expect(host.textContent).toContain("अदिती");
  expect(host.textContent).toContain("Example company");
  expect(host.textContent).not.toContain("Invented local industry");
  expect(host.textContent).not.toContain("Saved on this device");
  expect(host.textContent).toContain(
    "Change any fact here. Your change stays when later calls come in.",
  );
  expect(host.querySelectorAll("[data-server-prospect-facts] dt")).toHaveLength(
    6,
  );
  expect(fetcher.mock.calls[0][0]).toContain(`/calls/${CALL}/suggestions`);
  expect(localStorage.getItem(`ac.xray.facts.v1:${CALL}`)).toBe(legacy);
});
it("shows a human Unknown as locked without an old value or source", async () => {
  vi.mocked(client.fetchProspectDetail).mockResolvedValue(
    detail({
      ...syntheticProspect,
      profile_fields: {
        business: {
          state: "unknown",
          reason: "not_asked",
          basis: "person",
          locked: true,
          set_at: "2026-10-10T12:00:00Z",
        },
      },
    }),
  );
  await render();
  const fact = [
    ...host.querySelectorAll("[data-server-prospect-facts] dt"),
  ].find((label) =>
    label.textContent?.startsWith(PROSPECT_FIELD_LABELS.business),
  )?.parentElement;
  expect(fact?.textContent).toContain("Unknown");
  expect(fact?.textContent).toContain("Person edit · locked");
  expect(fact?.textContent).not.toContain("Example company");
  expect(fact?.querySelector("blockquote, details")).toBeNull();
});
it("Enter writes the locked field API, then reads back the server revision", async () => {
  const edit = vi.spyOn(client, "editProspectField").mockResolvedValue();
  await render();
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label^="Industry:"]')!
      .click(),
  );
  const input = host.querySelector<HTMLInputElement>(
    'input[aria-label="Industry"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Typed industry");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    input.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(edit).toHaveBeenCalledWith(
    syntheticProspect.prospect_id,
    3,
    "industry",
    "Typed industry",
  );
  expect(client.fetchProspectDetail).toHaveBeenCalledTimes(2);
  expect(localStorage.length).toBe(0);
});
it("distinguishes a successful write from a failed readback and withholds stale edits", async () => {
  vi.spyOn(client, "editProspectField").mockResolvedValue();
  await render();
  vi.mocked(client.fetchProspectDetail).mockRejectedValue(
    new Error("Unavailable"),
  );
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label^="Industry:"]')!
      .click(),
  );
  const input = host.querySelector<HTMLInputElement>(
    'input[aria-label="Industry"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Typed industry");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    input.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({ title: "Fact saved · refresh unavailable" }),
  );
  expect(host.textContent).toContain(
    "Your edit was saved. Latest facts are unavailable.",
  );
  expect(
    host.querySelector(
      "[data-server-prospect-facts] input, [data-server-prospect-facts] button",
    ),
  ).toBeNull();
});
it("keeps the report usable and offers a corner retry when the field service is missing", async () => {
  fetcher.mockResolvedValue(new Response("", { status: 404 }));
  await render();
  expect(host.textContent).toContain("Key facts are unavailable");
  expect(host.textContent).toContain("Facts heard in this call");
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({
      title: "Key facts unavailable",
      action: expect.objectContaining({ label: "Try again" }),
    }),
  );
  expect(host.querySelector("input")).toBeNull();
});
it("does not create or match a prospect when there is no canonical link", async () => {
  fetcher.mockResolvedValue(
    new Response(
      JSON.stringify({
        schema: "ac.sales-xray.prospect-link/1",
        submission_id: CALL,
        membership: null,
      }),
    ),
  );
  await render();
  expect(host.textContent).toContain("Link this call to a prospect");
  expect(client.fetchProspectDetail).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledOnce();
});
it("keeps shared customer and document fields read-only", async () => {
  vi.mocked(client.fetchProspectDetail).mockResolvedValue(
    detail({ ...syntheticProspect, can_edit: false }),
  );
  await render();
  expect(host.querySelector("[data-server-prospect-facts] button")).toBeNull();
  vi.mocked(client.fetchProspectDetail).mockResolvedValue(detail());
  await render(access, true);
  expect(host.querySelector("button, input, select, form")).toBeNull();
});
it("withholds old prospect edits immediately when the call link refreshes", async () => {
  await render();
  expect(
    host.querySelector("[data-server-prospect-facts] button"),
  ).not.toBeNull();
  vi.mocked(client.fetchProspectDetail).mockImplementationOnce(
    () => new Promise(() => {}),
  );
  await act(async () =>
    window.dispatchEvent(new Event("ac:prospect-facts-changed")),
  );
  expect(host.textContent).not.toContain("अदिती");
  expect(host.querySelector("[data-server-prospect-facts] button")).toBeNull();
  expect(host.querySelector('[aria-label="Loading key facts"]')).not.toBeNull();
});
it("withholds the previous workspace data as soon as account access is lost", async () => {
  await render();
  expect(host.textContent).toContain("अदिती");
  await render({
    ...access,
    status: "unauthenticated",
    authenticated: false,
    context: null,
  });
  expect(host.textContent).not.toContain("अदिती");
  expect(host.textContent).toContain("Sign in to save prospect facts");
});
