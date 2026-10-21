import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SellerSections } from "./seller-profile";

vi.mock("../../notice-center", () => ({ notify: vi.fn() }));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const SELLER = "0b8f4f0e-5b9a-4c51-9a77-1f2e3d4c5b6a";
let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string; body: string | null }[];

const team = {
  reps: [
    {
      person_id: SELLER,
      name: "Asha Fictional",
      role: "member",
      revision: 2,
      available: true,
      max_open: 50,
      languages: ["Marathi"],
      areas: ["Pune"],
      interests: [],
      open_leads: 31,
      due_now: 4,
      calls_today: 12,
      connected_today: 5,
      first_call_minutes: 6,
      phone: null,
    },
  ],
  settings: {
    revision: 1,
    auto_reassign: false,
    reassign_minutes: 10,
    default_country: "91",
  },
  by_stage: {},
  by_source: {},
  unassigned: 0,
  waiting_first_call: 0,
};
const callAi = {
  revision: 3,
  default: "full",
  people: [{ person_id: SELLER, name: "Asha Fictional", level: "data_only" }],
  you: { level: "full", source: "organisation" },
  levels: [
    { id: "off", name: "Off", hint: "No AI reads them." },
    { id: "data_only", name: "Data only", hint: "Transcript and lead facts." },
    { id: "auto", name: "Auto", hint: "Picks per call." },
    { id: "full", name: "Full", hint: "The full report." },
  ],
  can_edit: true,
};
const leads = {
  leads: [
    {
      lead_id: "00000000-0000-4000-8000-000000000201",
      name: "Ravi Fictional",
      city: "Pune",
      interest: "2 BHK",
      stage: "follow_up",
      stage_label: "Follow-up",
      source_label: "File upload",
      overdue: true,
    },
  ],
  total: 31,
  next_offset: 50,
};

beforeEach(() => {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: init?.body ? String(init.body) : null });
      const body = url.startsWith("/v1/lead-desk/team")
        ? team
        : url.startsWith("/v1/sales-xray/call-ai")
          ? method === "PUT"
            ? { ...callAi, revision: 4, people: [] }
            : callAi
          : url.startsWith("/v1/lead-desk/leads")
            ? leads
            : null;
      return body
        ? new Response(JSON.stringify(body), { status: 200 })
        : new Response(JSON.stringify({ detail: "Not found." }), {
            status: 404,
          });
    }),
  );
  window.history.replaceState(null, "", "/organisation/people/" + SELLER);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const tab = (label: string) =>
  [...host.querySelectorAll<HTMLButtonElement>('[role="tablist"] button')].find(
    (item) => item.textContent?.startsWith(label),
  )!;

async function show(canManage = true, isYou = false) {
  await act(async () =>
    root.render(
      <SellerSections
        personId={SELLER}
        firstName="Asha"
        isYou={isYou}
        canManage={canManage}
        overview={<p>Calls and charts</p>}
      />,
    ),
  );
}

it("shows a manager the seller's day, their AI level and five tabs at most", async () => {
  await show();
  expect(host.textContent).toContain("Takes new leads");
  expect(host.textContent).toContain("AI on calls: Data only");
  expect(host.textContent).toContain("Open leads");
  expect(host.textContent).toContain("Calls and charts");
  const tabs = [...host.querySelectorAll('[role="tablist"] button')].map(
    (item) => item.textContent,
  );
  expect(tabs.length).toBeLessThanOrEqual(5);
  expect(tabs.join(" ")).toMatch(/Overview.*Leads.*31.*Settings/);
  // No price or cost on a person's screen (owner, 19 Oct 2026).
  expect(host.textContent).not.toMatch(/₹|cost|price/i);
});

it("lists only this seller's open leads, each opening the lead", async () => {
  await show();
  await act(async () => tab("Leads").click());
  const read = calls.find((call) => call.url.startsWith("/v1/lead-desk/leads"));
  expect(read?.url).toContain(`owner=${SELLER}`);
  expect(read?.url).toContain("scope=team");
  expect(read?.url).toContain("stage=open");
  expect(host.textContent).toContain("Ravi Fictional");
  expect(host.textContent).toContain("Late · Follow-up");
  expect(
    host.querySelector(
      'a[href="/leads#lead=00000000-0000-4000-8000-000000000201"]',
    ),
  ).not.toBeNull();
  expect(window.location.search).toBe("?tab=leads");
});

it("lets a manager set the seller's AI level back to the default", async () => {
  await show();
  await act(async () => tab("Settings").click());
  expect(host.textContent).toContain("Lead rules");
  const fallback = host.querySelector<HTMLInputElement>(
    'input[type="radio"][value=""]',
  )!;
  await act(async () => fallback.click());
  const save = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === "Save",
  )!;
  await act(async () => save.click());
  const put = calls.find((call) => call.method === "PUT")!;
  expect(put.url).toBe(`/v1/sales-xray/call-ai/people/${SELLER}`);
  expect(JSON.parse(put.body!)).toEqual({ expected_revision: 3, level: null });
});

it("shows a seller their own level and no settings or team numbers", async () => {
  await show(false, true);
  expect(host.textContent).toContain("AI on calls: Full (default)");
  expect(host.textContent).not.toContain("Open leads");
  expect(tab("Settings")).toBeUndefined();
  expect(calls.some((call) => call.url.startsWith("/v1/lead-desk/team"))).toBe(
    false,
  );
});
