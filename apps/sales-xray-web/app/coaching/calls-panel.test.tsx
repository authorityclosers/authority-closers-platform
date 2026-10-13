import { act, createRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CallsPanel, type CallsPanelHandle } from "./calls-panel";
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
const links = () =>
  [...host.querySelectorAll("li")].map(
    (row) => row.querySelector<HTMLAnchorElement>("a")!,
  );
const findCall = () =>
  host.querySelector<HTMLInputElement>('input[type="search"]')!;
const searchFor = async (query: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(findCall(), query);
    findCall().dispatchEvent(new Event("input", { bubbles: true }));
  });
};

describe("calls on the current skill", () => {
  it("compares saved report findings, intersects call names and resets from shortcuts without changing destinations", async () => {
    const ref = createRef<CallsPanelHandle>();
    const calls = [
      ...Array.from({ length: 6 }, (_, index) => call(index + 1)),
      call(7, "pending"),
      call(8, "unavailable"),
      call(9),
      call(10),
    ];
    const progress = [
      ...Array.from({ length: 4 }, (_, index) => point(index + 1, "suggested")),
      point(5, "no_suggestion"),
      point(6, "no_suggestion"),
      point(7, "suggested"),
      point(8, "no_suggestion"),
      point(9, "not_covered"),
      point(99, "suggested"),
    ];
    for (const reports of [false, true]) {
      await act(async () =>
        root.render(
          <TheirCoaching.Provider value={reports}>
            <CallsOpenReports.Provider value={reports}>
              <CallsPanel
                key={String(reports)}
                ref={ref}
                calls={calls}
                progress={progress}
                focusLabel="Explore the consequence"
              />
            </CallsOpenReports.Provider>
          </TheirCoaching.Provider>,
        ),
      );
      expect(host.querySelector("select")).toBeNull();
      await act(async () => ref.current!.showSkill());
      let select = host.querySelector<HTMLSelectElement>(
        'select[aria-label="What the report found"]',
      )!;
      expect([...select.options].map((option) => option.textContent)).toEqual([
        "All on this skill",
        "Needed work",
        "Skill used, nothing to fix",
      ]);
      expect(select.getAttribute("aria-controls")).toBe(
        host.querySelector("ul")!.parentElement!.id,
      );
      const choose = async (value: string) =>
        act(async () => {
          select.value = value;
          select.dispatchEvent(new Event("change", { bubbles: true }));
        });
      const check = (ids: number[]) => {
        expect(links().map((link) => link.textContent)).toEqual(
          ids.map((id) => call(id).call_label),
        );
        expect(links().map((link) => link.getAttribute("href"))).toEqual(
          ids.map(
            (id) =>
              `${reports || calls[id - 1].state !== "ready" ? "/analysis/calls/" : "/coaching?call="}${call(id).submission_id}`,
          ),
        );
        expect(host.querySelector('[role="status"]')?.textContent).toBe(
          `${ids.length} call${ids.length === 1 ? "" : "s"}`,
        );
      };
      check([1, 2, 3, 4, 5, 6]);
      await act(async () => button("Show all 6 calls").click());
      await choose("suggested");
      check([1, 2, 3, 4]);
      expect(host.querySelector("[data-expanded]")).toBeNull();
      await searchFor("  cAlL 4  ");
      check([4]);
      await choose("no_suggestion");
      check([]);
      expect(host.textContent).toContain(
        "Try another call name, or show all calls on this skill.",
      );
      await act(async () => button("Clear search").click());
      expect(select.value).toBe("no_suggestion");
      expect(document.activeElement).toBe(findCall());
      check([5, 6]);
      expect(host.querySelector("ul")!.textContent).not.toContain(
        "Needed work",
      );
      // Every Report shortcut continues to target its original call.
      expect(
        [...host.querySelectorAll('a[aria-label^="Open Report for"]')].map(
          (link) => link.getAttribute("href"),
        ),
      ).toEqual(
        reports
          ? []
          : [5, 6].map((id) => `/analysis/calls/${call(id).submission_id}`),
      );
      await act(async () => button("All calls").click());
      expect(host.querySelector("select")).toBeNull();
      check([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
      await act(async () => button("On this skill").click());
      select = host.querySelector("select")!;
      expect(select.value).toBe("all");
      check([1, 2, 3, 4, 5, 6]);
      await choose("no_suggestion");
      await searchFor("missing call");
      await act(async () => ref.current!.showSkill());
      expect(findCall().value).toBe("");
      expect(select.value).toBe("all");
      check([1, 2, 3, 4, 5, 6]);
      expect(document.activeElement).toBe(host.querySelector("section"));
      await choose("suggested");
      await act(async () => ref.current!.showAll());
      expect(host.querySelector("select")).toBeNull();
      check([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    }
    // Neither unmatched nor unready progress records create a comparison.
    await act(async () =>
      root.render(
        <CallsPanel
          key="one-finding"
          calls={calls}
          progress={[
            point(1, "suggested"),
            point(7, "no_suggestion"),
            point(99, "no_suggestion"),
          ]}
          focusLabel="Explore the consequence"
        />,
      ),
    );
    await act(async () => button("On this skill").click());
    expect(links()).toHaveLength(1);
    expect(host.querySelector("select")).toBeNull();
  });

  it("offers the matching Report beside ready personal and fictional calls, preserving shared and unready destinations", async () => {
    const calls = [
      call(1),
      call(2, "pending"),
      call(3, "unavailable"),
      call(4),
    ];
    for (const [their, reports] of [
      [false, false],
      [true, false],
      [true, true],
    ]) {
      await act(async () =>
        root.render(
          <TheirCoaching.Provider value={their}>
            <CallsOpenReports.Provider value={reports}>
              <CallsPanel
                key={`${their}:${reports}`}
                calls={calls}
                focusLabel="Explore the consequence"
                progress={[point(4, "suggested")]}
              />
            </CallsOpenReports.Provider>
          </TheirCoaching.Provider>,
        ),
      );
      const checkRows = (shown: CallSummary[]) => {
        const rows = [...host.querySelectorAll("li")];
        expect(rows).toHaveLength(shown.length);
        rows.forEach((row, index) => {
          const source = shown[index];
          const anchors = [...row.querySelectorAll("a")];
          const hasShortcut = source.state === "ready" && !reports;
          expect(anchors).toHaveLength(hasShortcut ? 2 : 1);
          expect(anchors[0].textContent).toBe(source.call_label);
          expect(anchors[0].getAttribute("href")).toBe(
            source.state === "ready" && !reports
              ? `/coaching?call=${source.submission_id}`
              : `/analysis/calls/${source.submission_id}`,
          );
          if (hasShortcut) {
            expect(anchors[1].getAttribute("href")).toBe(
              `/analysis/calls/${source.submission_id}`,
            );
            expect(anchors[1].getAttribute("aria-label")).toBe(
              `Open Report for ${source.call_label}`,
            );
            expect(anchors[1].textContent).toBe("Report");
          }
        });
      };
      checkRows(calls);
      await act(async () => button("On this skill").click());
      checkRows([calls[3]]);
      await searchFor("no matching call");
      checkRows([]);
      await act(async () => button("Clear search").click());
      checkRows([calls[3]]);
    }
  });

  it("finds a call beyond the compact history and combines name and saved-skill filters without changing shared Report links", async () => {
    const calls = Array.from({ length: 10 }, (_, index) => call(index + 1));
    calls[7] = { ...call(8), call_label: "Follow-up [2]" };
    calls[8] = { ...call(9, "pending"), call_label: "Meera · चर्चा" };
    calls[9] = { ...call(10), call_label: "Meera · Follow-up" };
    await act(async () =>
      root.render(
        <TheirCoaching.Provider value>
          <CallsOpenReports.Provider value>
            <CallsPanel
              calls={calls}
              focusLabel="Explore the consequence"
              progress={[point(1, "suggested"), point(10, "no_suggestion")]}
            />
          </CallsOpenReports.Provider>
        </TheirCoaching.Provider>,
      ),
    );
    expect(findCall().getAttribute("aria-controls")).toBe(
      host.querySelector('[aria-label="Their recent calls"]')!.parentElement!
        .id,
    );
    await act(async () => button("Show all 10 calls").click());
    await searchFor("  mEeRa  ");
    expect(links().map((link) => link.textContent)).toEqual([
      "Meera · चर्चा",
      "Meera · Follow-up",
    ]);
    expect(
      [...host.querySelectorAll("mark")].map((mark) => mark.textContent),
    ).toEqual(["Meera", "Meera"]);
    expect(links().map((link) => link.getAttribute("href"))).toEqual([
      `/analysis/calls/${call(9).submission_id}`,
      `/analysis/calls/${call(10).submission_id}`,
    ]);
    expect(host.querySelector("[data-expanded]")).toBeNull();
    expect(host.textContent).toContain("Analysing…");
    expect(host.querySelector('[role="status"]')?.textContent).toBe("2 calls");
    await act(async () => button("On this skill").click());
    expect(links()).toHaveLength(1);
    expect(host.textContent).toContain("Skill used, nothing to fix");
    await searchFor("missing call");
    expect(links()).toHaveLength(0);
    expect(host.textContent).toContain("No matching calls");
    expect(host.querySelector('[role="status"]')?.textContent).toBe("0 calls");
    await act(async () => button("Clear search").click());
    expect(findCall().value).toBe("");
    expect(document.activeElement).toBe(findCall());
    expect(button("On this skill").getAttribute("aria-pressed")).toBe("true");
    expect(links()).toHaveLength(2);
    expect(host.querySelector("mark")).toBeNull();
    await act(async () => button("All calls").click());
    await searchFor("चर्चा");
    expect(links()).toHaveLength(1);
    expect(links()[0].textContent).toBe("Meera · चर्चा");
    expect(host.querySelector("mark")?.textContent).toBe("चर्चा");
    await searchFor("-up");
    expect(links().map((link) => link.textContent)).toEqual([
      "Follow-up [2]",
      "Meera · Follow-up",
    ]);
    expect(host.querySelector("mark")?.textContent).toBe("-up");
    await searchFor(".*[");
    expect(links()).toHaveLength(0);
    expect(host.querySelector("mark")).toBeNull();
    await searchFor("[2]");
    expect(links()[0].textContent).toBe("Follow-up [2]");
    expect(links()[0].getAttribute("href")).toBe(
      `/analysis/calls/${call(8).submission_id}`,
    );
    expect(host.querySelector("mark")?.textContent).toBe("[2]");
  });

  it("clears a prior search when the progress shortcut opens saved skill calls", async () => {
    const ref = createRef<CallsPanelHandle>();
    await act(async () =>
      root.render(
        <CallsPanel
          ref={ref}
          calls={Array.from({ length: 10 }, (_, index) => call(index + 1))}
          focusLabel="Explore the consequence"
          progress={[point(1, "suggested"), point(10, "no_suggestion")]}
        />,
      ),
    );
    await searchFor("missing call");
    expect(links()).toHaveLength(0);
    await act(async () => ref.current!.showSkill());
    expect(findCall().value).toBe("");
    expect(button("On this skill").getAttribute("aria-pressed")).toBe("true");
    expect(links()).toHaveLength(2);
    expect(document.activeElement).toBe(host.querySelector("#coaching-calls"));
  });

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
