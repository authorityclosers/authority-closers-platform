import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CallSummary } from "./coaching-client";
import { RepCallLinks } from "./rep-call-links";

const call = (
  day: number,
  state: CallSummary["state"] = "ready",
): CallSummary => ({
  submission_id: `00000000-0000-4000-8000-${String(day).padStart(12, "0")}`,
  call_label: `Fictional call ${day}`,
  created_at: `2026-10-${String(day).padStart(2, "0")}T10:00:00Z`,
  state,
  focus_label: null,
});

const links = (html: string) => {
  const host = document.createElement("div");
  host.innerHTML = html;
  return [...host.querySelectorAll("a")].map((a) => a.getAttribute("href"));
};

describe("rep call shortcuts", () => {
  it("opens the newest ready report, even when newer calls are pending or unavailable", () => {
    const newest = call(9);
    const html = renderToStaticMarkup(
      <RepCallLinks
        calls={[call(8), call(11, "pending"), newest, call(10, "unavailable")]}
      />,
    );
    expect(html).toContain("Fictional call 9");
    expect(html).toContain("9 Oct 2026");
    expect(html).toContain("See calls");
    expect(links(html)).toEqual([
      `/analysis/calls/${newest.submission_id}`,
      "#coaching-calls",
    ]);
    // Real shared-rep coaching never links to its private per-call Coaching API.
    expect(html).not.toContain("/coaching?call=");
  });

  it("also offers the existing call-coaching route for fictional Sandbox calls", () => {
    const latest = call(9);
    const html = renderToStaticMarkup(
      <RepCallLinks calls={[latest]} sandbox />,
    );
    expect(links(html)).toEqual([
      `/analysis/calls/${latest.submission_id}`,
      `/coaching?call=${latest.submission_id}`,
      "#coaching-calls",
    ]);
    expect(html).toContain("See calls");
  });

  it("keeps pending calls reachable without inventing a ready report or coaching", () => {
    const html = renderToStaticMarkup(
      <RepCallLinks calls={[call(9, "pending")]} sandbox />,
    );
    expect(links(html)).toEqual(["#coaching-calls"]);
    expect(html).not.toContain("Latest call with coaching");
    expect(renderToStaticMarkup(<RepCallLinks />)).toBe("");
    expect(renderToStaticMarkup(<RepCallLinks calls={[]} />)).toBe("");
  });
});
