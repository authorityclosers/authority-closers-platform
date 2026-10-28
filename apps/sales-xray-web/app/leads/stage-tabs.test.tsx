import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

import type { StageView } from "./journey/journey-client";
import { StageTabs, stageTabs } from "./stage-tabs";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const stage = (
  label: string,
  kind: StageView["kind"],
  archived = false,
): StageView => ({
  key: label.toLowerCase().replace(/\s+/g, "_"),
  label,
  kind,
  kindWords: "",
  milestone: "",
  meaning: "",
  archived,
  origin: "",
  leads: 0,
});

// Owner, 22 Oct 2026: stage tabs from the organisation's own stages.
it("names the tabs by the business's own stages, with every stage's count", () => {
  const journey = {
    stages: [
      stage("Enquiry", "new"),
      stage("Site visit booked", "interested"),
      stage("Negotiation", "interested"),
      stage("Old step", "follow_up", true),
      stage("Booked", "won"),
    ],
  };
  const tabs = stageTabs(journey, {
    new: 4,
    interested: 3,
    follow_up: 2,
    won: 1,
  });
  expect(tabs).toEqual([
    { key: "open", label: "All leads", count: 9 },
    { key: "new", label: "Enquiry", count: 4 },
    { key: "interested", label: "Interested", count: 3 },
    { key: "won", label: "Booked", count: 1 },
    { key: "lost", label: "Lost", count: 0 },
  ]);
});

// Owner, 26 Oct 2026: the sales team's eight stages have no Junk, so no Junk tab;
// a list with a Junk stage, or junk leads left from before, keeps it.
it("shows Junk only where the list has it or junk leads remain", () => {
  const eight = { stages: [stage("New lead", "new"), stage("Lost", "lost")] };
  expect(stageTabs(eight, { new: 2 }).map((tab) => tab.key)).toEqual([
    "open",
    "new",
    "won",
    "lost",
  ]);
  const withJunk = { stages: [...eight.stages, stage("Junk", "junk")] };
  expect(stageTabs(withJunk, null).at(-1)).toEqual({
    key: "junk",
    label: "Junk",
    count: undefined,
  });
  expect(stageTabs(eight, { junk: 3 }).at(-1)).toEqual({
    key: "junk",
    label: "Junk",
    count: 3,
  });
});

it("falls back to the desk's kinds, without counts until they arrive", () => {
  expect(stageTabs(null, null)).toEqual([
    { key: "open", label: "All leads", count: undefined },
    { key: "new", label: "New", count: undefined },
    { key: "not_connected", label: "Not connected", count: undefined },
    { key: "follow_up", label: "Follow up", count: undefined },
    { key: "interested", label: "Interested", count: undefined },
    { key: "won", label: "Won", count: undefined },
    { key: "lost", label: "Lost", count: undefined },
  ]);
});

it("marks the chosen tab and reports a tap", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <StageTabs
        tabs={[
          { key: "desk", label: "To call", count: 2 },
          { key: "open", label: "All leads", count: 5 },
        ]}
        current="desk"
        onChange={onChange}
      />,
    ),
  );
  const [desk, open] = host.querySelectorAll('[role="tab"]');
  expect(desk.getAttribute("aria-selected")).toBe("true");
  expect(desk.textContent).toBe("To call2");
  await act(async () => (open as HTMLButtonElement).click());
  expect(onChange).toHaveBeenCalledWith("open");
  await act(async () => root.unmount());
  host.remove();
});

// Production report #28 (26 Oct 2026): showing a later stage scrolls only the
// strip, never the page or a clipped parent.
it("scrolls only its own strip to show a later stage", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const intoView = vi.fn();
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = intoView;
  const rects = vi
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: Element) {
      const right = this.getAttribute("role") === "tablist" ? 300 : 480;
      const left = this.getAttribute("role") === "tablist" ? 0 : 400;
      return {
        left,
        right,
        top: 0,
        bottom: 44,
        width: right - left,
        height: 44,
        x: left,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect;
    });
  await act(async () =>
    root.render(
      <StageTabs
        tabs={[
          { key: "desk", label: "To call", count: 2 },
          { key: "won", label: "Won", count: 1 },
        ]}
        current="won"
        onChange={() => undefined}
      />,
    ),
  );
  const strip = host.querySelector<HTMLElement>('[role="tablist"]')!;
  // 480 - 300 + 24: the chosen tab clears the fade.
  expect(strip.scrollLeft).toBe(204);
  expect(intoView).not.toHaveBeenCalled();
  rects.mockRestore();
  Element.prototype.scrollIntoView = original;
  await act(async () => root.unmount());
  host.remove();
});

it("keeps a selected chip 16 px inside the strip's left edge", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const rects = vi
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: Element) {
      const isStrip = this.getAttribute("role") === "tablist";
      return {
        left: isStrip ? 100 : 104,
        right: isStrip ? 400 : 180,
      } as DOMRect;
    });
  try {
    await act(async () =>
      root.render(
        <StageTabs
          tabs={[{ key: "won", label: "Won" }]}
          current="won"
          onChange={() => undefined}
        />,
      ),
    );
    expect(
      host.querySelector<HTMLElement>('[role="tablist"]')!.scrollLeft,
    ).toBe(-12);
  } finally {
    rects.mockRestore();
    await act(async () => root.unmount());
    host.remove();
  }
});
