import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseGuide, type Guide } from "./guide-content";
import { GuideSkeleton, GuideView } from "./guide-view";

/** Fictional placeholder rows, never coaching content. */
const GUIDE = parseGuide({
  format: 1,
  version: 1,
  examples: false,
  welcome: "",
  starters: ["S-1", "S-2", "S-3", "S-4"],
  questions: [
    ...["S-1", "S-2", "S-3", "S-4"].map((id) => ({
      id,
      question: `Starter ${id}?`,
      answer: `Answer to ${id}.\n\nSecond part of ${id}.`,
      next: id === "S-1" ? ["F-1", "F-2", "S-2"] : [],
      category: "objection handling",
      example_line: id === "S-1" ? "Say this for S-1." : "",
      start: true,
    })),
    {
      id: "F-1",
      question: "Follow-up F-1?",
      answer: "Answer to F-1.",
      next: ["S-1"],
      category: "",
    },
    {
      id: "F-2",
      question: "Follow-up F-2?",
      answer: "Answer to F-2.",
      next: [],
    },
  ],
}) as Guide;

let root: Root, host: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  window.history.replaceState(null, "", "/coaching/guide");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const rows = () =>
  [...host.querySelectorAll("li a")].map((link) => link.textContent);
const heading = (text: string) =>
  [...host.querySelectorAll("h2")].find((item) => item.textContent === text);
const tap = async (text: string) => {
  const link = [...host.querySelectorAll<HTMLElement>("a, button")].find(
    (item) => item.textContent === text,
  );
  if (!link) throw new Error(`no "${text}" on screen`);
  await act(async () => link.click());
};
/** The Android back gesture or the browser's Back: the address moves back, then popstate. */
const back = async (to: string) => {
  window.history.replaceState(null, "", to);
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));
};

describe("Dipak's answers", () => {
  it("opens with the welcome and the four starters", async () => {
    await act(async () => root.render(<GuideView guide={GUIDE} />));
    expect(host.textContent).toContain("Tap a question to see Dipak’s answer.");
    expect(heading("People usually ask")).toBeDefined();
    expect(rows()).toEqual([
      "Starter S-1?",
      "Starter S-2?",
      "Starter S-3?",
      "Starter S-4?",
    ]);
    expect(
      host.querySelector<HTMLAnchorElement>("li a")?.getAttribute("href"),
    ).toBe("?q=S-1");
  });

  it("walks starter, answer and follow-ups, one history entry per tap, and Back walks it back", async () => {
    const push = vi.spyOn(window.history, "pushState");
    await act(async () => root.render(<GuideView guide={GUIDE} />));

    await tap("Starter S-1?");
    expect(window.location.search).toBe("?q=S-1");
    expect(heading("Starter S-1?")).toBeDefined();
    expect(host.textContent).toContain("Objection handling");
    expect(
      [...host.querySelectorAll("article p")].map((p) => p.textContent),
    ).toEqual([
      "Objection handling",
      "Answer to S-1.",
      "Second part of S-1.",
      "Say this for S-1.",
    ]);
    expect(host.querySelector("figcaption")?.textContent).toBe("Try saying");
    expect(heading("People also ask")).toBeDefined();
    expect(rows()).toEqual([
      "Follow-up F-1?",
      "Follow-up F-2?",
      "Starter S-2?",
    ]);
    expect(document.activeElement?.textContent).toBe("Starter S-1?");

    await tap("Follow-up F-1?");
    expect(window.location.search).toBe("?q=F-1");
    expect(heading("Follow-up F-1?")).toBeDefined();
    expect(rows()).toEqual(["Starter S-1?"]);
    expect(push).toHaveBeenCalledTimes(2);

    await back("/coaching/guide?q=S-1");
    expect(heading("Starter S-1?")).toBeDefined();
    expect(rows()).toEqual([
      "Follow-up F-1?",
      "Follow-up F-2?",
      "Starter S-2?",
    ]);

    await back("/coaching/guide");
    expect(heading("People usually ask")).toBeDefined();
    expect(rows()).toHaveLength(4);
    expect(push).toHaveBeenCalledTimes(2);
  });

  it("never dead-ends: an answer without follow-ups leads back to the first questions", async () => {
    window.history.replaceState(null, "", "/coaching/guide?q=F-2");
    await act(async () => root.render(<GuideView guide={GUIDE} />));
    expect(heading("Follow-up F-2?")).toBeDefined();
    expect(heading("People also ask")).toBeUndefined();
    expect(host.querySelector("figure")).toBeNull();
    await tap("First questions");
    expect(window.location.search).toBe("");
    expect(heading("People usually ask")).toBeDefined();
  });

  it("opens the starters for a step the content no longer has", async () => {
    window.history.replaceState(null, "", "/coaching/guide?q=GONE-1");
    await act(async () => root.render(<GuideView guide={GUIDE} />));
    expect(heading("People usually ask")).toBeDefined();
  });

  it("leaves a new-tab click to the browser", async () => {
    const push = vi.spyOn(window.history, "pushState");
    await act(async () => root.render(<GuideView guide={GUIDE} />));
    const link = host.querySelector<HTMLAnchorElement>("li a")!;
    // React's listener on the root runs first; this one then stops the test
    // page from really navigating.
    let prevented: boolean | null = null;
    host.addEventListener("click", (event) => {
      prevented = event.defaultPrevented;
      event.preventDefault();
    });
    const click = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      ctrlKey: true,
    });
    await act(async () => link.dispatchEvent(click));
    expect(prevented).toBe(false);
    expect(push).not.toHaveBeenCalled();
    expect(heading("People usually ask")).toBeDefined();
  });

  it("uses Dipak's own welcome line when he wrote one", async () => {
    const own = { ...GUIDE, welcome: "A fictional welcome line." };
    await act(async () => root.render(<GuideView guide={own} />));
    expect(host.textContent).toContain("A fictional welcome line.");
    expect(host.textContent).not.toContain("Tap a question");
  });

  it("server-renders the starters, and the loading outline has the starters' rows", () => {
    expect(renderToStaticMarkup(<GuideView guide={GUIDE} />)).toContain(
      "People usually ask",
    );
    const outline = document.createElement("div");
    outline.innerHTML = renderToStaticMarkup(<GuideSkeleton />);
    expect(outline.querySelector("[aria-busy='true']")).not.toBeNull();
  });
});
