import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ReportHeader } from "./report-header";

let root: Root;
let host: HTMLDivElement;
let onDownload: ReturnType<typeof vi.fn<() => void>>;
let onAnalyseAnother: ReturnType<typeof vi.fn<() => void>>;

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

beforeEach(async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  onDownload = vi.fn();
  onAnalyseAnother = vi.fn();
  await act(async () =>
    root.render(
      <ReportHeader
        durationMs={67_000}
        languageLabel="English"
        sourceLabel="Fictional test source"
        claimed
        busy={false}
        canDownload
        canRequestDeletion
        deletionDisabled={false}
        onAnalyseAnother={onAnalyseAnother}
        onDownload={onDownload}
        onRequestDeletion={() => {}}
      />,
    ),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.clearAllTimers();
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

function openMenu() {
  const trigger = host.querySelector<HTMLElement>(
    'summary[aria-label="More report actions"]',
  )!;
  const menu = trigger.parentElement as HTMLDetailsElement;
  // Native details owns its open state; React owns the dismissal behavior.
  menu.open = true;
  trigger.focus();
  return { trigger, menu };
}

it("Escape closes secondary actions and restores their trigger focus", async () => {
  const { trigger, menu } = openMenu();
  const download = menu.querySelector<HTMLButtonElement>("button")!;
  download.focus();
  await act(async () =>
    download.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(menu.open).toBe(false);
  expect(document.activeElement).toBe(trigger);
  expect(onDownload).not.toHaveBeenCalled();
});

it("outside pointer dismissal preserves the clicked action", async () => {
  const { menu } = openMenu();
  const next = Array.from(host.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("Analyse another call"),
  )!;
  await act(async () => {
    next.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    next.click();
  });
  expect(menu.open).toBe(false);
  expect(onAnalyseAnother).toHaveBeenCalledOnce();
});

it("tabbing away dismisses the popup without returning focus", () => {
  const { menu } = openMenu();
  // Source details now live inside the menu; tab to something outside it.
  const outside = document.createElement("button");
  host.appendChild(outside);
  outside.focus();
  expect(menu.open).toBe(false);
  expect(document.activeElement).toBe(outside);
});

it("the download action runs once and closes its disclosure", async () => {
  const { menu } = openMenu();
  await act(async () =>
    menu.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(onDownload).toHaveBeenCalledOnce();
  expect(menu.open).toBe(false);
});

it.each([
  [
    "/sales-xray?call=eaed7960-d4d0-4675-bd34-5b6a7d9c598d&view=report&token=fictional#overview",
    "/sales-xray?call=eaed7960-d4d0-4675-bd34-5b6a7d9c598d#overview",
  ],
  [
    "/analysis/calls/eaed7960-d4d0-4675-bd34-5b6a7d9c598d?view=report#overview",
    "/analysis/calls/eaed7960-d4d0-4675-bd34-5b6a7d9c598d#overview",
  ],
  ["/sales-xray?call=&view=report", "/sales-xray"],
])("copies the report URL from %s as %s", async (path, expected) => {
  vi.useFakeTimers();
  window.history.replaceState(null, "", path);
  const writeText = vi
    .spyOn(navigator.clipboard, "writeText")
    .mockResolvedValue(undefined);
  const { menu } = openMenu();
  const copy = Array.from(menu.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("Copy link"),
  )!;
  await act(async () => copy.click());
  expect(writeText).toHaveBeenCalledExactlyOnceWith(
    `${window.location.origin}${expected}`,
  );
  expect(copy.textContent).toContain("Link copied");
  expect(menu.open).toBe(false);
});

it.each(["unavailable", "denied"])(
  "keeps Copy link actionable when clipboard access is %s",
  async (failure) => {
    vi.useFakeTimers();
    const clipboard = navigator.clipboard;
    const write = vi
      .spyOn(clipboard, "writeText")
      .mockRejectedValue(new Error("denied"));
    const access = vi.spyOn(navigator, "clipboard", "get");
    if (failure === "unavailable") access.mockReturnValue(undefined!);
    const { menu } = openMenu();
    const copy = Array.from(menu.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Copy link"),
    )!;
    await act(async () => copy.click());
    expect(menu.open).toBe(true);
    expect(menu.querySelector('[role="alert"]')?.textContent).toContain(
      "Couldn’t copy the link. Try again or copy the address from your browser.",
    );
    expect(copy.textContent).toContain("Copy link");
    access.mockRestore();
    write.mockResolvedValue(undefined);
    await act(async () => copy.click());
    expect(copy.textContent).toContain("Link copied");
    expect(menu.querySelector('[role="alert"]')).toBeNull();
    expect(menu.open).toBe(false);
  },
);

it("renders clearly visible Transcript button beside More menu and entry inside More menu", async () => {
  const onOpenTranscript = vi.fn();
  await act(async () =>
    root.render(
      <ReportHeader
        durationMs={67_000}
        sourceLabel="Fictional test source"
        claimed
        busy={false}
        canDownload
        canRequestDeletion
        deletionDisabled={false}
        onAnalyseAnother={onAnalyseAnother}
        onDownload={onDownload}
        onRequestDeletion={() => {}}
        onOpenTranscript={onOpenTranscript}
      />,
    ),
  );

  const transcriptButton = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Open transcript reader"]',
  );
  expect(transcriptButton).not.toBeNull();
  expect(transcriptButton?.textContent).toContain("Transcript");
  await act(async () => transcriptButton?.click());
  expect(onOpenTranscript).toHaveBeenCalledOnce();

  const { menu } = openMenu();
  const transcriptMenuButton = Array.from(menu.querySelectorAll("button")).find(
    (b) => b.textContent?.includes("Transcript"),
  );
  expect(transcriptMenuButton).not.toBeUndefined();
  await act(async () => transcriptMenuButton?.click());
  expect(onOpenTranscript).toHaveBeenCalledTimes(2);
});
