import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CallsDrawer } from "./calls-drawer";
import { extractInsight } from "./calls-insights";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
const props = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Fictional call",
  meta: "Today",
  status: "Ready",
  tone: "ready",
  insight: null,
  readState: "loading" as const,
  hasReport: true,
  canRename: true,
  onOpen: vi.fn(),
  onRename: vi.fn(),
  onClose: vi.fn(),
  onRetry: vi.fn(),
};
const buttons = () =>
  Array.from(host.querySelectorAll<HTMLButtonElement>("button"));
const named = (text: string) =>
  buttons().find((button) => button.textContent?.trim() === text)!;
const dialog = () => host.querySelector("dialog")!;

beforeEach(async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<CallsDrawer {...props} />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

it("opens as the kit sheet, named by the call, with its meta and actions", () => {
  expect(dialog().open).toBe(true);
  const title = document.getElementById(
    dialog().getAttribute("aria-labelledby")!,
  );
  expect(title?.textContent).toBe("Fictional call");
  expect(dialog().textContent).toContain("Today");
  const footer = host.querySelector("footer")!;
  expect(
    Array.from(footer.querySelectorAll("button"), (button) =>
      button.textContent?.trim(),
    ),
  ).toEqual(["Open full report", "Rename", "Copy link"]);
});

it("closes from Escape and from its close button, as every sheet does", async () => {
  await act(async () => {
    dialog().dispatchEvent(new Event("cancel", { cancelable: true }));
  });
  expect(props.onClose).toHaveBeenCalledOnce();
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label="Close"]')!
      .click(),
  );
  expect(props.onClose).toHaveBeenCalledTimes(2);
});

it("keeps the call on it while it slides away", async () => {
  await act(async () => root.render(<CallsDrawer {...props} open={false} />));
  expect(host.textContent).toContain("Fictional call");
  expect(props.onClose).not.toHaveBeenCalled();
});

it("lets the player scrub without dragging the sheet", () => {
  expect(host.querySelector("audio")?.hasAttribute("data-sheet-no-drag")).toBe(
    true,
  );
});

it("opens the report and renames from its footer", async () => {
  await act(async () => named("Open full report").click());
  expect(props.onOpen).toHaveBeenCalledOnce();
  await act(async () => named("Rename").click());
  expect(props.onRename).toHaveBeenCalledOnce();
});

it("shows unavailable measurements without invented zeros and offers recovery", async () => {
  await act(async () =>
    root.render(
      <CallsDrawer
        {...props}
        insight={extractInsight(null, { verdict: "Report arrived" })}
        readState="error"
      />,
    ),
  );
  for (const title of [
    "Questions asked",
    "Next steps and commitments",
    "Business details",
    "Concerns",
  ])
    expect(host.querySelector(`[title="${title}"]`)?.textContent).toBe("—");
  await act(async () => named("Retry report").click());
  expect(props.onRetry).toHaveBeenCalledOnce();
});
