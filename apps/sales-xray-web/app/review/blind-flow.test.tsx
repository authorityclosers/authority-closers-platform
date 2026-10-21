import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { compareTone } from "./blind-flow";
import { ReviewFlow } from "./review-flow";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ASSIGNMENT = "11111111-1111-4111-8111-111111111111";
const REVIEW = "22222222-2222-4222-8222-222222222222";
const OBSERVED = "Fictional: you asked what happens to a lead.";

const DIMENSIONS = [
  {
    id: "D01",
    number: 1,
    label: "Starting the Call",
    category: "how_you_talk",
    category_label: "How You Talk",
    about: "The opening until the call moves into substance.",
    scale: "5 natural and helpful. 4 worked. 3 scripted.",
  },
  {
    id: "D02",
    number: 2,
    label: "Setting the Plan",
    category: "how_you_talk",
    category_label: "How You Talk",
    about: "Orientation around the move into discovery.",
    scale: "5 clear frame. 4 functional. 3 minimal.",
  },
];

function saved(target: string, value: Record<string, unknown>, n: number) {
  return {
    id: `44444444-4444-4444-8444-44444444444${n}`,
    target,
    value,
    supersedes_id: null,
    created_at: "2026-10-21T08:00:00Z",
  };
}

function workspace(rows: unknown[] = [], revealed = false) {
  return {
    mode: "brain4_blind",
    review_id: REVIEW,
    review_status: "blind_brain4_rating",
    lines: [],
    dimensions: DIMENSIONS,
    revealed,
    brain4: revealed
      ? {
          status: "read",
          label: "beta",
          dimensions: [
            {
              id: "D01",
              rating: 4,
              observed: OBSERVED,
              coaching: "On your next relevant call, pause after the price.",
              evidence: [
                {
                  segment_id: "s2",
                  quote: "When do you want to start?",
                  start_ms: 61_000,
                },
              ],
            },
            { id: "D02", rating: null, observed: "Not rated.", coaching: null },
          ],
        }
      : null,
    saved: rows,
    audio_source_url: `/v1/reviewer/review-assignments/${ASSIGNMENT}/source`,
    transcript: {
      segments: [
        {
          id: "s1",
          text: "Hello, thanks for the time.",
          speaker_id: "a",
          start_ms: 0,
        },
        {
          id: "s2",
          text: "When do you want to start?",
          speaker_id: "a",
          start_ms: 61_000,
        },
      ],
    },
    context: {
      recorded_at: "2026-10-21T10:30:00Z",
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
let reads: number;

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
  reads = 0;
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
      reads += 1;
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

async function open() {
  await act(async () => {
    root.render(<ReviewFlow assignmentId={ASSIGNMENT} onFinished={() => {}} />);
  });
  await settle();
}

it("rates blind: no AI answer on screen, each rating saves and moves on", async () => {
  await open();
  expect(host.textContent).toContain("Listen first, then rate");
  expect(host.textContent).toContain("0/2 rated");
  expect(host.textContent).not.toContain(OBSERVED);
  expect(host.textContent).not.toContain("AI draft");
  await act(async () => button("Start rating").click());
  expect(host.textContent).toContain("Starting the Call");
  expect(host.textContent).toContain(
    "The opening until the call moves into substance.",
  );
  expect(host.textContent).toContain("5 natural and helpful.");
  await act(async () => button("3").click());
  await settle();
  expect(posts[0].body).toMatchObject({
    review_id: REVIEW,
    target: "brain4:D01",
    rating: 3,
    supersedes_id: null,
  });
  expect(posts[0].body).not.toHaveProperty("verdict");
  expect(host.textContent).toContain("Setting the Plan");
  // Saving the last rating asks the server again, which then shows Brain 4.0's.
  current = workspace(
    [
      saved("brain4:D01", { rating: 3, blind: true }, 1),
      saved("brain4:D02", { skip: "not_applicable", blind: true }, 2),
    ],
    true,
  );
  const before = reads;
  await act(async () => button("– Didn't come up").click());
  await settle();
  expect(posts[1].body).toMatchObject({
    target: "brain4:D02",
    skip: "not_applicable",
  });
  expect(reads).toBeGreaterThan(before);
  expect(host.textContent).toContain("Your ratings and Brain 4.0's");
  expect(host.textContent).toContain("3 · 4");
  expect(host.textContent).toContain("– · –");
});

it("shows the comparison, locks ratings and marks what Brain 4.0 caught", async () => {
  current = workspace(
    [
      saved("brain4:D01", { rating: 2, blind: true }, 1),
      saved("brain4:D02", { rating: 3, blind: true }, 2),
      saved(
        "moment:01",
        {
          opinion: "Gave the price before asking about the team.",
          moment: { at_ms: 61_000, kind: "criticism", dimension: "D01" },
          blind: true,
        },
        3,
      ),
    ],
    true,
  );
  await open();
  expect(host.textContent).toContain("2 · 4");
  expect(
    host
      .querySelector('[aria-label="You 2, Brain 4.0 4"]')
      ?.getAttribute("data-tone"),
  ).toBe("bad");
  expect(host.textContent).toContain(OBSERVED);
  expect(host.textContent).toContain("pause after the price");
  expect(host.textContent).toContain(
    "did Brain 4.0's coaching catch each one?",
  );
  await act(async () => button("Partly").click());
  await settle();
  expect(posts[0].body).toMatchObject({
    target: "moment:01",
    opinion: "Gave the price before asking about the team.",
    moment: {
      at_ms: 61_000,
      kind: "criticism",
      dimension: "D01",
      caught: "partly",
    },
    supersedes_id: "44444444-4444-4444-8444-444444444443",
  });
  await act(async () => button("Back").click());
  expect(host.textContent).toContain("Locked");
  expect(button("2").disabled).toBe(true);
});

it("notes a moment with its time and kind", async () => {
  await open();
  await act(async () => button("Moment").click());
  const text = host.querySelector<HTMLInputElement>(
    'input[aria-label="What happened at this moment"]',
  )!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(text, "Talked over the buyer at the price.");
    text.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Save moment").click());
  await settle();
  expect(posts[0].body).toMatchObject({
    target: "moment:01",
    opinion: "Talked over the buyer at the price.",
    moment: { at_ms: 0, kind: "criticism" },
  });
  expect(host.textContent).toContain("Would correct");
});

it("compares ratings by distance", () => {
  expect(compareTone(3, 3)).toBe("good");
  expect(compareTone(3, 4)).toBe("warn");
  expect(compareTone(2, 4)).toBe("bad");
  expect(compareTone(null, 4)).toBe("warn");
  expect(compareTone(null, null)).toBe("good");
});
