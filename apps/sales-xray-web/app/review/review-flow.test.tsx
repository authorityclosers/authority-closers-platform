import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { saveLine } from "./review-client";
import { ReviewFlow } from "./review-flow";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ASSIGNMENT = "11111111-1111-4111-8111-111111111111";
const REVIEW = "22222222-2222-4222-8222-222222222222";

function workspace(saved: unknown[] = []) {
  const pointers = Array.from({ length: 27 }, (_, i) => ({
    id: `pointer-${i + 1}`,
    number: i + 1,
    label: `Fictional skill ${i + 1}`,
    status: "good",
    score: 72,
    what_happened: "The seller asked about timing.",
    evidence: [
      {
        quote: "When do you want to start?",
        start_ms: 61_000,
        segment_id: "s2",
      },
    ],
  }));
  return {
    review_id: REVIEW,
    review_status: "ai_draft_not_dipak_reviewed",
    lines: [
      ...pointers.map((p) => ({
        target: p.id,
        label: `${p.number}. ${p.label}`,
        ai: p,
      })),
      {
        target: "final_call_outcome",
        label: "Final Call Outcome",
        ai: { notes: ["Call back Friday."] },
      },
      { target: "coaching", label: "Coaching", ai: [] },
    ],
    saved,
    audio_source_url: `/v1/sales-xray/review/assignments/${ASSIGNMENT}/source`,
    transcript: {
      segments: [
        {
          id: "s1",
          text: "Hello, thanks for the time.",
          speaker_id: "spk_a",
          start_ms: 0,
        },
        {
          id: "s2",
          text: "When do you want to start?",
          speaker_id: "spk_a",
          start_ms: 61_000,
        },
        {
          id: "s3",
          text: "Next month, maybe.",
          speaker_id: "spk_b",
          start_ms: 64_000,
        },
      ],
    },
    context: {
      recorded_at: "2026-10-18T10:30:00Z",
      duration_ms: 240_000,
      summary: "A fictional discovery call.",
      verdict: null,
    },
  };
}

let root: Root;
let host: HTMLDivElement;
let posts: { url: string; body: Record<string, unknown>; key: string | null }[];

function respond(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

beforeEach(() => {
  posts = [];
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        posts.push({
          url,
          body,
          key: new Headers(init.headers).get("idempotency-key"),
        });
        return respond(
          {
            id: `33333333-3333-4333-8333-33333333333${posts.length}`,
            target: body.target,
            value: {
              verdict: body.verdict ?? null,
              score: body.score ?? null,
              opinion: "",
            },
            supersedes_id: body.supersedes_id ?? null,
            created_at: "2026-10-19T08:00:00Z",
          },
          201,
        );
      }
      return respond(workspace());
    }),
  );
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

function button(name: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((element) =>
    element.textContent?.trim().startsWith(name),
  );
  if (!found) throw new Error(`no button ${name}`);
  return found;
}

it("shows the AI draft with its evidence, and Agree saves and moves on", async () => {
  await act(async () => {
    root.render(<ReviewFlow assignmentId={ASSIGNMENT} onFinished={() => {}} />);
  });
  await settle();
  expect(host.textContent).toContain("Fictional skill 1");
  expect(host.textContent).toContain("AI draft");
  expect(host.textContent).toContain("When do you want to start?");
  expect(host.textContent).toContain("Next month, maybe.");
  expect(host.textContent).toContain("1/29");
  await act(async () => button("Agree").click());
  await settle();
  expect(posts).toHaveLength(1);
  expect(posts[0].url).toBe(
    `/v1/sales-xray/review/assignments/${ASSIGNMENT}/lines`,
  );
  expect(posts[0].body).toMatchObject({
    review_id: REVIEW,
    target: "pointer-1",
    verdict: "agree",
    supersedes_id: null,
  });
  expect(posts[0].body).not.toHaveProperty("opinion");
  expect(posts[0].key).toBeTruthy();
  expect(host.textContent).toContain("Fictional skill 2");
  expect(host.textContent).toContain("1 done");
});

it("Partly asks for the right status, score and reasons before saving", async () => {
  await act(async () => {
    root.render(<ReviewFlow assignmentId={ASSIGNMENT} onFinished={() => {}} />);
  });
  await settle();
  await act(async () => button("Partly").click());
  expect(posts).toHaveLength(0);
  await act(async () => button("Average").click());
  await act(async () => button("Too generous").click());
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Five points lower"]')!
      .click(),
  );
  await act(async () => button("Save & next").click());
  await settle();
  expect(posts[0].body).toMatchObject({
    target: "pointer-1",
    verdict: "partly",
    status: "average",
    score: 67,
    reasons: ["too_generous"],
  });
  expect(host.textContent).toContain("Fictional skill 2");
});

it("Skip asks why and saves a skip, not a judgement", async () => {
  await act(async () => {
    root.render(<ReviewFlow assignmentId={ASSIGNMENT} onFinished={() => {}} />);
  });
  await settle();
  await act(async () => button("Skip").click());
  await act(async () => button("Audio unclear").click());
  await settle();
  expect(posts[0].body).toMatchObject({
    target: "pointer-1",
    skip: "audio_unclear",
  });
  expect(posts[0].body).not.toHaveProperty("verdict");
});

it("leaves out empty fields when saving", async () => {
  await saveLine(
    ASSIGNMENT,
    REVIEW,
    "coaching",
    { verdict: "agree", opinion: "", reasons: [] },
    null,
    "k",
  );
  expect(posts[0].body).toEqual({
    review_id: REVIEW,
    target: "coaching",
    supersedes_id: null,
    verdict: "agree",
    reasons: [],
  });
});
