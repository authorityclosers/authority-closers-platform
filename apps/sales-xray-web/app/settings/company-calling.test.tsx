import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { Calling } from "../leads/company-call-client";
import { CompanyCallingPanel } from "./company-calling";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 27 Oct 2026: calls from the company number, consented leads only,
// the recording notice on. Shown only where the workspace has it.
const VIEW: Calling = {
  available: true,
  on: false,
  number: null,
  provider: "Exotel",
  notice: {
    version: "recording-notice-en-v1",
    text: "This call is recorded, for quality and training.",
  },
  notices: [
    {
      version: "recording-notice-en-v1",
      text: "This call is recorded, for quality and training.",
    },
  ],
  windowDays: 7,
  sources: [
    { key: "meta", label: "Facebook and Instagram lead forms", on: true },
    {
      key: "webhook",
      label: "Website forms, chats and connected apps",
      on: true,
    },
    { key: "csv", label: "Imported files", on: false },
  ],
  myMobile: null,
  canManage: true,
  ready: false,
  blockers: ["Company calling is off in this workspace."],
  paused: null,
  testOnly: true,
};

let root: Root;
let host: HTMLDivElement;
let state: Calling;
let puts: Array<{ url: string; body: Record<string, unknown> }>;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  state = VIEW;
  puts = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        puts.push({ url: String(url), body });
        state = String(url).endsWith("/me")
          ? { ...state, myMobile: "+919800000001", blockers: [] }
          : {
              ...state,
              on: body.on === true,
              number: "+912000000000",
              blockers: [],
              ready: true,
            };
      }
      return Response.json(state);
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const flush = async () => {
  for (let i = 0; i < 4; i += 1)
    await act(async () => {
      await Promise.resolve();
    });
};

const button = (name: string) =>
  [...host.querySelectorAll("button")].filter(
    (node) => node.textContent === name,
  );

function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

it("shows nothing where the workspace doesn't call from a company number", async () => {
  state = { ...VIEW, available: false };
  await act(async () => root.render(<CompanyCallingPanel />));
  await flush();
  expect(host.innerHTML).toBe("");
});

it("lets an owner turn it on with the number the lead sees, for leads who asked", async () => {
  await act(async () => root.render(<CompanyCallingPanel />));
  await flush();
  expect(host.textContent).toContain("Calls from the company number");
  expect(host.textContent).toContain(
    "Company calling is off in this workspace.",
  );
  expect(host.textContent).toContain("This is a test site");
  expect(host.textContent).toContain(
    "the lead hears: “This call is recorded, for quality and training.”",
  );
  // No price, cost or minutes anywhere.
  expect(host.textContent).not.toMatch(/₹|paise|per minute|cost/i);
  const toggle = host.querySelector<HTMLInputElement>('input[role="switch"]')!;
  await act(async () => toggle.click());
  const number = host.querySelector<HTMLInputElement>(
    'input[placeholder="020 4000 0000"]',
  )!;
  await act(async () => type(number, "020 0000 0000"));
  await act(async () => button("Save")[1].click());
  await flush();
  expect(puts).toEqual([
    {
      url: "/v1/lead-desk/calling",
      body: {
        on: true,
        number: "020 0000 0000",
        noticeVersion: "recording-notice-en-v1",
        windowDays: 7,
        sources: ["meta", "webhook"],
      },
    },
  ]);
  expect(host.textContent).toContain("They see +912000000000.");
});

it("lets a seller set the mobile we ring first, without the team's setup", async () => {
  state = {
    ...VIEW,
    canManage: false,
    on: true,
    number: "+912000000000",
    provider: null,
  };
  await act(async () => root.render(<CompanyCallingPanel />));
  await flush();
  expect(
    host.querySelector('form[aria-label="Company calling setup"]'),
  ).toBeNull();
  const mobile = host.querySelector<HTMLInputElement>(
    'input[autocomplete="tel"]',
  )!;
  await act(async () => type(mobile, "98000 00001"));
  await act(async () => button("Save")[0].click());
  await flush();
  expect(puts).toEqual([
    { url: "/v1/lead-desk/calling/me", body: { mobile: "98000 00001" } },
  ]);
  expect(mobile.value).toBe("+919800000001");
});
