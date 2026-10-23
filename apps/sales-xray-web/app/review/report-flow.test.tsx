import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { canSave, saveOf, type Draft } from "./report-flow";
import type { ReportItem } from "./review-client";
import { ReviewFlow } from "./review-flow";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ASSIGNMENT = "11111111-1111-4111-8111-111111111111";
const REVIEW = "22222222-2222-4222-8222-222222222222";

const SKILL: ReportItem = {
  id: "brain4.D01",
  section: "brain4",
  label: "Starting the Call",
  kind: "rating",
  number: 1,
  rating: 4,
  text: "Fictional: you opened warmly.",
  detail: "Ask what made them call.",
  evidence: [
    { segment_id: "s2", quote: "What made you call today?", start_ms: 61_000 },
  ],
};
const SECOND: ReportItem = {
  ...SKILL,
  id: "brain4.D02",
  label: "Setting the Plan",
  number: 2,
  rating: 3,
  evidence: [],
};
const SUMMARY: ReportItem = {
  id: "overview.summary",
  section: "overview",
  label: "Summary",
  kind: "text",
  rating: null,
  text: "Fictional: a first call about lead follow-up.",
  detail: null,
  evidence: [],
};
// A section no code knows about still shows (the server names it).
const RISK: ReportItem = {
  id: "deal_risks.whole",
  section: "deal_risks",
  label: "Deal risks",
  kind: "text",
  rating: null,
  text: "Partner may say no.",
  detail: null,
  evidence: [],
};

function saved(target: string, value: Record<string, unknown>, n: number) {
  return {
    id: `44444444-4444-4444-8444-44444444444${n}`,
    target,
    value,
    supersedes_id: null,
    created_at: "2026-10-23T08:00:00Z",
  };
}

function workspace(rows: unknown[] = []) {
  return {
    mode: "report",
    review_id: REVIEW,
    review_status: "report_review",
    lines: [],
    sections: [
      { id: "brain4", label: "AI coaching score", items: [SKILL, SECOND] },
      { id: "overview", label: "Overview", items: [SUMMARY] },
      { id: "deal_risks", label: "Deal risks", items: [RISK] },
    ],
    schema: {
      structure: "report-structure/1",
      registry: "review-schema/1",
      digest: "0123456789abcdef",
    },
    route: { review: "automatic:one-pass-plan:x", brain4: "shadow:x" },
    saved: rows,
    audio_source_url: `/v1/reviewer/review-assignments/${ASSIGNMENT}/source`,
    transcript: {
      segments: [
        { id: "s1", text: "Hello.", speaker_id: "a", start_ms: 0 },
        {
          id: "s2",
          text: "What made you call today?",
          speaker_id: "a",
          start_ms: 61_000,
        },
      ],
    },
    context: {
      recorded_at: "2026-10-23T10:30:00Z",
      duration_ms: 900_000,
      summary: null,
      verdict: null,
    },
  };
}

let root: Root;
let host: HTMLDivElement;
let posts: { body: Record<string, unknown> }[];
let current: ReturnType<typeof workspace>;

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
  current = workspace();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        posts.push({ body });
        const value: Record<string, unknown> = { ...body };
        for (const key of ["review_id", "target", "supersedes_id"])
          delete value[key];
        return respond(
          {
            ...saved(String(body.target), value, posts.length),
            supersedes_id: body.supersedes_id ?? null,
          },
          201,
        );
      }
      return respond(current);
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
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
  });
}

function button(name: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((element) =>
    element.textContent?.trim().startsWith(name),
  );
  if (!found) throw new Error(`no button ${name}`);
  return found;
}

