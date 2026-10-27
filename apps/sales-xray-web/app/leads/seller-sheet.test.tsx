import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { CallAiSettings } from "../call-ai/call-ai-client";
import { resetBackCloseForTests } from "../ui/back-close";
import type { RepView, Team } from "./leads-client";
import { SellerSheet, savedLanguages } from "./seller-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner bug #49 (27 Oct 2026): a seller's lead settings as a switch, a
// stepper with presets, who they fit as chips from the organisation's own
// leads, and the AI on their calls as one choice. Made-up people only.
let root: Root;
let host: HTMLDivElement;
let sent: { method: string; url: string; body?: Record<string, unknown> }[];
let offered: boolean;

const PRIYA = "aaaaaaaa-0000-4000-8000-000000000001";

const rep: RepView = {
  person_id: PRIYA,
  name: "Priya Example",
  role: "member",
  revision: 3,
  available: true,
  max_open: 50,
  languages: ["Marathi"],
  areas: ["Pune"],
  interests: [],
  open_leads: 12,
  due_now: 3,
  calls_today: 0,
  connected_today: 0,
};

const callAi: CallAiSettings = {
  revision: 2,
  default: "full",
  people: [],
  you: { level: "full", source: "organisation" },
  levels: [
    { id: "off", name: "Off", hint: "No AI reads them." },
    { id: "data_only", name: "Data only", hint: "Transcript and facts." },
    { id: "auto", name: "Auto", hint: "Sales X-Ray picks per call." },
    { id: "full", name: "Full", hint: "The full report on every call." },
  ],
  can_edit: true,
};

const CHOICES = {
  schema: "lead-desk/1",
  days: 90,
  leads: 412,
  areas: [
    { value: "Pune", key: "pune", leads: 120 },
    { value: "Kharadi", key: "kharadi", leads: 5 },
  ],
  languages: [
    { value: "English", key: "en", leads: 88 },
    { value: "Marathi", key: "mr", leads: 70 },
  ],
  products: [{ value: "3 BHK", key: "3 bhk", leads: 41 }],
  more: { areas: 0, languages: 0, products: 0 },
  industry: { id: "real_estate", name: "Real estate" },
  suggested_products: [],
};

beforeEach(() => {
  sent = [];
  offered = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      sent.push({ method, url, body });
      if (url.startsWith("/v1/lead-desk/team/choices/fit"))
        return Response.json({
          days: 30,
          leads: 140,
          fits: 52,
          percent: 37,
          by: { language: 120, area: 61, product: 90 },
        });
      if (url.startsWith("/v1/lead-desk/team/choices"))
        return offered
          ? Response.json(CHOICES)
          : Response.json({ detail: "Not here" }, { status: 404 });
      if (url.startsWith("/v1/lead-desk/team/"))
        return Response.json({ reps: [rep], settings: {} });
      if (url.startsWith("/v1/sales-xray/call-ai/people/"))
        return Response.json({ ...callAi, revision: 3 });
      return Response.json({ characters: [] });
    }),
  );
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });

const button = (label: string) =>
  [...document.querySelectorAll("button")].find(
    (item) =>
      item.textContent?.trim() === label ||
      item.getAttribute("aria-label") === label,
  );

const show = async (saved: (team: Team) => void = () => undefined) => {
  await act(async () =>
    root.render(
      <SellerSheet
        rep={rep}
        callAi={callAi}
        onClose={() => undefined}
        onSaved={saved}
        onCallAiSaved={() => undefined}
      />,
    ),
  );
  await settle();
};

it("sets taking leads with a switch and the limit with a stepper and presets", async () => {
  await show();
  expect(document.body.textContent).toContain("12 open leads · 3 due now");
  expect(document.body.textContent).toContain(
    "On: new leads can go to Priya now",
  );
  const output = () => document.querySelector("output")!.textContent;
  expect(output()).toContain("50");
  await act(async () => button("More")!.click());
  expect(output()).toContain("55");
  await act(async () => button("10")!.click());
  expect(output()).toContain("10");
  expect(button("10")!.getAttribute("aria-pressed")).toBe("true");
  await act(async () => button("No limit")!.click());
  expect(output()).toContain("No limit");
  expect(button("Fewer")!.disabled).toBe(true);
});

