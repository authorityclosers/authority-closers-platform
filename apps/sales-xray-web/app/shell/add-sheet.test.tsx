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
        callHref="/analysis/new"
        leadsHere={leadsHere}
      />,
    ),
  );
  return { onAddLead, onClose, dialog: host.querySelector("dialog")! };
}

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
});

// Owner, 22 Oct: the + asks for two things, a lead or a call.
it("offers exactly Add lead and Add a call", async () => {
  const { dialog, onAddLead } = await mount(true);
  expect(dialog.open).toBe(true);
  const titles = Array.from(dialog.querySelectorAll("strong"), (strong) =>
    strong.textContent?.trim(),
  );
  expect(titles).toEqual(["Add lead", "Add a call"]);
  const addCall = Array.from(dialog.querySelectorAll("a")).find((link) =>
    link.textContent?.includes("Add a call"),
  );
  expect(addCall?.getAttribute("href")).toBe("/analysis/new");
  const addLead = Array.from(dialog.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("Add lead"),
  )!;
  // Taps right after opening are the opening tap's echo; wait them out.
  await new Promise((resolve) => setTimeout(resolve, 400));
  await act(async () => addLead.click());
  expect(onAddLead).toHaveBeenCalledTimes(1);
});

it("sends Add lead to Leads outside an organisation", async () => {
  const { dialog } = await mount(false);
  const addLead = Array.from(dialog.querySelectorAll("a")).find((link) =>
    link.textContent?.includes("Add lead"),
  );
  expect(addLead?.getAttribute("href")).toBe("/leads");
  expect(addLead?.textContent).toContain("Leads live in your organisation");
});
