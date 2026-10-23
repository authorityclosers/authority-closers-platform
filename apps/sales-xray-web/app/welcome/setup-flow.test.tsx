// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SetupFlow } from "./setup-flow";
import {
  inviteEmails,
  needsSetup,
  readSetupMark,
  stepsFor,
  suggestedBusinessName,
} from "./setup-state";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// First-run setup (owner, 23 Oct 2026: "not progressive"): one question per
// step, every step skippable, built only from what the app already does.
const PERSON = "6f4b8f9e-1c2d-4e5f-8a9b-0c1d2e3f4a5b";
const PERSONAL = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d";
const NEW_ORG = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b";
const INVITED_ORG = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e";
const INVITE = "3c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f";

let root: Root;
let host: HTMLDivElement;
let sent: { method: string; path: string; body?: unknown }[];
let organisations: unknown[];
let invites: unknown[];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  sent = [];
  organisations = [];
  invites = [];
  window.localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = init?.method ?? "GET";
      sent.push({
        method,
        path,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      if (path === "/v1/me/workspaces")
        return json({
          person_id: PERSON,
          session_id: "s",
          selected_tenant_id: PERSONAL,
          workspaces: [],
        });
      if (path === "/v1/me/sales-xray-workspaces")
        return json({
          selected_tenant_id: PERSONAL,
          workspaces: [
            {
              tenant_id: PERSONAL,
              kind: "personal",
              name: "Personal",
              role: null,
              sales_xray_enabled: true,
            },
            ...organisations,
          ],
        });
      if (path === "/v1/me/sales-xray-profile")
        return json({
          name: "asha example",
          email: "asha@bright-homes.example",
          phone_number_e164: null,
          phone_verified: false,
          profile_complete: false,
          revision: 1,
        });
      if (path === "/v1/organisation/invites") return json({ invites });
      if (path === "/v1/organisation" && method === "POST")
        return json({ tenant_id: NEW_ORG, name: "Bright Homes" });
      if (path === `/v1/organisation/invites/${INVITE}/accept`)
        return json({
          status: "accepted",
          tenant_id: INVITED_ORG,
          role: "member",
        });
      if (path === "/v1/organisation/members") return json({});
      if (path === "/v1/context")
        return json({ tenant_id: JSON.parse(String(init?.body)).tenant_id });
      if (path === "/v1/lead-desk/journey/templates")
        return json([
          {
            id: "real_estate",
            name: "Real estate",
            blurb: "From enquiry to site visit to booking.",
            icon: "building",
            stages: [],
          },
          {
            id: "simple",
            name: "Any business",
            blurb: "Six stages that suit most teams.",
            icon: "spark",
            stages: [],
          },
        ]);
      if (path === "/v1/lead-desk/journey")
        return json({ version: 0, industry: null, stages: [] });
      if (path === "/v1/lead-desk/journey/template")
        return json({ version: 1, industry: "real_estate", stages: [] });
      return json({}, 404);
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    for (let index = 0; index < 12; index += 1) await Promise.resolve();
  });
}

async function press(name: string) {
  // The last match: a step's own action comes after the choice it names.
  const button = Array.from(host.querySelectorAll("button"))
    .filter((item) => item.textContent?.includes(name))
    .at(-1);
  if (!button) throw new Error(`Missing button: ${name}`);
  await act(async () => button.click());
  await settle();
}