function type(label: string, value: string) {
  const field = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(
    `[aria-label="${label}"]`,
  );
  if (!field) throw new Error(`no field ${label}`);
  const proto =
    field instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

async function open() {
  await act(async () => {
    root.render(<ReviewFlow assignmentId={ASSIGNMENT} onFinished={() => {}} />);
  });
  await settle();
}

it("agrees in one tap, fixes a rating, and shows a section no code knows", async () => {
  await open();
  expect(host.textContent).toContain("Starting the Call");
  expect(host.textContent).toContain("AI rating");
  expect(host.textContent).toContain("Ask what made them call.");
  expect(host.textContent).toContain("0/4 done");
  expect(host.textContent).toContain("Deal risks 0/1");
  await act(async () => button("Agree").click());
  await settle();
  expect(posts[0].body).toMatchObject({
    review_id: REVIEW,
    target: "item:brain4.D01",
    verdict: "agree",
    supersedes_id: null,
  });
  expect(posts[0].body).not.toHaveProperty("rating");
  expect(posts[0].body).not.toHaveProperty("correction");
  expect(host.textContent).toContain("Setting the Plan");
  // Fix on a rated item: Save waits for the right rating.
  await act(async () => button("Fix").click());
  expect(host.textContent).toContain("The right rating (AI: 3)");
  expect(button("Save").disabled).toBe(true);
  await act(async () => button("2").click());
  await act(async () => type("A short note (optional)", "Too generous."));
  await act(async () => button("Save").click());
  await settle();
  expect(posts[1].body).toMatchObject({
    target: "item:brain4.D02",
    verdict: "fix",
    rating: 2,
    opinion: "Too generous.",
  });
  // Fix on a written item needs the right words.
  expect(host.textContent).toContain("Fictional: a first call");
  await act(async () => button("Fix").click());
  expect(host.textContent).not.toContain("The right rating");
  expect(button("Save").disabled).toBe(true);
  await act(async () => type("What it should say", "A second call."));
  await act(async () => button("Save").click());
  await settle();
  expect(posts[2].body).toMatchObject({
    target: "item:overview.summary",
    verdict: "fix",
    correction: "A second call.",
  });
  expect(posts[2].body).not.toHaveProperty("rating");
  expect(host.textContent).toContain("Partner may say no.");
  await act(async () => button("Disagree").click());
  await act(async () => button("Save").click());
  await settle();
  expect(posts[3].body).toMatchObject({
    target: "item:deal_risks.whole",
    verdict: "disagree",
  });
  expect(host.textContent).toContain("This call's Report is reviewed");
  expect(host.textContent).toContain("1 agreed · 1 disagreed · 2 fixed");
});

it("resumes at the first open item, jumps by section and skips with a reason", async () => {
  current = workspace([
    saved("item:brain4.D01", { verdict: "agree" }, 1),
    saved("item:brain4.D02", { verdict: "fix", rating: 2 }, 2),
  ]);
  await open();
  expect(host.textContent).toContain("2/4 done");
  expect(host.textContent).toContain("Fictional: a first call");
  await act(async () => button("AI coaching score").click());
  expect(host.textContent).toContain("Starting the Call");
  expect(host.textContent).toContain("Agreed");
  // Keys for desktop: 1 agrees; an unchanged answer is not saved again.
  await act(async () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "1" }));
  });
  await settle();
  expect(posts).toHaveLength(0);
  expect(host.textContent).toContain("Setting the Plan");
  await act(async () => button("Skip").click());
  await act(async () => button("Audio unclear").click());
  await settle();
  expect(posts[0].body).toMatchObject({
    target: "item:brain4.D02",
    skip: "audio_unclear",
    supersedes_id: "44444444-4444-4444-8444-444444444442",
  });
  expect(posts[0].body).not.toHaveProperty("verdict");
});

it("sends only what each verdict carries", () => {
  const draft: Draft = {
    verdict: null,
    rating: null,
    correction: "",
    note: "",
  };
  expect(canSave(draft, SKILL)).toBe(false);
  expect(canSave({ ...draft, verdict: "agree" }, SKILL)).toBe(true);
  expect(canSave({ ...draft, verdict: "fix" }, SKILL)).toBe(false);
  expect(canSave({ ...draft, verdict: "fix", rating: 5 }, SKILL)).toBe(true);
  expect(canSave({ ...draft, verdict: "fix", rating: 5 }, SUMMARY)).toBe(false);
  expect(
    saveOf({ verdict: "agree", rating: 2, correction: "x", note: "y" }, SKILL),
  ).toEqual({ verdict: "agree" });
  expect(
    saveOf(
      { verdict: "fix", rating: 2, correction: " ok ", note: "" },
      SUMMARY,
    ),
  ).toEqual({ verdict: "fix", correction: "ok" });
});
