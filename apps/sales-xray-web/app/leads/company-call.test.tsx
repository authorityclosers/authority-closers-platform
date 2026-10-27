import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  callLine,
  readCompanyRecording,
  type CompanyCall,
} from "./company-call-client";
import {
  CompanyCallStrip,
  useCompanyCall,
  type CompanyCalling,
} from "./company-call";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 27 Oct 2026: a lead who asked to be contacted is called from the
// company number; the seller's phone rings first, then the lead's.
const LEAD = "11111111-1111-4111-8111-111111111111";
const ENDED: CompanyCall = {
  id: "22222222-2222-4222-8222-222222222222",
  leadId: LEAD,
  status: "completed",
  final: true,
  words: null,
  talkSeconds: 62,
  connected: true,
  eventId: "33333333-3333-4333-8333-333333333333",
  recording: true,
  requestedAt: "2026-10-27T10:00:00Z",
};

let root: Root;
let host: HTMLDivElement;
let seen: CompanyCalling | null;
let posts: Array<{ url: string; body: unknown }>;
let refuse: { status: number; reason: string; detail: string } | null;
let available: boolean;

const see = (value: CompanyCalling) => {
  seen = value;
};

function Harness({ enabled = true }: { enabled?: boolean }) {
  const company = useCompanyCall(LEAD, enabled);
  useEffect(() => see(company));
  return (
    <div>
      <button type="button" onClick={() => void company.start()}>
        Call
      </button>
      <CompanyCallStrip
        company={company}
        name="Asha Patil"
        phone="+919800000002"
      />
    </div>
  );
}

const flush = async () => {
  for (let i = 0; i < 4; i += 1)
    await act(async () => {
      await Promise.resolve();
    });
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  seen = null;
  posts = [];
  refuse = null;
  available = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url);
      if (path === `/v1/lead-desk/calling/leads/${LEAD}`)
        return Response.json({
          available,
          reason: available ? null : "not_asked",
          words: null,
        });
      if (init?.method === "POST") {
        posts.push({ url: path, body: JSON.parse(String(init.body)) });
        if (refuse)
          return Response.json(
            { detail: refuse.detail },
            {
              status: refuse.status,
              headers: { "x-company-call-refused": refuse.reason },
            },
          );
        return Response.json(ENDED);
      }
      if (path.endsWith("/recording"))
        return new Response(new Blob(["ID3"], { type: "audio/mpeg" }));
      return Response.json({ detail: "Not here." }, { status: 404 });
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const button = (name: string) =>
  [...host.querySelectorAll("button")].find(
    (node) => node.textContent === name,
  );

it("calls a lead who asked through the company number and offers its recording", async () => {
  await act(async () => root.render(<Harness />));
  await flush();
  expect(seen?.ready).toBe(true);
  await act(async () => button("Call")!.click());
  await flush();
  expect(posts).toHaveLength(1);
  expect(posts[0].url).toBe(`/v1/lead-desk/leads/${LEAD}/calls/company`);
  expect(posts[0].body).toEqual({ commandId: expect.any(String) });
  expect(host.textContent).toContain("Call ended · 1 min 2 s");
  // The ended call's recording goes to the recording panel like one the phone found.
  expect(seen?.found?.name).toMatch(/^Call at /);
  expect(seen?.found?.durationMs).toBe(62_000);
  const file = await seen!.readRecording();
  expect(file.name).toBe("company-call-202610271000.mp3");
  expect(file.type).toBe("audio/mpeg");
});

it("says plainly why the company number can't call, with the seller's own phone one tap away", async () => {
  refuse = {
    status: 409,
    reason: "paused",
    detail: "Company calling is paused for now. Call from your own phone.",
  };
  await act(async () => root.render(<Harness />));
  await flush();
  await act(async () => button("Call")!.click());
  await flush();
  expect(host.textContent).toContain("Company calling is paused for now.");
  const own = host.querySelector<HTMLAnchorElement>('a[href^="tel:"]');
  expect(own?.textContent).toBe("Call from my phone");
  expect(own?.getAttribute("href")).toBe("tel:+919800000002");
  // Refused for this lead: Call is the phone's again.
  expect(seen?.ready).toBe(false);
});

it("leaves Call to the seller's phone for a lead who didn't ask, and checks nothing when it can't call", async () => {
  available = false;
  await act(async () => root.render(<Harness />));
  await flush();
  expect(seen?.ready).toBe(false);
  expect(host.querySelector('[role="status"]')).toBeNull();
  const calls = (fetch as unknown as { mock: { calls: unknown[] } }).mock.calls
    .length;
  await act(async () => root.render(<Harness enabled={false} />));
  await flush();
  expect(seen?.ready).toBe(false);
  expect(
    (fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length,
  ).toBe(calls);
});

it("puts each step of the call in plain words, with no price anywhere", () => {
  const live = (status: CompanyCall["status"]) =>
    callLine({ ...ENDED, status, final: false }, "Asha");
  expect(live("queued")).toBe(
    "Ringing your phone. Pick up, and we'll call Asha.",
  );
  expect(live("ringing")).toBe("Pick up your phone to reach Asha.");
  expect(live("in_progress")).toBe(
    "On the call. Asha sees your company number.",
  );
  expect(
    callLine(
      { ...ENDED, connected: false, words: "They didn't answer." },
      "Asha",
    ),
  ).toBe("They didn't answer.");
  expect(
    callLine(
      {
        ...ENDED,
        status: "no_answer",
        words: "You didn't pick up, so the lead wasn't called.",
      },
      "Asha",
    ),
  ).toContain("You didn't pick up");
});

it("reads a recording that isn't ready as plain words", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json(
        { detail: "The recording isn't ready yet. Try again in a minute." },
        { status: 409 },
      ),
    ),
  );
  await expect(readCompanyRecording(ENDED)).rejects.toThrow("isn't ready yet");
});