async function type(selector: string, value: string) {
  const field = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(
    selector,
  )!;
  const prototype =
    field instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(
      field,
      value,
    );
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const heading = () => host.querySelector("h1")?.textContent;
const progress = () =>
  host.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow");
const writes = () =>
  sent
    .filter((item) => item.method !== "GET")
    .map((item) => [item.path, item.body]);

it("knows a new account, a business name and invite addresses", () => {
  expect(needsSetup({ organisations: 0, calls: 0 })).toBe(true);
  expect(needsSetup({ organisations: 1, calls: 0 })).toBe(false);
  expect(needsSetup({ organisations: 0, calls: 3 })).toBe(false);
  expect(needsSetup({ organisations: 0, calls: null })).toBe(false);
  expect(suggestedBusinessName("sales@bright-homes.in")).toBe("Bright Homes");
  expect(suggestedBusinessName("someone@gmail.com")).toBe("");
  expect(
    inviteEmails("a@x.example, b@y.example\nnot-an-email a@x.example"),
  ).toEqual({
    valid: ["a@x.example", "b@y.example"],
    invalid: ["not-an-email"],
  });
  expect(stepsFor("business")).toEqual([
    "start",
    "name",
    "business",
    "team",
    "first",
  ]);
  expect(stepsFor("solo")).toEqual(["start", "first"]);
});

it("sets up a business one question at a time, then adds the first lead", async () => {
  const assign = vi
    .spyOn(window.location, "assign")
    .mockImplementation(() => undefined);
  await act(async () => root.render(<SetupFlow />));
  await settle();

  expect(heading()).toBe("How will you use Sales X-Ray?");
  expect(host.textContent).toContain("Welcome, Asha");
  expect(progress()).toBe("1");
  expect(
    host.querySelector('[role="radio"][aria-checked="true"]')?.textContent,
  ).toContain("For my business");
  await press("Set up my business");

  expect(heading()).toBe("What’s your business called?");
  // A work address suggests the name; nothing is created until asked.
  expect(host.querySelector<HTMLInputElement>("input")?.value).toBe(
    "Bright Homes",
  );
  expect(writes()).toEqual([]);
  await press("Create my business");

  expect(heading()).toBe("What does your business sell?");
  expect(progress()).toBe("3");
  const use = Array.from(host.querySelectorAll("button")).find((item) =>
    item.textContent?.includes("Pick one to continue"),
  )!;
  expect(use.disabled).toBe(true);
  await press("Real estate");
  await press("Use these stages");

  expect(heading()).toBe("Who sells with you?");
  await type(
    "textarea",
    "ravi@bright-homes.example, meera@bright-homes.example",
  );
  await press("Send 2 invites");

  expect(heading()).toBe("Add your first lead");
  expect(host.textContent).toContain(
    "Bright Homes is ready, with you as owner",
  );
  expect(host.textContent).toContain("Lead stages for real estate");
  expect(host.textContent).toContain("2 invites sent");
  await press("Add your first lead");

  expect(writes()).toEqual([
    ["/v1/organisation", { name: "Bright Homes" }],
    ["/v1/context", { tenant_id: NEW_ORG }],
    [
      "/v1/lead-desk/journey/template",
      { expectedVersion: 0, template: "real_estate" },
    ],
    [
      "/v1/organisation/members",
      { email: "ravi@bright-homes.example", role: "member" },
    ],
    [
      "/v1/organisation/members",
      { email: "meera@bright-homes.example", role: "member" },
    ],
  ]);
  expect(assign).toHaveBeenCalledWith("/leads#add=lead");
  expect(readSetupMark(PERSON)).toBe("done");
});

it("lets every step be skipped, and Skip setup leaves at once", async () => {
  const assign = vi
    .spyOn(window.location, "assign")
    .mockImplementation(() => undefined);
  await act(async () => root.render(<SetupFlow />));
  await settle();
  await press("Skip setup");
  expect(assign).toHaveBeenCalledWith("/");
  expect(readSetupMark(PERSON)).toBe("skipped");
  expect(writes()).toEqual([]);
});

it("joins an organisation that invited the person, without the owner's steps", async () => {
  invites = [
    {
      invite_id: INVITE,
      tenant_id: INVITED_ORG,
      organisation_name: "Fictional Homes",
      role: "member",
      invited_at: null,
      expires_at: null,
    },
  ];
  await act(async () => root.render(<SetupFlow />));
  await settle();
  expect(
    host.querySelector('[role="radio"][aria-checked="true"]')?.textContent,
  ).toContain("Join Fictional Homes");
  expect(
    host.querySelector('[role="progressbar"]')?.getAttribute("aria-valuemax"),
  ).toBe("2");
  await press("Join Fictional Homes");
  expect(heading()).toBe("You’re in Fictional Homes");
  expect(writes()).toEqual([
    [`/v1/organisation/invites/${INVITE}/accept`, undefined],
    ["/v1/context", { tenant_id: INVITED_ORG }],
  ]);
});

it("sends someone who already has a business straight home", async () => {
  organisations = [
    {
      tenant_id: NEW_ORG,
      kind: "organisation",
      name: "Bright Homes",
      role: "owner",
      sales_xray_enabled: true,
    },
  ];
  const replace = vi
    .spyOn(window.location, "replace")
    .mockImplementation(() => undefined);
  await act(async () => root.render(<SetupFlow />));
  await settle();
  expect(replace).toHaveBeenCalledWith("/");
  expect(readSetupMark(PERSON)).toBe("not-needed");
});
