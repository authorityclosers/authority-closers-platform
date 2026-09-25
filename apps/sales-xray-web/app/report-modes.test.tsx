import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReportModes } from "./report-modes";
import { useReportNavigation } from "./report-reading-context";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  window.history.replaceState(null, "", "/");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

const call = "c2793fdf-4948-47e4-a4bc-973f2b7720bc";
function JumpToPoint() {
  const navigate = useReportNavigation();
  return (
    <button type="button" onClick={() => navigate?.("overview", "14")}>
      Focus point 14
    </button>
  );
}
function panels() {
  return [
    {
      id: "overview",
      label: "Overview",
      content: (
        <div data-review-point="14" tabIndex={-1}>
          Summary point
        </div>
      ),
    },
    { id: "prospect", label: "Prospect", content: <p>Prospect</p> },
    {
      id: "moments",
      label: "Moments",
      content: (
        <>
          <input aria-label="Moment note" />
          <JumpToPoint />
        </>
      ),
    },
    { id: "skills", label: "Sales skills", content: <p>Skills</p> },
    {
      id: "next-call-plan",
      label: "Next-call plan",
      content: <p>Plan</p>,
    },
    { id: "transcript", label: "Transcript", content: <p>Conversation</p> },
  ];
}
async function render(boundCallId?: string) {
  await act(async () =>
    root.render(<ReportModes panels={panels()} boundCallId={boundCallId} />),
  );
}
const sections = () => [
  ...container.querySelectorAll<HTMLElement>("[data-report-mode-section]"),
];
const mode = () => container.querySelector<HTMLElement>("[data-report-modes]")!;

it("shows all six report sections in one continuous reading layout", async () => {
  await render();
  expect(mode().dataset.view).toBe("reading");
  // The tab strip, section list and sections share one light report surface,
  // whatever the app theme (tokens.css [data-lx-surface="light"]).
  expect(mode().getAttribute("data-lx-surface")).toBe("light");
  expect(sections()).toHaveLength(6);
  expect(sections().every((section) => !section.hidden)).toBe(true);
  expect(
    container.querySelectorAll("nav[aria-label='Report sections'] a"),
  ).toHaveLength(6);
  expect(
    container.querySelector('[aria-pressed="true"]')?.textContent,
  ).toContain("Reading");
});

it("bookmarks a selected section without hiding other report content", async () => {
  await render(call);
  await act(async () =>
    container
      .querySelector<HTMLAnchorElement>('a[aria-label="Moments"]')!
      .click(),
  );
  expect(mode().dataset.reportSection).toBe("moments");
  expect(window.location.search).toContain(`call=${call}`);
  expect(window.location.search).toContain("view=reading");
  expect(window.location.search).toContain("section=moments");
  expect(sections().every((section) => !section.hidden)).toBe(true);
});

it("keeps all six accessible tabs available without horizontal overflow", async () => {
  await render(call);
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('button[aria-pressed="false"]')!
      .click(),
  );
  expect(mode().dataset.view).toBe("tabs");
  expect(window.location.search).toContain("view=tabs");
  expect(container.querySelectorAll('[role="tab"]')).toHaveLength(6);
  expect(sections().filter((section) => !section.hidden)).toHaveLength(1);

  const moments = container.querySelector<HTMLButtonElement>(
    '[role="tab"][aria-label="Moments"]',
  );
  expect(moments).not.toBeNull();
  await act(async () => moments!.click());
  expect(mode().dataset.reportSection).toBe("moments");
  expect(
    sections()
      .filter((section) => !section.hidden)
      .map((section) => section.id),
  ).toEqual([expect.stringContaining("section-moments")]);
  expect(window.location.search).toContain("view=tabs");

  const viewButtons = container.querySelectorAll<HTMLButtonElement>(
    '[role="group"] button',
  );
  await act(async () => viewButtons[0].click());
  expect(mode().dataset.view).toBe("reading");
  expect(sections().every((section) => !section.hidden)).toBe(true);
  await act(async () => viewButtons[1].click());
  expect(mode().dataset.view).toBe("tabs");
  const momentsTab = container.querySelector<HTMLButtonElement>(
    '[role="tab"][aria-label="Moments"]',
  );
  await act(async () => momentsTab!.click());

  const scroll = vi.fn();
  const previous = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "scrollIntoView",
  );
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scroll,
  });
  try {
    const jump = [
      ...container.querySelectorAll<HTMLButtonElement>("button"),
    ].find((button) => button.textContent?.trim() === "Focus point 14")!;
    await act(async () => jump.click());
    await act(async () => new Promise((resolve) => setTimeout(resolve, 30)));
    expect(mode().dataset.view).toBe("tabs");
    expect(mode().dataset.reportSection).toBe("overview");
    expect(sections().filter((section) => !section.hidden)).toHaveLength(1);
    expect(
      sections().find((section) => !section.hidden)?.dataset.reportModeSection,
    ).toBe("overview");
    expect(container.querySelector('[data-review-point="14"]')).toBe(
      document.activeElement,
    );
    expect(scroll).toHaveBeenCalledOnce();
  } finally {
    if (previous)
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", previous);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  }
});

