// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../../notice-center", () => ({ notify: () => undefined }));

import type { PipelinesView, TemplateView } from "./journey-client";
import { PipelineSheet, takesWords } from "./pipelines";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const SOURCES = {
  meta: "Facebook and Instagram lead ads",
  webhook: "Website forms and other apps",
  csv: "File imports",
  manual: "Added by hand",
};
const ONE: PipelinesView = {
  pipelines: [
    {
      key: "main",
      name: "Leads",
      position: 0,
      main: true,
      sources: [],
      industry: "education",
      leads: 4,
    },
  ],
  sources: SOURCES,
  canEdit: true,
};
const TWO: PipelinesView = {
  ...ONE,
  pipelines: [
    { ...ONE.pipelines[0], name: "Enrolment" },
    {
      key: "partner_outreach",
      name: "Partner outreach",
      position: 1,
      main: false,
      sources: ["csv"],
      industry: "b2b_services",
      leads: 382,
    },
  ],
};
const TEMPLATES = [
  { id: "simple", name: "Any business", blurb: "", icon: "spark", stages: [] },
  {
    id: "b2b_services",
    name: "B2B services & agencies",
    blurb: "",
    icon: "briefcase",
    stages: [],
  },
] as TemplateView[];

let host: HTMLDivElement;
let root: Root;
let sent: { url: string; method: string; body: unknown }[];
beforeEach(() => {
  sent = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      sent.push({
        url,
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      return Response.json(TWO);
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

const button = (text: string) =>
  [...document.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === text,
  );

it("says which new leads come into each pipeline", () => {
  expect(takesWords(ONE.pipelines[0], ONE)).toBe("Every new lead comes here.");
  expect(takesWords(TWO.pipelines[1], TWO)).toBe(
    "New leads from File imports.",
  );
  expect(takesWords(TWO.pipelines[0], TWO)).toBe(
    "Every other new lead: Facebook and Instagram lead ads, Website forms and other apps, Added by hand.",
  );
});

it("makes a pipeline from a kind of business and the sources ticked", async () => {
  const saved = vi.fn();
  await act(async () =>
    root.render(
      <PipelineSheet
        open
        view={ONE}
        pipeline={null}
        templates={TEMPLATES}
        onClose={() => undefined}
        onSaved={saved}
      />,
    ),
  );
  const dialog = document.querySelector("dialog")!;
  expect(button("Make pipeline")!.disabled).toBe(true);
  const name = dialog.querySelector<HTMLInputElement>("input:not([type])")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(name, "Partner outreach");
    name.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const kind = dialog.querySelector("select")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLSelectElement.prototype,
      "value",
    )!.set!.call(kind, "b2b_services");
    kind.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const boxes = [
    ...dialog.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
  ];
  expect(boxes).toHaveLength(4);
  await act(async () => boxes[2].click());
  await act(async () => button("Make pipeline")!.click());
  expect(sent).toEqual([
    {
      url: "/v1/lead-desk/pipelines",
      method: "POST",
      body: {
        name: "Partner outreach",
        template: "b2b_services",
        sources: ["csv"],
      },
    },
  ]);
  expect(saved).toHaveBeenCalledWith(TWO, "partner_outreach");
});

it("renames the first pipeline but never gives it sources", async () => {
  await act(async () =>
    root.render(
      <PipelineSheet
        open
        view={TWO}
        pipeline={TWO.pipelines[0]}
        templates={TEMPLATES}
        onClose={() => undefined}
        onSaved={() => undefined}
      />,
    ),
  );
  const dialog = document.querySelector("dialog")!;
  expect(dialog.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  expect(dialog.textContent).toContain("takes every new lead the others");
  await act(async () => button("Save")!.click());
  expect(sent[0]).toEqual({
    url: "/v1/lead-desk/pipelines/main",
    method: "PATCH",
    body: { name: "Enrolment" },
  });
});
