import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CallsPanel } from "./calls-panel";
import type { CallSummary, ProgressPoint } from "./coaching-client";
import { CallsOpenReports, TheirCoaching } from "./coaching-voice";

const call = (
  id: number,
  state: CallSummary["state"] = "ready",
): CallSummary => ({
  submission_id: `00000000-0000-4000-8000-${String(id).padStart(12, "0")}`,
  call_label: `Fictional call ${id}`,
  created_at: "2026-10-01T10:00:00Z",
  state,
  focus_label: "Same words as the current focus",
  recurring: true,
});
const point = (id: number, state: ProgressPoint["state"]): ProgressPoint => ({
  submission_id: call(id).submission_id,
  created_at: call(id).created_at,
  state,
  after_mission: true,
});
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
const button = (name: string) =>
  [...host.querySelectorAll("button")].find(
    (control) => control.textContent === name,
  )!;
const links = () => [...host.querySelectorAll<HTMLAnchorElement>("li a")];

describe("calls on the current skill", () => {
  it("uses saved progress, excludes no-opportunity/unready/missing calls and preserves shared Report links", async () => {
    await act(async () =>
      root.render(
        <TheirCoaching.Provider value>
          <CallsOpenReports.Provider value>
            <CallsPanel
              calls={[
                { ...call(1), focus_label: "Another call focus" },
                call(2),
                call(3),
                call(4),
                call(5, "pending"),
                call(6, "unavailable"),
              ]}
              focusLabel="Explore the consequence"
              progress={[
                point(1, "suggested"),
                point(2, "no_suggestion"),
                point(3, "not_covered"),
                point(5, "suggested"),
                point(6, "no_suggestion"),
                point(99, "suggested"),
              ]}
            />
          </CallsOpenReports.Provider>
        </TheirCoaching.Provider>,
      ),
    );
    expect(links()).toHaveLength(6);
    expect(button("All calls").getAttribute("aria-pressed")).toBe("true");
    expect(host.textContent).toContain("Analysing…");
    expect(host.textContent).toContain("Report couldn’t be read");
    await act(async () => button("On this skill").click());
    expect(button("On this skill").getAttribute("aria-pressed")).toBe("true");
    expect(button("All calls").getAttribute("aria-pressed")).toBe("false");
    expect(host.querySelector('[role="status"]')?.textContent).toBe("2 calls");
    expect(links().map((link) => link.getAttribute("href"))).toEqual([
      `/analysis/calls/${call(1).submission_id}`,
      `/analysis/calls/${call(2).submission_id}`,
    ]);
    const rows = [...host.querySelectorAll("li")];
    expect(rows[0].textContent).toContain("Needed work");
    expect(rows[1].textContent).toContain("Skill used, nothing to fix");
    expect(host.textContent).not.toContain("Also on other calls");
    expect(host.textContent).not.toContain("Fictional call 99");
    expect(
      host.querySelector('[aria-label="Their recent calls"]'),
    ).not.toBeNull();
    await act(async () => button("All calls").click());
    expect(links()).toHaveLength(6);
    expect(host.textContent).toContain("Another call focus");
    expect(host.textContent).toContain("Analysing…");
  });

  it("keeps call destinations, collapses without losing the filter and resets expansion when it changes", async () => {
    await act(async () =>
      root.render(
        <CallsPanel
          calls={Array.from({ length: 10 }, (_, index) => call(index + 1))}
          focusLabel="Explore the consequence"
          progress={Array.from({ length: 4 }, (_, index) =>
            point(index + 1, "suggested"),
          )}
        />,
      ),
    );
    const list = host.querySelector('[aria-label="Your recent calls"]')!;
    await act(async () => button("Show all 10 calls").click());
    expect(list.parentElement!.hasAttribute("data-expanded")).toBe(true);
    await act(async () => button("On this skill").click());
    expect(list.parentElement!.hasAttribute("data-expanded")).toBe(false);
    expect(links()).toHaveLength(4);
    expect(links()[0].getAttribute("href")).toBe(
      `/coaching?call=${call(1).submission_id}`,
    );
    expect(button("Show all 4 calls")).toBeDefined();
    expect(button("Show all 4 calls").getAttribute("aria-expanded")).toBe(
      "false",
    );
    await act(async () => button("Show all 4 calls").click());
    expect(list.parentElement!.hasAttribute("data-expanded")).toBe(true);
    expect(button("Show fewer calls").getAttribute("aria-expanded")).toBe(
      "true",
    );
    expect(button("Show fewer calls").getAttribute("aria-controls")).toBe(
      list.parentElement!.id,
    );
    await act(async () => button("Show fewer calls").click());
    expect(list.parentElement!.hasAttribute("data-expanded")).toBe(false);
    expect(document.activeElement).toBe(links()[0]);
    expect(button("On this skill").getAttribute("aria-pressed")).toBe("true");
    expect(links()).toHaveLength(4);
    expect(button("Show all 4 calls").getAttribute("aria-expanded")).toBe(
      "false",
    );
    await act(async () => button("Show all 4 calls").click());
    await act(async () => button("All calls").click());
    expect(list.parentElement!.hasAttribute("data-expanded")).toBe(false);
    expect(links()).toHaveLength(10);
    expect(button("Show all 10 calls")).toBeDefined();
  });

  it("keeps all calls without inventing a match for legacy, absent-focus or unavailable records", () => {
    for (const props of [
      { focusLabel: "Same words as the current focus" },
      { progress: [point(1, "suggested")] },
      {
        focusLabel: "Explore the consequence",
        progress: [point(1, "not_covered")],
      },
      {
        focusLabel: "Explore the consequence",
        progress: [point(99, "suggested")],
      },
      {
        calls: [call(1, "pending")],
        focusLabel: "Explore the consequence",
        progress: [point(1, "suggested")],
      },
    ]) {
      const html = renderToStaticMarkup(
        <CallsPanel calls={[call(1)]} {...props} />,
      );
      expect(html).not.toContain("On this skill");
      expect(html).toContain("Fictional call 1");
    }
    expect(
      renderToStaticMarkup(
        <CallsPanel
          progress={[point(99, "suggested")]}
          focusLabel="Unrelated"
        />,
      ),
    ).toBe("");
  });
});
