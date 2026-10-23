// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} />
  ),
}));
vi.mock("../../notice-center", () => ({ notify: () => undefined }));

import { pipelinesView, readPipelines } from "./journey-client";
import { JourneyTab } from "./journey-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Redmi QA, 23 Oct 2026 (P1): Lead stages broke ("This screen hit a snag") when the
// pipelines answer had no pipelines list: an error body, an older API, a fixture.
const stage = (key: string, label: string, kind: string) => ({
  key,
  label,
  kind,
  kindWords: "",
  milestone: "",
  meaning: "",
  archived: false,
  origin: "template",
  leads: 0,
});

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  Element.prototype.scrollIntoView = () => undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo) => {
      const path = String(input).split("?")[0];
      if (path === "/v1/lead-desk/pipelines")
        return Response.json({ detail: "Not here yet" });
      if (path === "/v1/lead-desk/journey")
        return Response.json({
          version: 1,
          industry: null,
          savedAt: null,
          savedBy: null,
          canEdit: false,
          kinds: {},
          meanings: {},
          stages: [
            stage("new_enquiry", "New enquiry", "new"),
            stage("keen", "Keen to join", "interested"),
          ],
        });
      if (path.startsWith("/v1/lead-desk/journey/suggestions"))
        return Response.json([]);
      if (path === "/v1/lead-desk/journey/templates") return Response.json([]);
      return Response.json({ detail: "Not Found" }, { status: 404 });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("reads a pipelines answer without pipelines as none", async () => {
  expect(await readPipelines()).toEqual({
    detail: "Not here yet",
    pipelines: [],
    sources: {},
    canEdit: false,
  });
  expect(pipelinesView(null).pipelines).toEqual([]);
  expect(
    pipelinesView({
      pipelines: [{ key: "main", name: "Enquiries" }, { name: "no key" }, null],
      canEdit: true,
    }),
  ).toMatchObject({
    pipelines: [{ key: "main", name: "Enquiries", sources: [] }],
    canEdit: true,
  });
});

it("shows Lead stages when the pipelines answer has no pipelines", async () => {
  await act(async () => root.render(<JourneyTab canManage={false} />));
  await act(async () => {
    for (let index = 0; index < 12; index += 1) await Promise.resolve();
  });
  expect(host.textContent).toContain("New enquiry");
  expect(host.textContent).toContain("Keen to join");
});
