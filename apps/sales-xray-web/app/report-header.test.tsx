import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ReportHeader } from "./report-header";

let root: Root;
let host: HTMLDivElement;
let onDownload: ReturnType<typeof vi.fn<() => void>>;
let onAnalyseAnother: ReturnType<typeof vi.fn<() => void>>;

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

beforeEach(async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  onDownload = vi.fn();
  onAnalyseAnother = vi.fn();
  await act(async () => root.render(
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
  ));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
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
  await act(async () => download.dispatchEvent(new KeyboardEvent("keydown", {
    key: "Escape", bubbles: true, cancelable: true,
  })));
  expect(menu.open).toBe(false);
  expect(document.activeElement).toBe(trigger);
  expect(onDownload).not.toHaveBeenCalled();
});

it("outside pointer dismissal preserves the clicked action", async () => {
  const { menu } = openMenu();
  const next = Array.from(host.querySelectorAll("button"))
    .find(button => button.textContent?.includes("Analyse another call"))!;
  await act(async () => {
    next.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    next.click();
  });
  expect(menu.open).toBe(false);
  expect(onAnalyseAnother).toHaveBeenCalledOnce();
});

it("tabbing away dismisses the popup without returning focus", () => {
  const { menu } = openMenu();
  const source = host.querySelectorAll<HTMLElement>("summary")[1];
  source.focus();
  expect(menu.open).toBe(false);
  expect(document.activeElement).toBe(source);
});

it("the download action runs once and closes its disclosure", async () => {
  const { menu } = openMenu();
  await act(async () => menu.querySelector<HTMLButtonElement>("button")!.click());
  expect(onDownload).toHaveBeenCalledOnce();
  expect(menu.open).toBe(false);
});
