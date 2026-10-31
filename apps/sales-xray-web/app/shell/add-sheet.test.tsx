import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { AddSheet } from "./add-sheet";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

async function mount(leadsHere: boolean) {
  const onAddLead = vi.fn();
  const onAddTask = vi.fn();
  const onClose = vi.fn();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <AddSheet
        open
        onClose={onClose}
        onAddLead={onAddLead}
        onAddTask={onAddTask}
        callHref="/analysis/new"
        leadsHere={leadsHere}
      />,
    ),
  );
  return {
    onAddLead,
    onAddTask,
    onClose,
    dialog: host.querySelector("dialog")!,
  };
}

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
});

// Owner, 22 Oct: the + asks for a lead or a call; the 28 Oct meeting added a
// task, and Add task opens its form (owner order, 30 Oct 2026, fix 4: it used
// to open nothing).
it("offers exactly Add lead, Add a call and Add task, each opening its form", async () => {
  const { dialog, onAddLead, onAddTask } = await mount(true);
  expect(dialog.open).toBe(true);
  const titles = Array.from(dialog.querySelectorAll("strong"), (strong) =>
    strong.textContent?.trim(),
  );
  expect(titles).toEqual(["Add lead", "Add a call", "Add task"]);
  const addCall = Array.from(dialog.querySelectorAll("a")).find((link) =>
    link.textContent?.includes("Add a call"),
  );
  expect(addCall?.getAttribute("href")).toBe("/analysis/new");
  const buttons = Array.from(dialog.querySelectorAll("button"));
  const addLead = buttons.find((button) =>
    button.textContent?.includes("Add lead"),
  )!;
  const addTask = buttons.find((button) =>
    button.textContent?.includes("Add task"),
  )!;
  // Taps right after opening are the opening tap's echo; wait them out.
  await new Promise((resolve) => setTimeout(resolve, 400));
  await act(async () => addLead.click());
  expect(onAddLead).toHaveBeenCalledTimes(1);
  await act(async () => addTask.click());
  expect(onAddTask).toHaveBeenCalledTimes(1);
});

it("sends Add lead to Leads outside an organisation", async () => {
  const { dialog } = await mount(false);
  const addLead = Array.from(dialog.querySelectorAll("a")).find((link) =>
    link.textContent?.includes("Add lead"),
  );
  expect(addLead?.getAttribute("href")).toBe("/leads");
  expect(addLead?.textContent).toContain("Leads live in your organisation");
});

// Persona QA, 31 Oct 2026: a double tap on Add task fell through to Ask Dipak.
it("takes one tap on Add task and shields the next", async () => {
  const { dialog, onAddTask } = await mount(true);
  const task = Array.from(dialog.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("Add task"),
  )!;
  // Taps right after opening are the opening tap's echo; wait them out.
  await new Promise((resolve) => setTimeout(resolve, 400));
  await act(async () => {
    task.click();
    task.click();
  });
  expect(onAddTask).toHaveBeenCalledTimes(1);
  expect(document.querySelector("[data-tap-shield]")).not.toBeNull();
});