it("names what Default means, and says each level in a line", async () => {
  await show();
  const levels = [
    ...document.querySelectorAll('[aria-label="AI on Priya\'s calls"] button'),
  ].map((item) => item.textContent);
  expect(levels).toEqual([
    "Default (Full)",
    "Off",
    "Data only",
    "Auto",
    "Full",
  ]);
  expect(document.body.textContent).toContain("The full report on every call.");
  await act(async () => button("Off")!.click());
  expect(document.body.textContent).toContain("No AI reads them.");
});

it("shows who Priya fits and how many of last month's leads that is", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  await show();
  await act(async () => {
    vi.advanceTimersByTime(400);
  });
  await settle();
  const fit = sent.find((item) => item.url.endsWith("/team/choices/fit"))!;
  expect(fit.body).toEqual({
    languages: ["Marathi"],
    areas: ["Pune"],
    products: [],
  });
  expect(document.body.textContent).toContain(
    "Fits 52 of last month's 140 leads (37%)",
  );
  // The per-part counts are for the editor, not the sheet.
  expect(document.body.textContent).not.toContain("By language");
  const row = button("Edit who Priya fits")!;
  expect(row.textContent).toContain("मराठी");
  expect(row.textContent).toContain("Pune");
});

it("edits languages in their own script, areas from the leads, and saves it all", async () => {
  const saved = vi.fn();
  await show(saved);
  await act(async () => button("Edit who Priya fits")!.click());
  await settle();
  // Languages: Marathi chosen; English is on the leads, with its count.
  const chosen = document.querySelector('[aria-label="Chosen"]')!;
  expect(chosen.textContent).toContain("मराठी Marathi");
  const leads = document.querySelector('[aria-label="On your leads"]')!;
  expect(leads.textContent).toContain("English88");
  expect(leads.textContent).not.toContain("Marathi");
  expect(
    document.querySelector('[aria-label="More languages"]')?.textContent,
  ).toContain("हिन्दी Hindi");
  await act(async () => button("English88")!.click());
  // Areas: on the leads first; any other place can be added.
  await act(async () => button("Areas1")!.click());
  const search = document.querySelector<HTMLInputElement>(
    'input[aria-label="Search areas"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(search, "Kha");
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(
    [...document.querySelectorAll('[aria-label="On your leads"] button')].map(
      (item) => item.textContent,
    ),
  ).toEqual(["Kharadi5"]);
  await act(async () => button("Add “Kha” as a place")!.click());
  expect(
    document.querySelector('[aria-label="Chosen"]')?.textContent,
  ).toContain("Kha");
  // Products carry the industry's icon.
  await act(async () => button("Products")!.click());
  expect(
    document.querySelector('[aria-label="On your leads"] button svg'),
  ).not.toBeNull();
  await act(async () => button("Done")!.click());
  await act(async () => button("Save")!.click());
  await settle();
  const put = sent.find((item) => item.method === "PUT")!;
  expect(put.url).toBe(`/v1/lead-desk/team/${PRIYA}`);
  expect(put.body).toMatchObject({
    expected_revision: 3,
    available: true,
    max_open: 50,
    languages: ["Marathi", "English"],
    areas: ["Pune", "Kha"],
    interests: [],
  });
  expect(saved).toHaveBeenCalled();
});

it("still edits without the organisation's choices, and shows no fit", async () => {
  offered = false;
  await show();
  expect(document.body.textContent).not.toContain("Fits ");
  await act(async () => button("Edit who Priya fits")!.click());
  await settle();
  expect(document.querySelector('[aria-label="On your leads"]')).toBeNull();
  expect(
    document.querySelector('[aria-label="More languages"]')?.textContent,
  ).toContain("English");
});

// Lead OS (27 Oct 2026): the server matches languages by English name or code,
// so one typed in its own script before is saved by its English name.
it("saves a language by its English name, whatever script it was typed in", () => {
  expect(savedLanguages(["हिन्दी", "Hindi", "मराठी", "Konkani"])).toEqual([
    "Hindi",
    "Marathi",
    "Konkani",
  ]);
});
