/** Per call: sortable, each call opens to its steps, free calls apart (19 Oct 2026). */
import type { AnchorHTMLAttributes } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

import { costQuery, normalizeMetrics, zeroReason } from "./cost-data";
import { CallsView } from "./cost-views";

vi.mock("next/link", () => ({
  default: (
    props: AnchorHTMLAttributes<HTMLAnchorElement> & { scroll?: boolean },
  ) => {
    const anchor = { ...props };
    delete anchor.scroll;
    return <a {...anchor} />;
  },
}));

const step = (stage: string, extra: Record<string, unknown> = {}) => ({
  stage,
  provider: stage === "C2" ? "elevenlabs" : "gemini",
  model: stage === "C2" ? "scribe_v2" : "gemini-3.8-flash",
  status: "succeeded",
  attempts: 1,
  input_tokens: stage === "C2" ? 0 : 1000,
  output_tokens: stage === "C2" ? 0 : 200,
  audio_minutes: stage === "C2" ? 10 : null,
  elapsed_ms: 20_000,
  rupees: stage === "C2" ? 3.67 : 0.15,
  at: "2026-10-18T10:00:00+00:00",
  ...extra,
});

const metrics = normalizeMetrics({
  here: "development",
  calls: {
    total: 1,
    sort: "cost",
    rows: [
      {
        environment: "development",
        id: "call-1",
        company: "Northwind Rooftops",
        kind: "real",
        at: "2026-10-18T10:00:00+00:00",
        audio_minutes: 10,
        stages: {
          C2: { rupees: 3.67, runs: 1 },
          C5: { rupees: 0.15, runs: 2 },
        },
        rupees: 3.82,
        per_minute: 0.38,
        billed_minutes: 10,
        report: true,
        report_ms: 52_000,
        tokens: 1200,
        models: ["gemini-3.8-flash", "scribe_v2"],
        statuses: { succeeded: 2 },
        steps: [step("C2"), step("C5", { attempts: 2, rupees: null })],
      },
    ],
    zero_total: 1,
    zero_rows: [
      {
        environment: "staging",
        id: "call-2",
        company: "Personal accounts",
        at: "2026-10-18T09:00:00+00:00",
        audio_minutes: 3,
        rupees: 0,
        statuses: { dead_letter: 1 },
      },
    ],
  },
});
const current = { tab: "calls", days: "30", env: "all", tests: false };

it("lists each call with its stage costs and opens it to every step", () => {
  const html = renderToStaticMarkup(
    <CallsView metrics={metrics} current={{ ...current, sort: "cost" }} />,
  );
  expect(html).toContain("1 call with a cost");
  expect(html).toContain("Northwind Rooftops");
  expect(html).toContain("gemini-3.8-flash · scribe_v2");
  expect(html).toContain("<details");
  expect(html).toContain("Provider and model");
  expect(html).toContain("elevenlabs");
  expect(html).toContain("no price"); // an unpriced step says so
  expect(html).toContain('href="/calls/call-1"'); // this Admin's own call opens
});

it("sorts by link and keeps calls that cost nothing apart", () => {
  const html = renderToStaticMarkup(
    <CallsView metrics={metrics} current={{ ...current, sort: "cost" }} />,
  );
  expect(html).toContain('href="/usage?tab=calls&amp;sort=tokens"');
  expect(html).toContain('href="/usage?tab=calls"'); // newest is the default
  expect(html).toContain("1 call cost nothing");
  expect(html).toContain("1 step failed before any paid work");
  expect(costQuery({ ...current, sort: "audio" }, { days: "7" })).toBe(
    "/usage?tab=calls&days=7&sort=audio",
  );
  expect(zeroReason({ succeeded: 2 })).toBe(
    "its finished steps have no price on the price sheet yet",
  );
  expect(zeroReason({ queued: 1 })).toBe("1 step hasn't finished");
  expect(zeroReason({})).toBe("no provider step ran");
});
