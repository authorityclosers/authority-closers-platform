// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBackCloseForTests } from "../ui/back-close";
import { MoreViews, ViewSwitch } from "./view-switch";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Leads' views (owner, 25 Oct 2026: "unclear what to focus on"): Now first,
// All leads beside it, the other views under More.
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
});
const render = (node: ReactNode) => act(async () => root.render(node));

it("puts Now first, All leads beside it, and names the More view that is open", async () => {
  const onNow = vi.fn();
  const onAll = vi.fn();
  const onMore = vi.fn();
  await render(
    <ViewSwitch
      section="more"
      nowCount={4}
      moreLabel="Board"
      onNow={onNow}
      onAll={onAll}
      onMore={onMore}
    />,
  );
  const buttons = [...host.querySelectorAll<HTMLButtonElement>("nav button")];
  expect(buttons.map((button) => button.textContent)).toEqual([
    "Now4",
    "All leads",
    "Board",
  ]);
  expect(buttons[2].getAttribute("aria-current")).toBe("page");
  expect(buttons[2].getAttribute("aria-haspopup")).toBe("dialog");
  expect(buttons[0].getAttribute("aria-current")).toBeNull();
  await act(async () => buttons[0].click());
  await act(async () => buttons[1].click());
  await act(async () => buttons[2].click());
  expect(onNow).toHaveBeenCalledOnce();
  expect(onAll).toHaveBeenCalledOnce();
  expect(onMore).toHaveBeenCalledOnce();
});

it("lists the other views in a sheet and opens the one picked", async () => {
  const onPick = vi.fn();
  const onClose = vi.fn();
  await render(
    <MoreViews
      open
      onClose={onClose}
      onPick={onPick}
      views={[
        { key: "board", label: "Board", note: "Every stage as a column" },
        { key: "work", label: "My work", note: "Your calls, notes and moves" },
      ]}
    />,
  );
  const work = [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.includes("My work"),
  )!;
  expect(work.textContent).toContain("Your calls, notes and moves");
  await act(async () => work.click());
  expect(onClose).toHaveBeenCalledOnce();
  expect(onPick).toHaveBeenCalledWith("work");
});
