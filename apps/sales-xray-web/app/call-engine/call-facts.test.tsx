import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { LeadDetail } from "../leads/leads-client";
import type { Fact, LeadFacts, Question } from "./call-data-client";
import { CallFacts } from "./call-facts";
import {
  basisLabel,
  clock,
  editedValue,
  groupFacts,
  numericFromText,
  questionText,
} from "./call-facts-model";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const evidence = {
  segment_id: "s3",
  quote: "Hamari team aath logon ki hai.",
  start_ms: 9100,
  end_ms: 15000,
  speaker: "speaker_1",
  role: "prospect" as const,
};

function fact(changes: Partial<Fact> = {}): Fact {
  return {
    object_id: "o1",
    type: "need.primary_pain",
    category: "need",
    label: "Biggest problem",
    kind: "text",
    value: { text: "All sales depend on Amit" },
    display: "All sales depend on Amit",
    confidence: 0.8,
    basis: "observed",
    status: "asked",
    ai_read: false,
    evidence: [evidence],
    call: {
      recording_id: "r1",
      submission_id: "c1",
      at: "2026-10-19T05:00:00Z",
    },
    source: {
      pipeline: "fast",
      version: "fast/1",
      taxonomy_version: "call-taxonomy/1",
    },
    ...changes,
  };
}

function question(changes: Partial<Question> = {}): Question {
  return {
    ...fact(),
    question: "confirm",
    lead_field: null,
    lead_value: null,
    ...changes,
  };
}

function view(questions: Question[], facts: Fact[] = []): LeadFacts {
  return {
    schema: "call-data-lead/1",
    lead_id: "l1",
    taxonomy_version: "call-taxonomy/1",
    pipelines: {
      fast: { state: "done", at: "2026-10-19T05:01:00Z" },
      deep: { state: "not_started", at: null },
    },
    questions,
    facts,
    filled: [
      {
        field: "name",
        value: "Amit Sharma",
        object_id: "o9",
        at: "2026-10-19T05:01:00Z",
      },
    ],
    categories: { people: "People", need: "Needs and goals" },
  };
}

const detail = {
  lead: { lead_id: "l1", calls: 1, revision: 3 },
  events: [{ kind: "call", at: "2026-10-19T05:00:00Z", submission_id: "c1" }],
} as unknown as LeadDetail;

it("speaks plainly about each fact and its question", () => {
  expect(clock(75_400)).toBe("1:15");
  expect(basisLabel(fact({ basis: "confirmed" }))).toBe("You confirmed");
  expect(basisLabel(fact({ ai_read: true }))).toBe("AI read");
  expect(basisLabel(fact({ status: "auto_filled" }))).toBe(
    "Filled from the call",
  );
  expect(
    questionText(question({ question: "replace", lead_value: "XYZ Media" })),
  ).toBe("The lead says “XYZ Media”. Use what the call says?");
  expect(questionText(question({ question: "fill", lead_field: "city" }))).toBe(
    "Add to the lead as City?",
  );
  const groups = groupFacts(
    [fact({ category: "need" }), fact({ object_id: "o2", category: "people" })],
    { people: "People", need: "Needs and goals" },
  );
  expect(groups.map((g) => g.label)).toEqual(["People", "Needs and goals"]);
});

it("turns a seller's words into the fact's typed value", () => {
  expect(numericFromText("4-5 lakh a month")).toMatchObject({
    interval_shape: "range",
    lower: "400000",
    upper: "500000",
    currency_code: "INR",
    period: "month",
  });
  expect(numericFromText("8", { unit: "people" })).toMatchObject({
    interval_shape: "point",
    lower: "8",
    unit: "people",
  });
  expect(numericFromText("no numbers here")).toBeNull();
  const when = editedValue(
    fact({
      kind: "when",
      value: { text: "Friday 4 PM", date: "2026-10-23", time: "16:00" },
    }),
    "Monday morning",
  );
  expect(when).toEqual({ text: "Monday morning" });
  expect(editedValue(fact(), "  ")).toBeNull();
  expect(
    editedValue(
      fact({ kind: "person", value: { name: "Raj", role: "partner" } }),
      "Rajesh",
    ),
  ).toEqual({ name: "Rajesh", role: "partner" });
});

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("asks one question at a time and saves the answer", async () => {
  const calls: { url: string; body?: unknown }[] = [];
  const first = view([
    question(),
    question({ object_id: "o3", label: "Next follow-up" }),
  ]);
  const after = view([question({ object_id: "o3", label: "Next follow-up" })]);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const body = url.includes("/decision") ? after : first;
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  await act(async () => {
    root.render(<CallFacts detail={detail} onChanged={() => undefined} />);
  });
  expect(host.textContent).toContain("From the calls");
  expect(host.textContent).toContain("Filled in for you: Name Amit Sharma");
  expect(host.textContent).toContain("Check 1 of 2");
  expect(host.textContent).toContain("All sales depend on Amit");
  expect(host.textContent).toContain("Prospect · 0:09");
  const keep = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("Yes, keep"),
  );
  await act(async () => {
    keep?.click();
  });
  const decision = calls.find((c) => c.url.includes("/objects/o1/decision"));
  expect(decision?.body).toMatchObject({ decision: "accepted" });
  expect(host.textContent).toContain("Check 2 of 2");
  expect(host.textContent).toContain("Next follow-up");
});

it("shows nothing when no call has been read", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ ...view([]), filled: [] }), {
          status: 200,
        }),
    ),
  );
  await act(async () => {
    root.render(
      <CallFacts
        detail={{ ...detail, events: [] } as unknown as LeadDetail}
        onChanged={() => undefined}
      />,
    );
  });
  expect(host.textContent).toBe("");
});