const settle = () =>
  act(async () => new Promise((resolve) => setTimeout(resolve, 90)));
const buttonNamed = (text: string) =>
  [...container.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.trim() === text,
  );
async function jumpFromMoments() {
  const jump = buttonNamed("Focus point 14")!;
  jump.focus();
  await act(async () => jump.click());
  await settle();
  return jump;
}

it("returns from a jump to the original URL without a section and its exact control", async () => {
  window.history.replaceState(null, "", `/?call=${call}`);
  await render(call);
  const push = vi.spyOn(window.history, "pushState");
  const jump = await jumpFromMoments();
  // The destination is a real history entry, focused and briefly marked.
  expect(push).toHaveBeenCalledOnce();
  expect(window.location.search).toContain("section=overview");
  const point = container.querySelector<HTMLElement>(
    '[data-review-point="14"]',
  );
  expect(document.activeElement).toBe(point);
  expect(point?.getAttribute("data-arrived")).toBe("true");

  await act(async () => buttonNamed("Back to Moments")!.click());
  await settle();
  // The jump entry is undone rather than stacked, so the URL is the original.
  expect(window.location.search).toBe(`?call=${call}`);
  expect(document.activeElement).toBe(jump);
  expect(container.querySelector("[data-report-return]")).toBeNull();
});

it("restores the jump origin on browser Back as well", async () => {
  window.history.replaceState(null, "", `/?call=${call}`);
  await render(call);
  const jump = await jumpFromMoments();
  expect(container.querySelector("[data-report-return]")).not.toBeNull();
  await act(async () => window.history.back());
  await settle();
  expect(window.location.search).toBe(`?call=${call}`);
  expect(document.activeElement).toBe(jump);
  expect(container.querySelector("[data-report-return]")).toBeNull();
});

it("returns to the originating tab in the tabbed view", async () => {
  const origin = `?call=${call}&view=tabs&section=moments`;
  window.history.replaceState(null, "", `/${origin}`);
  await render(call);
  const jump = await jumpFromMoments();
  expect(mode().dataset.view).toBe("tabs");
  expect(
    sections().find((section) => !section.hidden)?.dataset.reportModeSection,
  ).toBe("overview");

  await act(async () => buttonNamed("Back to Moments")!.click());
  await settle();
  expect(window.location.search).toBe(origin);
  expect(
    sections().find((section) => !section.hidden)?.dataset.reportModeSection,
  ).toBe("moments");
  expect(document.activeElement).toBe(jump);
});

