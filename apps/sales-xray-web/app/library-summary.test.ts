import { afterEach, expect, it, vi } from "vitest";

import { parseSubmissionLibraryPage } from "./acquisition-client";
import { forgetCalls, identityOf, readCallsList } from "./calls-cache";
import {
  insightFromSummary,
  needsOwnRead,
  SUMMARY_OUTCOMES,
} from "./call-summary";
import { OUTCOME_LABEL } from "./calls-insights";

afterEach(() => {
  forgetCalls();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const ID = "0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10";
const row = (extra: Record<string, unknown> = {}) => ({
  submission_id: ID,
  created_at: "2026-10-20T09:00:00Z",
  duration_seconds: 240,
  state: "complete",
  has_report: true,
  ...extra,
});
const page = (extra?: Record<string, unknown>) => ({
  submissions: [row(extra)],
  next_cursor: null,
});

it("reads a row's Report facts from the list (include_summary=true)", () => {
  const [call] = parseSubmissionLibraryPage(
    page({
      summary: {
        outcome: "follow_up",
        assessment: "Clear discovery, no agreed next step.",
        fix_first: "Ask for the next meeting",
        next_focus: "Budget",
        strengths: 3,
        missed: 1,
      },
    }),
  ).submissions;
  expect(call.summary).toEqual({
    outcome: "follow_up",
    assessment: "Clear discovery, no agreed next step.",
    fixFirst: "Ask for the next meeting",
    nextFocus: "Budget",
    strengths: 3,
    missed: 1,
  });
  expect(needsOwnRead(call)).toBe(false);
  // Null: no readable Report. Absent: a server that sends no summaries.
  expect(
    parseSubmissionLibraryPage(page({ summary: null })).submissions[0].summary,
  ).toBeNull();
  const old = parseSubmissionLibraryPage(page()).submissions[0];
  expect("summary" in old).toBe(false);
  expect(needsOwnRead(old)).toBe(true);
});

it("refuses a summary of the wrong shape", () => {
  for (const summary of [
    { outcome: "follow_up", extra: 1 },
    { assessment: 4 },
    { strengths: -1 },
    { missed: 1.5 },
    "follow_up",
  ])
    expect(() => parseSubmissionLibraryPage(page({ summary }))).toThrow();
});

it("turns a summary into the row's insight, an unknown outcome into none", () => {
  const insight = insightFromSummary({
    outcome: "closed",
    assessment: "Won on the call.",
    fixFirst: null,
    nextFocus: "Onboarding",
    strengths: 4,
    missed: 0,
  });
  expect(insight).toMatchObject({
    outcome: "closed",
    assessment: "Won on the call.",
    nextFocus: "Onboarding",
    strengths: 4,
    missed: 0,
    durationMs: null,
    moments: [],
  });
  expect(
    insightFromSummary({
      outcome: "something_new",
      assessment: null,
      fixFirst: null,
      nextFocus: null,
      strengths: null,
      missed: null,
    }).outcome,
  ).toBeNull();
});

it("reads an identity's list once however many ask at the same moment", async () => {
  vi.stubEnv("NODE_ENV", "production");
  let answer: (response: Response) => void = () => {};
  const fetcher = vi.fn<typeof fetch>(
    () => new Promise<Response>((resolve) => (answer = resolve)),
  );
  vi.stubGlobal("fetch", fetcher);
  const identity = identityOf({ personId: "p", sessionId: "s", tenantId: "t" });
  const leaving = new AbortController();
  const calls = readCallsList(identity);
  const home = readCallsList(identity, leaving.signal);
  // One caller gives up; the shared read goes on for the other.
  leaving.abort();
  await expect(home).rejects.toThrow();
  answer(Response.json(page()));
  expect((await calls).submissions[0].id).toBe(ID);
  expect(fetcher).toHaveBeenCalledOnce();
  expect(String(fetcher.mock.calls[0][0])).toContain("include_summary=true");
});

it("knows every outcome the Report names", () => {
  expect([...SUMMARY_OUTCOMES].sort()).toEqual(
    Object.keys(OUTCOME_LABEL).sort(),
  );
});
