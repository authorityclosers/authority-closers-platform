// @vitest-environment happy-dom
/*
 * Owner-screen contract (owner, 5 Oct 2026, AUT-1223): the report, document and
 * calls screens keep every section the owner approved. A PR that drops one
 * fails here; changing owner-surfaces.json needs the owner's yes.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
}));
vi.mock("./profile-menu", () => ({ ProfileMenu: () => null }));

import contract from "./owner-surfaces.json";
import { CallsLibrary } from "./calls-library";
import { UploadSessionProvider } from "./hooks/upload-session";
import { DOCUMENT_CHAPTERS } from "./report-document-data";
import { FullShellPreview } from "./review-fixture/shell/full-shell-preview";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    for (let index = 0; index < 10; index += 1) await Promise.resolve();
  });
}

const missing = (wanted: string[], found: string[]) =>
  wanted.filter((item) => !found.some((text) => text === item));

it("keeps every owner-approved report section", async () => {
  window.history.replaceState(null, "", "/review-fixture/shell");
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new Error("offline fixture"))),
  );
  await act(async () => root.render(<FullShellPreview />));
  await settle();
  const headings = [...host.querySelectorAll("h1, h2, h3")].map((node) =>
    (node.textContent ?? "").replace(/\s+/g, " ").trim(),
  );
  expect(missing(contract.reportOverview, headings)).toEqual([]);
  expect(missing(contract.reportSections, headings)).toEqual([]);
});

it("keeps every owner-approved Document section, in order", () => {
  expect(DOCUMENT_CHAPTERS.map((chapter) => chapter.id)).toEqual(
    contract.documentSections,
  );
});

it("keeps the Calls workspace controls", async () => {
  const row = (id: string) => ({
    submission_id: id,
    created_at: "2026-09-14T06:30:00Z",
    duration_seconds: 61,
    state: "completed",
    has_report: true,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo) =>
      String(input) ===
      "/v1/conversation/acquisition/submissions?include_owners=true"
        ? new Response(
            JSON.stringify({
              submissions: [
                row("11111111-1111-4111-8111-111111111111"),
                row("22222222-2222-4222-8222-222222222222"),
              ],
              next_cursor: null,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          )
        : new Response("{}", { status: 404 }),
    ),
  );
  vi.spyOn(window.location, "assign").mockImplementation(() => {});
  await act(async () =>
    root.render(
      <UploadSessionProvider>
        <WorkspaceAccessProvider
          value={{
            status: "ready",
            authenticated: true,
            context: null,
            retry: () => {},
          }}
        >
          <CallsLibrary insights />
        </WorkspaceAccessProvider>
      </UploadSessionProvider>,
    ),
  );
  await settle();
  const calls = contract.callsWorkspace;
  expect(host.querySelector("h1")?.textContent?.trim()).toBe(calls.title);
  const labels = [...host.querySelectorAll("[aria-label]")].map(
    (node) => node.getAttribute("aria-label") ?? "",
  );
  expect(missing(calls.labels, labels)).toEqual([]);
  for (const prefix of calls.rowLabels)
    expect(labels.some((label) => label.startsWith(prefix))).toBe(true);
  const buttons = [...host.querySelectorAll("button")].map((node) =>
    (node.textContent ?? "").trim(),
  );
  for (const text of calls.buttons)
    expect(buttons.some((label) => label.startsWith(text))).toBe(true);
});
