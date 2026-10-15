import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CallSummary, ProgressPoint } from "./coaching-client";
import { CallsOpenReports, TheirCoaching } from "./coaching-voice";
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

const point = (
  day: number,
  state: ProgressPoint["state"] = "suggested",
): ProgressPoint => ({
  submission_id: call(day).submission_id,
  created_at: call(day).created_at,
  state,
  after_mission: false,
});

const links = (html: string) => {
  const host = document.createElement("div");
  host.innerHTML = html;
  return [...host.querySelectorAll("a")].map((a) => a.getAttribute("href"));
};

const marks = (html: string) => {
  const host = document.createElement("div");
  host.innerHTML = html;
  return [...host.querySelectorAll("[data-state]")].map((mark) => [
    mark.getAttribute("data-state"),
    mark.textContent,
  ]);
};

/** A real rep who shared: labels say "their", and only Reports open. */
const shared = (node: React.ReactNode) =>
  renderToStaticMarkup(
    <TheirCoaching.Provider value>
      <CallsOpenReports.Provider value>{node}</CallsOpenReports.Provider>
    </TheirCoaching.Provider>,
  );

/** A fictional Sandbox rep: "their" labels, their call coaching may open. */
const sandbox = (node: React.ReactNode) =>
  renderToStaticMarkup(
    <TheirCoaching.Provider value>{node}</TheirCoaching.Provider>,
  );

describe("latest call shortcuts", () => {
  it("opens the newest ready report, even when newer calls are pending or unavailable", () => {
    const newest = call(9);
    const html = shared(
      <RepCallLinks
        calls={[call(8), call(11, "pending"), newest, call(10, "unavailable")]}
      />,
    );
    expect(html).toContain("Fictional call 9");
    expect(html).toContain("9 Oct 2026");
    expect(html).toContain("See calls");
    expect(html).toContain('aria-label="This rep’s calls"');
    expect(links(html)).toEqual([
      `/analysis/calls/${newest.submission_id}`,
      "#coaching-calls",
    ]);
    // Real shared-rep coaching never links to its private per-call Coaching API.
    expect(html).not.toContain("/coaching?call=");
  });

  it("also offers the existing call-coaching route for fictional Sandbox calls", () => {
    const latest = call(9);
    const html = sandbox(<RepCallLinks calls={[latest]} />);
    expect(links(html)).toEqual([
      `/analysis/calls/${latest.submission_id}`,
      `/coaching?call=${latest.submission_id}`,
      "#coaching-calls",
    ]);
    expect(html).toContain("See calls");
  });

  it("gives the rep their own latest call's Report and coaching from pillar 1", () => {
    const latest = call(9);
    const html = renderToStaticMarkup(
      <RepCallLinks calls={[call(8), latest]} />,
    );
    expect(html).toContain('aria-label="Your latest call"');
    expect(html).toContain("Latest call with coaching");
    expect(links(html)).toEqual([
      `/analysis/calls/${latest.submission_id}`,
      `/coaching?call=${latest.submission_id}`,
      "#coaching-calls",
    ]);
  });

  it("marks the latest call's saved record on the current focus like the progress history", () => {
    const latest = call(9);
    const needed = renderToStaticMarkup(
      <RepCallLinks
        calls={[call(8), latest]}
        progress={[point(8, "no_suggestion"), point(9)]}
      />,
    );
    expect(marks(needed)).toEqual([["suggested", "Needed work"]]);
    const clean = renderToStaticMarkup(
      <RepCallLinks calls={[latest]} progress={[point(9, "no_suggestion")]} />,
    );
    expect(marks(clean)).toEqual([
      ["no_suggestion", "Skill used, nothing to fix"],
    ]);
    // No record, a record for another call, or "Didn't come up": no mark.
    expect(
      marks(renderToStaticMarkup(<RepCallLinks calls={[latest]} />)),
    ).toEqual([]);
    expect(
      marks(
        renderToStaticMarkup(
          <RepCallLinks calls={[call(8), latest]} progress={[point(8)]} />,
        ),
      ),
    ).toEqual([]);
    expect(
      marks(
        renderToStaticMarkup(
          <RepCallLinks
            calls={[latest]}
            progress={[point(9, "not_covered")]}
          />,
        ),
      ),
    ).toEqual([]);
    expect(
      renderToStaticMarkup(
        <RepCallLinks calls={[latest]} progress={[point(9)]} />,
      ),
    ).not.toContain("Didn’t come up");
  });

  it("keeps pending calls reachable without inventing a ready report or coaching", () => {
    const html = sandbox(<RepCallLinks calls={[call(9, "pending")]} />);
    expect(links(html)).toEqual(["#coaching-calls"]);
    expect(html).not.toContain("Latest call with coaching");
    expect(renderToStaticMarkup(<RepCallLinks />)).toBe("");
    expect(renderToStaticMarkup(<RepCallLinks calls={[]} />)).toBe("");
  });
});
