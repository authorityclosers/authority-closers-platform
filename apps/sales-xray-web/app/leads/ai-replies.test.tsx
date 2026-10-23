import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AiHelp, AiRepliesSettings, SuggestReply } from "./ai-replies";
import type { AiLeadState, AiSettings } from "./ai-replies-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const SETTINGS: AiSettings = {
  mode: "suggest",
  channels: ["whatsapp", "messenger", "instagram"],
  quotePrices: false,
  businessName: "Fictional Homes",
  about: "Flats in Fictional Nagar.",
  offerings: "2 and 3 BHK.",
  faqs: [{ question: "Sunday visits?", answer: "Yes, 10am to 7pm." }],
  notes: "",
  ready: true,
  available: true,
};

let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string; body?: Record<string, unknown> }[];
let draft: Record<string, unknown>;
let later: Record<string, unknown>[];

beforeEach(() => {
  calls = [];
  later = [];
  draft = {
    replyId: "r1",
    draft: "Yes, every day 10am to 7pm.",
    handoff: false,
    words: "",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      const reply = url.endsWith("/ai-replies/settings")
        ? method === "PUT"
          ? { ...SETTINGS, ...body, ready: true }
          : SETTINGS
        : url.endsWith("/ai-draft") || url.endsWith("/ai-replies/try")
          ? draft
          : url.includes("/ai-draft/") || url.includes("/ai-replies/try/")
            ? (later.shift() ?? draft)
            : { detail: "not here" };
      return new Response(JSON.stringify(reply), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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

const button = (label: string) =>
  [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes(label),
  ) as HTMLButtonElement;

it("sets the mode and the business profile in Settings", async () => {
  await act(async () => root.render(<AiRepliesSettings />));
  expect(host.textContent).toContain("AI replies");
  expect(host.textContent).toContain("only about your business");
  const auto = [
    ...host.querySelectorAll('input[name="ai-mode"]'),
  ][2] as HTMLInputElement;
  await act(async () => auto.click());
  await act(async () => button("Save").click());
  const saved = calls.find((call) => call.method === "PUT");
  expect(saved?.url).toBe("/v1/lead-desk/ai-replies/settings");
  expect(saved?.body).toMatchObject({
    mode: "auto",
    quotePrices: false,
    businessName: "Fictional Homes",
    faqs: [{ question: "Sunday visits?", answer: "Yes, 10am to 7pm." }],
  });
  expect(host.textContent).toContain("Saved.");
});

it("puts the AI's draft in the reply box for the seller to send", async () => {
  const drafts: string[] = [];
  await act(async () =>
    root.render(
      <SuggestReply
        leadId="l1"
        channel="whatsapp"
        onDraft={(text) => drafts.push(text)}
      />,
    ),
  );
  await act(async () => button("Suggest a reply").click());
  expect(calls[0]).toMatchObject({
    url: "/v1/lead-desk/leads/l1/ai-draft",
    method: "POST",
    body: { channel: "whatsapp" },
  });
  expect(drafts).toEqual(["Yes, every day 10am to 7pm."]);
  expect(host.textContent).toContain("AI draft: read it");
});

it("waits for a draft written in the background", async () => {
  vi.useFakeTimers();
  try {
    draft = { replyId: "r3", status: "queued", handoff: false, words: "" };
    later = [
      { replyId: "r3", status: "queued", handoff: false, words: "" },
      {
        replyId: "r3",
        status: "drafted",
        draft: "Yes, there is covered parking.",
        handoff: false,
        words: "",
      },
    ];
    const drafts: string[] = [];
    await act(async () =>
      root.render(
        <SuggestReply
          leadId="l1"
          channel="instagram"
          onDraft={(text) => drafts.push(text)}
        />,
      ),
    );
    await act(async () => button("Suggest a reply").click());
    expect(host.textContent).toContain("Thinking…");
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    expect(drafts).toEqual([]);
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    expect(drafts).toEqual(["Yes, there is covered parking."]);
    expect(calls.map((call) => call.url)).toEqual([
      "/v1/lead-desk/leads/l1/ai-draft",
      "/v1/lead-desk/leads/l1/ai-draft/r3",
      "/v1/lead-desk/leads/l1/ai-draft/r3",
    ]);
  } finally {
    vi.useRealTimers();
  }
});

it("says plainly when AI replies are paused, with no amount", async () => {
  draft = {
    replyId: "r4",
    status: "paused",
    handoff: true,
    reason: "budget",
    words: "AI replies are paused for now.",
  };
  await act(async () =>
    root.render(
      <SuggestReply leadId="l1" channel="whatsapp" onDraft={() => {}} />,
    ),
  );
  await act(async () => button("Suggest a reply").click());
  expect(host.textContent).toContain("AI replies are paused for now.");
  expect(host.textContent).not.toContain("person should answer");
  expect(host.textContent).not.toMatch(/₹|Rs|INR/);
});

it("tries a sample message in Settings, sending nothing", async () => {
  vi.useFakeTimers();
  try {
    draft = { replyId: "t1", status: "queued", handoff: false, words: "" };
    later = [
      {
        replyId: "t1",
        status: "drafted",
        draft: "Yes, site visits run every day.",
        handoff: false,
        words: "",
      },
    ];
    await act(async () => root.render(<AiRepliesSettings />));
    const box = [...host.querySelectorAll("textarea")].at(
      -1,
    ) as HTMLTextAreaElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      set?.call(box, "Sunday visit?");
      box.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => button("Try it").click());
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    expect(host.textContent).toContain(
      "AI draft: Yes, site visits run every day.",
    );
    expect(host.textContent).toContain("Nothing is sent to anyone.");
    const tried = calls.find((call) => call.url.endsWith("/ai-replies/try"));
    expect(tried).toMatchObject({
      method: "POST",
      body: { message: "Sunday visit?" },
    });
    expect(
      calls.some((call) => call.url === "/v1/lead-desk/ai-replies/try/t1"),
    ).toBe(true);
  } finally {
    vi.useRealTimers();
  }
});

it("says why a person should answer instead", async () => {
  draft = {
    replyId: "r2",
    draft: null,
    handoff: true,
    reason: "price",
    words: "They're asking about price.",
  };
  const drafts: string[] = [];
  await act(async () =>
    root.render(
      <SuggestReply
        leadId="l1"
        channel="messenger"
        onDraft={(t) => drafts.push(t)}
      />,
    ),
  );
  await act(async () => button("Suggest a reply").click());
  expect(drafts).toEqual([]);
  expect(host.textContent).toContain(
    "A person should answer. They're asking about price.",
  );
});

it("shows a hand-off on the channel, and nothing when AI replies are off", async () => {
  const ai: AiLeadState = {
    mode: "auto",
    channels: ["whatsapp"],
    ready: true,
    available: true,
    handoffs: [
      { channel: "whatsapp", reason: "human", at: new Date().toISOString() },
    ],
  };
  await act(async () =>
    root.render(
      <AiHelp ai={ai} leadId="l1" channel="whatsapp" onDraft={() => {}} />,
    ),
  );
  expect(host.textContent).toContain(
    "A person should answer: They asked for a person.",
  );
  expect(button("Suggest a reply")).toBeTruthy();
  await act(async () =>
    root.render(
      <AiHelp
        ai={{ ...ai, mode: "off" }}
        leadId="l1"
        channel="whatsapp"
        onDraft={() => {}}
      />,
    ),
  );
  expect(host.textContent).toBe("");
  await act(async () =>
    root.render(
      <AiHelp ai={ai} leadId="l1" channel="instagram" onDraft={() => {}} />,
    ),
  );
  expect(host.textContent).toBe("");
  // Paused: the hand-off note stays, suggestions stop.
  await act(async () =>
    root.render(
      <AiHelp
        ai={{ ...ai, paused: true }}
        leadId="l1"
        channel="whatsapp"
        onDraft={() => {}}
      />,
    ),
  );
  expect(host.textContent).toContain("A person should answer");
  expect(button("Suggest a reply")).toBeUndefined();
});

it("stays out of the reply box until Sales X-Ray's AI is switched on", async () => {
  await act(async () =>
    root.render(
      <AiHelp
        ai={{
          mode: "suggest",
          channels: ["whatsapp"],
          ready: true,
          available: false,
          handoffs: [],
        }}
        leadId="l1"
        channel="whatsapp"
        onDraft={() => {}}
      />,
    ),
  );
  expect(host.textContent).toBe("");
});