it("moves instantly under reduced motion and smoothly otherwise", async () => {
  const scroll = vi.fn();
  const previous = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "scrollIntoView",
  );
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scroll,
  });
  const media = (reduce: boolean) =>
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({
          matches: reduce && query.includes("reduce"),
          media: query,
          addEventListener: () => {},
          removeEventListener: () => {},
        }) as unknown as MediaQueryList,
    );
  if (!window.matchMedia)
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: () => ({ matches: false }),
    });
  try {
    window.history.replaceState(null, "", `/?call=${call}`);
    await render(call);
    media(true);
    await jumpFromMoments();
    expect(scroll).toHaveBeenLastCalledWith(
      expect.objectContaining({ behavior: "auto" }),
    );
    await act(async () => buttonNamed("Back to Moments")!.click());
    await settle();
    vi.restoreAllMocks();
    media(false);
    await jumpFromMoments();
    expect(scroll).toHaveBeenLastCalledWith(
      expect.objectContaining({ behavior: "smooth" }),
    );
  } finally {
    if (previous)
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", previous);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  }
});

it("focuses a jump target even when it is a plain container", async () => {
  await act(async () =>
    root.render(
      <ReportModes
        boundCallId={call}
        panels={[
          {
            id: "overview",
            label: "Overview",
            content: <div data-review-point="14">Verdict</div>,
          },
          { id: "moments", label: "Moments", content: <JumpToPoint /> },
        ]}
      />,
    ),
  );
  await jumpFromMoments();
  const point = container.querySelector<HTMLElement>(
    '[data-review-point="14"]',
  );
  expect(point?.getAttribute("tabindex")).toBe("-1");
  expect(document.activeElement).toBe(point);
});

function desktopViewport(matches: boolean) {
  const previous = Object.getOwnPropertyDescriptor(window, "matchMedia");
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) =>
      ({
        matches: matches && query.includes("min-width"),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  });
  return () => {
    if (previous) Object.defineProperty(window, "matchMedia", previous);
    else Reflect.deleteProperty(window, "matchMedia");
  };
}

it("opens desktop reports in Tabbed view unless the URL or reader chose", async () => {
  const restore = desktopViewport(true);
  try {
    window.history.replaceState(null, "", `/?call=${call}`);
    await render(call);
    expect(mode().dataset.view).toBe("tabs");
    // One navigation row: the section tabs and the view choice together.
    const row = container.querySelector('[role="tablist"]')!.parentElement!;
    expect(row.querySelector('[role="group"]')).not.toBeNull();
    // The selected tab names the section; its heading is kept, visually hidden.
    const heading = sections()
      .find((section) => !section.hidden)!
      .querySelector("h2")!;
    expect(heading.className).not.toBe("");

    // A reader's explicit choice wins over the viewport default.
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[role="group"] button')!
        .click(),
    );
    expect(mode().dataset.view).toBe("reading");
    expect(window.location.search).toContain("view=reading");
    expect(
      container.querySelectorAll("nav[aria-label='Report sections'] a"),
    ).toHaveLength(6);
  } finally {
    restore();
  }
});

it("keeps an explicit reading bookmark on a desktop viewport", async () => {
  const restore = desktopViewport(true);
  try {
    window.history.replaceState(null, "", `/?call=${call}&view=reading`);
    await render(call);
    expect(mode().dataset.view).toBe("reading");
    // Reading view has no second sidebar: section links share the one row.
    const links = container.querySelector("nav[aria-label='Report sections']")!;
    expect(links.parentElement?.querySelector('[role="group"]')).not.toBeNull();
    expect(sections().every((section) => !section.hidden)).toBe(true);
  } finally {
    restore();
  }
});

it("stays in Reading view on a narrow viewport without a choice", async () => {
  const restore = desktopViewport(false);
  try {
    await render(call);
    expect(mode().dataset.view).toBe("reading");
  } finally {
    restore();
  }
});

it("preserves mounted section state while tabs show only one report section", async () => {
  await render(call);
  const note = container.querySelector<HTMLInputElement>(
    'input[aria-label="Moment note"]',
  )!;
  note.value = "keep this";

  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-pressed="false"]')!
      .click(),
  );
  expect(sections().filter((section) => !section.hidden)).toHaveLength(1);
  expect(note.isConnected).toBe(true);
  expect(note.value).toBe("keep this");
});

it("keeps a bookmarked tab when its already-selected view is clicked again", async () => {
  const query = `?call=${call}&view=tabs&section=transcript`;
  window.history.replaceState(null, "", `/${query}`);
  await render(call);
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-pressed="true"]')!
      .click(),
  );
  expect(mode().dataset.reportSection).toBe("transcript");
  expect(window.location.search).toBe(query);
});

