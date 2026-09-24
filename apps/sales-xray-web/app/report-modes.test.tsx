import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReportModes } from "./report-modes";

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
function panels() {
  return [
    { id: "overview", label: "Overview", content: <p>Summary</p> },
    {
      id: "moments",
      label: "Moments",
      content: <input aria-label="Moment note" />,
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

it("defaults to reading with every section visible and mounted", async () => {
  await render();
  expect(mode().dataset.view).toBe("reading");
  expect(sections()).toHaveLength(3);
  expect(sections().every((section) => !section.hidden)).toBe(true);
});

it("switches to one visible tab while preserving mounted section state", async () => {
  await render();
  const input = container.querySelector<HTMLInputElement>("input")!;
  await act(async () => {
    input.value = "keep this";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    container
      .querySelector<HTMLButtonElement>('[aria-pressed="false"]')!
      .click();
  });
  expect(mode().dataset.view).toBe("tabs");
  expect(sections().filter((section) => !section.hidden)).toHaveLength(1);
  expect(input.isConnected).toBe(true);
  expect(input.value).toBe("keep this");
});

it("opens the section currently in view when leaving continuous reading", async () => {
  await render();
  const positions = [-500, 90, 600];
  sections().forEach((section, index) => {
    vi.spyOn(
      section.querySelector("h2")!,
      "getBoundingClientRect",
    ).mockReturnValue({
      top: positions[index],
      height: 24,
    } as DOMRect);
  });
  await act(async () => document.dispatchEvent(new Event("scroll")));
  expect(mode().dataset.reportSection).toBe("moments");
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-pressed="false"]')!
      .click(),
  );
  expect(mode().dataset.view).toBe("tabs");
  expect(mode().dataset.reportSection).toBe("moments");
  expect(
    sections().find(
      (section) => section.dataset.reportModeSection === "moments",
    )?.hidden,
  ).toBe(false);
});

it("supports roving arrow, Home, and End keyboard navigation", async () => {
  await render();
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-pressed="false"]')!
      .click(),
  );
  const tabs = () => [
    ...container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
  ];
  const press = async (key: string) =>
    act(async () => {
      const current = tabs().find((tab) => tab.tabIndex === 0)!;
      current.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true }),
      );
    });
  await press("ArrowRight");
  expect(document.activeElement).toBe(tabs()[1]);
  expect(tabs()[1].getAttribute("aria-selected")).toBe("true");
  await press("Home");
  expect(document.activeElement).toBe(tabs()[0]);
  await press("End");
  expect(document.activeElement).toBe(tabs()[2]);
});

it("reads and replaces bookmark state only for its bound call", async () => {
  window.history.replaceState(
    null,
    "",
    `/?call=${call}&view=tabs&section=moments`,
  );
  await render(call);
  expect(mode().dataset.view).toBe("tabs");
  expect(mode().dataset.reportSection).toBe("moments");
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-pressed="false"]')!
      .click(),
  );
  expect(window.location.search).toContain("view=reading");
  expect(window.location.search).toContain("section=moments");

  window.history.replaceState(
    null,
    "",
    `/?call=${call}&view=tabs&section=overview`,
  );
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));
  expect(mode().dataset.view).toBe("tabs");
  expect(mode().dataset.reportSection).toBe("overview");
});

it("ignores a URL bound to a different call", async () => {
  window.history.replaceState(
    null,
    "",
    "/?call=7b6443d3-9b2d-4f97-9e70-5e82e54f8738&view=tabs&section=moments",
  );
  await render(call);
  expect(mode().dataset.view).toBe("reading");
  expect(mode().dataset.reportSection).toBe("overview");
});

it("keeps a bookmarked tab when its already-selected mode is clicked again", async () => {
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

it("opens an explicit reading bookmark at its linked section", async () => {
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
    window.history.replaceState(
      null,
      "",
      `/?call=${call}&view=reading&section=transcript`,
    );
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