it("supports arrow, Home and End navigation across all six report tabs", async () => {
  await render(call);
  const viewButtons = container.querySelectorAll<HTMLButtonElement>(
    '[role="group"] button',
  );
  await act(async () => viewButtons[1].click());
  const tabs = [
    ...container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
  ];
  tabs[0].focus();
  await act(async () =>
    tabs[0].dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "End",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(mode().dataset.reportSection).toBe("transcript");
  expect(document.activeElement).toBe(tabs[5]);
  await act(async () =>
    tabs[5].dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "ArrowLeft",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(mode().dataset.reportSection).toBe("next-call-plan");
  expect(document.activeElement).toBe(tabs[4]);
  await act(async () =>
    tabs[4].dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Home",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(mode().dataset.reportSection).toBe("overview");
  expect(document.activeElement).toBe(tabs[0]);
});

it("tracks the section in view and marks its navigation link", async () => {
  await render();
  const positions = [-500, -300, 90, 600, 900, 1100];
  sections().forEach((section, index) => {
    vi.spyOn(
      section.querySelector("h2")!,
      "getBoundingClientRect",
    ).mockReturnValue({ top: positions[index], height: 24 } as DOMRect);
  });
  await act(async () => document.dispatchEvent(new Event("scroll")));
  expect(mode().dataset.reportSection).toBe("moments");
  expect(
    container
      .querySelector('a[aria-label="Moments"]')
      ?.getAttribute("aria-current"),
  ).toBe("location");
});

it("preserves the section in view when switching from Reading to Tabs", async () => {
  await render(call);
  const positions = [-500, -300, -100, -80, 90, 900];
  sections().forEach((section, index) => {
    vi.spyOn(
      section.querySelector("h2")!,
      "getBoundingClientRect",
    ).mockReturnValue({ top: positions[index], height: 24 } as DOMRect);
  });
  await act(async () => document.dispatchEvent(new Event("scroll")));
  expect(mode().dataset.reportSection).toBe("next-call-plan");

  const tabsButton = container.querySelector<HTMLButtonElement>(
    '[role="group"] button[aria-pressed="false"]',
  )!;
  await act(async () => tabsButton.click());

  expect(mode().dataset.view).toBe("tabs");
  expect(mode().dataset.reportSection).toBe("next-call-plan");
  expect(window.location.search).toContain("section=next-call-plan");
  expect(
    sections()
      .filter((section) => !section.hidden)
      .map((section) => section.id),
  ).toEqual([expect.stringContaining("section-next-call-plan")]);
});

it("reads a tab bookmark only for its bound call", async () => {
  window.history.replaceState(
    null,
    "",
    `/?call=${call}&view=tabs&section=skills`,
  );
  await render(call);
  expect(mode().dataset.view).toBe("tabs");
  expect(mode().dataset.reportSection).toBe("skills");
  expect(sections().filter((section) => !section.hidden)).toHaveLength(1);
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>(
        '[role="tab"][aria-label="Transcript"]',
      )!
      .click(),
  );
  expect(window.location.search).toContain("section=transcript");
  expect(window.location.search).toContain("view=tabs");
});

it("ignores a bookmark URL bound to another call", async () => {
  window.history.replaceState(
    null,
    "",
    "/?call=7b6443d3-9b2d-4f97-9e70-5e82e54f8738&section=moments",
  );
  await render(call);
  expect(mode().dataset.reportSection).toBe("overview");
  expect(sections().every((section) => !section.hidden)).toBe(true);
});

it("opens a direct section bookmark at its section", async () => {
  const scroll = vi.fn();
  const previous = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "scrollIntoView",
  );
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scroll,
  });
  try {
    window.history.replaceState(null, "", `/?call=${call}&section=transcript`);
    await render(call);
    await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(mode().dataset.reportSection).toBe("transcript");
    expect(scroll).toHaveBeenCalledOnce();
  } finally {
    if (previous)
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", previous);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  }
});
